"""
This file implements the Core API, the abstraction layer between Integrations and Product code.
The Core API enables two primary use cases: maintaining a tree of ``ExecutionContext`` objects
and dispatching events.

When using the Core API, keep concerns separate between Products and Integrations. Integrations
should not contain any code that references Products (Tracing, AppSec, Spans, WAF, Debugging, et cetera)
and Product code should never reference the library being integrated with (for example by importing ``flask``).

It's helpful to think of the context tree as a Trace with extra data on each Span. It's similar
to a tree of Spans in that it represents the parts of the execution state that Datadog products
care about.

This example shows how ``core.context_with_data`` might be used to create a node in this context tree::


    import flask


    def _patched_request(pin, wrapped, args, kwargs):
        with core.context_with_data(
            "flask._patched_request",
            pin=pin,
            flask_request=flask.request,
            block_request_callable=_block_request_callable,
        ) as ctx, ctx.get_item("flask_request_call"):
            return wrapped(*args, **kwargs)


This example looks a bit like a span created by ``tracer.trace()``: it has a name, a ``Pin`` instance, and
``__enter__`` and ``__exit__`` functionality as a context manager. In fact, it's so similar to a span that
the Tracing code in ``ddtrace/tracing`` can create a span directly from it (that's what ``flask_request_call``
is in this example).

The ``ExecutionContext`` object in this example also holds some data that you wouldn't typically find on
spans, like ``flask_request`` and ``block_request_callable``. These illustrate the context's utility as a
generic container for data that Datadog products need related to the current execution. ``block_request_callable``
happens to be used in ``ddtrace/appsec`` by the AppSec product code to make request-blocking decisions, and
``flask_request`` is a reference to a library-specific function that Tracing uses.

The first argument to ``context_with_data`` is the unique name of the context. When choosing this name,
consider how to differentiate it from other similar contexts while making its purpose clear. An easy default
is to use the name of the function within which ``context_with_data`` is being called, prefixed with the
integration name and a dot, for example ``flask._patched_request``.

The integration code finds all of the library-specific objects that products need, and puts them into
the context tree it's building via ``context_with_data``. Product code then accesses the data it needs
by calling ``ExecutionContext.get_item`` like this::


    pin = ctx.get_item("pin")
    current_span = pin.tracer.current_span()
    ctx.set_item("current_span", current_span)
    flask_config = ctx.get_item("flask_config")
    _set_request_tags(ctx.get_item("flask_request"), current_span, flask_config)


Integration code can also call ``get_item`` when necessary, for example when the Flask integration checks
the request blocking flag that may have been set on the context by AppSec code and then runs Flask-specific
response logic::


    if core.get_item(HTTP_REQUEST_BLOCKED):
        result = start_response("403", [("content-type", "application/json")])


In order for ``get_item`` calls in Product code like ``ddtrace/appsec`` to find what they're looking for,
they need to happen at the right time. That's the problem that the ``core.dispatch`` and ``core.on``
functions solve.

The common pattern is that integration code generates events by calling ``dispatch`` and product code
listens to those events by calling ``on``. This allows product code to react to integration code at the
appropriate moments while maintaining clear separation of concerns.

For example, the Flask integration calls ``dispatch`` to indicate that a blocked response just started,
passing some data along with the event::


    call = tracer.trace("operation")
    core.dispatch("flask.blocked_request_callable", call)


The AppSec code listens for this event and does some AppSec-specific stuff in the handler::


    def _on_flask_blocked_request():
        core.set_item(HTTP_REQUEST_BLOCKED, True)
    core.on("flask.blocked_request_callable", _on_flask_blocked_request)


``ExecutionContexts`` also generate their own start and end events that Product code can respond to
like this::


    def _on_jsonify_context_started_flask(ctx):
        span = ctx.get_item("pin").tracer.trace(ctx.get_item("name"))
        ctx.set_item("flask_jsonify_call", span)
    core.on("context.started.flask.jsonify", _on_jsonify_context_started_flask)


The names of these events follow the pattern ``context.[started|ended].<context_name>``.
"""
from .hub import EventHub, dispatch, has_listeners, on, reset_listeners
from .context import (
    _CURRENT_CONTEXT,
    context_with_data,
    ExecutionContext,
    get_item,
    get_items,
    set_item,
    set_items,
    set_safe,
)

__all__ = [
    "EventHub",
    "dispatch",
    "has_listeners",
    "on",
    "reset_listeners",
    "ExecutionContext",
    "context_with_data",
    "get_item",
    "get_items",
    "set_item",
    "set_items",
    "set_safe",
]


def __getattr__(name):
    if name == "root":
        return _CURRENT_CONTEXT.get().root()
    raise AttributeError
