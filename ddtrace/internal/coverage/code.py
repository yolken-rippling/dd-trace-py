from collections import defaultdict
from collections import deque
from types import CodeType
from types import ModuleType
import typing as t

from ddtrace.internal.compat import Path
from ddtrace.internal.coverage._native import replace_in_tuple
from ddtrace.internal.coverage.instrumentation import instrument_all_lines
from ddtrace.internal.module import BaseModuleWatchdog
from ddtrace.vendor.contextvars import ContextVar


CWD = Path.cwd()

_original_exec = exec

ctx_covered = ContextVar("ctx_covered", default=None)
ctx_coverage_enabed = ContextVar("ctx_coverage_enabled", default=False)


def collapse_ranges(numbers):
    # This function turns an ordered list of numbers into a list of ranges.
    # For example, [1, 2, 3, 5, 6, 7, 9] becomes [(1, 3), (5, 7), (9, 9)]
    # WARNING: Written by Copilot
    if not numbers:
        return ""
    ranges = []
    start = end = numbers[0]
    for number in numbers[1:]:
        if number == end + 1:
            end = number
        else:
            ranges.append((start, end))
            start = end = number

    ranges.append((start, end))

    return ranges


def collect_code_objects(code: CodeType) -> t.Iterator[t.Tuple[CodeType, t.Optional[CodeType]]]:
    # Topological sorting
    q = deque([code])
    g = {}
    p = {}
    leaves: t.Deque[CodeType] = deque()

    # Build the graph and the parent map
    while q:
        c = q.popleft()
        new_codes = g[c] = {_ for _ in c.co_consts if isinstance(_, CodeType)}
        if not new_codes:
            leaves.append(c)
            continue
        for new_code in new_codes:
            p[new_code] = c
        q.extend(new_codes)

    # Yield the code objects in topological order
    while leaves:
        c = leaves.popleft()
        parent = p.get(c)
        yield c, parent
        if parent is not None:
            children = g[parent]
            children.remove(c)
            if not children:
                leaves.append(parent)


