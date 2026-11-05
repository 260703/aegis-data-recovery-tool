"""
Safe, Strictly Read-Only Disk Stream Handler
============================================
Ensures that all target drives and raw images are accessed in strict read-only mode ('rb').
Handles Windows sector-aligned seeks and reads for both physical drives (\\\\.\\PhysicalDriveX)
and logical volumes (\\\\.\\E:).
Never silently suppresses PermissionError or OSError on disk reads.
"""

import os
import sys
import platform
import ctypes
from ctypes import wintypes
from typing import Optional, Tuple
import threading


class DiskStream:
    """
    Thread-safe, strictly read-only binary stream handler.
    Automatically handles sector alignment for Windows physical/logical drives
    and provides a lock-free in-memory sliding-window cache for fast carving.
    """
    def __init__(self, target_path: str, sector_size: int = 512):
        self.raw_target = target_path
        self.sector_size = max(512, sector_size)
        # Use 4096-byte alignment for raw device I/O so both 512-byte and 4Kn drives succeed
        self.io_align = 4096
        self.is_windows = platform.system() == "Windows"
        self.is_device = False
        self.file_path = self._normalize_path(target_path)
        self.total_size = 0
        self._lock = threading.Lock()
        # Atomic tuple (window_start_offset, window_bytes) for lock-free RAM reads
        self._win_cache: Tuple[int, bytes] = (0, b"")

        # STRICT SAFETY: Strictly open in binary read-only ('rb') mode
        try:
            self._fd = open(self.file_path, "rb", buffering=0)
        except PermissionError as e:
            err_msg = (
                f"[!] Permission denied accessing '{self.file_path}'. "
                "Administrator privileges are required for raw physical drive access on Windows."
            )
            print(err_msg, file=sys.stderr)
            raise PermissionError(err_msg) from e
        except Exception as e:
            err_msg = f"[!] Unable to open target '{self.file_path}': {e}"
            print(err_msg, file=sys.stderr)
            raise RuntimeError(err_msg) from e

        self.total_size = self._determine_total_size()
        print(f"[DEBUG] Target stream initialized: {self.file_path}")
        print(f"[DEBUG] Total size: {self.total_size:,} bytes ({self.total_size / (1024**3):.2f} GB)")

    def set_window_cache(self, start_offset: int, data: bytes):
        """Updates the in-memory sliding window cache for zero-disk-I/O parser reads."""
        self._win_cache = (start_offset, data)

    def _normalize_path(self, path: str) -> str:
        """Normalizes physical drive numbers and volume paths."""
        p = path.strip()
        if self.is_windows:
            clean = p.rstrip("\\/")
            # Single drive letter (e.g. E: or E:\)
            if len(clean) == 2 and clean[1] == ":" and clean[0].isalpha():
                self.is_device = True
                return f"\\\\.\\{clean[0]}:"
            # Physical drive (e.g. \\.\PhysicalDrive1 or PhysicalDrive1)
            if clean.upper().startswith("PHYSICALDRIVE"):
                self.is_device = True
                return f"\\\\.\\{clean}"
            if clean.upper().startswith("\\\\.\\PHYSICALDRIVE"):
                self.is_device = True
                return clean
            if p.startswith("\\\\.\\"):
                self.is_device = True
                return p
        else:
            if p.startswith("/dev/"):
                self.is_device = True
                return p
        return p

    def _determine_total_size(self) -> int:
        """Determines device or image file size in bytes safely."""
        # 1. Standard file seek for image files
        try:
            self._fd.seek(0, os.SEEK_END)
            size = self._fd.tell()
            if size > 0:
                self._fd.seek(0, os.SEEK_SET)
                return size
        except (OSError, IOError):
            pass

        # 2. Windows IOCTL_DISK_GET_LENGTH_INFO (0x00074059) for raw physical disks & volumes
        if self.is_windows and self.is_device:
            try:
                IOCTL_DISK_GET_LENGTH_INFO = 0x00074059

                class GET_LENGTH_INFORMATION(ctypes.Structure):
                    _fields_ = [("Length", ctypes.c_int64)]

                import msvcrt
                handle = msvcrt.get_osfhandle(self._fd.fileno())
                out_buf = GET_LENGTH_INFORMATION()
                bytes_returned = wintypes.DWORD(0)

                kernel32 = ctypes.windll.kernel32
                kernel32.DeviceIoControl.argtypes = [
                    wintypes.HANDLE,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p,
                ]
                kernel32.DeviceIoControl.restype = wintypes.BOOL

                res = kernel32.DeviceIoControl(
                    wintypes.HANDLE(handle),
                    IOCTL_DISK_GET_LENGTH_INFO,
                    None,
                    0,
                    ctypes.byref(out_buf),
                    ctypes.sizeof(out_buf),
                    ctypes.byref(bytes_returned),
                    None
                )
                if res != 0 and out_buf.Length > 0:
                    self._fd.seek(0, os.SEEK_SET)
                    return int(out_buf.Length)
            except Exception:
                pass

            # 3. For volumes, check via psutil
            try:
                import psutil
                clean_letter = self.file_path.replace("\\\\.\\", "").rstrip(":")
                if len(clean_letter) == 1 and clean_letter.isalpha():
                    mount = f"{clean_letter}:\\"
                    usage = psutil.disk_usage(mount)
                    if usage.total > 0:
                        return usage.total
            except Exception:
                pass

        # 4. Binary probe fallback
        return self._probe_size_binary_search()

    def _probe_size_binary_search(self) -> int:
        low = 0
        high = 1024 * 1024 * 1024 * 1024 * 32  # Up to 32 TB
        step = self.io_align
        last_valid = 0

        while low <= high:
            mid = ((low + high) // (2 * step)) * step
            try:
                with self._lock:
                    self._fd.seek(mid, os.SEEK_SET)
                    data = self._fd.read(step)
                if data and len(data) > 0:
                    last_valid = mid + len(data)
                    low = mid + step
                else:
                    high = mid - step
            except (OSError, IOError):
                high = mid - step

        with self._lock:
            try:
                self._fd.seek(0, os.SEEK_SET)
            except Exception:
                pass
        return last_valid

    def read_at(self, offset: int, length: int) -> bytes:
        """
        Thread-safe sector-aligned read at absolute byte offset.
        Serves directly from the in-memory sliding window when possible,
        and aligns physical reads to 4096-byte boundaries on raw devices.
        """
        if offset < 0 or length <= 0:
            return b""

        if self.total_size > 0:
            if offset >= self.total_size:
                return b""
            length = min(length, self.total_size - offset)

        # Fast path: serve from in-memory sliding window without locking or disk I/O
        win_start, win_data = self._win_cache
        if win_data and offset >= win_start and (offset + length) <= (win_start + len(win_data)):
            rel_start = offset - win_start
            return win_data[rel_start : rel_start + length]

        with self._lock:
            # Regular disk image file
            if not self.is_device:
                try:
                    self._fd.seek(offset, os.SEEK_SET)
                    return self._fd.read(length)
                except (OSError, IOError) as err:
                    print(f"[!] Read error on file at offset {offset:,} (len {length:,}): {err}", file=sys.stderr)
                    raise

            # Raw device: align both seek offset and read length to hardware io_align (4096)
            align = self.io_align
            aligned_start = (offset // align) * align
            end_offset = offset + length
            aligned_end = ((end_offset + align - 1) // align) * align

            if self.total_size > 0 and aligned_end > self.total_size:
                aligned_end = ((self.total_size + self.sector_size - 1) // self.sector_size) * self.sector_size

            aligned_length = aligned_end - aligned_start
            if aligned_length <= 0:
                return b""

            try:
                self._fd.seek(aligned_start, os.SEEK_SET)
                raw_bytes = self._fd.read(aligned_length)
            except (OSError, IOError) as err:
                print(
                    f"[!] RAW DISK READ ERROR on {self.file_path} at sector offset {aligned_start:,} "
                    f"(len {aligned_length:,}): {err}",
                    file=sys.stderr
                )
                raise

            if not raw_bytes:
                return b""

            slice_start = offset - aligned_start
            slice_end = slice_start + length
            return raw_bytes[slice_start:slice_end]

    def close(self):
        self._win_cache = (0, b"")
        with self._lock:
            try:
                self._fd.close()
            except Exception:
                pass