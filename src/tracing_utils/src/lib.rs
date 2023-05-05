mod trace_id;

use pyo3::prelude::*;

use self::trace_id::{gen_trace_id_128_bits, gen_trace_id_64_bits, reseed};

fn register_trace_id_submodule(py: Python, parent: &PyModule) -> PyResult<()> {
    let child_module = PyModule::new(py, "trace_id")?;
    child_module.add_function(wrap_pyfunction!(reseed, child_module)?)?;
    child_module.add_function(wrap_pyfunction!(gen_trace_id_64_bits, child_module)?)?;
    child_module.add_function(wrap_pyfunction!(gen_trace_id_128_bits, child_module)?)?;

    parent.add_submodule(child_module)?;
    Ok(())
}

#[pymodule]
#[pyo3(name = "tracing_utils")]
fn tracing_utils_module(py: Python, m: &PyModule) -> PyResult<()> {
    register_trace_id_submodule(py, m)?;
    Ok(())
}
