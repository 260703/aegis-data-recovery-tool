//! Aegis Core - High Performance Rust Forensic Carving Engine
//! ==========================================================
//! Exposes native PyO3 / Maturin bindings for PySide6 GUI and Python CLI.

pub mod device_manager;
pub mod disk_stream;
pub mod engine;
pub mod parsers;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::engine::CarveEngine;

#[pyclass(name = "CarveEngine")]
pub struct PyCarveEngine {
    inner: CarveEngine,
}

#[pymethods]
impl PyCarveEngine {
    #[new]
    #[pyo3(signature = (target_path, output_dir, sector_step=512, block_size_mb=8, enabled_formats=None))]
    fn new(
        target_path: String,
        output_dir: String,
        sector_step: u64,
        block_size_mb: usize,
        enabled_formats: Option<Vec<String>>,
    ) -> Self {
        let fmts = enabled_formats.unwrap_or_else(|| {
            vec![
                "jpeg".to_string(),
                "png".to_string(),
                "mp4".to_string(),
                "mov".to_string(),
                "raw".to_string(),
            ]
        });
        Self {
            inner: CarveEngine::new(target_path, output_dir, sector_step, block_size_mb, fmts),
        }
    }

    /// Releases the Python GIL and begins multithreaded disk carving.
    fn start(
        &self,
        py: Python<'_>,
        on_started: PyObject,
        on_progress: PyObject,
        on_file_found: PyObject,
        on_log: PyObject,
    ) -> PyResult<PyObject> {
        self.inner
            .run(py, &on_started, &on_progress, &on_file_found, &on_log)
    }

    fn pause(&self) {
        self.inner.pause();
    }

    fn resume(&self) {
        self.inner.resume();
    }

    fn stop(&self) {
        self.inner.stop();
    }
}

#[pyfunction(name = "is_admin")]
fn is_admin_py() -> bool {
    device_manager::is_admin()
}

#[pyfunction(name = "is_output_safe")]
fn is_output_safe_py(target_device: &str, output_dir: &str) -> (bool, String) {
    device_manager::is_output_safe(target_device, output_dir)
}

#[pyfunction(name = "list_devices")]
fn list_devices_py<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let raw_devices = device_manager::list_devices();
    let py_list = PyList::empty_bound(py);

    for dev in raw_devices {
        let dict = PyDict::new_bound(py);
        dict.set_item("device_path", dev.device_path)?;
        dict.set_item("display_name", dev.display_name)?;
        dict.set_item("drive_type", dev.drive_type)?;
        dict.set_item("total_bytes", dev.total_bytes)?;
        dict.set_item("free_bytes", dev.free_bytes)?;
        dict.set_item("filesystem", dev.filesystem)?;
        dict.set_item("is_removable", dev.is_removable)?;
        dict.set_item("mountpoint", dev.mountpoint)?;
        dict.set_item("model", dev.model)?;
        py_list.append(dict)?;
    }

    Ok(py_list)
}

#[pymodule]
fn aegis_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyCarveEngine>()?;
    m.add_function(wrap_pyfunction!(list_devices_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_admin_py, m)?)?;
    m.add_function(wrap_pyfunction!(is_output_safe_py, m)?)?;
    Ok(())
}