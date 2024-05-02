mod scheduler;

use pyo3::prelude::*;

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3::prepare_freethreaded_python();
    m.add_class::<scheduler::SchedulerPy>()?;
    m.add_class::<scheduler::TaskPy>()?;
    Ok(())
}
