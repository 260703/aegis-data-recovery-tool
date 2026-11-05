<div align="center">

# 🛡️ Aegis Data Recovery

### *High-Performance Forensic Raw Disk Carving & Media Recovery Suite*

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://python.org)
[![Framework](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Code Style: Black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Safety Protocol](https://img.shields.io/badge/Safety-Strict%20Read--Only-red.svg)](#-strict-read-only-safety-guarantee)

<p align="center">
  <a href="#-key-features">Key Features</a> •
  <a href="#-how-it-works-under-the-hood">How It Works</a> •
  <a href="#-supported-file-formats">Supported Formats</a> •
  <a href="#-installation">Installation</a> •
  <a href="#-usage-guide">Usage Guide</a> •
  <a href="#-contributing">Contributing</a>
</p>

</div>

---

## 📌 Overview

**Aegis Data Recovery** is an open-source, digital forensics desktop application and command-line engine engineered to recover deleted photos, videos, and raw images directly from physical disks, USB flash drives, memory cards, and raw disk images (`.dd`, `.img`, `.raw`, `.bin`).

Unlike standard consumer data recovery tools that rely on naive header-footer pattern matching (which produce truncated, corrupt, or bloated false-positive files), Aegis implements **deep structural boundary parsing**. It analyzes the internal binary structures, atom trees, IFD tables, and CRC-32 checksums of media files to accurately extract files with zero data corruption.

Aegis provides both a modern **PySide6 desktop GUI** with live metrics and a high-performance **multi-threaded CLI** for automated forensic workflows.

---

## ✨ Key Features

- **🛡️ Strict Read-Only Safety Protocol**: 
  Target drives are strictly opened in binary read-only mode (`'rb'`). Aegis emulates hardware write-blocking: zero write, partition, or format commands are ever issued to source media.
- **🚫 Target Collision Prevention**: 
  Actively validates the recovery destination against the target drive. Prevents saving carved files onto the disk being scanned to protect deleted clusters from being overwritten.
- **⚡ Deep Structural Carving (No False Positives)**: 
  Parses true structural boundaries for JPEG (entropy stream & byte stuffing), PNG (chunk-by-chunk CRC-32 validation), MP4/MOV (ISOBMFF atom chains), and RAW photos (TIFF IFD tags and strip/tile offsets).
- **🔄 Sliding-Window Overlap Buffer**: 
  Reads disk sectors using an overlapping window mechanism (64 KB sliding margin), guaranteeing that file headers straddling read chunk boundaries are never missed.
- **🖥️ Modern PySide6 Desktop GUI**: 
  Dark-themed forensic dashboard with live I/O throughput (MB/s), estimated time remaining (ETA), real-time recovered file stream, search/filter controls, and activity logs.
- **🧵 Background `QThread` Architecture**: 
  All disk I/O and carving routines run asynchronously on dedicated background worker threads. The UI never freezes or stutters even under intensive disk I/O.
- **🔌 Automatic USB Hotplug Detection**: 
  Background timer dynamically senses when USB drives or external storage devices are connected or removed, updating the drive list seamlessly.
- **⚡ Standalone Multi-Threaded CLI (`carver.py`)**: 
  A lean, scriptable command-line tool with multi-threaded worker pools, ideal for headless servers, Linux forensic workstations, or batch image processing.
- **🔑 Automatic Windows UAC Elevation**: 
  Automatically detects administrator privileges needed for raw physical drive access (`\\.\PhysicalDriveX`) and triggers a UAC prompt (`runas`). Includes a safe `--no-elevate` mode for disk images.

---

## 🔬 How It Works (Under the Hood)

Aegis operates via a four-stage forensic pipeline:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. TARGET STREAMING (Strict Read-Only Direct I/O)                           │
│    Direct hardware access (\\.\PhysicalDriveX) or Disk Images (.dd, .img)   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 2. SLIDING-WINDOW BUFFER & SECTOR ALIGNMENT                                 │
│    8 MB read blocks with 64 KB overlap buffer to prevent split signatures   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 3. DEEP STRUCTURAL BOUNDARY PARSING (Zero False-Positives)                  │
│    • JPEG: Segment traversal, byte stuffing (0xFF00), progressive markers   │
│    • PNG:  Chunk header validation, full CRC-32 checksums, IEND chunk      │
│    • MP4:  ISOBMFF ftyp brands, top-level atom chain (moov + mdat pairing)  │
│    • RAW:  TIFF IFD/SubIFD directory tag walking, strip/tile offset sizing   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│ 4. ATOMIC RANGE CLAIMING & SAFE CARVING                                     │
│    Guarantees no duplicate/overlapping carvings; writes to safe output disk │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1. Target Streaming & Sector Alignment
Direct access to raw physical disks on modern operating systems requires sector alignment (typically 512 bytes for legacy MBR/FAT32 or 4096 bytes for Advanced Format / 4Kn drives). The `DiskStream` class automatically aligns seeks and reads to 4096-byte hardware boundaries, with a lock-free in-memory cache to eliminate redundant disk reads.

### 2. Overlap Window Buffering
When reading continuous raw sectors in chunks (e.g., 8 MB blocks), file headers that fall on the boundary between chunk $N$ and chunk $N+1$ would be split and lost in naive carvers. Aegis retains a 64 KB trailing overlap window across consecutive reads, ensuring 100% boundary detection coverage.

### 3. Structural Boundary Calculation
Rather than carving a fixed arbitrary size or stopping at the first matching footer:
- **JPEG (`.jpg`, `.jpeg`)**: Validates `FF D8 FF` Start of Image (SOI). Traverses segment markers (APPn, DQT, SOF, DHT). Upon reaching Start of Scan (`FF DA`), it enters the entropy-coded bitstream, correctly handling byte stuffing (`FF 00`), restart markers (`RST0`–`RST7`), and multi-scan progressive JPEGs until locating the true End of Image (`FF D9`).
- **PNG (`.png`)**: Validates 8-byte signature (`89 50 4E 47 0D 0A 1A 0A`). Traverses chunks sequentially (`IHDR`, `PLTE`, `IDAT`, etc.), verifies the 32-bit CRC checksum for each chunk against the IEEE 802.3 polynomial, and terminates cleanly at `IEND`.
- **MP4 / MOV (`.mp4`, `.mov`, `.cr3`)**: Validates the `ftyp` box and major/compatible brand declarations (`isom`, `iso2`, `mp41`, `qt  `, `crx `). Follows 32-bit and 64-bit (`largesize`) box chains, validating top-level containers (`moov`, `mdat`, `free`, `meta`) to calculate total file length.
- **RAW Photos (`.cr2`, `.nef`, `.arw`, `.dng`)**: Inspects TIFF header endianness (`II*` little-endian or `MM*` big-endian). Traverses Image File Directories (IFD0, SubIFDs, ExifIFD), extracts strip offsets (`0x0111`), strip byte counts (`0x0117`), tile offsets (`0x0144`), and JPEG interchange offsets (`0x0201`), calculating the exact outer envelope of the sensor payload.

### 4. Atomic Range Claiming
To prevent carving smaller embedded previews (such as JPEG EXIF thumbnails) as independent duplicate files, Aegis maintains an atomic `claimed_ranges` registry. Once a master RAW or JPEG file claims a sector range $[A, B)$, sub-allocations within that range are ignored.

---

## 📁 Supported File Formats

| Format | Extension | Magic Signature | Boundary Verification | Max Size Limit |
| :--- | :--- | :--- | :--- | :--- |
| **JPEG Images** | `.jpg`, `.jpeg` | `FF D8 FF` | Segment marker traversal, byte-stuffing decoding, true `FF D9` EOI | 50 MB |
| **PNG Images** | `.png` | `89 50 4E 47 0D 0A 1A 0A` | Chunk header parsing, full payload CRC-32 verification, terminal `IEND` | 100 MB |
| **MP4 Videos** | `.mp4` | `....ftyp(isom\|mp41\|...)` | ISOBMFF atom/box chain traversal (`moov` + `mdat` validation) | 4 GB |
| **QuickTime Videos** | `.mov` | `....ftypqt  ` or `wide` | QuickTime atom traversal, compatible brand check | 4 GB |
| **Canon RAW** | `.cr2` | `II*\x00` + `CR\x02\x00` | TIFF IFD directory parsing, SubIFDs (0x014A), sensor strip ranges | 250 MB |
| **Canon RAW 3** | `.cr3` | `....ftypcrx ` | ISOBMFF atom parser with Canon CRX box mapping | 250 MB |
| **Nikon RAW** | `.nef` | `II*\x00` (Make: NIKON) | TIFF IFD chain traversal, SubIFD strip byte count matching | 250 MB |
| **Sony RAW** | `.arw` | `II*\x00` (Make: SONY) | TIFF IFD chain traversal, Sony SubIFD offset calculation | 250 MB |
| **Adobe Digital Negative** | `.dng` | `II*\x00` (DNGVersion) | TIFF DNG tag 0xC612 verification and payload evaluation | 250 MB |

---

## 📦 Installation

### Prerequisites
- **Python 3.9+** (Compatible with Python 3.9, 3.10, 3.11, 3.12, 3.13, 3.14)
- **Windows**, **Linux**, or **macOS**

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/aegis-data-recovery.git
cd aegis-data-recovery
```

### 2. Create and Activate a Virtual Environment
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

*(Optional) For contributors and development tools (pytest, black, flake8):*
```bash
pip install -r requirements-dev.txt
```

---

## 🚀 Usage Guide

### Mode 1: Modern Desktop GUI Application

#### Running on Windows (Physical Drives & USB Sticks)
Accessing raw disks (`\\.\PhysicalDriveX`) requires Administrator privileges. Running `app.py` automatically prompts for Windows UAC elevation:
```powershell
python app.py
```

#### Running in Safe User Mode (Disk Images Only)
If you only need to analyze `.dd`, `.img`, or `.raw` disk images without triggering Windows UAC elevation:
```powershell
python app.py --no-elevate
```

#### GUI Workflow:
1. **Select Recovery Target**: Pick a physical drive, removable USB drive, or load a `.dd` / `.img` file.
2. **Choose Output Directory**: Select an output folder on a **separate drive** (the safety guard prevents selecting the recovery target).
3. **Select File Formats**: Choose any combination of JPEG, PNG, RAW, MP4, and MOV.
4. **Choose Sector Alignment**:
   - `512-Byte Sector`: Standard for FAT32, exFAT, and USB pendrives (fastest).
   - `4096-Byte Cluster`: Ultra-fast for modern NTFS and 4Kn drives.
   - `1-Byte Unaligned`: Deep byte-by-byte forensic search across corrupted file systems.
5. **Start Recovery**: Click `START RECOVERY SCAN`. Monitor live progress, throughput, and carved files in real time.

---

### Mode 2: Multi-Threaded CLI Carver (`carver.py`)

Aegis includes a standalone, scriptable CLI carver with configurable multi-threading.

```bash
python carver.py [-h] [-o OUTPUT] [-s SECTOR_STEP] [-b BLOCK_SIZE] [-t THREADS] [-f FORMATS] target
```

#### CLI Command-Line Arguments:
| Argument | Description | Default |
| :--- | :--- | :--- |
| `target` | Path to raw disk image (`.dd`, `.img`) or physical device (`\\.\PhysicalDrive1`, `/dev/sdb`) | *Required* |
| `-o`, `--output` | Destination directory for carved files | `Recovered_Data` |
| `-s`, `--sector-step` | Sector alignment in bytes (`512`, `4096`, or `1` for unaligned) | `512` |
| `-b`, `--block-size` | Read chunk buffer size in megabytes | `8` (MB) |
| `-t`, `--threads` | Number of concurrent worker threads | CPU Count |
| `-f`, `--formats` | Comma-separated list of formats (`jpeg,png,mp4,mov,raw`) | `all` |

#### Practical CLI Examples:

```bash
# 1. Carve a raw USB disk dump with 8 threads into a custom folder
python carver.py /path/to/evidence.dd -o ./Carved_Output -t 8

# 2. Carve only JPEG and RAW photos from a physical drive on Windows
python carver.py \\.\PhysicalDrive2 -f jpeg,raw -o D:\Recovered_Photos

# 3. Perform a deep 1-byte unaligned forensic carve on a damaged partition
python carver.py damaged_drive.img -s 1 -f jpeg,png -o ./Forensic_Carve
```

---

## 🔒 Strict Read-Only Safety Guarantee

In forensic investigations and emergency data recovery, **preventing secondary damage to target media is paramount**:

1. **Hardware Write-Block Emulation**: Target handles are opened exclusively in binary read-only mode (`mode='rb'`). The underlying engine contains zero write, erase, truncate, or format routines.
2. **Target Collision Prevention**: Aegis actively validates drive letters and volume mount points. If a user attempts to select an output directory located on the drive being recovered, Aegis blocks the scan to prevent overwriting unallocated clusters.

---

## 📂 Project Structure

```
aegis-data-recovery/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md        # GitHub bug report template
│   │   └── feature_request.md   # GitHub feature request template
│   ├── PULL_REQUEST_TEMPLATE.md # GitHub pull request template
│   └── workflows/
│       └── ci.yml               # Multi-OS automated test pipeline
├── core/
│   ├── __init__.py              # Core package exports
│   ├── device_manager.py        # USB / removable drive detection & safety validation
│   ├── disk_stream.py           # Strictly read-only binary stream handler ('rb')
│   ├── parsers.py               # Deep structural boundary carving parsers
│   └── worker.py                # Dedicated background QThread scanner worker
├── ui/
│   ├── __init__.py              # UI package exports
│   ├── icons/
│   │   └── check.svg            # Custom SVG checkmark icon
│   ├── main_window.py           # Main PySide6 desktop GUI window
│   └── styles.py                # Modern dark-theme stylesheet (QSS)
├── tests/
│   ├── __init__.py              # Test suite package
│   ├── test_device_manager.py   # Unit tests for hardware enumeration & safety
│   ├── test_disk_stream.py      # Unit tests for read-only streaming & cache
│   └── test_parsers.py          # Unit tests for JPEG, PNG, ISOBMFF boundary calculation
├── .gitignore                   # Comprehensive git ignore rules
├── app.py                       # Desktop application entry point with UAC auto-elevation
├── carver.py                    # Standalone multi-threaded CLI carver utility
├── CONTRIBUTING.md              # Contributor guide & developer documentation
├── LICENSE                      # MIT Open Source License
├── README.md                    # Project documentation
├── requirements.txt             # Core runtime dependencies
└── requirements-dev.txt         # Contributor & testing dependencies
```

---

## 🧪 Running Automated Unit Tests

Aegis includes an automated unit test suite verifying structural parsers, disk stream caching, and safety mechanisms.

Run the test suite using Python's built-in `unittest` runner:
```bash
python -m unittest discover tests -v
```

Or using `pytest`:
```bash
pytest -v
```

---

## 🤝 Contributing

Contributions are warmly welcome! Whether you are interested in adding new file format parsers (e.g., PDF, ZIP, WebP, audio files), optimizing carving algorithms, or improving UI translations:

1. Check out our **[Contributing Guidelines (CONTRIBUTING.md)](CONTRIBUTING.md)** for developer setup and coding standards.
2. Fork the repository and create a feature branch (`git checkout -b feature/new-parser`).
3. Commit your changes with descriptive messages (`git commit -m "feat(parsers): add WebP RIFF parser"`).
4. Run `python -m unittest discover tests` to ensure all tests pass.
5. Open a Pull Request!

---

## 🗺️ Roadmap

- [ ] **Additional Format Parsers**: PDF, ZIP / DOCX / XLSX, WebP, RIFF AVI, MP3 / AAC.
- [ ] **Filesystem Metadata Carving**: Complement unallocated sector carving with NTFS `$MFT` and FAT/exFAT Directory Entry parsing to recover original filenames and directory trees.
- [ ] **GPU-Accelerated Signature Scanning**: OpenCL/CUDA acceleration for multi-gigabyte-per-second signature matching.
- [ ] **Disk Imaging / Cloning Utility**: Forensic bit-stream image creation (`dd` image creation with SHA-256 hash validation).

---

## ⚖️ License & Ethical Disclaimer

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

> **Ethical & Legal Notice**: Aegis Data Recovery is designed for lawful data recovery, digital forensics investigations, educational research, and personal data restoration. Always ensure you have appropriate authorization before recovering or inspecting data from storage devices you do not own.
