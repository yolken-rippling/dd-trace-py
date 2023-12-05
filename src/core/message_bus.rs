use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::PyFunction;
use pyo3::types::PyList;
use pyo3::types::PyNone;
use pyo3::types::PyTuple;
use std::collections::HashMap;
use std::sync::Mutex;

static EVENT_LISTENERS: Lazy<Mutex<HashMap<String, Vec<Py<PyFunction>>>>> =
    Lazy::new(|| Mutex::new(HashMap::new()));
static GLOBAL_LISTENERS: Lazy<Mutex<Vec<Py<PyFunction>>>> = Lazy::new(|| Mutex::new(Vec::new()));

#[pyfunction]
pub fn has_listeners(event_id: String) -> PyResult<bool> {
    match EVENT_LISTENERS.lock().unwrap().get(&event_id) {
        Some(v) => Ok(!v.is_empty()),
        None => Ok(false),
    }
}

#[pyfunction]
pub fn on(event_id: String, callback: Py<PyFunction>) -> PyResult<()> {
    let mut listeners = EVENT_LISTENERS.lock().unwrap();

    if let Some(l) = listeners.get_mut(&event_id) {
        if !l.iter().any(|f| f.is(&callback)) {
            l.insert(0, callback);
        }
    } else {
        let mut v: Vec<Py<PyFunction>> = Vec::new();
        v.push(callback);
        listeners.insert(event_id, v);
    }

    Ok(())
}

#[pyfunction]
pub fn on_all(callback: Py<PyFunction>) -> PyResult<()> {
    let mut listeners = GLOBAL_LISTENERS.lock().unwrap();
    if !listeners.iter().any(|f| f.is(&callback)) {
        listeners.insert(0, callback);
    }

    Ok(())
}

#[pyfunction]
pub fn reset() -> PyResult<()> {
    EVENT_LISTENERS.lock().unwrap().clear();
    GLOBAL_LISTENERS.lock().unwrap().clear();

    Ok(())
}

#[pyfunction]
pub fn remove(event_id: String, callback: Py<PyFunction>) -> PyResult<()> {
    if let Some(l) = EVENT_LISTENERS.lock().unwrap().get_mut(&event_id) {
        l.retain(|f| !f.is(&callback));
    }

    Ok(())
}

#[pyfunction]
pub fn dispatch(py: Python<'_>, event_id: String, args: &PyTuple) -> PyResult<()> {
    if let Some(l) = EVENT_LISTENERS.lock().unwrap().get(&event_id) {
        for f in l {
            f.call1(py, args);
        }
    }

    let listeners = GLOBAL_LISTENERS.lock().unwrap();
    for f in listeners.iter() {
        f.call1(py, (event_id.clone(), args));
    }

    Ok(())
}

#[pyfunction]
pub fn dispatch_with_results<'py>(
    py: Python<'py>,
    event_id: String,
    args: &PyTuple,
) -> PyResult<(&'py PyList, &'py PyList)> {
    let none = PyNone::get(py);
    let results = PyList::empty(py);
    let exceptions = PyList::empty(py);

    if let Some(l) = EVENT_LISTENERS.lock().unwrap().get(&event_id) {
        for f in l {
            match f.call1(py, args) {
                Err(e) => {
                    results.append(none);
                    exceptions.append(e);
                }
                Ok(r) => {
                    results.append(r);
                    exceptions.append(none);
                }
            }
        }
    }

    let listeners = GLOBAL_LISTENERS.lock().unwrap();
    for f in listeners.iter() {
        f.call1(py, (event_id.clone(), args));
    }

    Ok((results, exceptions))
}
