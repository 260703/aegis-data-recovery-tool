"""
Background QThread Scanning & Recovery Worker
==============================================
Runs disk sector carving on a dedicated background QThread with PySide6 signals.
Implements a true sliding-window overlap buffer so signatures spanning chunk boundaries
are never missed.
Provides detailed debug logging of raw bytes read from the target drive.
Never suppresses PermissionError or OSError on disk reads.
"""

import sys
import time
import threading
from pathlib import Path
from typing import Set, List, Optional

from PySide6.QtCore import QThread, Signal

from core.disk_stream import DiskStream
from core.parsers import (
    CarveCandidate,
    parse_jpeg,
    parse_png,
    parse_isobmff,
    parse_tiff_raw,
    JPEG_SOI,
    PNG_MAGIC,
    ISOBMFF_FTYP,
    TIFF_LE_MAGIC,
    TIFF_BE_MAGIC
)


class RecoveryWorker(QThread):
    """
    Dedicated background worker thread for disk carving and file recovery.
    Uses a robust sliding window with overlap to prevent boundary misses.
    """
    # Signals to communicate with the main PySide6 UI thread (using object for arbitrary-precision ints)
    sig_started = Signal(object)                        # total_bytes (Python int)
    sig_progress = Signal(object, object, float, float, int)  # current_bytes, total_bytes, speed_mb, eta_sec, total_found
    sig_file_found = Signal(dict)                    # metadata dict for recovered file table
    sig_log = Signal(str, str)                       # message, level ('info', 'success', 'warning', 'error')
    sig_finished = Signal(dict)                      # final summary stats
    sig_error = Signal(str)                          # critical failure message

    def __init__(self, target_path: str, output_dir: str, sector_step: int = 512,
                 block_size_mb: int = 8, overlap_size_mb: int = 1,
                 enabled_formats: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.target_path = target_path
        self.output_dir = Path(output_dir)
        self.sector_step = max(1, sector_step)
        self.block_size = block_size_mb * 1024 * 1024
        # 64 KB overlap is plenty to catch magic headers across chunk boundaries
        self.overlap_size = 65536
        self.enabled_formats: Set[str] = set(enabled_formats or ["jpeg", "png", "mp4", "mov", "raw"])

        # Control flags
        self._is_running = True
        self._is_paused = False
        self._pause_cond = threading.Condition()

        # Tracking state
        self.claimed_ranges: List[tuple] = []
        self.stats = {
            "scanned_bytes": 0,
            "total_bytes": 0,
            "found": {"jpeg": 0, "png": 0, "mp4": 0, "mov": 0, "raw": 0},
            "elapsed_time": 0.0
        }

    def pause(self):
        """Pauses the scanning thread safely."""
        with self._pause_cond:
            self._is_paused = True
            self.sig_log.emit("Scan paused by user.", "warning")

    def resume(self):
        """Resumes the scanning thread."""
        with self._pause_cond:
            self._is_paused = False
            self._pause_cond.notify_all()
            self.sig_log.emit("Scan resumed.", "info")

    def stop(self):
        """Signals the background thread to terminate immediately."""
        self._is_running = False
        with self._pause_cond:
            self._is_paused = False
            self._pause_cond.notify_all()
        self.sig_log.emit("Stopping scan...", "warning")

    def _is_claimed(self, start: int, end: int) -> bool:
        for c_start, c_end in self.claimed_ranges:
            if not (end <= c_start or start >= c_end):
                return True
        return False

    def _claim(self, start: int, end: int):
        self.claimed_ranges.append((start, end))

    @staticmethod
    def _ext_to_stat_key(ext: str) -> str:
        ext = ext.lower()
        if ext in ("jpg", "jpeg"):
            return "jpeg"
        if ext == "png":
            return "png"
        if ext in ("cr2", "cr3", "raw", "nef", "arw", "dng"):
            return "raw"
        if ext == "mp4":
            return "mp4"
        if ext == "mov":
            return "mov"
        return "jpeg"

    def _get_target_folder(self, stat_key: str) -> Path:
        if stat_key == "jpeg":
            sub = self.output_dir / "Images" / "JPEG"
        elif stat_key == "png":
            sub = self.output_dir / "Images" / "PNG"
        elif stat_key == "raw":
            sub = self.output_dir / "Images" / "RAW"
        elif stat_key == "mp4":
            sub = self.output_dir / "Videos" / "MP4"
        elif stat_key == "mov":
            sub = self.output_dir / "Videos" / "MOV"
        else:
            sub = self.output_dir / "Other"
        sub.mkdir(parents=True, exist_ok=True)
        return sub

    def run(self):
        """Primary QThread execution procedure."""
        stream: Optional[DiskStream] = None
        try:
            self.sig_log.emit(f"Opening target device: {self.target_path}", "info")
            stream = DiskStream(self.target_path, sector_size=self.sector_step)
        except PermissionError:
            err_msg = f"ACCESS DENIED on {self.target_path}: Administrator privileges required."
            print(f"[!] {err_msg}", file=sys.stderr)
            self.sig_error.emit(err_msg)
            self.sig_log.emit(err_msg, "error")
            return
        except Exception as e:
            err_msg = f"Failed to initialize target {self.target_path}: {e}"
            print(f"[!] {err_msg}", file=sys.stderr)
            self.sig_error.emit(err_msg)
            self.sig_log.emit(err_msg, "error")
            return

        total_bytes = stream.total_size
        self.stats["total_bytes"] = total_bytes
        self.sig_started.emit(total_bytes)

        size_info = f"{total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)" if total_bytes > 0 else "Unknown / Dynamic"
        print(f"[DEBUG] Target: {self.target_path} | Total Size: {size_info}")
        self.sig_log.emit(f"Target ready: {self.target_path} | Size: {size_info}", "success")

        start_time = time.time()
        last_progress_time = start_time

        # Sliding window state
        window = b""
        window_start_offset = 0
        read_disk_offset = 0
        first_chunk_logged = False

        try:
            while self._is_running:
                # Handle pause state
                with self._pause_cond:
                    while self._is_paused and self._is_running:
                        self._pause_cond.wait(timeout=0.2)

                if not self._is_running:
                    break

                # 1. Read next chunk into sliding window
                read_chunk_len = self.block_size
                if total_bytes > 0:
                    remaining_on_disk = total_bytes - read_disk_offset
                    if remaining_on_disk <= 0 and len(window) == 0:
                        break
                    read_chunk_len = min(read_chunk_len, max(0, remaining_on_disk))

                new_chunk = b""
                if read_chunk_len > 0:
                    try:
                        new_chunk = stream.read_at(read_disk_offset, read_chunk_len)
                    except (PermissionError, OSError) as read_err:
                        err_str = f"Critical Disk Read Error at offset {read_disk_offset:,}: {read_err}"
                        print(f"[!] {err_str}", file=sys.stderr)
                        self.sig_log.emit(err_str, "error")
                        self.sig_error.emit(err_str)
                        break

                # 2. DEBUG OUTPUT: Confirm raw bytes read in the very first chunk
                if not first_chunk_logged:
                    bytes_read = len(new_chunk)
                    dbg_msg = f"[DEBUG] First chunk read: {bytes_read:,} raw bytes pulled from disk."
                    print(dbg_msg)
                    self.sig_log.emit(dbg_msg, "info" if bytes_read > 0 else "error")
                    if bytes_read == 0:
                        warn_msg = (
                            "[!] WARNING: First chunk returned 0 bytes! "
                            "Windows may be blocking raw disk access or the drive has 0 accessible sectors."
                        )
                        print(warn_msg, file=sys.stderr)
                        self.sig_log.emit(warn_msg, "error")
                    first_chunk_logged = True

                if not new_chunk:
                    if len(window) == 0:
                        break
                    scan_limit = len(window)
                    is_eof = True
                else:
                    window += new_chunk
                    read_disk_offset += len(new_chunk)
                    is_eof = (total_bytes > 0 and read_disk_offset >= total_bytes)
                    scan_limit = len(window) if is_eof else max(0, len(window) - self.overlap_size)

                # Update in-memory window cache so parsers read directly from RAM
                stream.set_window_cache(window_start_offset, window)

                # 3. Find Candidate Signatures in Window
                candidates_offsets = []

                if "jpeg" in self.enabled_formats:
                    p = 0
                    while p < scan_limit:
                        idx = window.find(JPEG_SOI, p)
                        if idx == -1 or idx >= scan_limit:
                            break
                        abs_off = window_start_offset + idx
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates_offsets.append((abs_off, "jpeg"))
                        p = idx + 1

                if "png" in self.enabled_formats:
                    p = 0
                    while p < scan_limit:
                        idx = window.find(PNG_MAGIC, p)
                        if idx == -1 or idx >= scan_limit:
                            break
                        abs_off = window_start_offset + idx
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates_offsets.append((abs_off, "png"))
                        p = idx + 1

                # MP4 / MOV / Canon CR3 Check (b'ftyp' box signature at offset +4)
                if any(f in self.enabled_formats for f in ("mp4", "mov", "raw")):
                    p = 0
                    ftyp_limit = min(len(window), scan_limit + 4)
                    while p < ftyp_limit:
                        idx = window.find(ISOBMFF_FTYP, p)
                        if idx == -1 or idx >= ftyp_limit:
                            break
                        base_idx = idx - 4
                        if 0 <= base_idx < scan_limit:
                            abs_off = window_start_offset + base_idx
                            if self.sector_step == 1 or abs_off % self.sector_step == 0:
                                candidates_offsets.append((abs_off, "video"))
                        p = idx + 1

                if "raw" in self.enabled_formats:
                    for sig in (TIFF_LE_MAGIC, TIFF_BE_MAGIC):
                        p = 0
                        while p < scan_limit:
                            idx = window.find(sig, p)
                            if idx == -1 or idx >= scan_limit:
                                break
                            abs_off = window_start_offset + idx
                            if self.sector_step == 1 or abs_off % self.sector_step == 0:
                                candidates_offsets.append((abs_off, "raw"))
                            p = idx + 1

                # 4. Parse Discovered Candidates & Sort (Parent RAW/JPEG before Embedded Thumbnails)
                candidates_offsets.sort(key=lambda x: (x[0], 0 if x[1] in ("raw", "video") else 1))
                parsed_candidates: List[CarveCandidate] = []

                for abs_off, fmt_hint in candidates_offsets:
                    if not self._is_running:
                        break
                    if self._is_claimed(abs_off, abs_off + self.sector_step):
                        continue

                    candidate: Optional[CarveCandidate] = None
                    try:
                        if fmt_hint == "jpeg":
                            candidate = parse_jpeg(stream, abs_off)
                        elif fmt_hint == "png":
                            candidate = parse_png(stream, abs_off)
                        elif fmt_hint == "video":
                            candidate = parse_isobmff(stream, abs_off)
                        elif fmt_hint == "raw":
                            candidate = parse_tiff_raw(stream, abs_off)
                    except Exception as parse_err:
                        print(f"[!] Parser error on {fmt_hint} at offset 0x{abs_off:X}: {parse_err}", file=sys.stderr)

                    if candidate:
                        stat_key = self._ext_to_stat_key(candidate.extension)
                        if stat_key in self.enabled_formats:
                            parsed_candidates.append(candidate)

                # Sort by start offset ascending, largest length first
                parsed_candidates.sort(key=lambda c: (c.offset, -c.length))

                for candidate in parsed_candidates:
                    if not self._is_running:
                        break
                    if self._is_claimed(candidate.offset, candidate.offset + candidate.length):
                        continue

                    stat_key = self._ext_to_stat_key(candidate.extension)
                    try:
                        file_data = stream.read_at(candidate.offset, candidate.length)
                        if len(file_data) == candidate.length:
                            out_folder = self._get_target_folder(stat_key)
                            file_name = f"carved_0x{candidate.offset:010X}_{candidate.length}B.{candidate.extension}"
                            full_save_path = out_folder / file_name

                            with open(full_save_path, "wb") as f_out:
                                f_out.write(file_data)

                            self._claim(candidate.offset, candidate.offset + candidate.length)
                            self.stats["found"][stat_key] += 1

                            file_meta = {
                                "name": file_name,
                                "path": str(full_save_path),
                                "type": candidate.file_type,
                                "ext": candidate.extension.upper(),
                                "size": candidate.length,
                                "offset": candidate.offset,
                                "details": candidate.details
                            }
                            self.sig_file_found.emit(file_meta)
                            log_msg = (
                                f"Recovered {candidate.file_type}: {file_name} "
                                f"({candidate.length / 1024:.1f} KB) at sector 0x{candidate.offset:X}"
                            )
                            print(f"[RECOVERED] {log_msg}")
                            self.sig_log.emit(log_msg, "success")
                    except Exception as save_err:
                        err_msg = f"Failed saving file at 0x{candidate.offset:X}: {save_err}"
                        print(f"[!] {err_msg}", file=sys.stderr)
                        self.sig_log.emit(err_msg, "error")

                # 5. Slide Window Forward
                if scan_limit > 0:
                    window = window[scan_limit:]
                    window_start_offset += scan_limit
                    self.stats["scanned_bytes"] = window_start_offset
                else:
                    break

                # 6. Emit Periodic UI Progress
                now = time.time()
                if now - last_progress_time >= 0.1 or is_eof:
                    elapsed = max(0.001, now - start_time)
                    speed_mb = (window_start_offset / (1024 * 1024)) / elapsed
                    eta_sec = (
                        ((total_bytes - window_start_offset) / (speed_mb * 1024 * 1024))
                        if (speed_mb > 0 and total_bytes > window_start_offset) else 0
                    )
                    total_found = sum(self.stats["found"].values())
                    self.sig_progress.emit(window_start_offset, total_bytes, speed_mb, eta_sec, total_found)
                    last_progress_time = now

                if is_eof and len(window) == 0:
                    break

            self.stats["elapsed_time"] = time.time() - start_time
            self.sig_finished.emit(self.stats)
            fin_msg = f"Recovery scan complete. Total files recovered: {sum(self.stats['found'].values())}."
            print(f"[DONE] {fin_msg}")
            self.sig_log.emit(fin_msg, "success")

        except Exception as e:
            err_msg = f"Unexpected scan exception: {e}"
            print(f"[!] {err_msg}", file=sys.stderr)
            self.sig_error.emit(err_msg)
            self.sig_log.emit(err_msg, "error")
        finally:
            if stream:
                stream.close()