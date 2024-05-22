from typing import Optional

from ddtrace import Span
from ddtrace import config
from ddtrace.ext import SpanTypes
from ddtrace.llmobs._constants import INPUT_DOCUMENTS
from ddtrace.llmobs._constants import INPUT_MESSAGES
from ddtrace.llmobs._constants import INPUT_VALUE
from ddtrace.llmobs._constants import LANGCHAIN_APM_SPAN_NAME
from ddtrace.llmobs._constants import ML_APP
from ddtrace.llmobs._constants import OUTPUT_DOCUMENTS
from ddtrace.llmobs._constants import OUTPUT_MESSAGES
from ddtrace.llmobs._constants import OUTPUT_VALUE
from ddtrace.llmobs._constants import SESSION_ID


def _get_input_tag_key_from_span_kind(span_kind):
    if span_kind == "llm":
        return INPUT_MESSAGES
    elif span_kind == "embedding" or "retrieval":
        return INPUT_DOCUMENTS
    else:
        return INPUT_VALUE


def _get_output_tag_key_from_span_kind(span_kind):
    if span_kind == "llm":
        return OUTPUT_MESSAGES
    elif span_kind == "retrieval":
        return OUTPUT_DOCUMENTS
    else:
        return OUTPUT_VALUE


def _get_nearest_llmobs_ancestor(span: Span) -> Optional[Span]:
    """Return the nearest LLMObs-type ancestor span of a given span."""
    if span.span_type != SpanTypes.LLM:
        return None
    parent = span._parent
    while parent:
        if parent.span_type == SpanTypes.LLM:
            return parent
        parent = parent._parent
    return None


def _get_llmobs_parent_id(span: Span) -> Optional[int]:
    """Return the span ID of the nearest LLMObs-type span in the span's ancestor tree."""
    nearest_llmobs_ancestor = _get_nearest_llmobs_ancestor(span)
    if nearest_llmobs_ancestor:
        return nearest_llmobs_ancestor.span_id
    return None


def _get_span_name(span: Span) -> str:
    if span.name == LANGCHAIN_APM_SPAN_NAME and span.resource != "":
        return span.resource
    return span.name


def _get_ml_app(span: Span) -> str:
    """
    Return the ML app name for a given span, by checking the span's nearest LLMObs span ancestor.
    Default to the global config LLMObs ML app name otherwise.
    """
    ml_app = span.get_tag(ML_APP)
    if ml_app:
        return ml_app
    nearest_llmobs_ancestor = _get_nearest_llmobs_ancestor(span)
    if nearest_llmobs_ancestor:
        ml_app = nearest_llmobs_ancestor.get_tag(ML_APP)
    return ml_app or config._llmobs_ml_app or "uknown-ml-app"


def _get_session_id(span: Span) -> str:
    """
    Return the session ID for a given span, by checking the span's nearest LLMObs span ancestor.
    Default to the span's trace ID.
    """
    session_id = span.get_tag(SESSION_ID)
    if session_id:
        return session_id
    nearest_llmobs_ancestor = _get_nearest_llmobs_ancestor(span)
    if nearest_llmobs_ancestor:
        session_id = nearest_llmobs_ancestor.get_tag(SESSION_ID)
    return session_id or "{:x}".format(span.trace_id)
