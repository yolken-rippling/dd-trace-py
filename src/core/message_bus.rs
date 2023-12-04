use pyo3::prelude::*;
use pyo3::types::PyFunction;
use pyo3::types::PyList;
use pyo3::types::PyTuple;
use std::collections::HashMap;

#[pyclass(module = "ddtrace.internal._core")]
pub struct MessageBus {
    listeners: HashMap<String, Vec<Py<PyFunction>>>,
    raise_errors: bool,
}

#[pymethods]
impl MessageBus {
    #[new]
    fn new(raise_errors: bool) -> Self {
        Self {
            listeners: HashMap::new(),
            raise_errors: raise_errors,
        }
    }

    #[pyo3(signature=(event_id))]
    fn has_listeners(&self, event_id: String) -> PyResult<bool> {
        Ok(self.listeners.get(&event_id).is_some())
    }

    #[pyo3(signature=(event_id, callback))]
    fn on(&mut self, event_id: String, callback: Py<PyFunction>) -> PyResult<()> {
        if let Some(v) = self.listeners.get_mut(&event_id) {
            v.insert(0, callback);
        } else {
            let mut v: Vec<Py<PyFunction>> = Vec::new();
            v.push(callback);
            self.listeners.insert(event_id, v);
        }
        Ok(())
    }

    #[pyo3(signature=())]
    fn reset(&mut self) -> PyResult<()> {
        self.listeners.clear();
        Ok(())
    }

    #[pyo3(signature=(event_id, callback))]
    fn remove(&mut self, event_id: String, callback: Py<PyFunction>) -> PyResult<()> {
        if let Some(v) = self.listeners.get_mut(&event_id) {
            v.retain(|f| !f.is(&callback))
        }
        Ok(())
    }

    #[pyo3(signature=(event_id, args))]
    fn dispatch<'py>(
        &self,
        py: Python<'py>,
        event_id: String,
        args: &PyTuple,
    ) -> PyResult<(&'py PyList, &'py PyList)> {
        let mut results = vec![];
        let mut exceptions = vec![];

        if let Some(v) = self.listeners.get(&event_id) {
            for f in v {
                let res = f.call1(py, args);
                if let Err(e) = res {
                    if self.raise_errors {
                        return Err(e);
                    }
                    exceptions.push(e);
                } else if let Ok(r) = res {
                    results.push(r);
                }
            }
        }

        Ok((PyList::new(py, results), PyList::new(py, exceptions)))
    }
}
