import math
import pprint
import sys
import traceback
from typing import Any  # noqa:F401
from typing import Callable  # noqa:F401
from typing import Dict  # noqa:F401
from typing import List  # noqa:F401
from typing import Optional  # noqa:F401
from typing import Text  # noqa:F401
from typing import Union  # noqa:F401

from ddtrace import config
from ddtrace._trace._span_link import SpanLink
from ddtrace._trace.context import Context
from ddtrace.constants import ANALYTICS_SAMPLE_RATE_KEY
from ddtrace.constants import ERROR_MSG
from ddtrace.constants import ERROR_STACK
from ddtrace.constants import ERROR_TYPE
from ddtrace.constants import MANUAL_DROP_KEY
from ddtrace.constants import MANUAL_KEEP_KEY
from ddtrace.constants import SAMPLING_AGENT_DECISION
from ddtrace.constants import SAMPLING_LIMIT_DECISION
from ddtrace.constants import SAMPLING_RULE_DECISION
from ddtrace.constants import SERVICE_KEY
from ddtrace.constants import SERVICE_VERSION_KEY
from ddtrace.constants import SPAN_MEASURED_KEY
from ddtrace.constants import USER_KEEP
from ddtrace.constants import USER_REJECT
from ddtrace.constants import VERSION_KEY
from ddtrace.ext import http
from ddtrace.ext import net
from ddtrace.internal._rand import rand64bits as _rand64bits
from ddtrace.internal._rand import rand128bits as _rand128bits
from ddtrace.internal.compat import NumericType
from ddtrace.internal.compat import StringIO
from ddtrace.internal.compat import ensure_text
from ddtrace.internal.compat import is_integer
from ddtrace.internal.compat import time_ns
from ddtrace.internal.constants import MAX_UINT_64BITS as _MAX_UINT_64BITS
from ddtrace.internal.constants import SPAN_API_DATADOG
from ddtrace.internal.logger import get_logger
from ddtrace.internal.sampling import SamplingMechanism
from ddtrace.internal.sampling import set_sampling_decision_maker
from ddtrace.internal.utils.deprecations import DDTraceDeprecationWarning
from ddtrace.vendor.debtcollector import deprecate


_NUMERIC_TAGS = (ANALYTICS_SAMPLE_RATE_KEY,)
_TagNameType = Union[Text, bytes]
_MetaDictType = Dict[_TagNameType, Text]
_MetricDictType = Dict[_TagNameType, NumericType]


class SpanEvent:
    __slots__ = ["name", "attributes", "time_unix_nano"]

    def __init__(self, name: str, attributes: Optional[Dict[str, str]] = None, time_unix_nano: Optional[int] = None):
        self.name: str = name
        self.attributes: Dict[str, str] = attributes or {}
        if time_unix_nano is None:
            time_unix_nano = time_ns()
        self.time_unix_nano: int = time_unix_nano

    def __dict__(self):
        d = {"name": self.name, "time_unix_nano": self.time_unix_nano}
        if self.attributes:
            d["attributes"] = self.attributes
        return d


log = get_logger(__name__)


def _get_64_lowest_order_bits_as_int(large_int):
    # type: (int) -> int
    """Get the 64 lowest order bits from a 128bit integer"""
    return _MAX_UINT_64BITS & large_int


def _get_64_highest_order_bits_as_hex(large_int):
    # type: (int) -> str
    """Get the 64 highest order bits from a 128bit integer"""
    return "{:032x}".format(large_int)[:16]


