"""
Format Parsers & Boundary Carving Engine
========================================
Implements structural boundary calculation for images and videos:
- JPEG: SOI (FF D8), segment header traversal, entropy decoding with byte stuffing (FF 00), EOI (FF D9).
- PNG: 8-byte magic, chunk CRC-32 verification, IEND terminal chunk.
- MP4 / MOV / CR3: ISOBMFF ftyp verification, top-level atom/box chain parsing.
- RAW: TIFF Image File Directory (IFD) & SubIFD tag walker (Canon CR2, Nikon NEF, Sony ARW, DNG).
"""

import struct
import zlib
from typing import Optional, List, Dict
from core.disk_stream import DiskStream

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PNG_IEND = b"IEND"

JPEG_SOI = b"\xFF\xD8\xFF"
JPEG_EOI = b"\xFF\xD9"

TIFF_LE_MAGIC = b"II\x2A\x00"
TIFF_BE_MAGIC = b"MM\x00\x2A"
CR2_SUBMAGIC = b"CR\x02\x00"

ISOBMFF_FTYP = b"ftyp"
KNOWN_MP4_BRANDS = {
    b"isom", b"iso2", b"iso4", b"iso5", b"iso6",
    b"mp41", b"mp42", b"mp71", b"avc1", b"hvc1", b"hev1",
    b"dash", b"MSNV", b"NDAS", b"NDSC", b"NDXH", b"NDXM",
    b"NDXP", b"NDXS", b"M4V ", b"M4A ", b"f4v ", b"kddi",
    b"XAVC", b"mmp4", b"3gp4", b"3gp5"
}
KNOWN_MOV_BRANDS = {
    b"qt  ", b"CAEP", b"mqt "
}
KNOWN_RAW_BRANDS = {
    b"crx "  # Canon CR3
}

TOP_LEVEL_ISOBMFF_BOXES = {
    b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide",
    b"uuid", b"meta", b"pdin", b"prft", b"styp", b"sidx",
    b"emsg", b"moof", b"mfra", b"udta", b"UDTA", b"PICT",
    b"junk", b"beam", b"ctab", b"cmov", b"rmra"
}


class CarveCandidate:
    """Represents a discovered file candidate with confirmed boundaries."""
    def __init__(self, offset: int, length: int, file_type: str, extension: str, details: str = ""):
        self.offset = offset
        self.length = length
        self.file_type = file_type
        self.extension = extension.lower()
        self.details = details


def parse_jpeg(stream: DiskStream, start_offset: int, max_size: int = 50 * 1024 * 1024) -> Optional[CarveCandidate]:
    """
    Parses JPEG stream by traversing marker segments, handling 0xFF fill bytes
    and multi-scan progressive JPEGs, avoiding false-positive truncation on embedded
    EXIF thumbnails, and finding the true top-level EOI (FF D9).
    """
    header = stream.read_at(start_offset, 4)
    if len(header) < 4 or header[:3] != JPEG_SOI:
        return None

    # Valid markers following SOI: APPn (E0..EF), DQT (DB), SOF (C0..CF), DHT (C4), COM (FE), DRI (DD)
    if header[3] < 0xC0 or header[3] in (0xD8, 0xD9):
        return None

    curr_offset = start_offset + 2
    in_sos = False
    read_chunk = 65536
    buffer = b""
    buf_start = curr_offset
    eof = False

    while (curr_offset - start_offset) < max_size:
        needed_rel = curr_offset - buf_start
        if not eof and (needed_rel + 4096 > len(buffer)):
            new_data = stream.read_at(buf_start + len(buffer), read_chunk)
            if not new_data:
                eof = True
            else:
                buffer += new_data

        rel_idx = curr_offset - buf_start
        if rel_idx >= len(buffer):
            break

        if not in_sos:
            if rel_idx + 2 > len(buffer):
                break
            if buffer[rel_idx] != 0xFF:
                # Lost marker sync
                break

            marker = buffer[rel_idx + 1]

            # Skip 0xFF fill padding bytes allowed by JPEG specification
            if marker == 0xFF:
                curr_offset += 1
                continue

            # Standalone markers without length: RSTn (D0..D7), TEM (01)
            if (0xD0 <= marker <= 0xD7) or marker == 0x01:
                curr_offset += 2
                continue

            if marker == 0xD8 or marker == 0x00:  # Unexpected SOI or stuffed byte outside SOS
                break

            if marker == 0xD9:  # EOI
                file_len = curr_offset + 2 - start_offset
                if file_len >= 512:
                    return CarveCandidate(start_offset, file_len, "JPEG Image", "jpg", "Standard JPEG")
                return None

            if rel_idx + 4 > len(buffer):
                break

            seg_len = struct.unpack(">H", buffer[rel_idx + 2 : rel_idx + 4])[0]
            if seg_len < 2:
                break

            curr_offset += 2 + seg_len
            if marker == 0xDA:  # Start of Scan (SOS) -> enter entropy stream
                in_sos = True

        else:
            # Inside entropy data (Scan stream)
            ff_idx = buffer.find(b"\xFF", rel_idx)
            if ff_idx == -1:
                if eof:
                    break
                slide = max(0, len(buffer) - 64)
                buf_start += slide
                buffer = buffer[slide:]
                curr_offset = buf_start + len(buffer)
                continue

            curr_offset = buf_start + ff_idx
            if ff_idx + 1 >= len(buffer):
                if eof:
                    break
                more = stream.read_at(buf_start + len(buffer), 4096)
                if not more:
                    eof = True
                    break
                buffer += more

            next_b = buffer[ff_idx + 1]

            if next_b == 0x00:
                # Byte stuffing (escaped 0xFF)
                curr_offset += 2
            elif 0xD0 <= next_b <= 0xD7:
                # Restart marker
                curr_offset += 2
            elif next_b == 0xD9:
                # True End of Image (EOI)
                file_len = curr_offset + 2 - start_offset
                if file_len >= 512:
                    return CarveCandidate(start_offset, file_len, "JPEG Image", "jpg", "Standard EXIF/JFIF")
                return None
            elif next_b == 0xFF:
                curr_offset += 1
            elif next_b in (0xC4, 0xDA, 0xDB, 0xDD, 0xFE) or (0xE0 <= next_b <= 0xEF):
                # Multi-scan / Progressive JPEG segment marker following scan data
                in_sos = False
            else:
                curr_offset += 2

    return None


