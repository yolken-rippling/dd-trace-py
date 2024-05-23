from collections import defaultdict
import dataclasses
import threading
import typing

from ddtrace._trace.span import Span
from ddtrace.internal.logger import get_logger


log = get_logger(__name__)


@dataclasses.dataclass
class Trace:
    _spans: typing.Set[Span] = dataclasses.field(default_factory=set)
    _num_finished: int = 0
    _lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)

    def __len__(self):
        return len(self._spans)

    @property
    def finished(self) -> bool:
        return len(self._spans) == self._num_finished

    def add_span(self, span: Span):
        with self._lock:
            self._spans.add(span)

    def finish_span(self, span: Span) -> int:
        with self._lock:
            if span not in self._spans:
                log.warning("Cannot finish span %s, not found in trace %s", span, span.trace_id)
            else:
                self._num_finished += 1
            return self._num_finished

    def remove_finished_spans(self) -> typing.List[Span]:
        with self._lock:
            trace_spans, self._spans = self._spans, set()
            self._num_finished = 0

            if len(trace_spans) == self._num_finished:
                return list(trace_spans)

            finished_spans = []
            for span in trace_spans:
                if span.finished:
                    finished_spans.append(span)
                else:
                    self._spans.add(span)
            return finished_spans


@dataclasses.dataclass
class Traces:
    _traces: typing.DefaultDict[int, Trace] = dataclasses.field(default_factory=lambda: defaultdict(Trace))

    def get_trace(self, trace_id: int) -> Trace:
        return self._traces[trace_id]

    def add_span(self, span: Span):
        self._traces[span.trace_id].add_span(span)

    def finish_span(self, span: Span) -> int:
        if span.trace_id not in self._traces:
            log.warning("Cannot finish span %s, trace %s not found", span, span.trace_id)
            return 0

        return self._traces[span.trace_id].finish_span(span)

    def remove_trace(self, trace_id: int):
        try:
            del self._traces[trace_id]
        except KeyError:
            pass

    def clear(self):
        self._traces.clear()

    def __len__(self):
        return len(self._traces)


# Global shared instanec of Traces so all spans created get aggregated into the same location
traces = Traces()
