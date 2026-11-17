"""
Device Detection & Drive Manager
================================
Detects physical disk drives (\\\\.\\PhysicalDriveX), removable USB drives, and partitions.
Integrates with the high-performance compiled Rust engine (`aegis_core`) for direct Win32
physical hardware enumeration and target overwrite safety checks.
"""

import os
import platform
import ctypes
import subprocess
import json
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
import psutil

try:
    import aegis_core
except ImportError:
    aegis_core = None

# Windows Drive Types
DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6


class DeviceInfo:
    """Encapsulates detailed information about a detectable drive or storage target."""
    def __init__(self, device_path: str, display_name: str, drive_type: str,
                 total_bytes: int, free_bytes: int, filesystem: str, is_removable: bool,
                 mountpoint: str = "", model: str = ""):
        self.device_path = device_path       # e.g., "\\\\.\\PhysicalDrive1" or "\\\\.\\E:"
        self.display_name = display_name     # User-facing label in GUI dropdown
        self.drive_type = drive_type         # "Raw Physical Drive", "USB Removable", "Local Disk"
        self.total_bytes = total_bytes
        self.free_bytes = free_bytes
        self.filesystem = filesystem
        self.is_removable = is_removable
        self.mountpoint = mountpoint.rstrip("\\/") + "\\" if mountpoint else ""
        self.model = model

    def __repr__(self):
        return f"<DeviceInfo {self.display_name}>"


