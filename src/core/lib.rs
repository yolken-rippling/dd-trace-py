use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::*;
use std::collections::HashMap;
use std::sync::Mutex;

struct Hub {
    listeners: HashMap<String, Vec<Py<PyFunction>>>,
}

static HUB: Lazy<Mutex<Hub>> = Lazy::new(|| {
    Mutex::new(Hub {
        listeners: HashMap::new(),
    })
});

#[pyfunction]
fn has_listeners<'py>(event_id: String) -> PyResult<bool> {
    match HUB.lock().unwrap().listeners.get(&event_id) {
        Some(v) => Ok(!v.is_empty()),
        None => Ok(false),
    }
}

#[pyfunction]
fn on(event_id: String, callback: &PyFunction) -> PyResult<()> {
    let c: Py<PyFunction> = callback.into();
    let mut h = HUB.lock().unwrap();

    if let Some(mut v) = h.listeners.get_mut(&event_id) {
        v.insert(0, c);
    } else {
        let mut v: Vec<Py<PyFunction>> = Vec::new();
        v.push(c);
        h.listeners.insert(event_id, v);
    }
    Ok(())
}

#[pyfunction]
fn reset_listeners() -> PyResult<()> {
    HUB.lock().unwrap().listeners.clear();
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (event_id, event_args))]
fn dispatch<'py>(
    py: Python<'py>,
    event_id: String,
    event_args: &PyTuple,
) -> PyResult<&'py PyTuple> {
    let mut h = HUB.lock().unwrap();
    if let Some(v) = h.listeners.get(&event_id) {
        for f in v {
            f.call1(py, (event_args,))?;
        }
    } else {
        return Ok(PyTuple::empty(py));
    }

    Ok(PyTuple::empty(py))
}

#[pymodule]
fn _hub(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(has_listeners, m)?)?;
    m.add_function(wrap_pyfunction!(on, m)?)?;
    m.add_function(wrap_pyfunction!(reset_listeners, m)?)?;
    m.add_function(wrap_pyfunction!(dispatch, m)?)?;
    Ok(())
}
