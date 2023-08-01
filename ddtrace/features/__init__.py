import abc
import binascii
from dataclasses import dataclass
import json
import os
import time
import typing

from open_feature.evaluation_context.evaluation_context import EvaluationContext
from open_feature.exception.error_code import ErrorCode
from open_feature.flag_evaluation.flag_evaluation_details import FlagEvaluationDetails
from open_feature.flag_evaluation.flag_type import FlagType
from open_feature.flag_evaluation.reason import Reason
from open_feature.flag_evaluation.resolution_details import FlagResolutionDetails
from open_feature.hooks.hook import Hook
from open_feature.hooks.hook import HookContext
from open_feature.open_feature_api import AbstractProvider
from open_feature.provider.metadata import Metadata

from ddtrace import tracer
from ddtrace.debugging._expressions import DDExpression
from ddtrace.debugging._expressions import DDExpressionEvaluationError
from ddtrace.debugging._expressions import dd_compile
from ddtrace.internal.remoteconfig._connectors import PublisherSubscriberConnector
from ddtrace.internal.remoteconfig._publishers import RemoteConfigPublisher
from ddtrace.internal.remoteconfig._pubsub import PubSub
from ddtrace.internal.remoteconfig._subscribers import RemoteConfigSubscriber
from ddtrace.internal.remoteconfig.worker import remoteconfig_poller


T = typing.TypeVar("T", covariant=True)


class Match(abc.ABC, typing.Generic[T]):
    @abc.abstractclassmethod
    def get_value_for(
        self, variants: dict[str, T], default_variant: str, evaluation_context: typing.Optional[EvaluationContext]
    ) -> T:
        pass


@dataclass(frozen=True)
class StaticMatch(Match, typing.Generic[T]):
    variant: str

    def get_value_for(
        self, variants: dict[str, T], default_variant: str, evaluation_context: typing.Optional[EvaluationContext]
    ) -> FlagResolutionDetails[T]:
        try:
            return FlagResolutionDetails(
                value=variants[self.variant],
                reason=Reason.STATIC,
                variant=self.variant,
            )
        except KeyError:
            return FlagResolutionDetails(
                value=variants[default_variant],
                reason=Reason.ERROR,
                variant=default_variant,
                error_code=ErrorCode.GENERAL,
                error_message=f"StaticMatch variant '{self.variant}' not available from '{','.join(variants.keys())}'",
            )


@dataclass(frozen=True)
class RolloutMatch(Match, typing.Generic[T]):
    variant: str
    targeting_key: typing.Optional[DDExpression]
    percentage: float

    def get_value_for(
        self, variants: dict[str, T], default_variant: str, evaluation_context: typing.Optional[EvaluationContext]
    ) -> FlagResolutionDetails[T]:
        if not evaluation_context:
            return FlagResolutionDetails(
                value=variants[default_variant],
                reason=Reason.DISABLED,
                variant=default_variant,
            )

        if self.targeting_key:
            res = self.targeting_key.eval(evaluation_context.attributes)
            if not res:
                return FlagResolutionDetails(
                    value=variants[default_variant],
                    reason=Reason.ERROR,
                    variant=default_variant,
                    error_code=ErrorCode.TARGETING_KEY_MISSING,
                )
            rollout_key: bytes = bytes(str(res), "utf-8")
        elif evaluation_context.targeting_key:
            rollout_key: bytes = bytes(evaluation_context.targeting_key, "utf-8")
        else:
            return FlagResolutionDetails(
                value=variants[default_variant],
                reason=Reason.ERROR,
                variant=default_variant,
                error_code=ErrorCode.TARGETING_KEY_MISSING,
            )
        rollout_hash: int = binascii.crc32(rollout_key)

        threshold = (self.percentage / 100.0) * (1 << 32) - 1
        if rollout_hash <= threshold:
            try:
                return FlagResolutionDetails(
                    value=variants[self.variant],
                    reason=Reason.TARGETING_MATCH,
                    variant=self.variant,
                )
            except KeyError:
                return FlagResolutionDetails(
                    value=variants[default_variant],
                    reason=Reason.ERROR,
                    variant=default_variant,
                    error_code=ErrorCode.GENERAL,
                    error_message=f"RolloutMatch variant '{self.variant}' not available from '{','.join(variants.keys())}'",
                )
        return FlagResolutionDetails(
            value=variants[default_variant],
            reason=Reason.DISABLED,
            variant=default_variant,
        )


@dataclass(frozen=True)
class ContextEvaluator:
    expr: typing.Optional[DDExpression]
    on_match: Match

    def matches(self, evaluation_context: EvaluationContext) -> bool:
        # If we have an expression to evaluate, check the match
        if self.expr:
            return self.expr.eval(evaluation_context.attributes)

        return True

    def get_value_details(
        self, variants: dict[str, T], default_variant: str, evaluation_context: EvaluationContext
    ) -> FlagResolutionDetails[T]:
        return self.on_match.get_value_for(variants, default_variant, evaluation_context)


