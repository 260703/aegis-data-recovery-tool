import unittest
import tempfile
import os
from pathlib import Path

from core.device_manager import DeviceInfo, DeviceManager


class TestDeviceManager(unittest.TestCase):
    def test_device_info_properties(self):
        dev = DeviceInfo(
            device_path="\\\\.\\PhysicalDrive1",
            display_name="SanDisk Ultra USB 3.0 (32 GB)",
            drive_type="USB Removable",
            total_bytes=32000000000,
            free_bytes=1000000000,
            filesystem="FAT32",
            is_removable=True,
            mountpoint="E:\\",
            model="SanDisk Ultra"
        )
        self.assertEqual(dev.device_path, "\\\\.\\PhysicalDrive1")
        self.assertTrue(dev.is_removable)
        self.assertIn("SanDisk Ultra", str(dev))

    def test_device_manager_initialization(self):
        mgr = DeviceManager()
        self.assertIsNotNone(mgr)
        devices = mgr.get_available_devices()
        self.assertIsInstance(devices, list)


if __name__ == "__main__":
    unittest.main()

