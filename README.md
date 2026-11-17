<div align="center">

# 🛡️ Aegis Data Recovery

### *High-Performance Forensic Raw Disk Carving & Media Recovery Suite*

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://python.org)
[![Rust Engine](https://img.shields.io/badge/Rust-2021%20Edition-orange.svg)](https://www.rust-lang.org)
[![Framework](https://img.shields.io/badge/GUI-PySide6%20%2F%20Qt6-green.svg)](https://wiki.qt.io/Qt_for_Python)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Safety Protocol](https://img.shields.io/badge/Safety-Strict%20Read--Only-red.svg)](#-strict-read-only-safety-guarantee)

<p align="center">
  <a href="#-key-features">Key Features</a> •
  <a href="#-architecture">Architecture</a> •
  <a href="#-supported-file-formats">Supported Formats</a> •
  <a href="#-installation--setup-guide">Installation & Setup</a> •
  <a href="#-compiling-the-rust-engine-aegis_core">Compiling Rust Engine</a> •
  <a href="#-usage-guide">Usage Guide</a> •
  <a href="#-contributing">Contributing</a>
</p>

</div>

---

## 📌 Overview

**Aegis Data Recovery** is a professional, open-source digital forensics suite engineered to recover deleted photos, videos, and raw camera files directly from physical disks, USB flash drives, memory cards, and raw disk images (`.dd`, `.img`, `.raw`, `.bin`).

Unlike standard consumer data recovery tools that rely on naive header-footer pattern matching (which produce truncated, corrupt, or bloated false-positive files), Aegis combines a **compiled Rust systems engine (`aegis_core`)** with a modern **PySide6 desktop GUI**. It analyzes internal binary structures, ISOBMFF atom trees, TIFF IFD tables, and CRC-32 checksums to extract files with zero data corruption.

---

## ✨ Key Features

- **🦀 High-Performance Native Rust Core (`aegis_core`)**:
  - **SIMD Byte Searching**: Hardware-accelerated AVX2/AVX-512 signature scanning using `memchr` (`memmem::Finder`).
  - **Rayon Multi-Core Parallelism**: Dynamic work-stealing parallel parsing across all physical CPU cores.
  - **Hardware CRC-32 Validation**: Hardware SSE4.2/PCLMULQDQ acceleration via `crc32fast` for chunk verification.
  - **GIL Release**: Releases the Python Global Interpreter Lock (`Python::allow_threads`) during disk I/O, ensuring the PySide6 UI runs at a buttery 60 FPS without freezing.
- **🛡️ Strict Read-Only Physical Disk Stream**:
  - Raw physical drives (`\\.\PhysicalDriveX`) and volumes (`\\.\E:`) are opened in strict binary read-only mode (`GENERIC_READ` / `rb`).
  - Emulates hardware write-blockers: zero write, erase, or partition commands are ever sent to the source media.
- **🚫 Physical Disk Overwrite Prevention**:
  - Compares physical disk numbers via Win32 `IOCTL_STORAGE_GET_DEVICE_NUMBER` to actively prevent selecting an output folder located on the physical disk being recovered.
- **🔄 Sliding-Window Overlap Buffer**:
  - Reads disk sectors in chunks with a 64 KB trailing sliding-window overlap margin, ensuring file signatures split across chunk boundaries are never missed.
- **🎯 Selective File Recovery & Interactive Table**:
  - **Checkbox Selection**: Every detected file features a clean select box under the **SELECT** column.
  - **Selective Output Sync**: Only files that are explicitly checked will be saved to your chosen output folder!
  - **Bulk Selection Controls**: Includes `☑ Select All` and `☐ Deselect All` buttons in the table header.
  - **Dynamic Save Button**: Prominent `💾 Save Selected (N)` action button that reflects selection count in real time.
  - **Right-Click Context Menu**: Instant options to *Preview File*, *Toggle Selection*, *Export Single File*, and *Open File Location*.
- **🖥️ Forensic Dashboard (PySide6)**:
  - Live I/O throughput (MB/s), peak speed tracking, estimated time remaining (ETA), LBA sector ticker, and integrity detail badges.
- **🔌 Automatic USB Hotplug Detection**:
  - Background polling dynamically detects when USB drives are inserted or removed, refreshing the target list automatically.
- **⚡ Standalone Multi-Threaded CLI (`carver.py`)**:
  - Scriptable, high-speed CLI tool ideal for automated forensic pipelines, headless servers, or batch processing.

---

## 🏛 Architecture

Aegis uses a hybrid architecture separating high-speed raw binary parsing from UI orchestration:

```
┌─────────────────────────────────────────────────────────────┐
│                 PySide6 Desktop GUI / CLI                   │
│          (app.py / main.py / carver.py / ui/)               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       core/ (Python)                        │
│  • worker.py          -> PySide6 QThread worker & signals   │
│  • device_manager.py  -> Drive enumeration & safety checks  │
│  • disk_stream.py     -> Read-only disk stream fallback     │
│  • parsers.py         -> Pure Python reference parsers      │
└──────────────────────────────┬──────────────────────────────┘
                               │ pyo3 bindings
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                      src/ (Rust Crate)                      │
│                Compiled into: aegis_core.pyd                │
│  • engine.rs          -> Rayon work-stealing carver         │
│  • disk_stream.rs     -> Win32 4096-byte direct sector I/O  │
│  • parsers.rs         -> SIMD JPEG, PNG, ISOBMFF, TIFF RAW  │
│  • device_manager.rs  -> Win32 physical IOCTL safety check  │
└─────────────────────────────────────────────────────────────┘
```

- **`src/` (Rust Engine)**: The high-performance core compiled via Maturin into `aegis_core`. Handles memory mapping, 4096-byte aligned Win32 direct I/O, SIMD scanning, and Rayon multi-threading.
- **`core/` (Python Bridge)**: PySide6 `QThread` wrappers (`worker.py`) that convert native engine callbacks into Qt signals (`sig_progress`, `sig_file_found`, `sig_log`) without blocking the event loop. Also provides pure-Python fallbacks.

---

## 📁 Supported File Formats

| Format | Extension | Magic Signature | Boundary Verification Logic | Max Carve Limit |
| :--- | :--- | :--- | :--- | :--- |
| **JPEG Images** | `.jpg`, `.jpeg` | `FF D8 FF` | Segment marker traversal, byte-stuffing decoding (`FF 00`), restart markers, true `FF D9` EOI | 50 MB |
| **PNG Images** | `.png` | `89 50 4E 47 0D 0A 1A 0A` | Chunk header parsing, full payload CRC-32 validation (`crc32fast`), terminal `IEND` | 100 MB |
| **MP4 Videos** | `.mp4` | `....ftyp(isom\|mp41\|...)` | Top-level atom chain validation (`moov` + `mdat` pairing, 64-bit `largesize`) | 4 GB |
| **QuickTime Videos** | `.mov` | `....ftypqt  ` or `wide` | QuickTime atom traversal, compatible brand check | 4 GB |
| **Canon RAW (CR2)** | `.cr2` | `II*\x00` + `CR\x02\x00` | TIFF IFD directory parsing, SubIFDs (`0x014A`), sensor strip offset pairing | 250 MB |
| **Canon RAW 3 (CR3)** | `.cr3` | `....ftypcrx ` | ISOBMFF atom parser with Canon CRX box mapping | 250 MB |
| **Nikon RAW (NEF)** | `.nef` | `II*\x00` (Make: NIKON) | TIFF IFD chain traversal, SubIFD strip byte count matching | 250 MB |
| **Sony RAW (ARW)** | `.arw` | `II*\x00` (Make: SONY) | TIFF IFD chain traversal, Sony SubIFD offset calculation | 250 MB |
| **Adobe Digital Negative** | `.dng` | `II*\x00` (DNGVersion) | TIFF DNG tag `0xC612` verification and payload evaluation | 250 MB |

---

## 📦 Installation & Setup Guide

### 1. Prerequisites

Before setting up the project, ensure you have the following installed on your system:

1. **Python 3.9+** (Tested on Python 3.9 through 3.14):
   - [Download Python](https://www.python.org/downloads/) (Make sure to check *"Add Python to PATH"* during installation).
2. **Rust & Cargo** (2021 Edition or newer):
   - Install Rust via [rustup.rs](https://rustup.rs/):
     ```powershell
     # In PowerShell / Command Prompt:
     winget install --id Rustlang.Rustup
     # OR download rustup-init.exe from https://rustup.rs
     ```
3. **C++ Build Tools (Windows Users)**:
   - Visual Studio 2017 or later, or **Build Tools for Visual Studio** with the **"Desktop development with C++"** workload and **Windows 10/11 SDK** selected (required by the MSVC linker `link.exe` and `kernel32.lib`).

---

### 2. Clone the Repository

```bash
git clone https://github.com/your-username/aegis-data-recovery.git
cd aegis-data-recovery
```

---

### 3. Create a Virtual Environment

```bash
# Windows (PowerShell / Command Prompt)
python -m venv venv
venv\Scripts\activate

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

---

### 4. Install Python Dependencies

For general users who only want to run the application:
```bash
pip install -r requirements.txt
```

For developers and contributors (includes `maturin`, `pytest`, `black`, `flake8`, `mypy`):
```bash
pip install -r requirements-dev.txt
```

---

## 🛠 Compiling the Rust Engine (`aegis_core`)

Aegis requires the compiled Rust extension module `aegis_core` to achieve full hardware carving speeds.

With your virtual environment active, compile and install the crate into your environment using **Maturin**:

```bash
maturin develop --release
```

#### What this command does:
1. Invokes `cargo build --release` with full Link-Time Optimization (`lto = "fat"`) and maximum optimization (`opt-level = 3`).
2. Generates the native Windows Python extension binary (`aegis_core.pyd`).
3. Installs the extension directly into your active virtual environment (`venv/Lib/site-packages/`).

#### Verify the Native Build:
Run this one-liner to verify `aegis_core` is compiled and exposes all native bindings:
```bash
python -c "import aegis_core; print('aegis_core loaded successfully! Exports:', [x for x in dir(aegis_core) if not x.startswith('_')])"
```
*Expected output:*
```text
aegis_core loaded successfully! Exports: ['CarveEngine', 'is_admin', 'is_output_safe', 'list_devices']
```

---

## 🚀 Usage Guide

### Mode 1: Desktop GUI Application

#### Running with UAC Auto-Elevation (Recommended for Physical Disks)
Accessing raw physical disks (`\\.\PhysicalDriveX`) requires Windows Administrator privileges. Running `app.py` automatically prompts for Windows UAC elevation:
```powershell
python app.py
```

#### Running in Safe Mode (Disk Images Only)
If you only need to analyze `.dd`, `.img`, or `.raw` disk images without triggering Windows UAC elevation:
```powershell
python app.py --no-elevate
# OR
python main.py
```

#### GUI Workflow:
1. **Select Recovery Target**: Pick a physical drive, removable USB drive, or load a `.dd` / `.img` file.
2. **Choose Output Directory**: Select an output destination on a **separate drive** (the safety guard prevents selecting the recovery target).
3. **Select File Formats**: Choose any combination of JPEG, PNG, RAW, MP4, and MOV.
4. **Choose Sector Alignment**:
   - `512-Byte Sector`: Standard for FAT32, exFAT, and USB flash drives (fastest).
   - `4096-Byte Cluster`: Optimized for modern NTFS and 4Kn drives.
   - `1-Byte Unaligned`: Deep forensic search across damaged partitions.
5. **Start Recovery**: Click `▶ START RECOVERY SCAN`. Watch real-time throughput, ETA, and detected files.
6. **Selective Saving**:
   - Check or uncheck files directly in the table using the select boxes under the **SELECT** column.
   - Use `☑ Select All` or `☐ Deselect All` for fast batch selection.
   - Click `💾 Save Selected (N)` to save only the files you want to your output directory!

---

### Mode 2: Multi-Threaded CLI Carver (`carver.py`)

Aegis includes a standalone, scriptable CLI tool:

```bash
python carver.py [-h] [-o OUTPUT] [-s SECTOR_STEP] [-b BLOCK_SIZE] [-t THREADS] [-f FORMATS] target
```

#### CLI Options:
| Option | Description | Default |
| :--- | :--- | :--- |
| `target` | Path to raw disk image (`.dd`, `.img`) or physical drive (`\\.\PhysicalDrive1`) | *Required* |
| `-o`, `--output` | Destination directory for carved files | `Recovered_Data` |
| `-s`, `--sector-step` | Sector alignment in bytes (`512`, `4096`, or `1` for unaligned) | `512` |
| `-b`, `--block-size` | Read chunk buffer size in megabytes | `16` (MB) |
| `-t`, `--threads` | Number of worker threads | CPU Count |
| `-f`, `--formats` | Comma-separated list of formats (`jpeg,png,mp4,mov,raw`) | `all` |

#### Practical Examples:
```bash
# Carve a raw USB disk image using 8 threads
python carver.py evidence.dd -o ./Carved_Output -t 8

# Carve only JPEG and RAW photos from a physical drive on Windows
python carver.py \\.\PhysicalDrive2 -f jpeg,raw -o D:\Recovered_Photos

# Perform a deep 1-byte unaligned forensic carve on a damaged image
python carver.py damaged_drive.img -s 1 -f jpeg,png -o ./Forensic_Carve
```

---

## 🧪 Testing & Verification

### Run Python Automated Unit Tests
Aegis includes an extensive test suite verifying structural parsers, disk stream caching, and device safety mechanisms:
```bash
python -m unittest discover tests -v
```

### Run Rust Static Analysis & Syntax Checks
Verify the native Rust engine compiles with zero warnings or errors:
```bash
cargo check
```

---

## 🔒 Strict Read-Only Safety Guarantee

In forensic investigations and emergency recovery, **preventing secondary damage to target media is paramount**:

1. **Hardware Write-Block Emulation**: Target device handles are opened exclusively in read-only mode (`GENERIC_READ` / `rb`). The underlying engine contains zero write, erase, truncate, or format routines.
2. **Physical Disk Overwrite Guard**: Aegis checks physical drive identifiers via `IOCTL_STORAGE_GET_DEVICE_NUMBER`. If an output directory resides on the physical disk being carved, the scan is blocked immediately to prevent overwriting unallocated clusters.

---

## 📂 Project Structure

```text
aegis-data-recovery/
├── src/                         # High-Performance Rust Systems Engine (aegis_core)
│   ├── lib.rs                   # PyO3 module interface & bindings
│   ├── engine.rs                # Rayon multi-threaded sliding-window carving engine
│   ├── disk_stream.rs           # 4096-byte sector-aligned Win32 direct I/O
│   ├── parsers.rs               # SIMD zero-copy structural boundary parsers
│   └── device_manager.rs        # Win32 physical drive enumeration & IOCTL safety
├── core/                        # Python Application Core & Qt Signal Bridges
│   ├── __init__.py              # Core package exports
│   ├── device_manager.py        # Python drive detection & safety validation
│   ├── disk_stream.py           # Pure-Python read-only stream fallback
│   ├── parsers.py               # Pure-Python structural parser fallback
│   └── worker.py                # Dedicated PySide6 QThread worker
├── ui/                          # PySide6 Desktop GUI
│   ├── __init__.py              # UI package exports
│   ├── main_window.py           # Main GUI window with interactive table & metrics
│   └── styles.py                # Modern dark-theme stylesheet (QSS)
├── tests/                       # Automated Forensic Test Suite
│   ├── __init__.py              # Test suite initialization
│   ├── test_device_manager.py   # Unit tests for drive detection & safety
│   ├── test_disk_stream.py      # Unit tests for stream alignment & RAM caching
│   └── test_parsers.py          # Unit tests for JPEG, PNG, ISOBMFF boundary calculation
├── aegis.ico                    # Official application logo & taskbar icon
├── aegis_core.pyi               # Type stub definitions for IDE autocomplete
├── app.py                       # Main GUI entry point with Windows UAC auto-elevation
├── main.py                      # Lightweight direct GUI entry point
├── carver.py                    # Standalone multi-threaded CLI carver utility
├── Cargo.toml                   # Rust crate configuration & dependencies
├── pyproject.toml               # Python build configuration for Maturin / PyO3
├── requirements.txt             # End-user runtime dependencies (PySide6, psutil)
├── requirements-dev.txt         # Contributor & compiler dependencies (maturin, pytest, etc.)
├── .gitignore                   # Git ignore rules for Rust & Python artifacts
├── CONTRIBUTING.md              # Contributor guidelines
├── LICENSE                      # MIT Open Source License
└── README.md                    # Project documentation
```

---

## 🤝 Contributing

Contributions are warmly welcome! Whether you are interested in adding new file format parsers (e.g. PDF, ZIP, WebP, audio files), optimizing carving algorithms, or improving UI translations:

1. Review our **[Contributing Guidelines (CONTRIBUTING.md)](CONTRIBUTING.md)**.
2. Fork the repository and create a feature branch (`git checkout -b feature/new-parser`).
3. Commit your changes with descriptive messages (`git commit -m "feat(parsers): add WebP RIFF parser"`).
4. Run `python -m unittest discover tests` and `cargo check` to ensure all tests pass.
5. Open a Pull Request!

---

## ⚖️ License & Ethical Disclaimer

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

> **Ethical & Legal Notice**: Aegis Data Recovery is designed for lawful data recovery, digital forensics investigations, educational research, and personal data restoration. Always ensure you have appropriate authorization before recovering or inspecting data from storage devices you do not own.
