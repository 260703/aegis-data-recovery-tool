//! Zero-Copy Structural File Boundary Parsers
//! ===========================================
//! Implements strict binary validation for JPEG, PNG, ISOBMFF (MP4, MOV, Canon CR3),
//! and TIFF-based RAW digital camera photos (CR2, NEF, ARW, DNG).

use std::collections::{HashSet, VecDeque};
use crate::disk_stream::DiskStream;

pub const JPEG_SOI: &[u8] = b"\xFF\xD8\xFF";
pub const PNG_MAGIC: &[u8] = b"\x89PNG\r\n\x1a\n";
pub const TIFF_LE_MAGIC: &[u8] = b"II*\x00";
pub const TIFF_BE_MAGIC: &[u8] = b"MM\x00*";
pub const ISOBMFF_FTYP: &[u8] = b"ftyp";

const TOP_LEVEL_ISOBMFF_BOXES: &[[u8; 4]] = &[
    *b"ftyp", *b"moov", *b"mdat", *b"free", *b"skip", *b"wide",
    *b"uuid", *b"meta", *b"pdin", *b"prft", *b"styp", *b"sidx",
    *b"emsg", *b"moof", *b"mfra", *b"udta", *b"UDTA", *b"PICT",
    *b"junk", *b"beam", *b"ctab", *b"cmov", *b"rmra",
];

const KNOWN_MP4_BRANDS: &[[u8; 4]] = &[
    *b"isom", *b"iso2", *b"iso4", *b"iso5", *b"iso6",
    *b"mp41", *b"mp42", *b"mp71", *b"avc1", *b"hvc1", *b"hev1",
    *b"dash", *b"MSNV", *b"NDAS", *b"NDSC", *b"NDXH", *b"NDXM",
    *b"NDXP", *b"NDXS", *b"M4V ", *b"M4A ", *b"f4v ", *b"kddi",
    *b"XAVC", *b"mmp4", *b"3gp4", *b"3gp5",
];

const KNOWN_MOV_BRANDS: &[[u8; 4]] = &[*b"qt  ", *b"CAEP", *b"mqt "];
const KNOWN_RAW_BRANDS: &[[u8; 4]] = &[*b"crx "];

#[derive(Debug, Clone)]
pub struct CarveCandidate {
    pub offset: u64,
    pub length: u64,
    pub file_type: String,
    pub extension: String,
    pub details: String,
}

