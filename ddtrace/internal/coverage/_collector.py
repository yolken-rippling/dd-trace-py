import pathlib
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, List, Tuple, Optional
import bitarray

ctx_executed_lines: ContextVar[Dict[int, bitarray]] = ContextVar("ctx_executable_lines")
ctx_collection_active: ContextVar[bool] = ContextVar("ctx_collection_active", default=False)

class Collector:
    _collection_lock = threading.Lock()
    _instrumentation_lock = threading.RLock()
    _executable_files_indices: Dict[pathlib.Path, int] = {}

    def __init__(self, include_path=pathlib.Path):
        self._include_path = include_path

        # Data containers
        self._executable_lines: List[Tuple[pathlib.Path, bitarray.bitarray]] = []
        self._executed_lines: Optional[Dict[int, bitarray.bitarray]] = None

        self._persisted_coverages = []

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

    @contextmanager
    def collect(self):
        ctx_executed_lines.set({})
        ctx_collection_active.set(True)
        yield self
        ctx_collection_active.set(False)

    def record_executed_line(self, file_idx: int, line_num: int):
        # print(f"RECORDING EXECUTED LINE {file_idx=} {line_num=} ")

        line_idx = line_num - 1

        if not ctx_collection_active.get():
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
            executed_lines = ctx_executed_lines.get()
            if file_idx not in executed_lines:
                executed_lines[file_idx] = bitarray.bitarray(len(self._executable_lines[file_idx][1]))
            # print(f"Executed lines for file {file_path}, index {file_idx} are: {file_executed_lines}")
            executed_lines[file_idx][line_idx] = 1
            # print(f"After recording: file_executed_lines")

    def report_executed_lines(self):
        with self._instrumentation_lock:
            executed_lines = ctx_executed_lines.get()
            return {self._executable_lines[file_idx][0]: file_executed_lines for file_idx, file_executed_lines in executed_lines.items()}

    def persist_coverage(self):
        self._persisted_coverages.append(ctx_executed_lines.get())