@dataclass(frozen=True)
class Flag(typing.Generic[T]):
    key: str
    default_variant: str
    variants: dict[str, T]
    targeting: list[ContextEvaluator]

    def get_value_details(
        self, evaluation_context: typing.Optional[EvaluationContext] = None
    ) -> FlagResolutionDetails[T]:
        # No targeting set for this flag, applies to all contexts
        if not self.targeting:
            return FlagResolutionDetails(
                value=self.variants[self.default_variant],
                reason=Reason.STATIC,
                variant=self.default_variant,
            )

        # Targeting is set, but we don't have an evaluation context, this flag doesn't match
        if not evaluation_context:
            return FlagResolutionDetails(
                value=self.variants[self.default_variant],
                reason=Reason.DISABLED,
                variant=self.default_variant,
            )

        # If any of the targeting rules match, then return True, else return False
        for ctx_eval in self.targeting:
            try:
                if ctx_eval.matches(evaluation_context):
                    return ctx_eval.get_value_details(self.variants, self.default_variant, evaluation_context)
            except DDExpressionEvaluationError as e:
                return FlagResolutionDetails(
                    value=self.variants[self.default_variant],
                    variant=self.default_variant,
                    reason=Reason.ERROR,
                    error_code=ErrorCode.GENERAL,
                    error_message=f"Error evaluating targeting rule: {ctx_eval!r}: {e}",
                )

        return FlagResolutionDetails(
            value=self.variants[self.default_variant],
            reason=Reason.DISABLED,
            variant=self.default_variant,
        )

    def get_value_for(self, evaluation_context: typing.Optional[EvaluationContext] = None) -> T:
        details = self.get_value_details(evaluation_context)
        return details.value


FlagStorage = typing.Dict[str, Flag]


class OpenFeatureHook(Hook):
    def before(self, hook_context: HookContext, hints: dict) -> EvaluationContext:
        """
        Runs before flag is resolved.

        :param hook_context: Information about the particular flag evaluation
        :param hints: An immutable mapping of data for users to
        communicate to the hooks.
        :return: An EvaluationContext. It will be merged with the
        EvaluationContext instances from other hooks, the client and API.
        """
        return EvaluationContext(
            attributes={
                "datadog": {
                    "service": os.environ.get("DD_SERVICE") or None,
                    "version": os.environ.get("DD_VERSION") or None,
                    "env": os.environ.get("DD_ENV") or None,
                },
            },
        )

    def after(self, hook_context: HookContext, details: FlagEvaluationDetails, hints: dict):
        """
        Runs after a flag is resolved.

        :param hook_context: Information about the particular flag evaluation
        :param details: Information about how the flag was resolved,
        including any resolved values.
        :param hints: A mapping of data for users to communicate to the hooks.
        """
        span = tracer.current_root_span()
        if not span:
            return

        span.set_tag(f"features.{details.flag_key}.value", details.value)
        span.set_tag(f"features.{details.flag_key}.variant", details.variant)
        if details.reason:
            span.set_tag(f"features.{details.flag_key}.reason", details.reason)
        if details.error_code:
            span.set_tag(f"features.{details.flag_key}.error_code", details.error_code)
        if details.error_message:
            span.set_tag(f"features.{details.flag_key}.error_message", details.error_message)

    def error(self, hook_context: HookContext, exception: Exception, hints: dict):
        """
        Run when evaluation encounters an error. Errors thrown will be swallowed.

        :param hook_context: Information about the particular flag evaluation
        :param exception: The exception that was thrown
        :param hints: A mapping of data for users to communicate to the hooks.
        """
        pass

    def finally_after(self, hook_context: HookContext, hints: dict):
        """
        Run after flag evaluation, including any error processing.
        This will always run. Errors will be swallowed.

        :param hook_context: Information about the particular flag evaluation
        :param hints: A mapping of data for users to communicate to the hooks.
        """
        pass

    def supports_flag_value_type(self, flag_type: FlagType) -> bool:
        """
        Check to see if the hook supports the particular flag type.

        :param flag_type: particular type of the flag
        :return: a boolean containing whether the flag type is supported (True)
        or not (False)
        """
        return True


