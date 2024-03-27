from typing import TYPE_CHECKING

import attr

from ddtrace._trace.processor import SpanProcessor
from ddtrace.appsec._constants import APPSEC
from ddtrace.appsec._constants import IAST
from ddtrace.constants import ORIGIN_KEY
from ddtrace.ext import SpanTypes
from ddtrace.internal import core
from ddtrace.internal.logger import get_logger

from .._trace_utils import _asm_manual_keep
from . import oce
from ._metrics import _set_metric_iast_request_tainted
from ._metrics import _set_span_tag_iast_executed_sink
from ._metrics import _set_span_tag_iast_request_tainted
from ._utils import _is_iast_enabled


if TYPE_CHECKING:  # pragma: no cover
    from typing import Optional  # noqa:F401

    from ddtrace._trace.span import Span  # noqa:F401

log = get_logger(__name__)


@attr.s(eq=False)
class AppSecIastSpanProcessor(SpanProcessor):
    @staticmethod
    def is_span_analyzed(span=None):
        # type: (Optional[Span]) -> bool
        if span is None:
            from ddtrace import tracer

            span = tracer.current_root_span()

        if span and span.span_type == SpanTypes.WEB and core.get_item(IAST.REQUEST_IAST_ENABLED, span=span):
            return True
        return False

    def on_span_start(self, span):
        # type: (Span) -> None
        if span.span_type != SpanTypes.WEB:
            return

        if not _is_iast_enabled():
            return

        from ._taint_tracking import create_context

        create_context()

        request_iast_enabled = False
        if oce.acquire_request(span):
            request_iast_enabled = True

        core.set_item(IAST.REQUEST_IAST_ENABLED, request_iast_enabled, span=span)

    def on_span_finish(self, span):
        # type: (Span) -> None
        """Report reported vulnerabilities.

        Span Tags:
            - `_dd.iast.json`: Only when one or more vulnerabilities have been detected will we include the custom tag.
            - `_dd.iast.enabled`: Set to 1 when IAST is enabled in a request. If a request is disabled
              (e.g. by sampling), then it is not set.
        """
        if span.span_type != SpanTypes.WEB:
            return

        if not core.get_item(IAST.REQUEST_IAST_ENABLED, span=span):
            span.set_metric(IAST.ENABLED, 0.0)
            return

        from ._taint_tracking import reset_context  # noqa: F401
        from ._utils import _iast_report_to_str

        span.set_metric(IAST.ENABLED, 1.0)

        data = core.get_item(IAST.CONTEXT_KEY, span=span)

        if data:
            span.set_tag_str(IAST.JSON, _iast_report_to_str(data))
            _asm_manual_keep(span)

        _set_metric_iast_request_tainted()
        _set_span_tag_iast_request_tainted(span)
        _set_span_tag_iast_executed_sink(span)
        reset_context()

        if span.get_tag(ORIGIN_KEY) is None:
            span.set_tag_str(ORIGIN_KEY, APPSEC.ORIGIN_VALUE)

        oce.release_request()