// =========================================================================
// 1. JPEG Boundary Parser
// =========================================================================
pub fn parse_jpeg(stream: &DiskStream, start_offset: u64, max_size: u64) -> Option<CarveCandidate> {
    let header = stream.read_at(start_offset, 4);
    if header.len() < 4 || &header[0..3] != JPEG_SOI {
        return None;
    }

    if header[3] < 0xC0 || header[3] == 0xD8 || header[3] == 0xD9 {
        return None;
    }

    let mut curr_offset = start_offset.checked_add(2)?;
    let mut in_sos = false;
    let read_chunk = 65536usize;
    let mut buffer: Vec<u8> = Vec::new();
    let mut buf_start = curr_offset;
    let mut eof = false;

    while curr_offset.saturating_sub(start_offset) < max_size {
        let needed_rel = (curr_offset - buf_start) as usize;
        if !eof && (needed_rel + 4096 > buffer.len()) {
            let next_read_off = buf_start.checked_add(buffer.len() as u64)?;
            let new_data = stream.read_at(next_read_off, read_chunk);
            if new_data.is_empty() {
                eof = true;
            } else {
                buffer.extend_from_slice(&new_data);
            }
        }

        let rel_idx = (curr_offset - buf_start) as usize;
        if rel_idx >= buffer.len() {
            break;
        }

        if !in_sos {
            if rel_idx + 2 > buffer.len() || buffer[rel_idx] != 0xFF {
                break;
            }

            let marker = buffer[rel_idx + 1];

            if marker == 0xFF {
                curr_offset = curr_offset.checked_add(1)?;
                continue;
            }

            if (0xD0..=0xD7).contains(&marker) || marker == 0x01 {
                curr_offset = curr_offset.checked_add(2)?;
                continue;
            }

            if marker == 0xD8 || marker == 0x00 {
                break;
            }

            if marker == 0xD9 {
                let file_len = curr_offset.checked_add(2)?.saturating_sub(start_offset);
                if file_len >= 512 {
                    return Some(CarveCandidate {
                        offset: start_offset,
                        length: file_len,
                        file_type: "JPEG Image".to_string(),
                        extension: "jpg".to_string(),
                        details: "Standard JPEG".to_string(),
                    });
                }
                return None;
            }

            if rel_idx + 4 > buffer.len() {
                break;
            }

            let seg_len = u16::from_be_bytes([buffer[rel_idx + 2], buffer[rel_idx + 3]]) as u64;
            if seg_len < 2 {
                break;
            }

            curr_offset = curr_offset.checked_add(2 + seg_len)?;
            if marker == 0xDA {
                in_sos = true;
            }
        } else {
            let search_slice = &buffer[rel_idx..];
            match memchr::memchr(0xFF, search_slice) {
                None => {
                    if eof {
                        break;
                    }
                    let slide = buffer.len().saturating_sub(64);
                    buffer.drain(0..slide);
                    buf_start = buf_start.checked_add(slide as u64)?;
                    curr_offset = buf_start.checked_add(buffer.len() as u64)?;
                }
                Some(ff_rel) => {
                    let ff_idx = rel_idx + ff_rel;
                    curr_offset = buf_start.checked_add(ff_idx as u64)?;

                    if ff_idx + 1 >= buffer.len() {
                        if eof {
                            break;
                        }
                        let more = stream.read_at(buf_start.checked_add(buffer.len() as u64)?, 4096);
                        if more.is_empty() {
                            break;
                        }
                        buffer.extend_from_slice(&more);
                    }

                    let next_b = buffer[ff_idx + 1];
                    if next_b == 0x00 || (0xD0..=0xD7).contains(&next_b) {
                        curr_offset = curr_offset.checked_add(2)?;
                    } else if next_b == 0xD9 {
                        let file_len = curr_offset.checked_add(2)?.saturating_sub(start_offset);
                        if file_len >= 512 {
                            return Some(CarveCandidate {
                                offset: start_offset,
                                length: file_len,
                                file_type: "JPEG Image".to_string(),
                                extension: "jpg".to_string(),
                                details: "Standard EXIF/JFIF".to_string(),
                            });
                        }
                        return None;
                    } else if next_b == 0xFF {
                        curr_offset = curr_offset.checked_add(1)?;
                    } else if matches!(next_b, 0xC0..=0xC7 | 0xC9..=0xCF | 0xDA | 0xDB | 0xDD | 0xFE)
                        || (0xE0..=0xEF).contains(&next_b)
                    {
                        in_sos = false;
                    } else {
                        curr_offset = curr_offset.checked_add(2)?;
                    }
                }
            }
        }
    }

    None
}

