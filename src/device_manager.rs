//! Hardware Device Enumeration & Physical Overwrite Safety Verification
//! ====================================================================
//! Probes physical storage drives (\\.\PhysicalDriveX) and logical volumes (\\.\E:).
//! Compares physical disk numbers via IOCTL_STORAGE_GET_DEVICE_NUMBER to actively
//! block overwriting target media unallocated clusters.

use std::path::{Path, PathBuf};

#[cfg(windows)]
use windows::core::PCWSTR;
#[cfg(windows)]
use windows::Win32::Foundation::{CloseHandle, GENERIC_READ, HANDLE, INVALID_HANDLE_VALUE};
#[cfg(windows)]
use windows::Win32::Storage::FileSystem::{
    CreateFileW, GetDiskFreeSpaceExW, GetDriveTypeW, GetLogicalDrives, FILE_ATTRIBUTE_NORMAL,
    FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
};
#[cfg(windows)]
use windows::Win32::System::IO::DeviceIoControl;
#[cfg(windows)]
#[cfg(windows)]
use windows::Win32::System::Ioctl::{
    GET_LENGTH_INFORMATION, IOCTL_DISK_GET_LENGTH_INFO,
    IOCTL_STORAGE_GET_DEVICE_NUMBER, IOCTL_STORAGE_QUERY_PROPERTY, PropertyStandardQuery,
    STORAGE_DEVICE_DESCRIPTOR, STORAGE_DEVICE_NUMBER, STORAGE_PROPERTY_QUERY,
    StorageDeviceProperty,
};
#[cfg(windows)]
use windows::Win32::UI::Shell::IsUserAnAdmin;

#[cfg(windows)]
const DRIVE_REMOVABLE: u32 = 2;
#[cfg(windows)]
const DRIVE_REMOTE: u32 = 4;
#[cfg(windows)]
const DRIVE_CDROM: u32 = 5;
#[cfg(windows)]
const DRIVE_RAMDISK: u32 = 6;

#[derive(Debug, Clone)]
pub struct DeviceInfoDto {
    pub device_path: String,
    pub display_name: String,
    pub drive_type: String,
    pub total_bytes: u64,
    pub free_bytes: u64,
    pub filesystem: String,
    pub is_removable: bool,
    pub mountpoint: String,
    pub model: String,
}

pub fn is_admin() -> bool {
    #[cfg(windows)]
    unsafe {
        IsUserAnAdmin().as_bool()
    }
    #[cfg(not(windows))]
    unsafe {
        libc::geteuid() == 0
    }
}

/// Resolves an existing ancestor path so `canonicalize()` succeeds even if leaf folders don't exist yet.
fn resolve_existing_path(path: &Path) -> PathBuf {
    let mut curr = Some(path);
    while let Some(p) = curr {
        if p.exists() {
            if let Ok(canon) = p.canonicalize() {
                return canon;
            }
            return p.to_path_buf();
        }
        curr = p.parent();
    }
    path.to_path_buf()
}

