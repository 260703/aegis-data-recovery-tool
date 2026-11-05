import unittest
import tempfile
import os
from pathlib import Path

from core.disk_stream import DiskStream


class TestDiskStream(unittest.TestCase):
    def setUp(self):
        # Create a temporary synthetic disk image file
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        # Write 64 KB of known pattern: 16-byte repeating blocks
        pattern = b"".join(bytes([i % 256]) * 16 for i in range(4096))
        self.temp_file.write(pattern)
        self.temp_file.flush()
        self.temp_file.close()
        self.target_path = self.temp_file.name
        self.stream = DiskStream(self.target_path, sector_size=512)

    def tearDown(self):
        self.stream.close()
        try:
            os.remove(self.target_path)
        except OSError:
            pass

    def test_total_size(self):
        self.assertEqual(self.stream.total_size, 65536)

    def test_read_at_beginning(self):
        data = self.stream.read_at(0, 16)
        self.assertEqual(len(data), 16)
        self.assertEqual(data, bytes([0]) * 16)

    def test_read_at_arbitrary_offset(self):
        # Offset 32 corresponds to block index 2 (value 2 repeated 16 times)
        data = self.stream.read_at(32, 16)
        self.assertEqual(len(data), 16)
        self.assertEqual(data, bytes([2]) * 16)

    def test_read_out_of_bounds(self):
        # Read past end of stream
        data = self.stream.read_at(70000, 16)
        self.assertEqual(data, b"")

    def test_read_clamped_at_end(self):
        # Read starting 10 bytes before end, requesting 50 bytes
        data = self.stream.read_at(65526, 50)
        self.assertEqual(len(data), 10)

    def test_sliding_window_cache(self):
        # Populate window cache
        cache_data = b"ABCDEFGHIJKL"
        self.stream.set_window_cache(100, cache_data)
        # Reading inside cache should return cached slice
        data = self.stream.read_at(102, 4)
        self.assertEqual(data, b"CDEF")


if __name__ == "__main__":
    unittest.main()