// =========================================================================
// 2. PNG Boundary Parser
// =========================================================================
pub fn parse_png(stream: &DiskStream, start_offset: u64, max_size: u64) -> Option<CarveCandidate> {
    let header = stream.read_at(start_offset, 16);
    if header.len() < 16 || &header[0..8] != PNG_MAGIC || &header[12..16] != b"IHDR" {
        return None;
    }

    let mut curr_offset = start_offset.checked_add(8)?;

    while curr_offset.saturating_sub(start_offset) < max_size {
        let chunk_hdr = stream.read_at(curr_offset, 8);
        if chunk_hdr.len() < 8 {
            break;
        }

        let chunk_len = u32::from_be_bytes([chunk_hdr[0], chunk_hdr[1], chunk_hdr[2], chunk_hdr[3]]) as u64;
        let chunk_type = &chunk_hdr[4..8];

        if chunk_len > 64 * 1024 * 1024 || !chunk_type.iter().all(|b| b.is_ascii_alphabetic()) {
            break;
        }

        let payload_and_crc_len = (chunk_len as usize).checked_add(4)?;
        let payload_and_crc = stream.read_at(curr_offset.checked_add(8)?, payload_and_crc_len);
        if payload_and_crc.len() < payload_and_crc_len {
            break;
        }

        let crc_start = payload_and_crc.len() - 4;
        let chunk_crc = u32::from_be_bytes([
            payload_and_crc[crc_start],
            payload_and_crc[crc_start + 1],
            payload_and_crc[crc_start + 2],
            payload_and_crc[crc_start + 3],
        ]);

        let mut hasher = crc32fast::Hasher::new();
        hasher.update(chunk_type);
        hasher.update(&payload_and_crc[..chunk_len as usize]);

        if hasher.finalize() != chunk_crc {
            break;
        }

        curr_offset = curr_offset.checked_add(8 + chunk_len + 4)?;

        if chunk_type == b"IEND" {
            let file_len = curr_offset.saturating_sub(start_offset);
            return Some(CarveCandidate {
                offset: start_offset,
                length: file_len,
                file_type: "PNG Image".to_string(),
                extension: "png".to_string(),
                details: "Validated CRC-32".to_string(),
            });
        }
    }

    None
}

