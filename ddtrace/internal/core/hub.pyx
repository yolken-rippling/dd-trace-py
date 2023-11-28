import contextvars

from ddtrace import config

cdef class EventHub:
    cdef dict _listeners

    def __init__(self):
        self._listeners = {}

    cpdef bint has_listeners(self, str event_id):
        # type: (str) -> bool
        return event_id in self._listeners

    cpdef void on(self, str event_id, object callback):
        # type: (str, Callable) -> None
        if event_id not in self._listeners:
            self._listeners[event_id] = []

        if callback not in self._listeners[event_id]:
            self._listeners[event_id].insert(0, callback)

    cpdef void reset(self):
        self._listeners.clear()

    def dispatch(self, str event_id, object args, *other_args):
        # type: (...) -> Tuple[List[Optional[Any]], List[Optional[Exception]]]
        if not self.has_listeners(event_id):
            return [], []

        if not isinstance(args, list):
            args = [args] + list(other_args)
        else:
            if other_args:
                raise TypeError(
                    "When the first argument expected by the event handler is a list, all arguments "
                    "must be passed in a list. For example, use dispatch('foo', [[l1, l2], arg2]) "
                    "instead of dispatch('foo', [l1, l2], arg2)."
                )

        return self._dispatch(event_id, args)

    cpdef tuple _dispatch(self, str event_id, list args):
        if not self.has_listeners(event_id):
            return [], []

        results = []
        exceptions = []
        for listener in self._listeners[event_id]:
            result = None
            exception = None
            try:
                result = listener(*args)
            except Exception as exc:
                exception = exc
                if config._raise:
                    raise
            results.append(result)
            exceptions.append(exception)
        return results, exceptions

_EVENT_HUB = contextvars.ContextVar("EventHub_var", default=EventHub())

cpdef bint has_listeners(str event_id):
    # type: (str) -> bool
    return _EVENT_HUB.get().has_listeners(event_id)  # type: ignore

cpdef void on(str event_id, object callback):
    # type: (str, Callable) -> None
    _EVENT_HUB.get().on(event_id, callback)  # type: ignore

cpdef void reset_listeners():
    # type: () -> None
    _EVENT_HUB.get().reset()  # type: ignore

def dispatch(str event_id, object args, *other_args):
    return _EVENT_HUB.get().dispatch(event_id, args, *other_args)  # type: ignore

cdef tuple _dispatch(str event_id, list args):
    return _EVENT_HUB.get()._dispatch(event_id, args)  # type: ignore
