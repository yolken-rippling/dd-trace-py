from cpython cimport *

from ddtrace import config


cdef dict[str, list[callable]] _listeners = {}


cpdef void on(event_id: str, listener: callable):
    if event_id not in _listeners:
        _listeners[event_id] = [listener]
    else:
        _listeners[event_id].append(listener)

cpdef void dispatch(event_id: str, args: tuple):
    if event_id not in _listeners:
        return

    for hook in _listeners[event_id]:
        try:
            hook(*args)
        except Exception:
            if config._raise:
                raise

cpdef tuple[list, list] dispatch_with_results(event_id: str, args: tuple):
    if event_id not in _listeners:
        return [], []

    results = []
    exceptions = []
    for hook in _listeners[event_id]:
        try:
            results.append(hook(*args))
            exceptions.append(None)
        except Exception as e:
            if config._raise:
                raise
            exceptions.append(e)
            results.append(None)
    return results, exceptions

cpdef void reset():
    _listeners = {}

cpdef bool has_listeners(event_id: str):
    return _listeners.get(event_id)