// =========================================================================
// 3. ISOBMFF Video & CR3 Parser (MP4, MOV, Canon CR3)
// =========================================================================
pub fn parse_isobmff(stream: &DiskStream, mut start_offset: u64, max_size: u64) -> Option<CarveCandidate> {
    let mut hdr = stream.read_at(start_offset, 16);
    if hdr.len() < 16 {
        return None;
    }

    let mut box_size = u32::from_be_bytes([hdr[0], hdr[1], hdr[2], hdr[3]]) as u64;
    let mut box_type = &hdr[4..8];

    if box_type == b"wide" && box_size == 8 {
        box_size = u32::from_be_bytes([hdr[8], hdr[9], hdr[10], hdr[11]]) as u64;
        box_type = &hdr[12..16];
        if box_type != ISOBMFF_FTYP {
            return None;
        }
        start_offset = start_offset.checked_add(8)?;
        hdr = stream.read_at(start_offset, 16);
        if hdr.len() < 16 {
            return None;
        }
    } else if box_type != ISOBMFF_FTYP {
        return None;
    }

    if !(16..=4096).contains(&box_size) {
        return None;
    }

    let major_brand = &hdr[8..12];
    let mut ext = "mp4".to_string();
    let mut file_type = "MP4 Video".to_string();
    let mut matched = false;

    if KNOWN_MOV_BRANDS.iter().any(|b| b == major_brand) {
        ext = "mov".to_string();
        file_type = "QuickTime MOV".to_string();
        matched = true;
    } else if KNOWN_RAW_BRANDS.iter().any(|b| b == major_brand) {
        ext = "cr3".to_string();
        file_type = "Canon RAW (CR3)".to_string();
        matched = true;
    } else if KNOWN_MP4_BRANDS.iter().any(|b| b == major_brand) {
        matched = true;
    } else {
        let ftyp_body = stream.read_at(
            start_offset.checked_add(8)?,
            (box_size as usize).saturating_sub(8).min(256),
        );
        if ftyp_body.len() >= 8 {
            for i in (8..ftyp_body.len().saturating_sub(3)).step_by(4) {
                let brand = &ftyp_body[i..i + 4];
                if KNOWN_MP4_BRANDS.iter().any(|b| b == brand) {
                    matched = true;
                    break;
                }
                if KNOWN_MOV_BRANDS.iter().any(|b| b == brand) {
                    ext = "mov".to_string();
                    file_type = "QuickTime MOV".to_string();
                    matched = true;
                    break;
                }
                if KNOWN_RAW_BRANDS.iter().any(|b| b == brand) {
                    ext = "cr3".to_string();
                    file_type = "Canon RAW (CR3)".to_string();
                    matched = true;
                    break;
                }
            }
        }
    }

    if !matched {
        return None;
    }

    let mut curr_offset = start_offset;
    let mut has_moov = false;
    let mut has_mdat = false;
    let mut box_count = 0usize;

    while curr_offset.saturating_sub(start_offset) < max_size {
        box_count += 1;
        if box_count > 10_000 {
            break;
        }

        let b_hdr = stream.read_at(curr_offset, 16);
        if b_hdr.len() < 8 {
            break;
        }

        let mut b_size = u32::from_be_bytes([b_hdr[0], b_hdr[1], b_hdr[2], b_hdr[3]]) as u64;
        let b_type = [b_hdr[4], b_hdr[5], b_hdr[6], b_hdr[7]];

        if b_size == 1 {
            if b_hdr.len() < 16 {
                break;
            }
            b_size = u64::from_be_bytes([
                b_hdr[8], b_hdr[9], b_hdr[10], b_hdr[11],
                b_hdr[12], b_hdr[13], b_hdr[14], b_hdr[15],
            ]);
            if b_size < 16 {
                break;
            }
        } else if b_size < 8 {
            break;
        }

        if !TOP_LEVEL_ISOBMFF_BOXES.contains(&b_type) {
            break;
        }

        let next_offset = match curr_offset.checked_add(b_size) {
            Some(off) => off,
            None => break,
        };

        if next_offset.saturating_sub(start_offset) > max_size {
            break;
        }

        if b_type == *b"moov" {
            has_moov = true;
        } else if b_type == *b"mdat" {
            has_mdat = true;
        }

        curr_offset = next_offset;

        if has_moov && has_mdat {
            let next_hdr = stream.read_at(curr_offset, 8);
            if next_hdr.len() < 8 {
                break;
            }
            let n_size = u32::from_be_bytes([next_hdr[0], next_hdr[1], next_hdr[2], next_hdr[3]]) as u64;
            let n_type = [next_hdr[4], next_hdr[5], next_hdr[6], next_hdr[7]];
            if !TOP_LEVEL_ISOBMFF_BOXES.contains(&n_type) || (n_size != 1 && n_size < 8) {
                break;
            }
        }
    }

    let file_len = curr_offset.saturating_sub(start_offset);
    if file_len >= 16384 && has_moov && has_mdat {
        let brand_str = String::from_utf8_lossy(major_brand).trim().to_string();
        return Some(CarveCandidate {
            offset: start_offset,
            length: file_len,
            file_type,
            extension: ext,
            details: format!("Brand: {}", brand_str),
        });
    }

    None
}

