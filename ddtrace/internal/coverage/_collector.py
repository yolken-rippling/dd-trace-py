from contextlib import contextmanager
from contextvars import ContextVar
import pathlib
import threading
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import bitarray


# ctx_executed_lines: ContextVar[Dict[int, bitarray]] = ContextVar("ctx_executable_lines")
# ctx_collection_active: ContextVar[bool] = ContextVar("ctx_collection_active", default=False)


class Collector:
    _collection_lock = threading.Lock()
    _instrumentation_lock = threading.RLock()
    _executable_files_indices: Dict[pathlib.Path, int] = {}

    def __init__(self, include_path=pathlib.Path):
        self._include_path = include_path

        # Data containers
        self._executable_lines: List[Tuple[pathlib.Path, bitarray.bitarray]] = []
        self._executed_lines: Optional[Dict[int, bitarray.bitarray]] = None

        self._collect_coverage = False

    def record_executable_line(self, file_path: pathlib.Path, line_num: int):
        # print(f"RECORDING EXECUTABLE LINE {file_path=} {line_num=} {self._include_path=}")

        line_idx = line_num - 1

        if self._include_path not in file_path.parents:
            # breakpoint()
            # print(f"Ignoring file: {file_path=} not under include path {self._include_path=}")
            return

        with self._instrumentation_lock:
            # print(f"RECORDING EXECUTABLE LINE {file_path=} {line_num=} {self._include_path=}")
            file_idx = self.get_file_idx(file_path)
            if file_idx is None:
                # print(f"NEW FILE: {file_path=}, {line_num=}")
                self._executable_files_indices[file_path] = len(self._executable_lines)
                self._executable_lines.append((file_path, bitarray.bitarray(line_num)))
                self._executable_lines[-1][1].setall(0)
                self._executable_lines[-1][1][line_idx] = 1
                return len(self._executable_lines) - 1

            file_executable_lines = self._executable_lines[file_idx][1]
            file_length = len(file_executable_lines)

            if line_num <= file_length:
                # print(f"NO NEED TO EXTEND: {line_num=} {file_length=}")
                file_executable_lines[line_idx] = 1
            else:
                # print(f"EXTENDING: {line_num=} {file_length=}")
                file_executable_lines.extend([0] * (line_num - file_length))
                file_executable_lines[line_idx] = 1

            return file_idx

    @classmethod
    def get_file_idx(cls, file_path: pathlib.Path):
        with cls._instrumentation_lock:
            if file_path in cls._executable_files_indices:
                return cls._executable_files_indices[file_path]
            return None

    def discover_file(self, file_path: pathlib.Path, executable_lines: bitarray.bitarray):
        if self._include_path not in file_path.parents:
            # print(f"Ignoring file: {file_path=} not under include path {self._include_path=}")
            return
        with self._instrumentation_lock:
            file_idx = len(self._executable_lines)
            self._executable_files_indices[file_path] = file_idx
            self._executable_lines.append((file_path, bitarray.frozenbitarray(executable_lines)))

    # @contextmanager
    # def collect(self):
    #     ctx_executed_lines.set({})
    #     ctx_collection_active.set(True)
    #     yield self
    #     ctx_collection_active.set(False)

    def start(self):
        self._collect_coverage = True
        self._executed_lines = {}

    def stop(self):
        self._collect_coverage = False

    def clear_data(self):
        self._executable_lines = {}

    def record_executed_line(self, file_idx: int, line_num: int):
        # print(f"RECORDING EXECUTED LINE {file_idx=} {line_num=} ")

        line_idx = line_num - 1

        if not self._collect_coverage:
            # print("NOT RECORDING LINE BECAUSE COLLECTION IS NOT ACTIVE")
            return

        # # print(f"Marking line {line_num} as executed in file {file_path}")
        # if file_path not in self._executable_files_indices:
        #     # print(f"Not recording because {file_path=} not in executable files")
        #     return
        # with self._instrumentation_lock:
        #     file_idx = self._executable_files_indices[file_path]

        # breakpoint()

        with self._collection_lock:
            executed_lines = self._executed_lines
            if file_idx not in executed_lines:
                executed_lines[file_idx] = bitarray.bitarray(len(self._executable_lines[file_idx][1]))
            # print(f"Executed lines for file {file_path}, index {file_idx} are: {file_executed_lines}")
            executed_lines[file_idx][line_idx] = 1
            # print(f"After recording: file_executed_lines")

    def report_executed_lines(self):
        cwd = pathlib.Path.cwd()

        with self._instrumentation_lock:
            print("\n")
            print("{:^83}".format("COVERAGE REPORT"))
            print(
                "{:<60}{:>8}{:>8}{:>7}".format(
                    "Name",
                    "Stmts",
                    "Miss",
                    "Cover",
                )
            )
            print("-" * (60 + 8 + 8 + 7))
            total_executable_lines_count = 0
            total_executed_lines_count = 0
            total_missed_statements = 0
            total_magic_lines_from_hell = 0

            # breakpoint()
            for executable_file in sorted(self._executable_files_indices.keys()):
                file_idx = self._executable_files_indices[executable_file]

                executable_lines = self._executable_lines[file_idx][1]
                if file_idx in self._executed_lines:
                    executed_lines = self._executed_lines.get(file_idx, bitarray.bitarray(len(executable_lines)))
                else:
                    # print(f"FILE NOT EXECUTED: {executable_file}")
                    executed_lines = bitarray.bitarray(len(executable_lines))

                if len(executable_lines) != len(executed_lines):
                    print(f"FILE {executable_file} HAS MISMATCHED LENGTH")
                    if len(executable_lines) < len(executed_lines):
                        print("EXECUTED LINES IS LONGER -- WAT")

                file_executable_lines_count = 0
                file_executed_lines_count = 0
                file_missed_statements = 0
                file_magic_lines_from_hell = 0

                for i in range(len(executable_lines)):
                    if executable_lines[i] == 1:
                        file_executable_lines_count += 1
                        if executed_lines[i]:
                            file_executed_lines_count += 1
                        else:
                            file_missed_statements = 1
                    elif executed_lines[i] == 1:
                        file_executed_lines_count += 1
                        file_magic_lines_from_hell += 1

                total_executable_lines_count += file_executable_lines_count
                total_executed_lines_count += file_executed_lines_count
                total_missed_statements += file_missed_statements
                total_magic_lines_from_hell += file_magic_lines_from_hell

                relpath = executable_file.relative_to(cwd)

                file_pct = int(file_executed_lines_count / file_executable_lines_count * 100)

                print(
                    "{:<60}{:>8}{:>8}{:>6}%".format(
                        str(relpath),
                        file_executable_lines_count,
                        file_missed_statements,
                        file_pct,
                    )
                )
            print("-" * (60 + 8 + 8 + 7))

            total_pct = int(total_executed_lines_count / total_executable_lines_count * 100)
            print(
                "{:<60}{:>8}{:>8}{:>6}%".format(
                    "TOTAL",
                    total_executable_lines_count,
                    total_missed_statements,
                    total_pct,
                )
            )

    # def persist_coverage(self):
    #     self._persisted_coverages.append(ctx_executed_lines.get())
