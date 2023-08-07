from ddtrace import tracer
from ddtrace.internal.agent import get_stats_url
from ddtrace.internal.dogstatsd import get_dogstatsd_client
from ddtrace.internal.utils import get_argument_value
from ddtrace.internal.wrapping import unwrap
from ddtrace.internal.wrapping import wrap
from ddtrace.settings import config


_statsd_client = None


def _wrapped_evaluate_internal(func, args, kwargs):
    # def _evaluate_internal(self, key: str, context: Union[Context, dict], default: Any, event_factory):
    global _statsd_client

    evaluation_detail = func(*args, **kwargs)

    try:
        key = get_argument_value(args, kwargs, 1, "key")
        variation_index = evaluation_detail.variation_index
        reason_kind = None
        if evaluation_detail.reason:
            reason_kind = evaluation_detail.reason["kind"]
    except Exception:
        return evaluation_detail

    if _statsd_client:
        tags = ["key:{}".format(key), "variation_index:{}".format(variation_index)]
        if reason_kind:
            tags.append("reason_kind:{}".format(reason_kind))
        _statsd_client.increment("datadog.features.evaluation", tags=tags)

    span = tracer.current_root_span()
    if not span:
        return evaluation_detail

    try:
        tag_prefix = "features.{}".format(key)
        span.set_tag("{}.variation_index".format(tag_prefix), variation_index)
        span.set_tag("{}.value".format(tag_prefix), evaluation_detail.value)
        if reason_kind:
            span.set_tag("{}.reason.kind".format(tag_prefix), reason_kind)
    finally:
        return evaluation_detail


def patch():
    import ldclient

    if getattr(ldclient, "_datadog_patch", False):
        return
    setattr(ldclient, "_datadog_patch", True)

    global _statsd_client
    if not _statsd_client:
        _statsd_client = get_dogstatsd_client(get_stats_url())

    wrap(ldclient.LDClient._evaluate_internal, _wrapped_evaluate_internal)


def unpatch():
    import ldclient

    if not getattr(ldclient, "_datadog_patch", False):
        return
    setattr(ldclient, "_datadog_patch", False)

    unwrap(ldclient.LDClient._evaluate_internal, _wrapped_evaluate_internal)
