cpdef bint has_listeners(str event_id)
cpdef void on(str event_id, object callback)
cpdef void reset_listeners()
cdef tuple _dispatch(str event_id, list args)