def parse_png(stream: DiskStream, start_offset: int, max_size: int = 100 * 1024 * 1024) -> Optional[CarveCandidate]:
    """
    Parses PNG chunk by chunk without duplicate reads, verifying CRC32 checksums
    to ensure integrity and stopping at the validated IEND chunk.
    """
    header = stream.read_at(start_offset, 16)
    if len(header) < 16 or header[:8] != PNG_MAGIC or header[12:16] != b"IHDR":
        return None

    curr_offset = start_offset + 8

    while (curr_offset - start_offset) < max_size:
        chunk_hdr = stream.read_at(curr_offset, 8)
        if len(chunk_hdr) < 8:
            break

        chunk_len, chunk_type = struct.unpack(">I4s", chunk_hdr)
        if chunk_len > 64 * 1024 * 1024:
            break

        if not all(65 <= b <= 90 or 97 <= b <= 122 for b in chunk_type):
            break

        # Read only payload + 4-byte CRC (avoid re-reading the 8-byte header)
        payload_and_crc = stream.read_at(curr_offset + 8, chunk_len + 4)
        if len(payload_and_crc) < chunk_len + 4:
            break

        chunk_crc = struct.unpack(">I", payload_and_crc[-4:])[0]
        crc = zlib.crc32(chunk_type)
        computed_crc = zlib.crc32( memoryview(payload_and_crc)[:chunk_len], crc ) & 0xFFFFFFFF
        if computed_crc != chunk_crc:
            break

        curr_offset += 8 + chunk_len + 4

        if chunk_type == PNG_IEND:
            file_len = curr_offset - start_offset
            return CarveCandidate(start_offset, file_len, "PNG Image", "png", "Validated CRC-32")

    return None


