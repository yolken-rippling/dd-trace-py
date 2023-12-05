import cython
from cpython cimport *

from ddtrace import config


cdef dict[str, set[callable]] _listeners = {}
cdef set[callable] _all_listeners = set()


cpdef void on(event_id: str, listener: callable):
    if event_id not in _listeners:
        _listeners[event_id] = {listener}
    else:
        _listeners[event_id].add(listener)

cpdef void on_all(listener: callable):
    _all_listeners.add(listener)

cpdef void remove(event_id: str, listener: callable):
    if event_id not in _listeners:
        return

    _listeners[event_id].remove(listener)


@cython.nonecheck(False)
cdef inline void _call_all_listeners(event_id: str, args: tuple):
    for hook in _all_listeners:
        try:
            hook(event_id, args)
        except Exception:
            if config._raise:
                raise

@cython.nonecheck(False)
cpdef void dispatch(event_id: str, args: tuple):
    _call_all_listeners(event_id, args)

    if event_id not in _listeners:
        return

    cdef set hooks = _listeners[event_id]
    for hook in hooks:
        try:
            hook(*args)
        except Exception:
            if config._raise:
                raise


@cython.nonecheck(False)
cpdef tuple[list, list] dispatch_with_results(event_id: str, args: tuple):
    # Do not add all listener results or exceptions to results
    _call_all_listeners(event_id, args)

    if event_id not in _listeners:
        return [], []

    cdef list results = []
    cdef list exceptions = []
    cdef set hooks = _listeners[event_id]
    for hook in hooks:
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
    _all_listeners = set()

@cython.nonecheck(False)
cpdef bool has_listeners(event_id: str):
    return _listeners.get(event_id)
