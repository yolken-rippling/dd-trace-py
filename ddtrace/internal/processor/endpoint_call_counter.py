import dataclasses
import threading
import typing

from ddtrace.ext import SpanTypes
from ddtrace.internal import forksafe
from ddtrace.internal.compat import ensure_str
from ddtrace.internal.processor import SpanProcessor
from ddtrace.span import Span


EndpointCountsType = typing.Dict[str, int]


@dataclasses.dataclass(eq=False)
class EndpointCallCounterProcessor(SpanProcessor):
    endpoint_counts: EndpointCountsType = dataclasses.field(init=False, repr=False, default_factory=dict)
    _endpoint_counts_lock: forksafe.ResetObject[threading.Lock] = dataclasses.field(
        init=False,
        repr=False,
        default_factory=forksafe.Lock,
    )
    _enabled: bool = dataclasses.field(default=False, repr=False)

    def enable(self):
        # type: () -> None
        self._enabled = True

    def on_span_start(self, span):
        # type: (Span) -> None
        pass

    def on_span_finish(self, span):
        # type: (Span) -> None
        if not self._enabled:
            return
        if span._local_root == span and span.span_type == SpanTypes.WEB:
            resource = ensure_str(span.resource, errors="backslashreplace")
            with self._endpoint_counts_lock:
                self.endpoint_counts[resource] = self.endpoint_counts.get(resource, 0) + 1

    def reset(self):
        # type: () -> EndpointCountsType
        with self._endpoint_counts_lock:
            counts = self.endpoint_counts
            self.endpoint_counts = {}
            return counts
