import unittest
import tempfile
import os
import struct
import zlib

from core.disk_stream import DiskStream
from core.parsers import (
    parse_jpeg,
    parse_png,
    parse_isobmff,
    parse_tiff_raw,
    JPEG_SOI,
    PNG_MAGIC,
    ISOBMFF_FTYP,
)


class TestParsers(unittest.TestCase):
    def setUp(self):
        self.temp_file = tempfile.NamedTemporaryFile(delete=False)
        self.target_path = self.temp_file.name
        self.temp_file.close()

    def tearDown(self):
        try:
            os.remove(self.target_path)
        except OSError:
            pass

    def _write_and_open_stream(self, data: bytes) -> DiskStream:
        with open(self.target_path, "wb") as f:
            f.write(data)
        return DiskStream(self.target_path, sector_size=512)

    def test_parse_png_valid(self):
        # Build synthetic valid PNG
        # 1. Header (8 bytes)
        png_data = bytearray(PNG_MAGIC)

        def make_chunk(chunk_type: bytes, payload: bytes) -> bytes:
            length = len(payload)
            crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
            return struct.pack(">I4s", length, chunk_type) + payload + struct.pack(">I", crc)

        # 2. IHDR chunk: 13 bytes
        ihdr_payload = struct.pack(">IIBBBBB", 100, 100, 8, 2, 0, 0, 0)
        png_data.extend(make_chunk(b"IHDR", ihdr_payload))

        # 3. IDAT chunk: dummy compressed data
        raw_scanlines = b"\x00" + (b"\xFF\x00\x00" * 100)
        idat_payload = zlib.compress(raw_scanlines)
        png_data.extend(make_chunk(b"IDAT", idat_payload))

        # 4. IEND chunk: 0 payload
        png_data.extend(make_chunk(b"IEND", b""))

        stream = self._write_and_open_stream(bytes(png_data))
        try:
            candidate = parse_png(stream, 0)
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.extension, "png")
            self.assertEqual(candidate.length, len(png_data))
            self.assertEqual(candidate.offset, 0)
        finally:
            stream.close()

    def test_parse_jpeg_valid(self):
        # Build minimal valid JPEG >= 512 bytes
        jpeg = bytearray(b"\xFF\xD8\xFF\xE0")  # SOI + APP0 marker
        # APP0 segment length = 16 (0x0010) + JFIF identifier + 00 + version + units + x/y
        app0_payload = b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        jpeg.extend(struct.pack(">H", len(app0_payload) + 2))
        jpeg.extend(app0_payload)

        # DQT marker
        jpeg.extend(b"\xFF\xDB\x00\x43\x00" + (b"\x10" * 64))

        # SOF0 marker
        jpeg.extend(b"\xFF\xC0\x00\x11\x08\x00\x10\x00\x10\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01")

        # SOS marker: enters entropy scan
        jpeg.extend(b"\xFF\xDA\x00\x0C\x03\x01\x00\x02\x11\x03\x11\x00\x3F\x00")

        # Pad entropy stream with non-marker bytes and byte stuffing (FF 00)
        entropy = (b"\x12\x34\x56\x78\xFF\x00\x9A\xBC" * 50)
        jpeg.extend(entropy)

        # EOI marker
        jpeg.extend(b"\xFF\xD9")

        # Ensure >= 512 bytes
        self.assertGreaterEqual(len(jpeg), 512)

        stream = self._write_and_open_stream(bytes(jpeg))
        try:
            candidate = parse_jpeg(stream, 0)
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.extension, "jpg")
            self.assertEqual(candidate.length, len(jpeg))
        finally:
            stream.close()

    def test_parse_isobmff_mp4_valid(self):
        # Build minimal ISOBMFF container >= 16 KB with ftyp, moov, and mdat
        mp4 = bytearray()

        # 1. ftyp box
        ftyp_payload = b"isom\x00\x00\x02\x00isomiso2mp41"
        ftyp_len = 8 + len(ftyp_payload)
        mp4.extend(struct.pack(">I4s", ftyp_len, b"ftyp") + ftyp_payload)

        # 2. moov box
        moov_payload = b"\x00" * 128
        moov_len = 8 + len(moov_payload)
        mp4.extend(struct.pack(">I4s", moov_len, b"moov") + moov_payload)

        # 3. mdat box
        mdat_payload = b"\xAA" * 16384  # To satisfy >= 16 KB requirement
        mdat_len = 8 + len(mdat_payload)
        mp4.extend(struct.pack(">I4s", mdat_len, b"mdat") + mdat_payload)

        stream = self._write_and_open_stream(bytes(mp4))
        try:
            candidate = parse_isobmff(stream, 0)
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.extension, "mp4")
            self.assertEqual(candidate.length, len(mp4))
        finally:
            stream.close()


if __name__ == "__main__":
    unittest.main()
