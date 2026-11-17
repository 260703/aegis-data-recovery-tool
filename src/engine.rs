//! Multithreaded Sliding-Window Carve Engine
//! ==========================================
//! Orchestrates SIMD pattern scanning, Rayon work-stealing parallel parsing,
//! zero-copy streaming file extraction, and throttled UI callbacks.

use std::collections::{HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use parking_lot::{Condvar, Mutex, RwLock};
use pyo3::prelude::*;
use rayon::prelude::*;

use crate::disk_stream::DiskStream;
use crate::parsers::{
    parse_isobmff, parse_jpeg, parse_png, parse_tiff_raw, CarveCandidate, ISOBMFF_FTYP, JPEG_SOI,
    PNG_MAGIC, TIFF_BE_MAGIC, TIFF_LE_MAGIC,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum FormatHint {
    Jpeg,
    Png,
    Isobmff,
    TiffRaw,
}

/// Interval-based claimed range registry supporting O(log N) disjoint checks and insertions.
#[derive(Default)]
pub struct ClaimedRanges {
    ranges: Vec<(u64, u64)>,
}

impl ClaimedRanges {
    pub fn try_claim(&mut self, start: u64, end: u64) -> bool {
        if start >= end {
            return false;
        }

        let idx = self.ranges.partition_point(|&(s, _)| s < start);

        if idx > 0 && start < self.ranges[idx - 1].1 {
            return false;
        }
        if idx < self.ranges.len() && end > self.ranges[idx].0 {
            return false;
        }

        self.ranges.insert(idx, (start, end));
        true
    }

    pub fn is_claimed(&self, start: u64, end: u64) -> bool {
        if start >= end {
            return true;
        }
        let idx = self.ranges.partition_point(|&(s, _)| s < start);
        if idx > 0 && start < self.ranges[idx - 1].1 {
            return true;
        }
        if idx < self.ranges.len() && end > self.ranges[idx].0 {
            return true;
        }
        false
    }
}

pub struct ScanStats {
    pub scanned_bytes: u64,
    pub total_bytes: u64,
    pub found: HashMap<String, usize>,
    pub elapsed_time: f64,
}

/// Core high-performance carving engine.
pub struct CarveEngine {
    pub target_path: String,
    pub output_dir: PathBuf,
    pub sector_step: u64,
    pub block_size: usize,
    pub overlap_size: usize,
    pub enabled_formats: HashSet<String>,
    pub running: Arc<AtomicBool>,
    pub paused: Arc<AtomicBool>,
    pub pause_cond: Arc<(Mutex<bool>, Condvar)>,
    pub claimed: Arc<RwLock<ClaimedRanges>>,
    pub stats: Arc<RwLock<ScanStats>>,
}

impl CarveEngine {
    pub fn new(
        target_path: String,
        output_dir: String,
        sector_step: u64,
        block_size_mb: usize,
        enabled_formats: Vec<String>,
    ) -> Self {
        let block_size = block_size_mb.max(1) * 1024 * 1024;
        let overlap_size = 65536usize;
        let sector_step = sector_step.max(1);

        let mut found = HashMap::new();
        for key in ["jpeg", "png", "mp4", "mov", "raw"] {
            found.insert(key.to_string(), 0);
        }

        Self {
            target_path,
            output_dir: PathBuf::from(output_dir),
            sector_step,
            block_size,
            overlap_size,
            enabled_formats: enabled_formats.into_iter().map(|s| s.to_lowercase()).collect(),
            running: Arc::new(AtomicBool::new(true)),
            paused: Arc::new(AtomicBool::new(false)),
            pause_cond: Arc::new((Mutex::new(false), Condvar::new())),
            claimed: Arc::new(RwLock::new(ClaimedRanges::default())),
            stats: Arc::new(RwLock::new(ScanStats {
                scanned_bytes: 0,
                total_bytes: 0,
                found,
                elapsed_time: 0.0,
            })),
        }
    }

    pub fn pause(&self) {
        self.paused.store(true, Ordering::SeqCst);
        let (lock, _cvar) = &*self.pause_cond;
        *lock.lock() = true;
    }

    pub fn resume(&self) {
        self.paused.store(false, Ordering::SeqCst);
        let (lock, cvar) = &*self.pause_cond;
        *lock.lock() = false;
        cvar.notify_all();
    }

    pub fn stop(&self) {
        self.running.store(false, Ordering::SeqCst);
        self.resume();
    }

    fn ext_to_stat_key(ext: &str) -> &'static str {
        match ext.to_ascii_lowercase().as_str() {
            "jpg" | "jpeg" => "jpeg",
            "png" => "png",
            "cr2" | "cr3" | "raw" | "nef" | "arw" | "dng" => "raw",
            "mp4" => "mp4",
            "mov" => "mov",
            _ => "jpeg",
        }
    }

    fn get_target_folder(&self, stat_key: &str) -> PathBuf {
        let sub = match stat_key {
            "jpeg" => self.output_dir.join("Images").join("JPEG"),
            "png" => self.output_dir.join("Images").join("PNG"),
            "raw" => self.output_dir.join("Images").join("RAW"),
            "mp4" => self.output_dir.join("Videos").join("MP4"),
            "mov" => self.output_dir.join("Videos").join("MOV"),
            _ => self.output_dir.join("Other"),
        };
        let _ = fs::create_dir_all(&sub);
        sub
    }

    /// Releases the Python GIL during disk I/O and invokes UI callbacks safely.
    pub fn run(
        &self,
        py: Python<'_>,
        on_started: &PyObject,
        on_progress: &PyObject,
        on_file_found: &PyObject,
        on_log: &PyObject,
    ) -> PyResult<PyObject> {
        self.running.store(true, Ordering::SeqCst);
        self.paused.store(false, Ordering::SeqCst);

        let stream = match DiskStream::open(&self.target_path, self.sector_step) {
            Ok(s) => s,
            Err(e) => {
                let err_msg = format!("Failed to open target media '{}': {}", self.target_path, e);
                let _ = on_log.call1(py, (err_msg.clone(), "error"));
                return Err(pyo3::exceptions::PyIOError::new_err(err_msg));
            }
        };

        let _ = fs::create_dir_all(&self.output_dir);

        let total_bytes = stream.total_size;
        self.stats.write().total_bytes = total_bytes;

        let _ = on_started.call1(py, (total_bytes,));
        let ready_msg = format!(
            "Target initialized: {} | Size: {:.2} GB ({} bytes)",
            self.target_path,
            total_bytes as f64 / (1024.0 * 1024.0 * 1024.0),
            total_bytes
        );
        let _ = on_log.call1(py, (ready_msg, "success"));

        let start_time = Instant::now();
        let mut last_progress_time = Instant::now();
        let mut critical_read_error: Option<String> = None;

        py.allow_threads(|| {
            let mut overlap_tail: Vec<u8> = Vec::with_capacity(self.overlap_size);
            let mut window_start_offset = 0u64;
            let mut read_disk_offset = 0u64;
            let mut first_chunk_logged = false;

            let finder_jpeg = memchr::memmem::Finder::new(JPEG_SOI);
            let finder_png = memchr::memmem::Finder::new(PNG_MAGIC);
            let finder_isobmff = memchr::memmem::Finder::new(ISOBMFF_FTYP);
            let finder_tiff_le = memchr::memmem::Finder::new(TIFF_LE_MAGIC);
            let finder_tiff_be = memchr::memmem::Finder::new(TIFF_BE_MAGIC);

            while self.running.load(Ordering::SeqCst) {
                if self.paused.load(Ordering::SeqCst) {
                    let (lock, cvar) = &*self.pause_cond;
                    let mut p = lock.lock();
                    while *p && self.running.load(Ordering::SeqCst) {
                        cvar.wait(&mut p);
                    }
                }

                if !self.running.load(Ordering::SeqCst) {
                    break;
                }

                let mut read_chunk_len = self.block_size;
                if total_bytes > 0 {
                    let remaining = total_bytes.saturating_sub(read_disk_offset);
                    if remaining == 0 && overlap_tail.is_empty() {
                        break;
                    }
                    read_chunk_len = read_chunk_len.min(remaining as usize);
                }

                let new_chunk = if read_chunk_len > 0 {
                    match stream.read_at_checked(read_disk_offset, read_chunk_len) {
                        Ok(bytes) => bytes,
                        Err(err) => {
                            let msg = format!(
                                "Critical disk read error at offset {}: {}",
                                read_disk_offset, err
                            );
                            Python::with_gil(|py| {
                                let _ = on_log.call1(py, (msg.clone(), "error"));
                            });
                            critical_read_error = Some(msg);
                            break;
                        }
                    }
                } else {
                    Vec::new()
                };

                if !first_chunk_logged {
                    let bytes_read = new_chunk.len();
                    let dbg_msg = format!("First chunk read: {} raw bytes pulled from disk.", bytes_read);
                    Python::with_gil(|py| {
                        let _ = on_log.call1(py, (dbg_msg, if bytes_read > 0 { "info" } else { "error" }));
                    });
                    first_chunk_logged = true;
                }

                // Assemble window without cloning 16 MB on every iteration
                let mut window = Vec::with_capacity(overlap_tail.len() + new_chunk.len());
                window.extend_from_slice(&overlap_tail);
                window.extend_from_slice(&new_chunk);
                read_disk_offset += new_chunk.len() as u64;

                if window.is_empty() {
                    break;
                }

                let is_eof = new_chunk.is_empty()
                    || (total_bytes > 0 && read_disk_offset >= total_bytes);
                let scan_limit = if is_eof {
                    window.len()
                } else {
                    window.len().saturating_sub(self.overlap_size)
                };

                // Preserve only the trailing overlap bytes for the next window
                overlap_tail.clear();
                if !is_eof && scan_limit < window.len() {
                    overlap_tail.extend_from_slice(&window[scan_limit..]);
                }

                // Wrap window directly into Arc with zero full-buffer clone
                let window_arc = Arc::new(window);
                stream.set_window_cache(window_start_offset, Arc::clone(&window_arc));

                let scan_slice = &window_arc[..scan_limit.min(window_arc.len())];
                let mut candidate_offsets: Vec<(u64, FormatHint)> = Vec::new();

                if self.enabled_formats.contains("jpeg") {
                    for hit in finder_jpeg.find_iter(scan_slice) {
                        let abs_off = window_start_offset + hit as u64;
                        if self.sector_step == 1 || abs_off % self.sector_step == 0 {
                            candidate_offsets.push((abs_off, FormatHint::Jpeg));
                        }
                    }
                }

                if self.enabled_formats.contains("png") {
                    for hit in finder_png.find_iter(scan_slice) {
                        let abs_off = window_start_offset + hit as u64;
                        if self.sector_step == 1 || abs_off % self.sector_step == 0 {
                            candidate_offsets.push((abs_off, FormatHint::Png));
                        }
                    }
                }

                if self.enabled_formats.contains("mp4")
                    || self.enabled_formats.contains("mov")
                    || self.enabled_formats.contains("raw")
                {
                    let ftyp_search_len = (scan_limit + 4).min(window_arc.len());
                    for hit in finder_isobmff.find_iter(&window_arc[..ftyp_search_len]) {
                        if hit >= 4 {
                            let base_idx = hit - 4;
                            if base_idx < scan_limit {
                                let abs_off = window_start_offset + base_idx as u64;
                                if self.sector_step == 1 || abs_off % self.sector_step == 0 {
                                    candidate_offsets.push((abs_off, FormatHint::Isobmff));
                                }
                            }
                        }
                    }
                }

                if self.enabled_formats.contains("raw") {
                    for hit in finder_tiff_le.find_iter(scan_slice) {
                        let abs_off = window_start_offset + hit as u64;
                        if self.sector_step == 1 || abs_off % self.sector_step == 0 {
                            candidate_offsets.push((abs_off, FormatHint::TiffRaw));
                        }
                    }
                    for hit in finder_tiff_be.find_iter(scan_slice) {
                        let abs_off = window_start_offset + hit as u64;
                        if self.sector_step == 1 || abs_off % self.sector_step == 0 {
                            candidate_offsets.push((abs_off, FormatHint::TiffRaw));
                        }
                    }
                }

                // Parallel structural validation across all CPU cores
                let mut parsed_candidates: Vec<CarveCandidate> = candidate_offsets
                    .into_par_iter()
                    .filter_map(|(abs_off, hint)| {
                        if self.claimed.read().is_claimed(abs_off, abs_off + self.sector_step) {
                            return None;
                        }

                        let cand = match hint {
                            FormatHint::Jpeg => parse_jpeg(&stream, abs_off, 50 * 1024 * 1024),
                            FormatHint::Png => parse_png(&stream, abs_off, 100 * 1024 * 1024),
                            FormatHint::Isobmff => parse_isobmff(&stream, abs_off, 4 * 1024 * 1024 * 1024),
                            FormatHint::TiffRaw => parse_tiff_raw(&stream, abs_off, 250 * 1024 * 1024),
                        }?;

                        let stat_key = Self::ext_to_stat_key(&cand.extension);
                        if self.enabled_formats.contains(stat_key) {
                            Some(cand)
                        } else {
                            None
                        }
                    })
                    .collect();

                // Parent RAW/JPEG files claim ranges before embedded EXIF thumbnails
                parsed_candidates.sort_by(|a, b| {
                    a.offset.cmp(&b.offset).then_with(|| b.length.cmp(&a.length))
                });

                for cand in parsed_candidates {
                    if !self.running.load(Ordering::SeqCst) {
                        break;
                    }

                    let end_offset = match cand.offset.checked_add(cand.length) {
                        Some(end) => end,
                        None => continue,
                    };

                    if !self.claimed.write().try_claim(cand.offset, end_offset) {
                        continue;
                    }

                    let stat_key = Self::ext_to_stat_key(&cand.extension);
                    let folder = self.get_target_folder(stat_key);
                    let file_name = format!("carved_0x{:010X}_{}B.{}", cand.offset, cand.length, cand.extension);
                    let full_save_path = folder.join(&file_name);

                    let in_window_slice = cand.offset.checked_sub(window_start_offset).and_then(|rel| {
                        let start = usize::try_from(rel).ok()?;
                        let len = usize::try_from(cand.length).ok()?;
                        let end = start.checked_add(len)?;
                        window_arc.get(start..end)
                    });

                    let write_ok = match in_window_slice {
                        Some(slice) => fs::write(&full_save_path, slice).is_ok(),
                        None => match File::create(&full_save_path) {
                            Ok(f) => {
                                let mut writer = BufWriter::with_capacity(1024 * 1024, f);
                                let mut written = 0u64;
                                let mut ok = true;
                                while written < cand.length && self.running.load(Ordering::SeqCst) {
                                    let chunk_sz = (cand.length - written).min(1024 * 1024) as usize;
                                    let bytes = stream.read_at(cand.offset + written, chunk_sz);
                                    if bytes.is_empty() || writer.write_all(&bytes).is_err() {
                                        ok = false;
                                        break;
                                    }
                                    written += bytes.len() as u64;
                                }
                                ok && writer.flush().is_ok()
                            }
                            Err(_) => false,
                        },
                    };

                    if write_ok {
                        *self.stats.write().found.entry(stat_key.to_string()).or_insert(0) += 1;

                        Python::with_gil(|py| {
                            let dict = pyo3::types::PyDict::new_bound(py);
                            let _ = dict.set_item("name", &file_name);
                            let _ = dict.set_item("path", full_save_path.to_string_lossy().to_string());
                            let _ = dict.set_item("type", &cand.file_type);
                            let _ = dict.set_item("ext", cand.extension.to_ascii_uppercase());
                            let _ = dict.set_item("size", cand.length);
                            let _ = dict.set_item("offset", cand.offset);
                            let _ = dict.set_item("details", &cand.details);

                            let _ = on_file_found.call1(py, (dict,));
                            let log_msg = format!(
                                "Recovered {}: {} ({:.1} KB) at sector 0x{:X}",
                                cand.file_type,
                                file_name,
                                cand.length as f64 / 1024.0,
                                cand.offset
                            );
                            let _ = on_log.call1(py, (log_msg, "success"));
                        });
                    }
                }

                if scan_limit > 0 {
                    window_start_offset += scan_limit as u64;
                    self.stats.write().scanned_bytes = window_start_offset;
                } else {
                    break;
                }

                if last_progress_time.elapsed() >= Duration::from_millis(100) || is_eof {
                    let elapsed = start_time.elapsed().as_secs_f64().max(0.001);
                    let speed_mb = (window_start_offset as f64 / (1024.0 * 1024.0)) / elapsed;
                    let eta_sec = if speed_mb > 0.0 && total_bytes > window_start_offset {
                        (total_bytes - window_start_offset) as f64 / (speed_mb * 1024.0 * 1024.0)
                    } else {
                        0.0
                    };
                    let total_found = self.stats.read().found.values().sum::<usize>();

                    Python::with_gil(|py| {
                        let _ = on_progress.call1(
                            py,
                            (window_start_offset, total_bytes, speed_mb, eta_sec, total_found),
                        );
                    });
                    last_progress_time = Instant::now();
                }

                if is_eof && overlap_tail.is_empty() {
                    break;
                }
            }
        });

        if let Some(err) = critical_read_error {
            return Err(pyo3::exceptions::PyIOError::new_err(err));
        }

        let mut st = self.stats.write();
        st.elapsed_time = start_time.elapsed().as_secs_f64();

        let dict = pyo3::types::PyDict::new_bound(py);
        dict.set_item("scanned_bytes", st.scanned_bytes)?;
        dict.set_item("total_bytes", st.total_bytes)?;
        dict.set_item("elapsed_time", st.elapsed_time)?;

        let found_dict = pyo3::types::PyDict::new_bound(py);
        for (k, v) in &st.found {
            found_dict.set_item(k, *v)?;
        }
        dict.set_item("found", found_dict)?;

        let fin_msg = format!(
            "Recovery scan complete. Total files recovered: {}.",
            st.found.values().sum::<usize>()
        );
        let _ = on_log.call1(py, (fin_msg, "success"));

        Ok(dict.into())
    }
}