"""
Aegis Data Recovery - Core Forensic Engine
==========================================
Provides raw disk streaming, hardware device enumeration,
structural file boundary parsers, and background recovery workers.
"""

from core.disk_stream import DiskStream
from core.device_manager import DeviceManager, DeviceInfo
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
    TIFF_BE_MAGIC,
)
from core.worker import RecoveryWorker

__all__ = [
    "DiskStream",
    "DeviceManager",
    "DeviceInfo",
    "CarveCandidate",
    "parse_jpeg",
    "parse_png",
    "parse_isobmff",
    "parse_tiff_raw",
    "JPEG_SOI",
    "PNG_MAGIC",
    "ISOBMFF_FTYP",
    "TIFF_LE_MAGIC",
    "TIFF_BE_MAGIC",
    "RecoveryWorker",
]

