"""
Background QThread Scanning & Recovery Worker
==============================================
Thin PySide6 QThread wrapper around the high-performance compiled Rust engine (`aegis_core`).
Dispatches hardware carving to native Rust worker threads while streaming real-time
progress, log events, and recovered file metadata to the PySide6 UI at 60 FPS.
"""

import os
import sys
import time
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import threading

from PySide6.QtCore import QThread, Signal

try:
    import aegis_core
except ImportError:
    aegis_core = None


class RecoveryWorker(QThread):
    """
    QThread worker driving the native Rust `aegis_core.CarveEngine`,
    with a pure-Python fallback mode if aegis_core is not compiled.
    Emits custom Qt signals without blocking the GUI.
    """
    # Signals to communicate with the main PySide6 UI thread (using object for arbitrary-precision ints)
    sig_started = Signal(object)                              # total_bytes (Python int)
    sig_progress = Signal(object, object, float, float, int)  # current_bytes, total_bytes, speed_mb, eta_sec, total_found
    sig_file_found = Signal(dict)                             # metadata dict for recovered file table
    sig_log = Signal(str, str)                                # message, level ('info', 'success', 'warning', 'error')
    sig_finished = Signal(dict)                               # final summary stats
    sig_error = Signal(str)                                   # critical failure message

    def __init__(self, target_path: str, output_dir: str, sector_step: int = 512,
                 block_size_mb: int = 8, overlap_size_mb: int = 1,
                 enabled_formats: Optional[List[str]] = None,
                 parent=None):
        super().__init__(parent)
        self.target_path = target_path
        self.output_dir = Path(output_dir)
        self.sector_step = max(1, sector_step)
        self.block_size_mb = max(1, block_size_mb)
        self.enabled_formats = list(enabled_formats or ["jpeg", "png", "mp4", "mov", "raw"])
        self.engine: Optional[Any] = None
        self._is_running = True
        self._is_paused = False
        self._pause_cond = threading.Condition()

    def pause(self):
        """Pauses the scanning engine."""
        self._is_paused = True
        if self.engine:
            self.engine.pause()
        self.sig_log.emit("Scan paused by user.", "warning")

    def resume(self):
        """Resumes the scanning engine."""
        with self._pause_cond:
            self._is_paused = False
            self._pause_cond.notify_all()
        if self.engine:
            self.engine.resume()
        self.sig_log.emit("Scan resumed.", "info")

    def stop(self):
        """Stops the scanning engine immediately."""
        self._is_running = False
        with self._pause_cond:
            self._is_paused = False
            self._pause_cond.notify_all()
        if self.engine:
            self.engine.stop()
        self.sig_log.emit("Stopping scan...", "warning")

    def run(self):
        """Executes either native Rust CarveEngine or pure-Python fallback."""
        if aegis_core is not None:
            self._run_rust_engine()
        else:
            self._run_python_fallback()

    def _run_rust_engine(self):
        """Executes the high-speed compiled Rust CarveEngine on background thread."""
        try:
            self.sig_log.emit(f"Initializing native Rust carving engine for {self.target_path}...", "info")
            self.engine = aegis_core.CarveEngine(
                self.target_path,
                str(self.output_dir),
                self.sector_step,
                self.block_size_mb,
                self.enabled_formats
            )

            # Bridging callbacks from Rust thread to Qt UI signals
            def on_started(total_bytes: int):
                self.sig_started.emit(total_bytes)

            def on_progress(scanned: int, total: int, speed: float, eta: float, found: int):
                self.sig_progress.emit(scanned, total, speed, eta, found)

            def on_file_found(file_info: dict):
                self.sig_file_found.emit(file_info)

            def on_log(msg: str, level: str):
                self.sig_log.emit(msg, level)

            # Start engine (releases Python GIL during execution)
            stats = self.engine.start(on_started, on_progress, on_file_found, on_log)
            self.sig_finished.emit(stats)

        except Exception as e:
            err_str = f"CarveEngine error: {e}"
            self.sig_error.emit(err_str)
            self.sig_log.emit(err_str, "error")

    def _run_python_fallback(self):
        """Pure-Python fallback carving loop if aegis_core is not compiled."""
        try:
            from core.disk_stream import DiskStream
            from core.parsers import (
                parse_jpeg, parse_png, parse_isobmff, parse_tiff_raw,
                JPEG_SOI, PNG_MAGIC, ISOBMFF_FTYP, TIFF_LE_MAGIC, TIFF_BE_MAGIC
            )
            self.sig_log.emit(f"Initializing Pure Python carving engine for {self.target_path} (Fallback Mode)...", "warning")
            stream = DiskStream(self.target_path, sector_size=self.sector_step)
            total_bytes = stream.total_size
            self.sig_started.emit(total_bytes)
            self.sig_log.emit(f"Target initialized: {self.target_path} | Size: {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)", "success")

            block_size = self.block_size_mb * 1024 * 1024
            overlap_size = 65536
            window = bytearray()
            window_start_offset = 0
            read_disk_offset = 0
            claimed_ranges: List[Tuple[int, int]] = []
            found_stats = {k: 0 for k in ["jpeg", "png", "mp4", "mov", "raw"]}
            start_time = time.time()
            last_progress_time = time.time()
            first_chunk_logged = False

            def is_claimed(s: int, e: int) -> bool:
                for cs, ce in claimed_ranges:
                    if not (e <= cs or s >= ce):
                        return True
                return False

            def try_claim(s: int, e: int) -> bool:
                if is_claimed(s, e):
                    return False
                claimed_ranges.append((s, e))
                return True

            while self._is_running:
                # Handle paused state
                with self._pause_cond:
                    while self._is_paused and self._is_running:
                        self._pause_cond.wait()
                if not self._is_running:
                    break

                read_chunk_len = block_size
                if total_bytes > 0:
                    remaining = max(0, total_bytes - read_disk_offset)
                    if remaining == 0 and len(window) == 0:
                        break
                    read_chunk_len = min(read_chunk_len, remaining)

                new_chunk = stream.read_at(read_disk_offset, read_chunk_len) if read_chunk_len > 0 else b""
                if not first_chunk_logged:
                    bytes_read = len(new_chunk)
                    self.sig_log.emit(f"First chunk read: {bytes_read:,} raw bytes pulled from disk.", "info" if bytes_read > 0 else "error")
                    first_chunk_logged = True

                is_eof = len(new_chunk) == 0
                if is_eof:
                    scan_limit = len(window)
                else:
                    window.extend(new_chunk)
                    read_disk_offset += len(new_chunk)
                    scan_limit = max(0, len(window) - overlap_size)

                if len(window) == 0:
                    break

                window_bytes = bytes(window)
                stream.set_window_cache(window_start_offset, window_bytes)

                scan_slice = memoryview(window_bytes)[:min(scan_limit, len(window_bytes))]

                candidates_to_parse: List[Tuple[int, str]] = []

                if "jpeg" in self.enabled_formats:
                    idx = 0
                    while True:
                        hit = scan_slice.obj.find(JPEG_SOI, idx, scan_limit)
                        if hit == -1:
                            break
                        abs_off = window_start_offset + hit
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates_to_parse.append((abs_off, "jpeg"))
                        idx = hit + 1

                if "png" in self.enabled_formats:
                    idx = 0
                    while True:
                        hit = scan_slice.obj.find(PNG_MAGIC, idx, scan_limit)
                        if hit == -1:
                            break
                        abs_off = window_start_offset + hit
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates_to_parse.append((abs_off, "png"))
                        idx = hit + 1

                if any(f in self.enabled_formats for f in ["mp4", "mov", "raw"]):
                    idx = 0
                    ftyp_limit = min(scan_limit + 4, len(window_bytes))
                    while True:
                        hit = scan_slice.obj.find(ISOBMFF_FTYP, idx, ftyp_limit)
                        if hit == -1:
                            break
                        if hit >= 4:
                            base_off = hit - 4
                            if base_off < scan_limit:
                                abs_off = window_start_offset + base_off
                                if self.sector_step == 1 or abs_off % self.sector_step == 0:
                                    candidates_to_parse.append((abs_off, "video"))
                        idx = hit + 1

                if "raw" in self.enabled_formats:
                    for magic in [TIFF_LE_MAGIC, TIFF_BE_MAGIC]:
                        idx = 0
                        while True:
                            hit = scan_slice.obj.find(magic, idx, scan_limit)
                            if hit == -1:
                                break
                            abs_off = window_start_offset + hit
                            if self.sector_step == 1 or abs_off % self.sector_step == 0:
                                candidates_to_parse.append((abs_off, "raw"))
                            idx = hit + 1

                # Parse candidates
                parsed_candidates = []
                for abs_off, fmt in candidates_to_parse:
                    if is_claimed(abs_off, abs_off + self.sector_step):
                        continue
                    cand = None
                    if fmt == "jpeg":
                        cand = parse_jpeg(stream, abs_off)
                    elif fmt == "png":
                        cand = parse_png(stream, abs_off)
                    elif fmt == "video":
                        cand = parse_isobmff(stream, abs_off)
                    elif fmt == "raw":
                        cand = parse_tiff_raw(stream, abs_off)

                    if cand:
                        stat_k = cand.extension.lower()
                        if stat_k in ("jpg", "jpeg"):
                            stat_k = "jpeg"
                        elif stat_k in ("cr2", "cr3", "raw", "nef", "arw", "dng"):
                            stat_k = "raw"
                        if stat_k in self.enabled_formats:
                            parsed_candidates.append((cand, stat_k))

                # Sort parent before thumbnail
                parsed_candidates.sort(key=lambda x: (x[0].offset, -x[0].length))

                for cand, stat_k in parsed_candidates:
                    if not self._is_running:
                        break
                    if not try_claim(cand.offset, cand.offset + cand.length):
                        continue

                    # Subfolder path
                    sub_folder = {
                        "jpeg": self.output_dir / "Images" / "JPEG",
                        "png": self.output_dir / "Images" / "PNG",
                        "raw": self.output_dir / "Images" / "RAW",
                        "mp4": self.output_dir / "Videos" / "MP4",
                        "mov": self.output_dir / "Videos" / "MOV",
                    }.get(stat_k, self.output_dir / "Other")
                    os.makedirs(sub_folder, exist_ok=True)
                    fname = f"carved_0x{cand.offset:010X}_{cand.length}B.{cand.extension}"
                    fpath = sub_folder / fname

                    # Write file
                    try:
                        file_bytes = stream.read_at(cand.offset, cand.length)
                        if len(file_bytes) == cand.length:
                            with open(fpath, "wb") as f_out:
                                f_out.write(file_bytes)
                            found_stats[stat_k] += 1
                            meta = {
                                "name": fname,
                                "path": str(fpath),
                                "type": cand.file_type,
                                "ext": cand.extension.upper(),
                                "size": cand.length,
                                "offset": cand.offset,
                                "details": cand.details,
                            }
                            self.sig_file_found.emit(meta)
                            self.sig_log.emit(f"Recovered {cand.file_type}: {fname} ({cand.length / 1024:.1f} KB) at sector 0x{cand.offset:X}", "success")
                    except Exception as e:
                        self.sig_log.emit(f"Write error for {fname}: {e}", "error")

                # Slide window
                if scan_limit > 0:
                    del window[:scan_limit]
                    window_start_offset += scan_limit
                else:
                    break

                # Progress throttling ~10 Hz
                now = time.time()
                if (now - last_progress_time >= 0.1) or is_eof:
                    elapsed = max(0.001, now - start_time)
                    speed_mb = (window_start_offset / (1024 * 1024)) / elapsed
                    eta_sec = ((total_bytes - window_start_offset) / (speed_mb * 1024 * 1024)) if speed_mb > 0 and total_bytes > window_start_offset else 0.0
                    tot_found = sum(found_stats.values())
                    self.sig_progress.emit(window_start_offset, total_bytes, speed_mb, eta_sec, tot_found)
                    last_progress_time = now

                if is_eof and len(window) == 0:
                    break

            elapsed_total = time.time() - start_time
            stats = {
                "scanned_bytes": window_start_offset,
                "total_bytes": total_bytes,
                "elapsed_time": elapsed_total,
                "found": found_stats,
            }
            self.sig_finished.emit(stats)
            self.sig_log.emit(f"Recovery scan complete. Total files recovered: {sum(found_stats.values())}.", "success")
        except Exception as e:
            self.sig_error.emit(f"Python fallback error: {e}")
            self.sig_log.emit(f"Python fallback error: {e}", "error")