// =========================================================================
// 4. TIFF RAW Photo Parser (CR2, NEF, ARW, DNG)
// =========================================================================
pub fn parse_tiff_raw(stream: &DiskStream, start_offset: u64, max_size: u64) -> Option<CarveCandidate> {
    let hdr = stream.read_at(start_offset, 16);
    if hdr.len() < 16 {
        return None;
    }

    let is_le = &hdr[0..4] == TIFF_LE_MAGIC;
    let is_be = &hdr[0..4] == TIFF_BE_MAGIC;
    if !is_le && !is_be {
        return None;
    }

    let read_u16 = |b: &[u8]| -> u16 {
        if is_le {
            u16::from_le_bytes([b[0], b[1]])
        } else {
            u16::from_be_bytes([b[0], b[1]])
        }
    };

    let read_u32 = |b: &[u8]| -> u64 {
        if is_le {
            u32::from_le_bytes([b[0], b[1], b[2], b[3]]) as u64
        } else {
            u32::from_be_bytes([b[0], b[1], b[2], b[3]]) as u64
        }
    };

    let ifd0_offset = read_u32(&hdr[4..8]);
    if ifd0_offset < 8 || ifd0_offset >= max_size {
        return None;
    }

    let is_cr2 = &hdr[8..12] == b"CR\x02\x00";
    let mut ext = if is_cr2 { "cr2" } else { "raw" }.to_string();
    let mut file_type = if is_cr2 { "Canon RAW (CR2)" } else { "TIFF/RAW Image" }.to_string();

    let mut max_referenced_byte = start_offset.checked_add(if is_cr2 { 16 } else { 8 })?;
    let mut visited_ifds = HashSet::new();
    let mut ifd_queue: VecDeque<u64> = VecDeque::new();
    ifd_queue.push_back(ifd0_offset);

    let get_type_size = |t: u16| -> u64 {
        match t {
            1 | 2 | 6 | 7 => 1,
            3 | 8 => 2,
            4 | 9 | 11 => 4,
            5 | 10 | 12 => 8,
            _ => 1,
        }
    };

    let read_uint_list = |tag_type: u16, count: u64, val_or_offset: &[u8]| -> Vec<u64> {
        if count == 0 || count > 65536 {
            return Vec::new();
        }
        let item_sz = match tag_type {
            3 => 2usize,
            4 | 9 => 4usize,
            _ => return Vec::new(),
        };
        let total_bytes = (count as usize).saturating_mul(item_sz);
        let raw = if total_bytes <= 4 {
            val_or_offset[..total_bytes].to_vec()
        } else {
            let rel_off = read_u32(val_or_offset);
            let Some(rel_end) = rel_off.checked_add(total_bytes as u64) else {
                return Vec::new();
            };
            if rel_off == 0 || rel_end > max_size {
                return Vec::new();
            }
            let Some(abs_off) = start_offset.checked_add(rel_off) else {
                return Vec::new();
            };
            stream.read_at(abs_off, total_bytes)
        };

        if raw.len() < total_bytes {
            return Vec::new();
        }

        let mut result = Vec::with_capacity(count as usize);
        for i in 0..count as usize {
            let chunk = &raw[i * item_sz..(i + 1) * item_sz];
            let val = if item_sz == 2 {
                read_u16(chunk) as u64
            } else {
                read_u32(chunk)
            };
            result.push(val);
        }
        result
    };

    while let Some(curr_ifd_off) = ifd_queue.pop_front() {
        if curr_ifd_off == 0 || visited_ifds.contains(&curr_ifd_off) || curr_ifd_off >= max_size {
            continue;
        }
        if visited_ifds.len() >= 32 {
            break;
        }
        visited_ifds.insert(curr_ifd_off);

        let Some(abs_ifd_pos) = start_offset.checked_add(curr_ifd_off) else {
            continue;
        };
        let ifd_hdr = stream.read_at(abs_ifd_pos, 2);
        if ifd_hdr.len() < 2 {
            continue;
        }

        let entry_count = read_u16(&ifd_hdr) as usize;
        if entry_count == 0 || entry_count > 512 {
            continue;
        }

        let ifd_bytes_len = entry_count * 12 + 4;
        let ifd_bytes = stream.read_at(abs_ifd_pos + 2, ifd_bytes_len);
        if ifd_bytes.len() < entry_count * 12 {
            continue;
        }

        max_referenced_byte = max_referenced_byte.max(abs_ifd_pos + 2 + ifd_bytes.len() as u64);

        let mut offset_tags: Vec<(u16, Vec<u64>)> = Vec::new();

        for i in 0..entry_count {
            let entry = &ifd_bytes[i * 12..(i + 1) * 12];
            let tag = read_u16(&entry[0..2]);
            let tag_type = read_u16(&entry[2..4]);
            let count = read_u32(&entry[4..8]);
            let val_or_offset = &entry[8..12];

            let item_size = get_type_size(tag_type);
            let total_val_bytes = count.saturating_mul(item_size);

            if total_val_bytes > 4 {
                let val_offset = read_u32(val_or_offset);
                if let Some(rel_end) = val_offset.checked_add(total_val_bytes) {
                    if val_offset > 0 && rel_end <= max_size {
                        if let Some(abs_end) = start_offset.checked_add(rel_end) {
                            max_referenced_byte = max_referenced_byte.max(abs_end);
                        }
                    }
                }
            }

            if tag == 0xC612 && !is_cr2 {
                ext = "dng".to_string();
                file_type = "Adobe DNG RAW".to_string();
            } else if tag == 0x010F && tag_type == 2 && (1..=64).contains(&total_val_bytes) && !is_cr2 {
                let make_bytes = if total_val_bytes > 4 {
                    let make_off = read_u32(val_or_offset);
                    match start_offset.checked_add(make_off) {
                        Some(abs_make) => stream.read_at(abs_make, total_val_bytes as usize),
                        None => Vec::new(),
                    }
                } else {
                    val_or_offset[..total_val_bytes as usize].to_vec()
                };
                let upper_make = make_bytes.to_ascii_uppercase();
                if memchr::memmem::find(&upper_make, b"NIKON").is_some() {
                    ext = "nef".to_string();
                    file_type = "Nikon RAW (NEF)".to_string();
                } else if memchr::memmem::find(&upper_make, b"SONY").is_some() {
                    ext = "arw".to_string();
                    file_type = "Sony RAW (ARW)".to_string();
                } else if memchr::memmem::find(&upper_make, b"CANON").is_some() {
                    ext = "cr2".to_string();
                    file_type = "Canon RAW (CR2)".to_string();
                }
            }

            if matches!(tag, 0x014A | 0x8769) {
                for sub_off in read_uint_list(tag_type, count, val_or_offset) {
                    if sub_off > 0 && sub_off < max_size && !visited_ifds.contains(&sub_off) {
                        ifd_queue.push_back(sub_off);
                    }
                }
            } else if matches!(tag, 0x0111 | 0x0117 | 0x0144 | 0x0145 | 0x0201 | 0x0202) {
                offset_tags.push((tag, read_uint_list(tag_type, count, val_or_offset)));
            }
        }

        let get_tag_list = |t: u16| -> Vec<u64> {
            offset_tags
                .iter()
                .find(|(k, _)| *k == t)
                .map(|(_, v)| v.clone())
                .unwrap_or_default()
        };

        for (off_tag, len_tag) in &[(0x0111, 0x0117), (0x0144, 0x0145), (0x0201, 0x0202)] {
            let offsets = get_tag_list(*off_tag);
            let lengths = get_tag_list(*len_tag);
            if !offsets.is_empty() && offsets.len() == lengths.len() {
                for (off, len) in offsets.iter().zip(lengths.iter()) {
                    if let Some(rel_end) = off.checked_add(*len) {
                        if *off > 0 && *len > 0 && rel_end <= max_size {
                            if let Some(abs_end) = start_offset.checked_add(rel_end) {
                                max_referenced_byte = max_referenced_byte.max(abs_end);
                            }
                        }
                    }
                }
            } else {
                for off in offsets {
                    if off > 0 && off < max_size {
                        if let Some(abs_off) = start_offset.checked_add(off) {
                            max_referenced_byte = max_referenced_byte.max(abs_off);
                        }
                    }
                }
            }
        }

        if ifd_bytes.len() >= entry_count * 12 + 4 {
            let next_off = read_u32(&ifd_bytes[entry_count * 12..entry_count * 12 + 4]);
            if next_off > 0 && next_off < max_size && !visited_ifds.contains(&next_off) {
                ifd_queue.push_back(next_off);
            }
        }
    }

    let mut file_len = max_referenced_byte.saturating_sub(start_offset);
    if file_len % 2 != 0 {
        file_len += 1;
    }

    if (32768..=max_size).contains(&file_len) {
        Some(CarveCandidate {
            offset: start_offset,
            length: file_len,
            file_type,
            extension: ext,
            details: "TIFF Directory Structure".to_string(),
        })
    } else {
        None
    }
}