class DeviceManager:
    """Manages disk drive enumeration and safety verifications."""
    def __init__(self):
        self.is_windows = platform.system() == "Windows"

    def get_available_devices(self) -> List[DeviceInfo]:
        """
        Returns all detectable storage drives.
        Prioritizes raw physical drives (\\\\.\\PhysicalDriveX) and removable USB media.
        """
        if aegis_core is not None:
            try:
                raw_devices = aegis_core.list_devices()
                return [
                    DeviceInfo(
                        device_path=d["device_path"],
                        display_name=d["display_name"],
                        drive_type=d["drive_type"],
                        total_bytes=d["total_bytes"],
                        free_bytes=d["free_bytes"],
                        filesystem=d["filesystem"],
                        is_removable=d["is_removable"],
                        mountpoint=d.get("mountpoint", ""),
                        model=d.get("model", "")
                    )
                    for d in raw_devices
                ]
            except Exception:
                pass

        # Fallback Python enumeration if aegis_core is not loaded
        devices: List[DeviceInfo] = []
        seen_paths = set()

        if self.is_windows:
            phys_drives = self._get_windows_physical_drives()
            for pd in phys_drives:
                dev_id = pd.get("DeviceID", "")
                if not dev_id:
                    continue
                model = pd.get("Model", "Physical Drive")
                size_bytes = int(pd.get("Size", 0) or 0)
                media_type = str(pd.get("MediaType", "") or "")
                interface_type = str(pd.get("InterfaceType", "") or "")

                is_usb = ("USB" in interface_type.upper()) or ("REMOVABLE" in media_type.upper())
                size_gb = size_bytes / (1024**3)

                rec_tag = " [RECOMMENDED FOR CARVING]" if is_usb else ""
                disp = f"{dev_id} [{model}] - {size_gb:.1f} GB ({interface_type or 'Raw Disk'}){rec_tag}"

                devices.append(DeviceInfo(
                    device_path=dev_id,
                    display_name=disp,
                    drive_type="Raw Physical Drive",
                    total_bytes=size_bytes,
                    free_bytes=0,
                    filesystem="Raw Sectors (Direct I/O)",
                    is_removable=is_usb,
                    model=model
                ))
                seen_paths.add(dev_id.upper())

        try:
            partitions = psutil.disk_partitions(all=True)
            for p in partitions:
                mountpoint = p.mountpoint
                fstype = p.fstype or "RAW"
                total_bytes = 0
                free_bytes = 0
                try:
                    usage = psutil.disk_usage(mountpoint)
                    total_bytes = usage.total
                    free_bytes = usage.free
                except Exception:
                    pass

                type_desc = "Local Disk"
                is_removable = False

                if self.is_windows:
                    try:
                        dtype = ctypes.windll.kernel32.GetDriveTypeW(mountpoint)
                        if dtype == DRIVE_REMOVABLE:
                            type_desc = "USB Removable Volume"
                            is_removable = True
                        elif dtype == DRIVE_CDROM:
                            continue
                        elif dtype == DRIVE_REMOTE:
                            type_desc = "Network Drive"
                        else:
                            type_desc = "Local Volume"
                    except Exception:
                        pass

                size_gb = total_bytes / (1024**3)
                drive_letter = mountpoint.rstrip("\\/")
                raw_path = f"\\\\.\\{drive_letter}" if (self.is_windows and len(drive_letter) == 2 and drive_letter[1] == ":") else p.device
                disp = f"{drive_letter} [{type_desc}] - {size_gb:.1f} GB ({fstype})"
                devices.append(DeviceInfo(
                    device_path=raw_path,
                    display_name=disp,
                    drive_type=type_desc,
                    total_bytes=total_bytes,
                    free_bytes=free_bytes,
                    filesystem=fstype,
                    is_removable=is_removable,
                    mountpoint=mountpoint
                ))
        except Exception:
            pass

        devices.sort(key=lambda d: (
            0 if (d.is_removable and "PHYSICALDRIVE" in d.device_path.upper()) else
            1 if d.is_removable else
            2 if "PHYSICALDRIVE" in d.device_path.upper() else 3,
            d.display_name
        ))
        return devices

    def _get_windows_physical_drives(self) -> List[Dict[str, Any]]:
        try:
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_DiskDrive | Select-Object DeviceID, Model, Size, MediaType, InterfaceType | ConvertTo-Json -Compress"
            ]
            out = subprocess.check_output(cmd, text=True, timeout=5).strip()
            if not out:
                return []
            data = json.loads(out)
            return [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
        except Exception:
            return []

    def is_admin(self) -> bool:
        """Checks if current process has Windows Administrator privileges."""
        if aegis_core is not None:
            return aegis_core.is_admin()
        if not self.is_windows:
            return os.geteuid() == 0 if hasattr(os, "geteuid") else False
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def is_output_safe(self, target_device_path: str, output_dir: str) -> Tuple[bool, str]:
        """
        STRICT SAFETY ENFORCEMENT:
        Verifies that the output directory is NOT on the drive being recovered.
        """
        if aegis_core is not None:
            try:
                return aegis_core.is_output_safe(target_device_path, output_dir)
            except Exception:
                pass

        try:
            out_path = Path(output_dir).resolve()
            out_root = out_path.anchor.upper()
            tgt = target_device_path.upper()

            if "\\\\.\\" in tgt and "PHYSICALDRIVE" not in tgt:
                clean_tgt = tgt.replace("\\\\.\\", "").rstrip(":\\")
                if len(clean_tgt) == 1 and clean_tgt.isalpha():
                    tgt_root = f"{clean_tgt}:\\"
                    if out_root == tgt_root:
                        return False, (
                            f"SAFETY ALERT: Output folder is located on the target recovery drive ({tgt_root})!\n\n"
                            "Writing recovered files to the same drive will permanently OVERWRITE deleted data.\n"
                            "Please choose a folder on a different drive (e.g. C: or an external backup disk)."
                        )

            for p in psutil.disk_partitions(all=True):
                p_mount = p.mountpoint.upper()
                if p_mount and p.device.upper() in tgt:
                    if str(out_path).upper().startswith(p_mount):
                        return False, (
                            f"SAFETY ALERT: Output folder is inside the target drive ({p_mount})!\n\n"
                            "Please select an output directory on a separate drive."
                        )

            return True, "Safe"
        except Exception as e:
            return True, f"Warning checking safety: {e}"
