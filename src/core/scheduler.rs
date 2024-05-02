use pyo3::prelude::*;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::sync::Mutex;
use std::thread;

fn now_millis() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
}

#[pyclass(subclass, name = "Task")]
pub struct TaskPy {
    name: String,
    target: Py<PyAny>,
    on_shutdown: Option<Py<PyAny>>,
    interval: f32,
    last_run: u128,
}

#[pymethods]
impl TaskPy {
    #[new]
    fn new(
        interval: f32,
        target: Bound<'_, PyAny>,
        name: String,
        on_shutdown: Option<Bound<'_, PyAny>>,
    ) -> PyResult<Self> {
        let _on_shutdown = match on_shutdown {
            Some(on_shutdown) => Some(on_shutdown.unbind()),
            None => None,
        };

        Ok(TaskPy {
            name,
            target: target.unbind(),
            on_shutdown: _on_shutdown,
            interval,
            last_run: now_millis(),
        })
    }

    pub fn run(&mut self, py: Python<'_>, now_ms: Option<u128>) -> PyResult<()> {
        let now = now_ms.unwrap_or_else(now_millis);

        let interval_ms = (self.interval * 1000.0).round() as u128;
        if now - self.last_run >= interval_ms {
            // TODO: Handle errors
            let _ = self.target.call0(py);
            self.last_run = now;
        }
        Ok(())
    }

    pub fn shutdown(&mut self, py: Python<'_>) -> PyResult<()> {
        match &self.on_shutdown {
            Some(on_shutdown) => {
                let _ = on_shutdown.call0(py);
            }
            None => {}
        }
        Ok(())
    }
}

#[pyclass(name = "Scheduler")]
pub struct SchedulerPy {
    tasks: Arc<Mutex<Vec<Py<TaskPy>>>>,
    handle: Option<thread::JoinHandle<()>>,
    is_running: Arc<AtomicBool>,
}

#[pymethods]
impl SchedulerPy {
    #[new]
    fn new(auto_start: bool) -> PyResult<Self> {
        let mut scheduler = SchedulerPy {
            tasks: Arc::new(Mutex::new(Vec::new())),
            handle: None,
            is_running: Arc::new(AtomicBool::new(false)),
        };
        if auto_start {
            scheduler.start()?;
        }

        Ok(scheduler)
    }

    pub fn register_task(&mut self, task: Bound<'_, TaskPy>) -> PyResult<()> {
        if self
            .tasks
            .lock()
            .unwrap()
            .iter()
            .find(|t| t.as_ptr() == task.as_ptr())
            .is_none()
        {
            self.tasks.lock().unwrap().push(task.unbind());
        }
        Ok(())
    }

    pub fn unregister_task(&mut self, py: Python<'_>, task: Bound<'_, TaskPy>) -> PyResult<()> {
        self.tasks
            .lock()
            .unwrap()
            .retain(|t| t.bind(py).as_ptr() != task.as_ptr());
        Ok(())
    }

    pub fn schedule(
        &mut self,
        py: Python<'_>,
        name: String,
        interval: f32,
        target: Bound<'_, PyAny>,
        on_shutdown: Option<Bound<'_, PyAny>>,
    ) -> PyResult<()> {
        let task = Bound::new(py, TaskPy::new(interval, target, name, on_shutdown)?)?;
        self.register_task(task)
    }

    pub fn start(&mut self) -> PyResult<()> {
        if self.handle.is_some() {
            return Ok(());
        }

        self.is_running.store(true, Ordering::SeqCst);
        let is_running = self.is_running.clone();
        let tasks = Arc::clone(&self.tasks);

        self.handle = Some(thread::spawn(move || {
            while is_running.load(Ordering::SeqCst) {
                Python::with_gil(|py| match py.check_signals() {
                    Ok(_) => {}
                    Err(_) => {
                        is_running.store(false, Ordering::SeqCst);
                        return;
                    }
                });

                let now = now_millis();
                for task in tasks.lock().unwrap().iter_mut() {
                    if !is_running.load(Ordering::SeqCst) {
                        break;
                    }
                    Python::with_gil(|py| {
                        let mut t = task.borrow_mut(py);
                        let _ = t.run(py, Some(now));
                    });
                }

                thread::sleep(std::time::Duration::from_millis(100));
            }
        }));
        Ok(())
    }

    pub fn stop(&mut self, py: Python<'_>) -> PyResult<()> {
        if self.handle.is_none() {
            return Ok(());
        }

        self.is_running.store(false, Ordering::SeqCst);

        let handle = self.handle.take();
        handle.unwrap().join().ok();

        for task in self.tasks.lock().unwrap().iter_mut() {
            let mut t = task.borrow_mut(py);
            let _ = t.shutdown(py);
        }
        Ok(())
    }
}

impl Drop for SchedulerPy {
    fn drop(&mut self) {
        // This is a duplicate of `stop` without calling `shutdown` on tasks
        // because we can't access the Python runtime here, Python may be
        // in the middle of finalizing and it's not safe to call Python
        if self.handle.is_none() {
            return;
        }

        self.is_running.store(false, Ordering::SeqCst);
        let handle = self.handle.take();
        handle.unwrap().join().ok();
    }
}
