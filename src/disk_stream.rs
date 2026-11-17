//! Safe, Strictly Read-Only Disk Stream & Shared Window RAM Cache
//! ==============================================================
//! Provides sector-aligned direct I/O for raw physical drives (\\.\PhysicalDriveX),
//! logical volumes (\\.\E:), and raw disk images (.dd, .img, .raw).

use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::Path;
use std::sync::Arc;
use parking_lot::{Mutex, RwLock};

#[cfg(windows)]
use windows::core::PCWSTR;
#[cfg(windows)]
use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(windows)]
use windows::Win32::Storage::FileSystem::{
    CreateFileW, ReadFile, SetFilePointerEx, FILE_ATTRIBUTE_NORMAL, FILE_BEGIN, FILE_SHARE_READ,
    FILE_SHARE_WRITE, OPEN_EXISTING,
};
#[cfg(windows)]
use windows::Win32::System::IO::DeviceIoControl;
#[cfg(windows)]
use windows::Win32::System::Ioctl::{GET_LENGTH_INFORMATION, IOCTL_DISK_GET_LENGTH_INFO};

/// Shared in-memory window buffer for zero-I/O candidate parsing across Rayon worker threads.
#[derive(Clone)]
pub struct WindowBuffer {
    pub start_offset: u64,
    pub data: Arc<Vec<u8>>,
}

impl WindowBuffer {
    #[inline]
    pub fn slice_range(&self, offset: u64, length: usize) -> Option<&[u8]> {
        if offset < self.start_offset {
            return None;
        }
        let rel_start = usize::try_from(offset - self.start_offset).ok()?;
        let rel_end = rel_start.checked_add(length)?;
        self.data.get(rel_start..rel_end)
    }
}

enum StreamBackend {
    #[cfg(windows)]
    Win32Device { handle: Mutex<HANDLE> },
    StdFile { file: Mutex<File> },
}

unsafe impl Send for StreamBackend {}
unsafe impl Sync for StreamBackend {}

impl Drop for StreamBackend {
    fn drop(&mut self) {
        #[cfg(windows)]
        if let StreamBackend::Win32Device { handle } = self {
            let h = *handle.lock();
            if h != INVALID_HANDLE_VALUE && !h.is_invalid() {
                unsafe {
                    let _ = CloseHandle(h);
                }
            }
        }
    }
}

/// High-performance, strictly read-only binary stream handler.
pub struct DiskStream {
    target_path: String,
    backend: StreamBackend,
    pub is_device: bool,
    pub total_size: u64,
    pub sector_size: u64,
    pub io_align: u64,
    window_cache: RwLock<Option<WindowBuffer>>,
}