/// Strict Safety Enforcement: blocks saving recovered files onto the same drive or physical disk.
pub fn is_output_safe(target_device_path: &str, output_dir: &str) -> (bool, String) {
    let out_resolved = resolve_existing_path(Path::new(output_dir));
    let tgt_upper = target_device_path.trim().to_ascii_uppercase();

    #[cfg(windows)]
    {
        let out_clean = out_resolved
            .to_string_lossy()
            .to_ascii_uppercase()
            .trim_start_matches(r"\\?\")
            .to_string();

        // 1. Direct logical volume string collision (e.g. \\.\E: vs E:\Output)
        if tgt_upper.starts_with(r"\\.\") && !tgt_upper.contains("PHYSICALDRIVE") {
            let clean_tgt = tgt_upper.trim_start_matches(r"\\.\").trim_end_matches([':', '\\']);
            if clean_tgt.len() == 1 {
                let tgt_root = format!("{}:\\", clean_tgt);
                if out_clean.starts_with(&tgt_root) {
                    return (
                        false,
                        format!(
                            "SAFETY ALERT: Output folder is located on the target recovery drive ({})!\n\n\
                            Writing recovered files to the same drive will permanently OVERWRITE deleted clusters.\n\
                            Please select a folder on a different drive (e.g. C:\\ or an external drive).",
                            tgt_root
                        ),
                    );
                }
            }
        }

        // 2. Physical device number comparison via IOCTL_STORAGE_GET_DEVICE_NUMBER
        if let (Some(target_dev_num), Some(output_dev_num)) = (
            get_win32_storage_device_number(&tgt_upper),
            get_output_dir_storage_device_number(&out_clean),
        ) {
            if target_dev_num == output_dev_num {
                return (
                    false,
                    format!(
                        "SAFETY ALERT: Output directory is located on physical disk #{}.\n\n\
                        Target device is on physical disk #{}.\n\
                        Writing recovered data to the same physical disk will overwrite unallocated clusters.\n\
                        Please choose a destination on a different physical disk.",
                        output_dev_num, target_dev_num
                    ),
                );
            }
        }
    }

    #[cfg(not(windows))]
    {
        let out_str = out_resolved.to_string_lossy();
        if out_str.starts_with(target_device_path.trim()) {
            return (
                false,
                "SAFETY ALERT: Output directory resides inside the target device mountpoint.".to_string(),
            );
        }
    }

    (true, "Safe".to_string())
}

#[cfg(windows)]
fn open_win32_device(path: &str) -> Option<HANDLE> {
    let wide: Vec<u16> = path.encode_utf16().chain(Some(0)).collect();
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
        Ok(h) if h != INVALID_HANDLE_VALUE && !h.is_invalid() => Some(h),
        _ => None,
    }
}

#[cfg(windows)]
fn get_win32_storage_device_number(device_path: &str) -> Option<u32> {
    let handle = open_win32_device(device_path)?;
    let mut dev_num = STORAGE_DEVICE_NUMBER::default();
    let mut bytes_returned = 0u32;
    let res = unsafe {
        DeviceIoControl(
            handle,
            IOCTL_STORAGE_GET_DEVICE_NUMBER,
            None,
            0,
            Some(&mut dev_num as *mut _ as *mut _),
            std::mem::size_of::<STORAGE_DEVICE_NUMBER>() as u32,
            Some(&mut bytes_returned),
            None,
        )
    };
    unsafe {
        let _ = CloseHandle(handle);
    }
    if res.is_ok() {
        Some(dev_num.DeviceNumber)
    } else {
        None
    }
}

#[cfg(windows)]
fn get_output_dir_storage_device_number(clean_output_path: &str) -> Option<u32> {
    let bytes = clean_output_path.as_bytes();
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        let volume_path = format!(r"\\.\{}:", bytes[0] as char);
        get_win32_storage_device_number(&volume_path)
    } else {
        None
    }
}

#[cfg(windows)]
fn query_physical_drive_removable(handle: HANDLE) -> bool {
    let query = STORAGE_PROPERTY_QUERY {
        PropertyId: StorageDeviceProperty,
        QueryType: PropertyStandardQuery,
        AdditionalParameters: [0],
    };
    let mut desc = STORAGE_DEVICE_DESCRIPTOR::default();
    let mut bytes_ret = 0u32;

    let res = unsafe {
        DeviceIoControl(
            handle,
            IOCTL_STORAGE_QUERY_PROPERTY,
            Some(&query as *const _ as *const _),
            std::mem::size_of::<STORAGE_PROPERTY_QUERY>() as u32,
            Some(&mut desc as *mut _ as *mut _),
            std::mem::size_of::<STORAGE_DEVICE_DESCRIPTOR>() as u32,
            Some(&mut bytes_ret),
            None,
        )
    };

    res.is_ok() && (desc.RemovableMedia.as_bool() || desc.BusType.0 == 7)
}

