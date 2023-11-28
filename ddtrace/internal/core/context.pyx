from contextlib import contextmanager
import contextvars
import logging

from ddtrace.internal.core cimport hub

cdef object log = logging.getLogger(__name__)

_CURRENT_CONTEXT = None
cdef str ROOT_CONTEXT_ID = "__root"

cdef class ExecutionContext:
    cdef readonly str identifier
    cdef readonly dict _data
    cdef list _parents
    cdef object _span
    cdef object _token

    def __init__(self, str identifier, object parent=None, object span=None, **kwargs):
        self.identifier = identifier
        self._data = {}
        self._parents = []
        self._span = span
        if parent is not None:
            self.addParent(parent)
        self._data.update(kwargs)
        if self._span is None and _CURRENT_CONTEXT is not None:
            self._token = _CURRENT_CONTEXT.set(self)
        hub._dispatch("context.started.%s" % self.identifier, [self])

    def __repr__(self):
        return self.__class__.__name__ + " '" + self.identifier + "' @ " + str(id(self))

    @property
    def parents(self):
        return self._parents

    @property
    def parent(self):
        return self._parents[0] if self._parents else None

    cpdef tuple end(self):
        dispatch_result = hub._dispatch("context.ended.%s" % self.identifier, [self])
        if self._span is None:
            try:
                _CURRENT_CONTEXT.reset(self._token)
            except ValueError:
                log.debug(
                    "Encountered ValueError during core contextvar reset() call. "
                    "This can happen when a span holding an executioncontext is "
                    "finished in a Context other than the one that started it."
                )
            except LookupError:
                log.debug(
                    "Encountered LookupError during core contextvar reset() call. I don't know why this is possible."
                )
        return dispatch_result

    cpdef void addParent(self, object context):
        if self.identifier == ROOT_CONTEXT_ID:
            raise ValueError("Cannot add parent to root context")
        self._parents.append(context)

    @classmethod
    @contextmanager
    def context_with_data(object cls, str identifier, object parent=None, object span=None, **kwargs):
        new_context = cls(identifier, parent=parent, span=span, **kwargs)
        try:
            yield new_context
        finally:
            new_context.end()

    cpdef object get_item(self, str data_key, object default = None, bint traverse = True):
        # NB mimic the behavior of `ddtrace.internal._context` by doing lazy inheritance
        current = self
        while current is not None:
            if data_key in current._data:
                return current._data.get(data_key)
            if not traverse:
                break
            current = current.parent
        return default

    def __getitem__(self, str key):
        value = self.get_item(key)
        if value is None and key not in self._data:
            raise KeyError
        return value

    cpdef list get_items(self, list data_keys):
        return [self.get_item(key) for key in data_keys]

    cpdef void set_item(self, str data_key, object data_value):
        self._data[data_key] = data_value

    cpdef void set_safe(self, str data_key, object data_value):
        if data_key in self._data:
            raise ValueError("Cannot overwrite ExecutionContext data key '%s'", data_key)
        self.set_item(data_key, data_value)

    cpdef void set_items(self, dict keys_values):
        for data_key, data_value in keys_values.items():
            self.set_item(data_key, data_value)

    cpdef object root(self):
        if self.identifier == ROOT_CONTEXT_ID:
            return self
        current = self
        while current.parent is not None:
            current = current.parent
        return current


_CURRENT_CONTEXT = contextvars.ContextVar("ExecutionContext_var", default=ExecutionContext(ROOT_CONTEXT_ID))
cdef _CONTEXT_CLASS = ExecutionContext


def context_with_data(str identifier, object parent=None, **kwargs):
    return _context_with_data(identifier, parent, kwargs)

cpdef object _context_with_data(str identifier, object parent=None, object kwargs = None):
    if not kwargs:
        kwargs = {}
    return _CONTEXT_CLASS.context_with_data(identifier, parent=(parent or _CURRENT_CONTEXT.get()), **kwargs)


cpdef object get_item(str data_key, object span=None):
    # type: (str, Optional[Span]) -> Optional[Any]
    if span is not None and span._local_root is not None:
        return span._local_root._get_ctx_item(data_key)
    else:
        return _CURRENT_CONTEXT.get().get_item(data_key)  # type: ignore


cpdef object get_items(list data_keys, object span=None):
    # type: (List[str], Optional[Span]) -> Optional[Any]
    if span is not None and span._local_root is not None:
        return [span._local_root._get_ctx_item(key) for key in data_keys]
    else:
        return _CURRENT_CONTEXT.get().get_items(data_keys)  # type: ignore


cpdef void set_safe(str data_key, object data_value):
    _CURRENT_CONTEXT.get().set_safe(data_key, data_value)  # type: ignore


# NB Don't call these set_* functions from `ddtrace.contrib`, only from product code!
cpdef void set_item(str data_key, object data_value, object span=None):
    if span is not None and span._local_root is not None:
        span._local_root._set_ctx_item(data_key, data_value)
    else:
        _CURRENT_CONTEXT.get().set_item(data_key, data_value)  # type: ignore


cpdef void set_items(dict keys_values, object span=None):
    if span is not None and span._local_root is not None:
        span._local_root._set_ctx_items(keys_values)
    else:
        _CURRENT_CONTEXT.get().set_items(keys_values)  # type: ignore
