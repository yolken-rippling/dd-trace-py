from .tracing_utils import trace_id
from ddtrace.internal import forksafe


seed = trace_id.reseed
rand64bits = trace_id.gen_trace_id_64_bits
rand128bits = trace_id.gen_trace_id_128_bits

# We have to reseed the RNG or we will get collisions between the processes as
# they will share the seed and generate the same random numbers.
forksafe.register(trace_id.reseed)
