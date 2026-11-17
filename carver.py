#!/usr/bin/env python3
"""
High-Performance Multithreaded File Carver CLI
==============================================
Carves deleted images (JPEG, PNG, RAW) and videos (MP4, MOV) from raw disk images
(.dd, .img) or direct drive paths (e.g. \\\\.\\PhysicalDrive1 or \\\\.\\E:).
Implements true sliding-window overlap buffer and sector-aligned direct I/O.
"""

import os
import sys
import time
import argparse
from pathlib import Path
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
import threading

# Ensure project root is in sys.path for standalone CLI execution
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    import aegis_core
except ImportError:
    aegis_core = None

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


class FileCarver:
    def __init__(self, target: str, output_dir: str, sector_step: int = 512,
                 block_size_mb: int = 8, overlap_size_mb: int = 1,
                 num_threads: int = 4, enabled_formats: Optional[List[str]] = None):
        self.stream = DiskStream(target, sector_size=sector_step)
        self.output_dir = Path(output_dir)
        self.sector_step = max(1, sector_step)
        self.block_size = block_size_mb * 1024 * 1024
        # 64 KB overlap catches any magic header straddling chunk boundaries
        self.overlap_size = 65536
        self.num_threads = max(1, num_threads)
        self.enabled_formats = set(enabled_formats or ["jpeg", "png", "mp4", "mov", "raw"])

        # Create output directories only for enabled formats
        self.cat_dirs = {
            "jpeg": self.output_dir / "Images" / "JPEG",
            "png": self.output_dir / "Images" / "PNG",
            "raw": self.output_dir / "Images" / "RAW",
            "mp4": self.output_dir / "Videos" / "MP4",
            "mov": self.output_dir / "Videos" / "MOV",
        }
        for fmt, d in self.cat_dirs.items():
            if fmt in self.enabled_formats:
                d.mkdir(parents=True, exist_ok=True)

        self.claimed_ranges: List[tuple] = []
        self.range_lock = threading.Lock()
        self.stats = {"scanned_bytes": 0, "found": {k: 0 for k in ["jpeg", "png", "mp4", "mov", "raw"]}}
        self.stats_lock = threading.Lock()
        self.start_time = 0.0

    def _is_claimed(self, start: int, end: int) -> bool:
        with self.range_lock:
            for c_start, c_end in self.claimed_ranges:
                if not (end <= c_start or start >= c_end):
                    return True
            return False

    def _try_claim(self, start: int, end: int) -> bool:
        """Atomically verifies and claims [start, end) under a single lock acquisition."""
        with self.range_lock:
            for c_start, c_end in self.claimed_ranges:
                if not (end <= c_start or start >= c_end):
                    return False
            self.claimed_ranges.append((start, end))
            return True

    @staticmethod
    def _ext_to_stat_key(ext: str) -> str:
        cat = ext.lower()
        if cat in ("jpg", "jpeg"):
            return "jpeg"
        if cat == "png":
            return "png"
        if cat in ("cr2", "cr3", "raw", "nef", "arw", "dng"):
            return "raw"
        if cat == "mp4":
            return "mp4"
        if cat == "mov":
            return "mov"
        return "jpeg"

    def _parse_candidate(self, abs_offset: int, fmt_hint: str) -> Optional[CarveCandidate]:
        """Worker thread task: parses candidate boundaries without writing to disk yet."""
        if self._is_claimed(abs_offset, abs_offset + self.sector_step):
            return None
        try:
            if fmt_hint == "jpeg":
                cand = parse_jpeg(self.stream, abs_offset)
            elif fmt_hint == "png":
                cand = parse_png(self.stream, abs_offset)
            elif fmt_hint == "video":
                cand = parse_isobmff(self.stream, abs_offset)
            elif fmt_hint == "raw":
                cand = parse_tiff_raw(self.stream, abs_offset)
            else:
                return None

            if cand and self._ext_to_stat_key(cand.extension) in self.enabled_formats:
                return cand
        except Exception:
            pass
        return None

    def _save_file(self, candidate: CarveCandidate) -> bool:
        stat_key = self._ext_to_stat_key(candidate.extension)
        if stat_key not in self.enabled_formats:
            return False

        if not self._try_claim(candidate.offset, candidate.offset + candidate.length):
            return False

        try:
            data = self.stream.read_at(candidate.offset, candidate.length)
        except Exception as e:
            print(f"\n[!] Failed reading {candidate.file_type} at 0x{candidate.offset:X}: {e}", file=sys.stderr)
            return False

        if len(data) != candidate.length:
            return False

        out_folder = self.cat_dirs.get(stat_key, self.output_dir)
        out_folder.mkdir(parents=True, exist_ok=True)
        file_name = f"carved_0x{candidate.offset:010X}_{candidate.length}B.{candidate.extension}"
        out_path = out_folder / file_name

        try:
            with open(out_path, "wb") as f:
                f.write(data)
            with self.stats_lock:
                self.stats["found"][stat_key] += 1
            return True
        except Exception as e:
            print(f"\n[!] Error saving {file_name}: {e}", file=sys.stderr)
            return False

    def run(self):
        total_bytes = self.stream.total_size
        print("\n" + "=" * 70)
        print("          MULTI-THREADED HIGH PERFORMANCE FILE CARVER")
        print("=" * 70)
        print(f"[*] Target Source   : {self.stream.file_path}")
        print(f"[*] Total Size      : {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)")
        print(f"[*] Sector Step     : {self.sector_step} bytes (Alignment)")
        print(f"[*] Read Block Size : {self.block_size / (1024**2):.0f} MB (Overlap: {self.overlap_size // 1024} KB)")
        print(f"[*] Worker Threads  : {self.num_threads}")
        print(f"[*] Output Dir      : {self.output_dir.resolve()}")
        print(f"[*] Active Formats  : {', '.join(sorted(self.enabled_formats)).upper()}")
        print("=" * 70 + "\n")

        self.start_time = time.time()
        window = b""
        window_start_offset = 0
        read_disk_offset = 0
        first_chunk_logged = False

        with ThreadPoolExecutor(max_workers=self.num_threads) as executor:
            while True:
                # Read next chunk
                read_chunk_len = self.block_size
                if total_bytes > 0:
                    remaining = total_bytes - read_disk_offset
                    if remaining <= 0 and len(window) == 0:
                        break
                    read_chunk_len = min(read_chunk_len, max(0, remaining))

                new_chunk = b""
                if read_chunk_len > 0:
                    try:
                        new_chunk = self.stream.read_at(read_disk_offset, read_chunk_len)
                    except (PermissionError, OSError) as err:
                        print(f"\n[!] Critical read error at disk offset {read_disk_offset:,}: {err}", file=sys.stderr)
                        break

                if not first_chunk_logged:
                    bytes_read = len(new_chunk)
                    print(f"[DEBUG] First chunk read: {bytes_read:,} raw bytes pulled from disk.")
                    if bytes_read == 0:
                        print("[!] WARNING: First chunk returned 0 bytes! Check administrator permissions.", file=sys.stderr)
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

                # Cache current window in DiskStream for fast lock-free RAM reads
                self.stream.set_window_cache(window_start_offset, window)

                # Search signatures in window
                candidates = []

                if "jpeg" in self.enabled_formats:
                    p = 0
                    while p < scan_limit:
                        idx = window.find(JPEG_SOI, p)
                        if idx == -1 or idx >= scan_limit:
                            break
                        abs_off = window_start_offset + idx
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates.append((abs_off, "jpeg"))
                        p = idx + 1

                if "png" in self.enabled_formats:
                    p = 0
                    while p < scan_limit:
                        idx = window.find(PNG_MAGIC, p)
                        if idx == -1 or idx >= scan_limit:
                            break
                        abs_off = window_start_offset + idx
                        if self.sector_step == 1 or abs_off % self.sector_step == 0:
                            candidates.append((abs_off, "png"))
                        p = idx + 1

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
                                candidates.append((abs_off, "video"))
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
                                candidates.append((abs_off, "raw"))
                            p = idx + 1

                # Parse candidates in parallel across worker threads
                candidates.sort(key=lambda x: x[0])
                futures = [
                    executor.submit(self._parse_candidate, abs_off, fmt_hint)
                    for abs_off, fmt_hint in candidates
                    if not self._is_claimed(abs_off, abs_off + self.sector_step)
                ]

                valid_candidates = [
                    res for f in futures
                    if (res := f.result()) is not None
                ]

                # Sort by earliest offset first, largest length first so parent RAW/JPEGs
                # always claim their byte range before embedded EXIF preview thumbnails
                valid_candidates.sort(key=lambda c: (c.offset, -c.length))

                for cand in valid_candidates:
                    self._save_file(cand)

                # Slide window
                if scan_limit > 0:
                    window = window[scan_limit:]
                    window_start_offset += scan_limit
                    with self.stats_lock:
                        self.stats["scanned_bytes"] = window_start_offset
                    self._print_progress(window_start_offset, total_bytes)
                else:
                    break

                if is_eof and len(window) == 0:
                    break

        self._print_final_summary()
        self.stream.close()

    def _print_progress(self, current: int, total: int):
        elapsed = max(0.001, time.time() - self.start_time)
        speed_mb = (current / (1024 * 1024)) / elapsed
        pct = (current / total * 100) if total > 0 else 0
        eta_sec = ((total - current) / (speed_mb * 1024 * 1024)) if (speed_mb > 0 and total > current) else 0

        with self.stats_lock:
            jpg_c = self.stats["found"]["jpeg"]
            png_c = self.stats["found"]["png"]
            raw_c = self.stats["found"]["raw"]
            mp4_c = self.stats["found"]["mp4"]
            mov_c = self.stats["found"]["mov"]

        tot_gb = total / (1024**3) if total > 0 else 0.0
        line = (
            f"\r[{pct:5.1f}%] {current / (1024**3):6.2f}/{tot_gb:.2f} GB "
            f"| {speed_mb:5.1f} MB/s | ETA: {int(eta_sec//60):02d}:{int(eta_sec%60):02d} "
            f"| Recovered: JPG:{jpg_c} PNG:{png_c} RAW:{raw_c} MP4:{mp4_c} MOV:{mov_c}"
        )
        sys.stdout.write(line)
        sys.stdout.flush()

    def _print_final_summary(self):
        elapsed = max(0.001, time.time() - self.start_time)
        total_found = sum(self.stats["found"].values())
        print("\n\n" + "=" * 70)
        print("                   CARVING TASK COMPLETED")
        print("=" * 70)
        print(f"[*] Elapsed Time     : {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
        print(f"[*] Total Scanned    : {self.stats['scanned_bytes'] / (1024**3):.2f} GB")
        print(f"[*] Files Recovered  : {total_found}")
        print(f"    - JPEG Images    : {self.stats['found']['jpeg']}")
        print(f"    - PNG Images     : {self.stats['found']['png']}")
        print(f"    - RAW Photos     : {self.stats['found']['raw']}")
        print(f"    - MP4 Videos     : {self.stats['found']['mp4']}")
        print(f"    - MOV Videos     : {self.stats['found']['mov']}")
        print(f"[*] Output Directory : {self.output_dir.resolve()}")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Fast Multi-Threaded Raw Disk Image & Drive File Carver"
    )
    parser.add_argument(
        "target",
        help="Path to raw disk image (.dd, .img) or direct drive (e.g. \\\\.\\PhysicalDrive1 or \\\\.\\E:)"
    )
    parser.add_argument(
        "-o", "--output",
        default="Recovered_Data",
        help="Destination directory for recovered files (default: Recovered_Data)"
    )
    parser.add_argument(
        "-s", "--sector-step",
        type=int,
        default=512,
        help="Sector alignment step in bytes (default: 512 for FAT32/exFAT; use 1 for unaligned)"
    )
    parser.add_argument(
        "-b", "--block-size",
        type=int,
        default=8,
        help="Streaming read buffer block size in megabytes (default: 8 MB)"
    )
    parser.add_argument(
        "-t", "--threads",
        type=int,
        default=os.cpu_count() or 4,
        help=f"Number of worker threads (default: {os.cpu_count() or 4})"
    )
    parser.add_argument(
        "-f", "--formats",
        default="jpeg,png,mp4,mov,raw",
        help="Comma-separated file formats to carve: jpeg,png,mp4,mov,raw (default: all)"
    )

    args = parser.parse_args()
    enabled = [fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()]

    if aegis_core is not None:
        print("=" * 70)
        print("   AEGIS CORE - NATIVE RUST PARALLEL DISK CARVER (RAYON / AVX2)")
        print("=" * 70)
        print(f"[*] Target       : {args.target}")
        print(f"[*] Output Dir   : {Path(args.output).resolve()}")
        print(f"[*] Sector Step  : {args.sector_step} bytes")
        print(f"[*] Formats      : {', '.join(enabled)}")
        print("=" * 70)

        engine = aegis_core.CarveEngine(
            args.target,
            args.output,
            args.sector_step,
            args.block_size,
            enabled
        )

        def on_started(total_bytes: int):
            print(f"[*] Stream initialized: {total_bytes / (1024**3):.2f} GB ({total_bytes:,} bytes)")

        def on_progress(scanned: int, total: int, speed: float, eta: float, found: int):
            pct = (scanned / total * 100.0) if total > 0 else 0.0
            tot_gb = total / (1024**3) if total > 0 else 0.0
            eta_m = int(eta // 60)
            eta_s = int(eta % 60)
            sys.stdout.write(
                f"\r[{pct:5.1f}%] {scanned / (1024**3):6.2f}/{tot_gb:.2f} GB "
                f"| {speed:5.1f} MB/s | ETA: {eta_m:02d}:{eta_s:02d} | Recovered: {found} files"
            )
            sys.stdout.flush()

        def on_file_found(meta: dict):
            pass

        def on_log(msg: str, level: str):
            if level == "error":
                print(f"\n[!] {msg}", file=sys.stderr)
            elif level == "success" and "Recovered" in msg:
                print(f"\n[+] {msg}")

        try:
            stats = engine.start(on_started, on_progress, on_file_found, on_log)
            elapsed = stats.get("elapsed_time", 0.0)
            found_map = stats.get("found", {})
            total_found = sum(found_map.values())
            print("\n\n" + "=" * 70)
            print("                   CARVING TASK COMPLETED")
            print("=" * 70)
            print(f"[*] Elapsed Time     : {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
            print(f"[*] Total Scanned    : {stats.get('scanned_bytes', 0) / (1024**3):.2f} GB")
            print(f"[*] Files Recovered  : {total_found}")
            for k, v in found_map.items():
                print(f"    - {k.upper():14} : {v}")
            print(f"[*] Output Directory : {Path(args.output).resolve()}")
            print("=" * 70 + "\n")
        except KeyboardInterrupt:
            engine.stop()
            print("\n[!] Carving interrupted by user. Partial files safely retained.")
        sys.exit(0)

    carver = FileCarver(
        target=args.target,
        output_dir=args.output,
        sector_step=args.sector_step,
        block_size_mb=args.block_size,
        num_threads=args.threads,
        enabled_formats=enabled
    )

    try:
        carver.run()
    except KeyboardInterrupt:
        print("\n[!] Carving interrupted by user. Partial files safely retained.")
        carver.stream.close()
        sys.exit(0)


if __name__ == "__main__":
    main()