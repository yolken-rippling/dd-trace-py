use libdd_data_pipeline::trace_exporter::TraceExporter;
use libdd_data_pipeline::trace_exporter::TraceExporterBuilder;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use pyo3::types::PyString;
use url::Url;

#[pyclass(name = "TraceExporter")]
pub struct TraceExporterPy {
    exporter: TraceExporter,
}

#[pymethods]
impl TraceExporterPy {
    #[new]
    fn new(intake_url: &str) -> PyResult<Self> {
        Python::with_gil(|py| -> PyResult<Self> {
            // Imported necessary Python modules
            let sys: Bound<'_, PyModule> = PyModule::import_bound(py, "sys")?;
            let platform: Bound<'_, PyModule> = PyModule::import_bound(py, "platform")?;
            let ddtrace_version: Bound<'_, PyModule> =
                PyModule::import_bound(py, "ddtrace.version")?;

            // Get Python platform information
            let version_info: &PyAny = sys.getattr("version_info")?.extract()?;

            // Get Datadog Agent connection url and parse the host and port
            let url = match Url::parse(intake_url) {
                Ok(url) => url,
                Err(e) => return Err(PyValueError::new_err(format!("{:?}", e))),
            };
            let host = url
                .host_str()
                .ok_or(PyValueError::new_err("Invalid host"))?;
            let port = url.port().ok_or(PyValueError::new_err("Invalid port"))?;

            let mut builder = TraceExporterBuilder::default();
            let exporter = builder
                .set_host(host)
                .set_port(port)
                .set_tracer_version(
                    ddtrace_version
                        .getattr("get_version")?
                        .call0()?
                        .downcast::<PyString>()?
                        .to_str()?,
                )
                .set_language("python")
                .set_language_version(
                    format!(
                        "{}.{}.{}",
                        version_info.getattr("major")?,
                        version_info.getattr("minor")?,
                        version_info.getattr("micro")?
                    )
                    .as_str(),
                )
                .set_language_interpreter(
                    platform
                        .getattr("python_implementation")?
                        .call0()?
                        .downcast::<PyString>()?
                        .to_str()?,
                )
                .build();

            match exporter {
                Ok(exporter) => Ok(TraceExporterPy { exporter }),
                Err(e) => Err(PyValueError::new_err(format!("{:?}", e))),
            }
        })
    }

    fn send<'py>(
        &self,
        py: Python<'py>,
        data: &[u8],
        trace_count: usize,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let result = self.exporter.send(data, trace_count);
        if let Err(e) = result {
            return Err(PyValueError::new_err(format!("{:?}", e)));
        }

        Ok(PyBytes::new_bound(py, result.unwrap().as_bytes()))
    }
}

pub fn register_child_module(parent_module: &Bound<'_, PyModule>) -> PyResult<()> {
    let data_pipeline_module = PyModule::new_bound(parent_module.py(), "data_pipeline")?;
    data_pipeline_module.add_class::<TraceExporterPy>()?;
    parent_module.add_submodule(&data_pipeline_module)?;
    Ok(())
}