/// Enumerates connected physical disks and logical volumes.
pub fn list_devices() -> Vec<DeviceInfoDto> {
    let mut devices = Vec::new();

    #[cfg(windows)]
    {
        for i in 0..=31 {
            let path = format!(r"\\.\PhysicalDrive{}", i);
            if let Some(h) = open_win32_device(&path) {
                let mut length_info = GET_LENGTH_INFORMATION::default();
                let mut bytes_ret = 0u32;
                let size_ok = unsafe {
                    DeviceIoControl(
                        h,
                        IOCTL_DISK_GET_LENGTH_INFO,
                        None,
                        0,
                        Some(&mut length_info as *mut _ as *mut _),
                        std::mem::size_of::<GET_LENGTH_INFORMATION>() as u32,
                        Some(&mut bytes_ret),
                        None,
                    )
                };

                let total_bytes = if size_ok.is_ok() && length_info.Length > 0 {
                    length_info.Length as u64
                } else {
                    0
                };

                let is_removable = query_physical_drive_removable(h);
                unsafe {
                    let _ = CloseHandle(h);
                }

                let size_gb = total_bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                let tag = if is_removable {
                    " [REMOVABLE / USB]"
                } else {
                    ""
                };
                let model = format!("Physical Disk #{}", i);
                let disp = format!("{} [{}] - {:.1} GB (Raw Disk){}", path, model, size_gb, tag);

                devices.push(DeviceInfoDto {
                    device_path: path,
                    display_name: disp,
                    drive_type: "Raw Physical Drive".to_string(),
                    total_bytes,
                    free_bytes: 0,
                    filesystem: "Raw Sectors (Direct I/O)".to_string(),
                    is_removable,
                    mountpoint: String::new(),
                    model,
                });
            }
        }

        let drives_mask = unsafe { GetLogicalDrives() };
        for letter in b'A'..=b'Z' {
            let idx = letter - b'A';
            if (drives_mask & (1 << idx)) != 0 {
                let drive_root = format!("{}:\\", letter as char);
                let wide_root: Vec<u16> = drive_root.encode_utf16().chain(Some(0)).collect();
                let dtype = unsafe { GetDriveTypeW(PCWSTR(wide_root.as_ptr())) };

                if dtype == DRIVE_CDROM {
                    continue;
                }

                let (type_desc, is_removable) = match dtype {
                    DRIVE_REMOVABLE => ("USB Removable Volume", true),
                    DRIVE_REMOTE => ("Network Drive", false),
                    DRIVE_RAMDISK => ("RAM Disk", false),
                    _ => ("Local Disk Volume", false),
                };

                let mut free_bytes_avail = 0u64;
                let mut total_bytes = 0u64;
                let mut total_free_bytes = 0u64;

                let space_ok = unsafe {
                    GetDiskFreeSpaceExW(
                        PCWSTR(wide_root.as_ptr()),
                        Some(&mut free_bytes_avail),
                        Some(&mut total_bytes),
                        Some(&mut total_free_bytes),
                    )
                };

                if space_ok.is_err() {
                    total_bytes = 0;
                    total_free_bytes = 0;
                }

                let size_gb = total_bytes as f64 / (1024.0 * 1024.0 * 1024.0);
                let raw_path = format!(r"\\.\{}:", letter as char);
                let disp = format!("{}: [{}] - {:.1} GB", letter as char, type_desc, size_gb);

                devices.push(DeviceInfoDto {
                    device_path: raw_path,
                    display_name: disp,
                    drive_type: type_desc.to_string(),
                    total_bytes,
                    free_bytes: total_free_bytes,
                    filesystem: "Mounted Volume".to_string(),
                    is_removable,
                    mountpoint: drive_root,
                    model: format!("Volume {}", letter as char),
                });
            }
        }
    }

    devices.sort_by(|a, b| {
        let a_is_phys = a.device_path.to_ascii_uppercase().contains("PHYSICALDRIVE");
        let b_is_phys = b.device_path.to_ascii_uppercase().contains("PHYSICALDRIVE");
        let a_prio = if a.is_removable && a_is_phys {
            0
        } else if a.is_removable {
            1
        } else if a_is_phys {
            2
        } else {
            3
        };
        let b_prio = if b.is_removable && b_is_phys {
            0
        } else if b.is_removable {
            1
        } else if b_is_phys {
            2
        } else {
            3
        };
        a_prio.cmp(&b_prio).then_with(|| a.display_name.cmp(&b.display_name))
    });

    devices
}