def parse_isobmff(stream: DiskStream, start_offset: int, max_size: int = 4 * 1024 * 1024 * 1024) -> Optional[CarveCandidate]:
    """
    Parses MP4/MOV/CR3 files by walking top-level atoms/boxes and verifying brands.
    """
    hdr = stream.read_at(start_offset, 16)
    if len(hdr) < 16:
        return None

    box_size, box_type = struct.unpack(">I4s", hdr[:8])
    if box_type != ISOBMFF_FTYP:
        if box_type == b"wide" and box_size == 8:
            box_size, box_type = struct.unpack(">I4s", hdr[8:16])
            if box_type != ISOBMFF_FTYP:
                return None
            start_offset += 8
            hdr = stream.read_at(start_offset, 16)
            if len(hdr) < 16:
                return None
        else:
            return None

    if box_size < 16 or box_size > 4096:
        return None

    major_brand = hdr[8:12]
    ext = "mp4"
    file_type = "MP4 Video"
    if major_brand in KNOWN_MOV_BRANDS:
        ext = "mov"
        file_type = "QuickTime MOV"
    elif major_brand in KNOWN_RAW_BRANDS:
        ext = "cr3"
        file_type = "Canon RAW (CR3)"
    elif major_brand not in KNOWN_MP4_BRANDS:
        ftyp_body = stream.read_at(start_offset + 8, min(box_size - 8, 256))
        matched = False
        for i in range(8, len(ftyp_body) - 3, 4):
            brand = ftyp_body[i : i + 4]
            if brand in KNOWN_MP4_BRANDS:
                matched = True
                break
            if brand in KNOWN_MOV_BRANDS:
                ext = "mov"
                file_type = "QuickTime MOV"
                matched = True
                break
            if brand in KNOWN_RAW_BRANDS:
                ext = "cr3"
                file_type = "Canon RAW (CR3)"
                matched = True
                break
        if not matched:
            return None

    curr_offset = start_offset
    has_moov = False
    has_mdat = False

    while (curr_offset - start_offset) < max_size:
        b_hdr = stream.read_at(curr_offset, 16)
        if len(b_hdr) < 8:
            break

        b_size, b_type = struct.unpack(">I4s", b_hdr[:8])

        if b_size == 1:
            if len(b_hdr) < 16:
                break
            b_size = struct.unpack(">Q", b_hdr[8:16])[0]
            if b_size < 16:
                break
        elif b_size < 8:
            break

        # Validate box type and size BEFORE advancing curr_offset
        if b_type not in TOP_LEVEL_ISOBMFF_BOXES:
            break

        if (curr_offset + b_size - start_offset) > max_size:
            break

        if b_type == b"moov":
            has_moov = True
        elif b_type == b"mdat":
            has_mdat = True

        curr_offset += b_size

        if has_moov and has_mdat:
            next_hdr = stream.read_at(curr_offset, 8)
            if len(next_hdr) < 8:
                break
            n_size, n_type = struct.unpack(">I4s", next_hdr)
            if n_type not in TOP_LEVEL_ISOBMFF_BOXES or n_size < 8:
                break

    file_len = curr_offset - start_offset
    if file_len >= 16384 and has_moov and has_mdat:
        brand_str = major_brand.decode("latin1", errors="replace").strip()
        return CarveCandidate(start_offset, file_len, file_type, ext, f"Brand: {brand_str}")

    return None


