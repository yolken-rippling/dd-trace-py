from types import ModuleType
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from ddtrace.internal.agent import get_stats_url
from ddtrace.internal.dogstatsd import get_dogstatsd_client
from ddtrace.internal.utils import get_argument_value
from ddtrace.internal.wrapping import wrap


class _MLFlowIntegration:
    def __init__(self, mlflow, stats_url):
        # type: (ModuleType, str) -> None
        self._mlflow = mlflow
        self._statsd = get_dogstatsd_client(stats_url, namespace="mlflow")

    def get_active_run_statsd_tags(self):
        # type: () -> List[str]

        active_run = self._mlflow.active_run()
        if not active_run:
            return []

        tags = [
            "mlflow.experiment_id:{}".format(active_run.info.experiment_id),
            "mlflow.run_id:{}".format(active_run.info.run_id),
            "mlflow.run_name:{}".format(active_run.info.run_name),
            "mlflow.run_uuid:{}".format(active_run.info.run_uuid),
            "mlflow.user_id:{}".format(active_run.info.user_id),
        ]
        for tag, value in active_run.data.tags.items():
            tags.append("{}:{}".format(tag, value))
        return tags

    def metric(self, kind, name, val, tags=None):
        # type: (str, str, Union[int, float], Optional[List[str]]) -> None
        """Set a metric using the OpenAI context from the given span."""
        if kind == "dist":
            self._statsd.distribution(name, val, tags=tags)
        elif kind == "incr":
            self._statsd.increment(name, val, tags=tags)
        elif kind == "gauge":
            self._statsd.gauge(name, val, tags=tags)
        else:
            raise ValueError("Unexpected metric type %r" % kind)


def _patch_with_integration(integration, fn):
    def _wrapper(*args, **kwargs):
        return fn(integration, *args, **kwargs)

    return _wrapper


def _patched_log_metric(integration, func, args, kwargs):
    # type: (_MLFlowIntegration, Callable, List[Any], Dict[str, Any]) -> Any
    # def log_metric(key: str, value: float, step: Optional[int] = None) -> None:

    try:
        return func(*args, **kwargs)
    finally:
        metric_key = get_argument_value(args, kwargs, 0, "key")  # type: Optional[str]
        metric_value = get_argument_value(args, kwargs, 1, "value")  # type: Optional[float]
        # step = get_argument_value(args, kwargs, 2, "step")  # type: Optional[int]
        if metric_key and metric_value is not None:
            tags = integration.get_active_run_statsd_tags()
            integration.metric("gauge", metric_key, metric_value, tags=tags)


def _patched_log_metrics(integration, func, args, kwargs):
    # type: (_MLFlowIntegration, Callable, List[Any], Dict[str, Any]) -> Any
    # def log_metrics(metrics: Dict[str, float], step: Optional[int] = None) -> None:

    try:
        return func(*args, **kwargs)
    finally:
        metrics = get_argument_value(args, kwargs, 0, "metrics")  # type: Optional[Dict[str, float]]
        # step = get_argument_value(args, kwargs, 1, "step")  # type: Optional[int]
        if metrics:
            tags = integration.get_active_run_statsd_tags()
            for metric_key, metric_value in metrics.items():
                integration.metric("gauge", metric_key, metric_value, tags=tags)


def _patched_client_log_metric(integration, func, args, kwargs):
    # type: (_MLFlowIntegration, Callable, List[Any], Dict[str, Any]) -> Any
    # def log_metric(
    #     self,
    #     run_id: str,
    #     key: str,
    #     value: float,
    #     timestamp: Optional[int] = None,
    #     step: Optional[int] = None,
    # ) -> None:
    try:
        return func(*args, **kwargs)
    finally:
        metric_key = get_argument_value(args, kwargs, 2, "key")  # type: Optional[str]
        metric_value = get_argument_value(args, kwargs, 3, "value")  # type: Optional[float]
        if metric_key and metric_value is not None:
            tags = integration.get_active_run_statsd_tags()
            integration.metric("gauge", metric_key, metric_value, tags=tags)


def _patched_client_log_batch(integration, func, args, kwargs):
    # type: (_MLFlowIntegration, Callable, List[Any], Dict[str, Any]) -> Any
    # def log_batch(
    #     self,
    #     run_id: str,
    #     metrics: Sequence[Metric] = (),
    #     params: Sequence[Param] = (),
    #     tags: Sequence[RunTag] = (),
    # ) -> None:
    try:
        return func(*args, **kwargs)
    finally:
        metrics = get_argument_value(args, kwargs, 2, "metrics")  # type: Optional[List[Any]]
        batch_tags = get_argument_value(args, kwargs, 4, "tags")  # type: Optional[List[Any]]
        if not metrics:
            return

        tags = integration.get_active_run_statsd_tags()
        if batch_tags:
            for tag in batch_tags:
                tags.append("{}:{}".format(tag.key, tag.value))

        for metric in metrics:
            integration.metric("gauge", metric.key, metric.value, tags=tags)


def patch():
    # type: () -> None
    # Avoid importing mlflow at the module level, eventually will be an import hook
    import mlflow

    if getattr(mlflow, "__datadog_patch", False):
        return

    """
    log_param,
    set_tag,
    delete_tag,
    log_artifacts,
    log_artifact,
    log_text,
    log_dict,
    log_image,
    log_figure,
    start_run,
    end_run,
    log_params,
    log_metrics,
    set_experiment_tags,
    set_experiment_tag,
    set_tags,
    """

    integration = _MLFlowIntegration(
        mlflow=mlflow,
        stats_url=get_stats_url(),
    )

    # Try to wrap as low level as we can, but fallback to public API wrapping
    try:
        wrap(
            mlflow.MlflowClient.log_metric,
            _patch_with_integration(integration, _patched_client_log_metric),
        )
        wrap(
            mlflow.MlflowClient.log_batch,
            _patch_with_integration(integration, _patched_client_log_batch),
        )
    except ImportError:
        wrap(mlflow.log_metric, _patch_with_integration(integration, _patched_log_metric))
        wrap(mlflow.log_metrics, _patch_with_integration(integration, _patched_log_metrics))

    setattr(mlflow, "__datadog_patch", True)


def unpatch():
    # type: () -> None
    # Avoid importing mlflow at the module level, eventually will be an import hook
    import mlflow

    if not getattr(mlflow, "__datadog_patch", False):
        return

    setattr(mlflow, "__datadog_patch", False)
