# Contributing to Aegis Data Recovery

Thank you for your interest in contributing to **Aegis Data Recovery**! We welcome contributions from developers, digital forensics practitioners, and security researchers worldwide.

---

## Code of Conduct

We are committed to providing a welcoming, inclusive, and harassment-free experience for everyone. Please be respectful and constructive in all discussions, issues, and code reviews.

---

## Getting Started

### 1. Prerequisites
- **Python 3.9+** (Tested on Python 3.9 through 3.14)
- **Git**

### 2. Fork and Clone
```bash
# Clone your fork
git clone https://github.com/<your-username>/aegis-data-recovery.git
cd aegis-data-recovery
```

### 3. Create a Virtual Environment
```bash
# On Windows
python -m venv venv
venv\Scripts\activate

# On Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 4. Install Dependencies
```bash
pip install -r requirements-dev.txt
```

---

## Project Architecture

Aegis is architected into modular components:

```
├── app.py                   # Desktop application entry point with UAC elevation
├── carver.py                # Standalone multithreaded CLI carver
├── core/
│   ├── __init__.py          # Core package exports
│   ├── disk_stream.py       # Strict read-only binary stream handler ('rb')
│   ├── device_manager.py    # Hardware drive detection & safety verification
│   ├── parsers.py           # Binary boundary & structure parsers
│   └── worker.py            # QThread background worker for GUI
├── ui/
│   ├── __init__.py          # UI package exports
│   ├── main_window.py       # PySide6 desktop GUI window
│   ├── styles.py            # Modern dark-theme QSS stylesheet
│   └── icons/               # SVG / PNG UI icons
└── tests/                   # Automated unit test suite
```

---

## How to Add a New File Format Parser

Aegis relies on **structural boundary parsing** rather than naive header-footer matching. To add support for a new file format (e.g., PDF, ZIP, WebP, MP3):

1. **Define File Signatures in [`core/parsers.py`](core/parsers.py)**:
   Add magic bytes and markers as constants.
   ```python
   WEBP_RIFF = b"RIFF"
   WEBP_MAGIC = b"WEBP"
   ```

2. **Implement the Boundary Parser Function**:
   Create a function matching the signature:
   ```python
   def parse_webp(stream: DiskStream, start_offset: int, max_size: int = 50 * 1024 * 1024) -> Optional[CarveCandidate]:
       # 1. Verify magic header
       # 2. Extract structural length/atoms
       # 3. Validate sanity checks (file size > min, < max)
       # 4. Return CarveCandidate(start_offset, file_len, "WebP Image", "webp", "Details")
       ...
   ```

3. **Register in [`core/worker.py`](core/worker.py) and [`carver.py`](carver.py)**:
   - Add signature detection check in the sliding-window read loop.
   - Wire candidate parser to thread pool tasks.

4. **Add Unit Tests in [`tests/test_parsers.py`](tests/test_parsers.py)**:
   - Provide minimal valid binary fixtures and corrupted boundary edge cases.
   - Assert `CarveCandidate` offset and length calculation.

---

## Running Unit Tests

Run tests using Python's standard `unittest` runner:
```bash
python -m unittest discover tests
```

Or with `pytest`:
```bash
pytest -v --cov=core
```

Ensure all existing tests pass before submitting your Pull Request.

---

## Coding Standards

- **PEP 8 Compliance**: Follow standard Python conventions.
- **Type Hints**: Annotate public methods and helper functions with `typing` hints.
- **Strict Read-Only Safety**: Any code accessing physical drives or disk streams must **NEVER** write, format, or delete bytes on the source target.
- **Docstrings**: Document classes and boundary parsing algorithms explaining hex specifications and endianness.

---

## Submitting a Pull Request

1. **Create a Feature Branch**:
   ```bash
   git checkout -b feature/add-webp-carver
   ```
2. **Commit Your Changes**:
   Use descriptive commit messages:
   ```bash
   git commit -m "feat(parsers): implement RIFF WebP structural boundary carver"
   ```
3. **Push to Your Fork**:
   ```bash
   git push origin feature/add-webp-carver
   ```
4. **Open a Pull Request**:
   - Provide a clear summary of what your PR introduces.
   - Reference any related GitHub issues.
   - Ensure the CI automated test pipeline passes.

---

## Questions or Ideas?

Feel free to open an issue or start a discussion on GitHub. We appreciate your help in making digital forensic data recovery accessible to everyone!