class Span(object):
    __slots__ = [
        # Public span attributes
        "service",
        "name",
        "_resource",
        "_span_api",
        "span_id",
        "trace_id",
        "parent_id",
        "_meta",
        "_meta_struct",
        "error",
        "_metrics",
        "_store",
        "span_type",
        "start_ns",
        "duration_ns",
        # Internal attributes
        "_context",
        "_local_root",
        "_parent",
        "_ignored_exceptions",
        "_on_finish_callbacks",
        "_links",
        "_events",
        "__weakref__",
    ]

    def __init__(
        self,
        name,  # type: str
        service=None,  # type: Optional[str]
        resource=None,  # type: Optional[str]
        span_type=None,  # type: Optional[str]
        trace_id=None,  # type: Optional[int]
        span_id=None,  # type: Optional[int]
        parent_id=None,  # type: Optional[int]
        start=None,  # type: Optional[int]
        context=None,  # type: Optional[Context]
        on_finish=None,  # type: Optional[List[Callable[[Span], None]]]
        span_api=SPAN_API_DATADOG,  # type: str
        links=None,  # type: Optional[List[SpanLink]]
    ):
        # type: (...) -> None
        """
        Create a new span. Call `finish` once the traced operation is over.

        **Note:** A ``Span`` should only be accessed or modified in the process
        that it was created in. Using a ``Span`` from within a child process
        could result in a deadlock or unexpected behavior.

        :param str name: the name of the traced operation.

        :param str service: the service name
        :param str resource: the resource name
        :param str span_type: the span type

        :param int trace_id: the id of this trace's root span.
        :param int parent_id: the id of this span's direct parent span.
        :param int span_id: the id of this span.

        :param int start: the start time of request as a unix epoch in seconds
        :param object context: the Context of the span.
        :param on_finish: list of functions called when the span finishes.
        """
        # pre-conditions
        if not (span_id is None or isinstance(span_id, int)):
            raise TypeError("span_id must be an integer")
        if not (trace_id is None or isinstance(trace_id, int)):
            raise TypeError("trace_id must be an integer")
        if not (parent_id is None or isinstance(parent_id, int)):
            raise TypeError("parent_id must be an integer")

        # required span info
        self.name = name
        self.service = service
        self._resource = [resource or name]
        self.span_type = span_type
        self._span_api = span_api

        # tags / metadata
        self._meta = {}  # type: _MetaDictType
        self.error = 0
        self._metrics = {}  # type: _MetricDictType

        self._meta_struct: Dict[str, Dict[str, Any]] = {}

        # timing
        self.start_ns = time_ns() if start is None else int(start * 1e9)  # type: int
        self.duration_ns = None  # type: Optional[int]

        # tracing
        if trace_id is not None:
            self.trace_id = trace_id  # type: int
        elif config._128_bit_trace_id_enabled:
            self.trace_id = _rand128bits()
        else:
            self.trace_id = _rand64bits()
        self.span_id = span_id or _rand64bits()  # type: int
        self.parent_id = parent_id  # type: Optional[int]
        self._on_finish_callbacks = [] if on_finish is None else on_finish

        self._context = context._with_span(self) if context else None  # type: Optional[Context]

        self._links = {}  # type: Dict[int, SpanLink]
        if links:
            self._links = {link.span_id: link for link in links}
        self._events = []  # type: List[SpanEvent]
        self._parent = None  # type: Optional[Span]
        self._ignored_exceptions = None  # type: Optional[List[Exception]]
        self._local_root = None  # type: Optional[Span]
        self._store = None  # type: Optional[Dict[str, Any]]

    def _ignore_exception(self, exc):
        # type: (Exception) -> None
        if self._ignored_exceptions is None:
            self._ignored_exceptions = [exc]
        else:
            self._ignored_exceptions.append(exc)

    def _set_ctx_item(self, key, val):
        # type: (str, Any) -> None
        if not self._store:
            self._store = {}
        self._store[key] = val

    def _set_ctx_items(self, items):
        # type: (Dict[str, Any]) -> None
        if not self._store:
            self._store = {}
        self._store.update(items)

    def _get_ctx_item(self, key):
        # type: (str) -> Optional[Any]
        if not self._store:
            return None
        return self._store.get(key)

    @property
    def _trace_id_64bits(self):
        return _get_64_lowest_order_bits_as_int(self.trace_id)

    @property
    def start(self):
        # type: () -> float
        """The start timestamp in Unix epoch seconds."""
        return self.start_ns / 1e9

    @start.setter
    def start(self, value):
        # type: (Union[int, float]) -> None
        self.start_ns = int(value * 1e9)

    @property
    def resource(self):
        return self._resource[0]

    @resource.setter
    def resource(self, value):
        self._resource[0] = value

    @property
    def finished(self):
        # type: () -> bool
        return self.duration_ns is not None

    @finished.setter
    def finished(self, value):
        # type: (bool) -> None
        """Finishes the span if set to a truthy value.

        If the span is already finished and a truthy value is provided
        no action will occur.
        """
        if value:
            if not self.finished:
                self.duration_ns = time_ns() - self.start_ns
        else:
            self.duration_ns = None

    @property
    def duration(self):
        # type: () -> Optional[float]
        """The span duration in seconds."""
        if self.duration_ns is not None:
            return self.duration_ns / 1e9
        return None

    @duration.setter
    def duration(self, value):
        # type: (float) -> None
        self.duration_ns = int(value * 1e9)

    @property
    def sampled(self):
        # type: () -> Optional[bool]
        deprecate(
            "span.sampled is deprecated and will be removed in a future version of the tracer.",
            message="""span.sampled references the state of span.context.sampling_priority.
            Please use span.context.sampling_priority instead to check if a span is sampled.""",
            category=DDTraceDeprecationWarning,
        )
        if self.context.sampling_priority is None:
            # this maintains original span.sampled behavior, where all spans would start
            # with span.sampled = True until sampling runs
            return True
        return self.context.sampling_priority > 0

    @sampled.setter
    def sampled(self, value):
        deprecate(
            "span.sampled is deprecated and will be removed in a future version of the tracer.",
            message="""span.sampled has a no-op setter.
            Please use span.set_tag('manual.keep'/'manual.drop') to keep or drop spans.""",
            category=DDTraceDeprecationWarning,
        )

    def finish(self, finish_time=None):
        # type: (Optional[float]) -> None
        """Mark the end time of the span and submit it to the tracer.
        If the span has already been finished don't do anything.

        :param finish_time: The end time of the span, in seconds. Defaults to ``now``.
        """
        if finish_time is None:
            self._finish_ns(time_ns())
        else:
            self._finish_ns(int(finish_time * 1e9))

    def _finish_ns(self, finish_time_ns):
        # type: (int) -> None
        if self.duration_ns is not None:
            return

        # be defensive so we don't die if start isn't set
        self.duration_ns = finish_time_ns - (self.start_ns or finish_time_ns)

        for cb in self._on_finish_callbacks:
            cb(self)

    def _override_sampling_decision(self, decision):
        self.context.sampling_priority = decision
        set_sampling_decision_maker(self.context, SamplingMechanism.MANUAL)
        for key in (SAMPLING_RULE_DECISION, SAMPLING_AGENT_DECISION, SAMPLING_LIMIT_DECISION):
            if key in self._local_root._metrics:
                del self._local_root._metrics[key]

    def set_tag(self, key: _TagNameType, value: Any = None) -> None:
        """Set a tag key/value pair on the span.

        Keys must be strings, values must be ``str``-able.

        :param key: Key to use for the tag
        :type key: str
        :param value: Value to assign for the tag
        :type value: ``str``-able value
        """

        if not isinstance(key, str):
            log.warning("Ignoring tag pair %s:%s. Key must be a string.", key, value)
            return

        # Special case, force `http.status_code` as a string
        # DEV: `http.status_code` *has* to be in `meta` for metrics
        #   calculated in the trace agent
        if key == http.STATUS_CODE:
            value = str(value)

        # Determine once up front
        val_is_an_int = is_integer(value)

        # Explicitly try to convert expected integers to `int`
        # DEV: Some integrations parse these values from strings, but don't call `int(value)` themselves
        INT_TYPES = (net.TARGET_PORT,)
        if key in INT_TYPES and not val_is_an_int:
            try:
                value = int(value)
                val_is_an_int = True
            except (ValueError, TypeError):
                pass

        # Set integers that are less than equal to 2^53 as metrics
        if value is not None and val_is_an_int and abs(value) <= 2**53:
            self.set_metric(key, value)
            return

        # All floats should be set as a metric
        elif isinstance(value, float):
            self.set_metric(key, value)
            return

        # Key should explicitly be converted to a float if needed
        elif key in _NUMERIC_TAGS:
            if value is None:
                log.debug("ignoring not number metric %s:%s", key, value)
                return

            try:
                # DEV: `set_metric` will try to cast to `float()` for us
                self.set_metric(key, value)
            except (TypeError, ValueError):
                log.warning("error setting numeric metric %s:%s", key, value)

            return

        elif key == MANUAL_KEEP_KEY:
            self._override_sampling_decision(USER_KEEP)
            return
        elif key == MANUAL_DROP_KEY:
            self._override_sampling_decision(USER_REJECT)
            return
        elif key == SERVICE_KEY:
            self.service = value
        elif key == SERVICE_VERSION_KEY:
            # Also set the `version` tag to the same value
            # DEV: Note that we do no return, we want to set both
            self.set_tag(VERSION_KEY, value)
        elif key == SPAN_MEASURED_KEY:
            # Set `_dd.measured` tag as a metric
            # DEV: `set_metric` will ensure it is an integer 0 or 1
            if value is None:
                value = 1
            self.set_metric(key, value)
            return

        try:
            self._meta[key] = str(value)
            if key in self._metrics:
                del self._metrics[key]
        except Exception:
            log.warning("error setting tag %s, ignoring it", key, exc_info=True)

    def set_struct_tag(self, key: str, value: Dict[str, Any]) -> None:
        """
        Set a tag key/value pair on the span meta_struct
        Currently it will only be exported with V3/V4 encoding
        """
        self._meta_struct[key] = value

    def get_struct_tag(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the given struct or None if it doesn't exist."""
        return self._meta_struct.get(key, None)

    def set_tag_str(self, key: _TagNameType, value: Text) -> None:
        """Set a value for a tag. Values are coerced to unicode in Python 2 and
        str in Python 3, with decoding errors in conversion being replaced with
        U+FFFD.
        """
        try:
            self._meta[key] = ensure_text(value, errors="replace")
        except Exception as e:
            if config._raise:
                raise e
            log.warning("Failed to set text tag '%s'", key, exc_info=True)

    def get_tag(self, key: _TagNameType) -> Optional[Text]:
        """Return the given tag or None if it doesn't exist."""
        return self._meta.get(key, None)

    def get_tags(self) -> _MetaDictType:
        """Return all tags."""
        return self._meta.copy()

    def set_tags(self, tags: Dict[_TagNameType, Any]) -> None:
        """Set a dictionary of tags on the given span. Keys and values
        must be strings (or stringable)
        """
        if tags:
            for k, v in iter(tags.items()):
                self.set_tag(k, v)

    def set_metric(self, key: _TagNameType, value: NumericType) -> None:
        """This method sets a numeric tag value for the given key."""
        # Enforce a specific constant for `_dd.measured`
        if key == SPAN_MEASURED_KEY:
            try:
                value = int(bool(value))
            except (ValueError, TypeError):
                log.warning("failed to convert %r tag to an integer from %r", key, value)
                return

        # FIXME[matt] we could push this check to serialization time as well.
        # only permit types that are commonly serializable (don't use
        # isinstance so that we convert unserializable types like numpy
        # numbers)
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (ValueError, TypeError):
                log.debug("ignoring not number metric %s:%s", key, value)
                return

        # don't allow nan or inf
        if math.isnan(value) or math.isinf(value):
            log.debug("ignoring not real metric %s:%s", key, value)
            return

        if key in self._meta:
            del self._meta[key]
        self._metrics[key] = value

    def set_metrics(self, metrics: _MetricDictType) -> None:
        """Set a dictionary of metrics on the given span. Keys must be
        must be strings (or stringable). Values must be numeric.
        """
        if metrics:
            for k, v in metrics.items():
                self.set_metric(k, v)

    def get_metric(self, key: _TagNameType) -> Optional[NumericType]:
        """Return the given metric or None if it doesn't exist."""
        return self._metrics.get(key)

    def _set_baggage_item(self, key, value):
        # type: (str, Any) -> Span
        """Sets a baggage item in the span context of this span.
        Baggage is used to propagate state between spans (in-process, http/https).
        """
        self._context = self.context._with_baggage_item(key, value)
        return self

    def _add_event(self, name, attributes=None, timestamp=None):
        # type: (str, Optional[Dict[str, str]], Optional[int]) -> None
        """Add an event to the span."""
        self._events.append(SpanEvent(name, attributes, timestamp))

    def _get_baggage_item(self, key):
        # type: (str) -> Optional[Any]
        """Gets a baggage item from the span context of this span."""
        return self.context._get_baggage_item(key)

    def get_metrics(self) -> _MetricDictType:
        """Return all metrics."""
        return self._metrics.copy()

    def set_traceback(self, limit: Optional[int] = None):
        """If the current stack has an exception, tag the span with the
        relevant error info. If not, tag it with the current python stack.
        """
        if limit is None:
            limit = config._span_traceback_max_size

        (exc_type, exc_val, exc_tb) = sys.exc_info()

        if exc_type and exc_val and exc_tb:
            self.set_exc_info(exc_type, exc_val, exc_tb)
        else:
            tb = "".join(traceback.format_stack(limit=limit + 1)[:-1])
            self._meta[ERROR_STACK] = tb

    def set_exc_info(self, exc_type, exc_val, exc_tb):
        # type: (Any, Any, Any) -> None
        """Tag the span with an error tuple as from `sys.exc_info()`."""
        if not (exc_type and exc_val and exc_tb):
            return  # nothing to do

        # SystemExit(0) is not an error
        if issubclass(exc_type, SystemExit) and exc_val.code == 0:
            return

        if self._ignored_exceptions and any([issubclass(exc_type, e) for e in self._ignored_exceptions]):  # type: ignore[arg-type]  # noqa:F401
            return

        self.error = 1
        self._set_exc_tags(exc_type, exc_val, exc_tb)

    def _set_exc_tags(self, exc_type, exc_val, exc_tb):
        limit = config._span_traceback_max_size
        if limit is None:
            limit = 30

        # get the traceback
        buff = StringIO()
        traceback.print_exception(exc_type, exc_val, exc_tb, file=buff, limit=limit)
        tb = buff.getvalue()

        # readable version of type (e.g. exceptions.ZeroDivisionError)
        exc_type_str = "%s.%s" % (exc_type.__module__, exc_type.__name__)

        self._meta[ERROR_MSG] = str(exc_val)
        self._meta[ERROR_TYPE] = exc_type_str
        self._meta[ERROR_STACK] = tb

    def _pprint(self):
        # type: () -> str
        """Return a human readable version of the span."""
        data = [
            ("name", self.name),
            ("id", self.span_id),
            ("trace_id", self.trace_id),
            ("parent_id", self.parent_id),
            ("service", self.service),
            ("resource", self.resource),
            ("type", self.span_type),
            ("start", self.start),
            ("end", None if not self.duration else self.start + self.duration),
            ("duration", self.duration),
            ("error", self.error),
            ("tags", dict(sorted(self._meta.items()))),
            ("metrics", dict(sorted(self._metrics.items()))),
        ]
        return " ".join(
            # use a large column width to keep pprint output on one line
            "%s=%s" % (k, pprint.pformat(v, width=1024**2).strip())
            for (k, v) in data
        )

    @property
    def context(self):
        # type: () -> Context
        """Return the trace context for this span."""
        if self._context is None:
            self._context = Context(trace_id=self.trace_id, span_id=self.span_id, is_remote=False)
        return self._context

    def link_span(self, context, attributes=None):
        # type: (Context, Optional[Dict[str, Any]]) -> None
        """Defines a causal relationship between two spans"""
        if not context.trace_id or not context.span_id:
            raise ValueError(f"Invalid span or trace id. trace_id:{context.trace_id} span_id:{context.span_id}")

        self.set_link(
            trace_id=context.trace_id,
            span_id=context.span_id,
            tracestate=context._tracestate,
            flags=int(context._traceflags),
            attributes=attributes,
        )

    def set_link(self, trace_id, span_id, tracestate=None, flags=None, attributes=None):
        # type: (int, int, Optional[str], Optional[int], Optional[Dict[str, Any]]) -> None
        if attributes is None:
            attributes = dict()

        if span_id in self._links:
            log.debug(
                "Span %d already linked to span %d. Overwriting existing link: %s",
                self.span_id,
                span_id,
                str(self._links[span_id]),
            )
        self._links[span_id] = SpanLink(
            trace_id=trace_id,
            span_id=span_id,
            tracestate=tracestate,
            flags=flags,
            attributes=attributes,
        )

    def finish_with_ancestors(self):
        # type: () -> None
        """Finish this span along with all (accessible) ancestors of this span.

        This method is useful if a sudden program shutdown is required and finishing
        the trace is desired.
        """
        span = self  # type: Optional[Span]
        while span is not None:
            span.finish()
            span = span._parent

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type:
                self.set_exc_info(exc_type, exc_val, exc_tb)
            self.finish()
        except Exception:
            log.exception("error closing trace")

    def __repr__(self):
        return "<Span(id=%s,trace_id=%s,parent_id=%s,name=%s)>" % (
            self.span_id,
            self.trace_id,
            self.parent_id,
            self.name,
        )


def _is_top_level(span):
    # type: (Span) -> bool
    """Return whether the span is a "top level" span.

    Top level meaning the root of the trace or a child span
    whose service is different from its parent.
    """
    return (span._local_root is span) or (
        span._parent is not None and span._parent.service != span.service and span.service is not None
    )
