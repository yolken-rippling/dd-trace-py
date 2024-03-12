from collections import deque
from dis import findlinestarts
from types import CodeType
from types import ModuleType
import typing as t

from ddtrace.internal.compat import Path
from ddtrace.internal.coverage._native import replace_in_tuple
from ddtrace.internal.injection import inject_hooks_in_code
from ddtrace.internal.module import BaseModuleWatchdog


CWD = Path.cwd()

_original_exec = exec


def collect_code_objects(code: CodeType, recursive: bool = False) -> t.Iterator[t.Tuple[CodeType, CodeType]]:
    q = deque([code])
    while q:
        c = q.popleft()
        for next_code in (_ for _ in c.co_consts if isinstance(_, CodeType)):
            if recursive:
                q.append(next_code)
            yield (next_code, c)


def get_lines(code: CodeType) -> t.List[int]:
    return [ln for _, ln in findlinestarts(code) if ln > 0]


class ModuleCodeCollector(BaseModuleWatchdog):
    def __init__(self):
        super().__init__()
        self.seen = set()
        self._collectors = []
        self._input_paths = []

        # Replace the built-in exec function with our own in the pytest globals
        try:
            import _pytest.assertion.rewrite as par

            par.exec = self._exec
        except ImportError:
            pass

    def _gen_hook_closure(self, collector, file_path, line_num):
        file_idx = collector.record_executable_line(file_path, line_num)

        def hook(_arg):
            collector.record_executed_line(file_idx, line_num)

        return hook

    @classmethod
    def add_collector(cls, collector):
        print(f"ADDING COLLECTOR {collector=}")
        cls._instance._collectors.append(collector)

    @classmethod
    def get_first_collector(cls):
        return cls._instance._collectors[0]

    @classmethod
    def add_input_path(cls, path):
        print(f"ADDING INPUT PATH {path=}")
        cls._instance._input_paths.append(path)

    def transform(self, code: CodeType, _module: ModuleType) -> CodeType:
        code_path = Path(code.co_filename).resolve()

        keep_path = False
        for input_path in self._input_paths:
            try:
                if code_path.is_relative_to(input_path):
                    # print(f"KEEPING PATH {path=}")
                    keep_path = True
                    break
            except ValueError:
                #
                pass

        if not keep_path:
            # print(f"REJECT PATH {path=}")
            return code

        # Transform the module code object
        new_code = self.instrument_code(code)

        # Recursively instrument nested code objects
        for nested_code, parent_code in collect_code_objects(new_code, recursive=True):
            replace_in_tuple(parent_code.co_consts, nested_code, self.instrument_code(nested_code))

        return new_code

    def after_import(self, _module: ModuleType) -> None:
        pass

    def instrument_code(self, code: CodeType) -> CodeType:
        if code in self.seen:
            return code

        self.seen.add(code)

        path = Path(code.co_filename).resolve()
        lines = set(get_lines(code))

        new_code, failed = inject_hooks_in_code(
            code,
            [
                (self._gen_hook_closure(collector, path, line), line, (path, line))
                for collector in self._collectors
                for line in lines
            ],
        )

        assert not failed, "All lines instrumented"

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
