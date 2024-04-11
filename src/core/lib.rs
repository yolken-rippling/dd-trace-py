mod data_pipeline;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    data_pipeline::register_child_module(m)?;
    Ok(())
}
