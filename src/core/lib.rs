mod message_bus;

use pyo3::prelude::*;

#[pymodule]
fn _core(py: Python<'_>, m: &PyModule) -> PyResult<()> {
    let msg_bus_module = PyModule::new(py, "message_bus")?;
    msg_bus_module.add_function(wrap_pyfunction!(message_bus::on, msg_bus_module)?);
    msg_bus_module.add_function(wrap_pyfunction!(message_bus::on_all, msg_bus_module)?);
    msg_bus_module.add_function(wrap_pyfunction!(message_bus::remove, msg_bus_module)?);
    msg_bus_module.add_function(wrap_pyfunction!(message_bus::reset, msg_bus_module)?);
    msg_bus_module.add_function(wrap_pyfunction!(
        message_bus::has_listeners,
        msg_bus_module
    )?);
    msg_bus_module.add_function(wrap_pyfunction!(message_bus::dispatch, msg_bus_module)?);
    msg_bus_module.add_function(wrap_pyfunction!(
        message_bus::dispatch_with_results,
        msg_bus_module
    )?);

    m.add_submodule(msg_bus_module)?;
    Ok(())
}