class ModuleCodeCollector(BaseModuleWatchdog):
    COUNT_TOTAL_HOOK_RUNS = 0
    COUNT_TOTAL_INSTANCE_CHECKS = 0
    COUNT_TOTAL_CONTEXT_LINE_CHECKS = 0

    def __init__(self):
        super().__init__()
        self.seen = set()
        self.coverage_enabled = False
        self.lines = defaultdict(set)
        self.covered = defaultdict(set)

        # Replace the built-in exec function with our own in the pytest globals
        try:
            import _pytest.assertion.rewrite as par

            par.exec = self._exec
        except ImportError:
            pass

    def hook(self, arg):
        self.__class__.COUNT_TOTAL_HOOK_RUNS += 1
        path, line = arg
        if self.coverage_enabled:
            lines = self.covered[path]
            self.__class__.COUNT_TOTAL_INSTANCE_CHECKS += 1
            if line not in lines:
                # This line has already been covered
                lines.add(line)

        if ctx_coverage_enabed.get():
            self.__class__.COUNT_TOTAL_CONTEXT_LINE_CHECKS += 1
            ctx_lines = ctx_covered.get()[path]
            if line not in ctx_lines:
                ctx_lines.add(line)

    @classmethod
    def report(cls):
        if cls._instance is None:
            return

        instance = cls._instance
        total_executable_lines = 0
        total_covered_lines = 0
        total_missed_lines = 0
        n = max(len(path) for path in instance.lines) + 4
        width = n + 8 + 8 + 8 + 1
        print(f"{'COVERAGE REPORT:':^{width}}")
        print(f"{'PATH':<{n}}{'LINES':>8}{'MISSED':>8} {'COVERED':>8}  MISSED LINES")
        print("-" * (width))
        for path, lines in sorted(instance.lines.items()):
            covered_lines = cls._instance._get_covered_lines()
            n_covered = len(covered_lines[path])
            total_executable_lines += len(lines)
            total_covered_lines += n_covered
            total_missed_lines += len(lines) - n_covered
            if n_covered == 0:
                continue
            missed_ranges = collapse_ranges(sorted(lines - covered_lines[path]))
            missed = ",".join([f"{start}-{end}" if start != end else str(start) for start, end in missed_ranges])
            missed_str = f"  [{missed}]" if missed else ""
            print(
                f"{path:{n}s}{len(lines):>8}{len(lines)-n_covered:>8}{int(n_covered/len(lines) * 100):>8}%{missed_str}"
            )
        print("-" * width)
        total_covered_percent = int((total_covered_lines / total_executable_lines) * 100)
        print(f"{'TOTAL':<{n}}{total_executable_lines:>8}{total_missed_lines:>8}{total_covered_percent:>8}%")
        print()

    def _get_covered_lines(self):
        if ctx_coverage_enabed.get(False):
            print("RETURNING CONTEXT LINES")
            return ctx_covered.get()
        return self.covered

    class CollectInContext:
        def __enter__(self):
            ctx_covered.set(defaultdict(set))
            ctx_coverage_enabed.set(True)

        def __exit__(*args, **kwargs):
            ctx_coverage_enabed.set(False)

    @classmethod
    def start_coverage(cls):
        if cls._instance is None:
            return
        cls._instance.coverage_enabled = True

    @classmethod
    def stop_coverage(cls):
        if cls._instance is None:
            return
        cls._instance.coverage_enabled = False

    @classmethod
    def clear_covered(cls):
        # This alwasy clears the instance's covered lines and does not apply to context coverage
        if cls._instance is None:
            return
        cls._instance.covered.clear()

    @classmethod
    def coverage_enabled(cls):
        if ctx_coverage_enabed.get():
            return True
        if cls._instance is None:
            return False
        return cls._instance.coverage_enabled

    @classmethod
    def report_seen_lines(cls):
        """Generate the same data as expected by ddtrace.ci_visibility.coverage.build_payload:

        if input_path is provided, filter files to only include that path, and make it relative to said path

        "files": [
            {
                "filename": <String>,
                "segments": [
                    [Int, Int, Int, Int, Int],  # noqa:F401
                ]
            },
            ...
        ]
        """
        if cls._instance is None:
            return []
        files = []
        if ctx_coverage_enabed.get():
            covered = ctx_covered.get()
        else:
            covered = cls._instance.covered
        for path, lines in covered.items():
            sorted_lines = sorted(lines)
            collapsed_ranges = collapse_ranges(sorted_lines)
            file_segments = []
            for file_segment in collapsed_ranges:
                file_segments.append([file_segment[0], 0, file_segment[1], 0, -1])
            files.append({"filename": path, "segments": file_segments})

        return files

    @classmethod
    def report_seen_lines_from_context(cls):
        if ctx_covered.get() is None:
            return []
        return cls.report_seen_lines()

    def transform(self, code: CodeType, _module: ModuleType) -> CodeType:
        code_path = Path(code.co_filename).resolve()
        # TODO: Remove hardcoded paths
        if all(not code_path.is_relative_to(CWD / folder) for folder in ("starlette", "tests")):
            # Not a code object we want to instrument
            return code

        # Recursively instrument nested code objects, in topological order
        # DEV: We need to make a list of the code objects because when we start
        # mutating the parent code objects, the hashes maintained by the
        # generator will be invalidated.
        for nested_code, parent_code in list(collect_code_objects(code)):
            # Instrument the code object
            new_code = self.instrument_code(nested_code)

            # If it has a parent, update the parent's co_consts to point to the
            # new code object.
            if parent_code is not None:
                replace_in_tuple(parent_code.co_consts, nested_code, new_code)

        return new_code

    def after_import(self, _module: ModuleType) -> None:
        pass

    def instrument_code(self, code: CodeType) -> CodeType:
        # Avoid instrumenting the same code object multiple times
        if code in self.seen:
            return code
        self.seen.add(code)

        path = str(Path(code.co_filename).resolve().relative_to(CWD))

        new_code, lines = instrument_all_lines(code, self.hook, path)

        # Keep note of all the lines that have been instrumented. These will be
        # the ones that can be covered.
        self.lines[path] |= lines

        return new_code

    def _exec(self, _object, _globals=None, _locals=None, **kwargs):
        # The pytest module loader doesn't implement a get_code method so we
        # need to intercept the loading of test modules by wrapping around the
        # exec built-in function.
        new_object = (
            self.transform(_object, None)
            if isinstance(_object, CodeType) and _object.co_name == "<module>"
            else _object
        )

        # Execute the module before calling the after_import hook
        _original_exec(new_object, _globals, _locals, **kwargs)

    @classmethod
    def uninstall(cls) -> None:
        # Restore the original exec function
        try:
            import _pytest.assertion.rewrite as par

            par.exec = _original_exec
        except ImportError:
            pass

        return super().uninstall()