impl DiskStream {
    /// Opens target strictly in read-only mode with 4096-byte hardware sector alignment.
    pub fn open(target: &str, sector_size: u64) -> io::Result<Arc<Self>> {
        let (normalized, is_device) = Self::normalize_path(target);
        let sector_size = sector_size.max(512);
        let io_align = 4096u64;

        #[cfg(windows)]
        let backend = if is_device {
            let wide: Vec<u16> = normalized.encode_utf16().chain(Some(0)).collect();
            let handle = unsafe {
                CreateFileW(
                    PCWSTR(wide.as_ptr()),
                    GENERIC_READ.0,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    None,
                )
            };

            match handle {
                Ok(h) if h != INVALID_HANDLE_VALUE && !h.is_invalid() => {
                    StreamBackend::Win32Device {
                        handle: Mutex::new(h),
                    }
                }
                Err(e) => {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        format!(
                            "Failed to open raw device '{}': {}. Administrator privileges are required.",
                            normalized, e
                        ),
                    ));
                }
                Ok(_) => {
                    return Err(io::Error::new(
                        io::ErrorKind::PermissionDenied,
                        format!("Invalid handle returned opening '{}'.", normalized),
                    ));
                }
            }
        } else {
            let f = File::open(&normalized)?;
            StreamBackend::StdFile {
                file: Mutex::new(f),
            }
        };

        #[cfg(not(windows))]
        let backend = {
            let f = File::open(&normalized)?;
            StreamBackend::StdFile {
                file: Mutex::new(f),
            }
        };

        let mut stream = Self {
            target_path: normalized,
            backend,
            is_device,
            total_size: 0,
            sector_size,
            io_align,
            window_cache: RwLock::new(None),
        };

        stream.total_size = stream.determine_total_size();
        Ok(Arc::new(stream))
    }

    /// Normalizes Windows drive letters, PhysicalDrive paths, and regular file paths.
    pub fn normalize_path(path: &str) -> (String, bool) {
        let trimmed = path.trim();
        #[cfg(windows)]
        {
            let clean = trimmed.trim_end_matches(['\\', '/']);
            if clean.len() == 2
                && clean.ends_with(':')
                && clean.chars().next().is_some_and(|c| c.is_ascii_alphabetic())
            {
                return (format!(r"\\.\{}", &clean[0..2]), true);
            }
            let upper = clean.to_ascii_uppercase();
            if upper.starts_with("PHYSICALDRIVE") {
                return (format!(r"\\.\{}", clean), true);
            }
            if upper.starts_with(r"\\.\PHYSICALDRIVE") || clean.starts_with(r"\\.\") {
                return (clean.to_string(), true);
            }
        }

        #[cfg(not(windows))]
        {
            if trimmed.starts_with("/dev/") {
                return (trimmed.to_string(), true);
            }
        }

        (trimmed.to_string(), false)
    }

    fn determine_total_size(&self) -> u64 {
        if !self.is_device {
            if let Ok(meta) = Path::new(&self.target_path).metadata() {
                if meta.len() > 0 {
                    return meta.len();
                }
            }
            if let StreamBackend::StdFile { ref file } = self.backend {
                let mut guard = file.lock();
                if let Ok(len) = guard.seek(SeekFrom::End(0)) {
                    let _ = guard.seek(SeekFrom::Start(0));
                    if len > 0 {
                        return len;
                    }
                }
            }
        }

        #[cfg(windows)]
        if self.is_device {
            if let StreamBackend::Win32Device { ref handle } = self.backend {
                let h = *handle.lock();
                let mut length_info = GET_LENGTH_INFORMATION::default();
                let mut bytes_returned = 0u32;
                let res = unsafe {
                    DeviceIoControl(
                        h,
                        IOCTL_DISK_GET_LENGTH_INFO,
                        None,
                        0,
                        Some(&mut length_info as *mut _ as *mut _),
                        std::mem::size_of::<GET_LENGTH_INFORMATION>() as u32,
                        Some(&mut bytes_returned),
                        None,
                    )
                };

                if res.is_ok() && length_info.Length > 0 {
                    return length_info.Length as u64;
                }
            }
        }

        self.probe_size_binary_search()
    }

    fn probe_size_binary_search(&self) -> u64 {
        let mut low = 0u64;
        let mut high = 32u64 * 1024 * 1024 * 1024 * 1024;
        let step = self.io_align;
        let mut last_valid = 0u64;

        while low <= high {
            let mid = ((low + high) / (2 * step)) * step;
            let test_data = self.raw_read_direct(mid, step as usize).unwrap_or_default();
            if !test_data.is_empty() {
                last_valid = mid + test_data.len() as u64;
                low = match mid.checked_add(step) {
                    Some(next) => next,
                    None => break,
                };
            } else {
                if mid < step {
                    break;
                }
                high = mid - step;
            }
        }

        last_valid
    }

    pub fn set_window_cache(&self, start_offset: u64, data: Arc<Vec<u8>>) {
        let mut cache = self.window_cache.write();
        *cache = Some(WindowBuffer { start_offset, data });
    }

    /// Speculative read for parsers: checks RAM window cache first, returns empty Vec on EOF/error.
    pub fn read_at(&self, offset: u64, length: usize) -> Vec<u8> {
        self.read_at_checked(offset, length).unwrap_or_default()
    }

    /// Checked read for sequential block streaming: propagates OS/hardware disconnect errors.
    pub fn read_at_checked(&self, offset: u64, length: usize) -> io::Result<Vec<u8>> {
        if length == 0 {
            return Ok(Vec::new());
        }

        let req_len = if self.total_size > 0 {
            if offset >= self.total_size {
                return Ok(Vec::new());
            }
            (length as u64).min(self.total_size - offset) as usize
        } else {
            length
        };

        if req_len == 0 {
            return Ok(Vec::new());
        }

        // Fast path: serve from shared in-memory window buffer
        {
            let cache = self.window_cache.read();
            if let Some(ref win) = *cache {
                if let Some(slice) = win.slice_range(offset, req_len) {
                    return Ok(slice.to_vec());
                }
            }
        }

        self.raw_read_direct(offset, req_len)
    }

    fn raw_read_direct(&self, offset: u64, length: usize) -> io::Result<Vec<u8>> {
        if length == 0 {
            return Ok(Vec::new());
        }

        match &self.backend {
            #[cfg(windows)]
            StreamBackend::Win32Device { handle } => {
                let handle_guard = handle.lock();
                let h = *handle_guard;
                let align = self.io_align;
                let aligned_start = (offset / align) * align;
                let end_offset = offset
                    .checked_add(length as u64)
                    .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "Offset overflow"))?;

                let mut aligned_end = ((end_offset + align - 1) / align) * align;

                if self.total_size > 0 && aligned_end > self.total_size {
                    aligned_end = self.total_size;
                }

                if aligned_start >= aligned_end {
                    return Ok(Vec::new());
                }

                let aligned_length = (aligned_end - aligned_start) as usize;
                let mut buffer = vec![0u8; aligned_length];

                unsafe {
                    let mut new_pos = 0i64;
                    SetFilePointerEx(h, aligned_start as i64, Some(&mut new_pos), FILE_BEGIN)
                        .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("Seek failed: {}", e)))?;

                    let mut bytes_read = 0u32;
                    ReadFile(
                        h,
                        Some(&mut buffer[..aligned_length]),
                        Some(&mut bytes_read),
                        None,
                    )
                    .map_err(|e| io::Error::new(io::ErrorKind::Other, format!("ReadFile failed: {}", e)))?;

                    if bytes_read == 0 {
                        return Ok(Vec::new());
                    }

                    buffer.truncate(bytes_read as usize);
                }

                let slice_start = (offset - aligned_start) as usize;
                if slice_start >= buffer.len() {
                    return Ok(Vec::new());
                }

                let slice_end = (slice_start + length).min(buffer.len());
                Ok(buffer[slice_start..slice_end].to_vec())
            }
            StreamBackend::StdFile { file } => {
                let mut guard = file.lock();
                guard.seek(SeekFrom::Start(offset))?;
                let mut buffer = vec![0u8; length];
                let bytes_read = guard.read(&mut buffer)?;
                buffer.truncate(bytes_read);
                Ok(buffer)
            }
        }
    }
}