mod message_bus;

use pyo3::prelude::*;

#[pymodule]
fn _core(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_class::<message_bus::MessageBus>()?;
    Ok(())
}