class OpenFeatureProvider(AbstractProvider):
    def __init__(self):
        self._flags: FlagStorage = {}
        self._hook = OpenFeatureHook()
        self._metadata = Metadata(name="Datadog")

    def _update_flags(self, flags: FlagStorage):
        self._flags = flags

    def get_metadata(self) -> Metadata:
        return self._metadata

    def get_provider_hooks(self) -> typing.List[Hook]:
        return [self._hook]

    def resolve_boolean_details(
        self,
        flag_key: str,
        default_value: bool,
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[bool]:
        return self._resolve_details(flag_key, default_value, evaluation_context)

    def resolve_string_details(
        self,
        flag_key: str,
        default_value: str,
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[str]:
        return self._resolve_details(flag_key, default_value, evaluation_context)

    def resolve_integer_details(
        self,
        flag_key: str,
        default_value: int,
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[int]:
        return self._resolve_details(flag_key, default_value, evaluation_context)

    def resolve_float_details(
        self,
        flag_key: str,
        default_value: float,
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[float]:
        return self._resolve_details(flag_key, default_value, evaluation_context)

    def resolve_object_details(
        self,
        flag_key: str,
        default_value: typing.Union[dict, list],
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[typing.Union[dict, list]]:
        return self._resolve_details(flag_key, default_value, evaluation_context)

    def _resolve_details(
        self,
        flag_key: str,
        default_value: T,
        evaluation_context: typing.Optional[EvaluationContext] = None,
    ) -> FlagResolutionDetails[T]:
        flag_key = flag_key.lower()

        # TODO: Filter flags based on evaluation_context ?
        if flag_key not in self._flags:
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.FLAG_NOT_FOUND,
                error_message=f"Flag '{flag_key}' not found",
            )

        # Is the feature enabled?
        flag = self._flags[flag_key]
        details = flag.get_value_details(evaluation_context)

        if isinstance(details.value, type(default_value)):
            return details

        flag_value: T = None

        default_value_type = type(default_value)
        if default_value_type is bool:
            if isinstance(details.value, str):
                flag_value = details.value.lower() in ("true", "1")
            else:
                flag_value = bool(details.value)
        elif default_value_type is str:
            flag_value = str(details.value)
        elif default_value_type is int:
            flag_value = int(details.value)
        elif default_value_type is float:
            flag_value = float(details.value)
        elif default_value_type in (dict, list):
            if isinstance(details.value, str):
                flag_value = json.loads(details.value)
            else:
                return FlagResolutionDetails(
                    value=default_value,
                    reason=Reason.ERROR,
                    error_code=ErrorCode.TYPE_MISMATCH,
                    error_message=f"Flag results of type '{type(details.value)}' is not supported for dict|list",
                )
        else:
            return FlagResolutionDetails(
                value=default_value,
                reason=Reason.ERROR,
                error_code=ErrorCode.TYPE_MISMATCH,
                error_message=f"Default value of type '{type(default_value)}' is not supported",
            )

        return FlagResolutionDetails(
            value=flag_value,
            reason=details.reason,
            variant=details.variant,
            error_code=details.error_code,
            error_message=details.error_message,
        )


class FeatureFlagsRC(PubSub):
    __subscriber_class__ = RemoteConfigSubscriber
    __publisher_class__ = RemoteConfigPublisher
    __shared_data__ = PublisherSubscriberConnector()

    def __init__(self):
        self._publisher = self.__publisher_class__(self.__shared_data__)
        self._subscriber = self.__subscriber_class__(self.__shared_data__, self.callback, "TRACING")

    def callback(self, metadata, test_tracer=None):
        if not metadata["config"]:
            return

        ff = metadata["config"][0]["feature_flags"]
        flags = {}
        for feature_flag in ff["flags"]:
            targeting: list[ContextEvaluator] = []

            for target in feature_flag.get("targeting", []):
                on_match: typing.Optional[Match] = None
                if target["on_match"]["type"] == "static":
                    on_match = StaticMatch(target["on_match"]["value"])
                elif target["on_match"]["type"] == "rollout":
                    value = target["on_match"]["value"]
                    targeting_key = None
                    if value["targeting_key"]:
                        targeting_key = DDExpression(
                            dsl=value["targeting_key"]["dsl"],
                            callable=dd_compile(value["targeting_key"]["json"]),
                        )
                    on_match = RolloutMatch(
                        variant=value["variant"],
                        targeting_key=targeting_key,
                        percentage=value["percentage"],
                    )
                else:
                    raise ValueError(f"Unexpected target on_match type of {target['on_match']['type']!r}")

                expr: typing.Optional[DDExpression] = None
                if "expr" in target:
                    expr = DDExpression(dsl=target["expr"]["dsl"], callable=dd_compile(target["expr"]["json"]))

                targeting.append(
                    ContextEvaluator(
                        expr=expr,
                        on_match=on_match,
                    )
                )

            flag = Flag(
                key=feature_flag["key"].lower(),
                default_variant=feature_flag["default_variant"],
                variants=feature_flag["variants"],
                targeting=targeting,
            )
            flags[flag.key] = flag

        _provider._update_flags(flags)


_apm_rc = FeatureFlagsRC()


def enable():
    remoteconfig_poller.register("FEATURE_FLAGS", _apm_rc)


def disable():
    remoteconfig_poller.unregister("FEATURE_FLAGS")


_provider: OpenFeatureProvider = OpenFeatureProvider()


def get_provider():
    return _provider


def wait_for_flags(timeout=None, wait=0.2):
    start = time.time()
    while True:
        elapsed = time.time() - start
        if timeout and elapsed > timeout:
            raise Exception("Took too long waiting for feature flags to load")

        if _provider._flags:
            break

        time.sleep(wait)