def parse_tiff_raw(stream: DiskStream, start_offset: int, max_size: int = 250 * 1024 * 1024) -> Optional[CarveCandidate]:
    """
    Parses TIFF-based RAW files (Canon CR2, Nikon NEF, Sony ARW, DNG) by traversing
    IFD chains, SubIFDs (0x014A), ExifIFD (0x8769), and pairing strip/tile/JPEG offsets
    with their corresponding byte counts to calculate exact file size.
    """
    hdr = stream.read_at(start_offset, 16)
    if len(hdr) < 16:
        return None

    is_le = hdr[:4] == TIFF_LE_MAGIC
    is_be = hdr[:4] == TIFF_BE_MAGIC
    if not is_le and not is_be:
        return None

    endian = "<" if is_le else ">"
    ifd0_offset = struct.unpack(f"{endian}I", hdr[4:8])[0]
    if ifd0_offset < 8 or ifd0_offset >= max_size:
        return None

    is_cr2 = (hdr[8:12] == CR2_SUBMAGIC)
    ext = "cr2" if is_cr2 else "raw"
    file_type = "Canon RAW (CR2)" if is_cr2 else "TIFF/RAW Image"

    max_referenced_byte = start_offset + (16 if is_cr2 else 8)
    visited_ifds = set()
    ifd_queue: List[int] = [ifd0_offset]

    type_sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}

    def _read_uint_list(tag_type: int, count: int, val_or_offset: bytes) -> List[int]:
        """Extracts list of unsigned integers from inline value or relative offset."""
        if count <= 0 or count > 65536:
            return []
        item_sz = type_sizes.get(tag_type, 0)
        if item_sz not in (2, 4):
            return []
        total_bytes = count * item_sz
        if total_bytes <= 4:
            raw = val_or_offset[:total_bytes]
        else:
            rel_off = struct.unpack(f"{endian}I", val_or_offset)[0]
            if rel_off == 0 or rel_off + total_bytes > max_size:
                return []
            raw = stream.read_at(start_offset + rel_off, total_bytes)
            if len(raw) < total_bytes:
                return []
        fmt_char = "H" if item_sz == 2 else "I"
        return list(struct.unpack(f"{endian}{count}{fmt_char}", raw))

    while ifd_queue and len(visited_ifds) < 32:
        curr_ifd_off = ifd_queue.pop(0)
        if curr_ifd_off == 0 or curr_ifd_off in visited_ifds or curr_ifd_off >= max_size:
            continue
        visited_ifds.add(curr_ifd_off)

        abs_ifd_pos = start_offset + curr_ifd_off
        ifd_header = stream.read_at(abs_ifd_pos, 2)
        if len(ifd_header) < 2:
            continue

        entry_count = struct.unpack(f"{endian}H", ifd_header)[0]
        if entry_count == 0 or entry_count > 512:
            continue

        ifd_bytes_len = entry_count * 12 + 4
        ifd_bytes = stream.read_at(abs_ifd_pos + 2, ifd_bytes_len)
        if len(ifd_bytes) < entry_count * 12:
            continue

        max_referenced_byte = max(max_referenced_byte, abs_ifd_pos + 2 + len(ifd_bytes))

        ifd_int_tags: Dict[int, List[int]] = {}

        for i in range(entry_count):
            tag_bytes = ifd_bytes[i * 12 : (i + 1) * 12]
            tag, tag_type, count, val_or_offset = struct.unpack(f"{endian}HHI4s", tag_bytes)

            item_size = type_sizes.get(tag_type, 1)
            total_val_bytes = count * item_size

            if total_val_bytes > 4:
                val_offset = struct.unpack(f"{endian}I", val_or_offset)[0]
                if 0 < val_offset < max_size and (val_offset + total_val_bytes) <= max_size:
                    max_referenced_byte = max(max_referenced_byte, start_offset + val_offset + total_val_bytes)

            # Detect specific RAW format from Make (0x010F) or DNGVersion (0xC612)
            if tag == 0xC612 and not is_cr2:
                ext = "dng"
                file_type = "Adobe DNG RAW"
            elif tag == 0x010F and tag_type == 2 and 0 < total_val_bytes <= 64 and not is_cr2:
                make_off = struct.unpack(f"{endian}I", val_or_offset)[0] if total_val_bytes > 4 else 0
                make_bytes = (
                    stream.read_at(start_offset + make_off, total_val_bytes)
                    if total_val_bytes > 4 else val_or_offset[:total_val_bytes]
                ).upper()
                if b"NIKON" in make_bytes:
                    ext = "nef"
                    file_type = "Nikon RAW (NEF)"
                elif b"SONY" in make_bytes:
                    ext = "arw"
                    file_type = "Sony RAW (ARW)"
                elif b"CANON" in make_bytes:
                    ext = "cr2"
                    file_type = "Canon RAW (CR2)"

            # Traverse SubIFDs (0x014A) and ExifIFD (0x8769)
            if tag in (0x014A, 0x8769):
                for sub_off in _read_uint_list(tag_type, count, val_or_offset):
                    if 0 < sub_off < max_size and sub_off not in visited_ifds:
                        ifd_queue.append(sub_off)

            # Collect offset/byte-count tags (both inline count==1 and array count>1)
            elif tag in (0x0111, 0x0117, 0x0144, 0x0145, 0x0201, 0x0202):
                ifd_int_tags[tag] = _read_uint_list(tag_type, count, val_or_offset)

        # Pair offsets with byte counts to find the true end of image data blocks
        for off_tag, len_tag in ((0x0111, 0x0117), (0x0144, 0x0145), (0x0201, 0x0202)):
            offsets = ifd_int_tags.get(off_tag, [])
            lengths = ifd_int_tags.get(len_tag, [])
            if offsets and lengths and len(offsets) == len(lengths):
                for off, length in zip(offsets, lengths):
                    if 0 < off < max_size and 0 < length < max_size and (off + length) <= max_size:
                        max_referenced_byte = max(max_referenced_byte, start_offset + off + length)
            elif offsets:
                for off in offsets:
                    if 0 < off < max_size:
                        max_referenced_byte = max(max_referenced_byte, start_offset + off)

        if len(ifd_bytes) >= entry_count * 12 + 4:
            next_ifd_raw = ifd_bytes[entry_count * 12 : entry_count * 12 + 4]
            next_ifd_offset = struct.unpack(f"{endian}I", next_ifd_raw)[0]
            if 0 < next_ifd_offset < max_size and next_ifd_offset not in visited_ifds:
                ifd_queue.append(next_ifd_offset)

    file_len = max_referenced_byte - start_offset
    if file_len % 2 != 0:
        file_len += 1

    if 32768 <= file_len <= max_size:
        return CarveCandidate(start_offset, file_len, file_type, ext, "TIFF Structure")

    return None