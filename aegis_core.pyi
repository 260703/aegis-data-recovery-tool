from typing import List, Dict, Any, Tuple, Callable, Optional

def is_admin() -> bool:
    """Checks if the current process has administrator privileges."""
    ...

def is_output_safe(target_device_path: str, output_dir: str) -> Tuple[bool, str]:
    """Ensures output directory is not on the target drive being recovered."""
    ...

def list_devices() -> List[Dict[str, Any]]:
    """Lists physical drives and logical storage volumes."""
    ...

class CarveEngine:
    """High-performance multi-threaded carving engine."""
    def __init__(
        self,
        target_path: str,
        output_dir: str,
        sector_step: int = 512,
        block_size_mb: int = 8,
        enabled_formats: Optional[List[str]] = None,
    ) -> None: ...

    def pause(self) -> None: ...
    def resume(self) -> None: ...
    def stop(self) -> None: ...
    def run(
        self,
        on_started: Callable[[int], Any],
        on_progress: Callable[[int, int, float, float, int], Any],
        on_file_found: Callable[[Dict[str, Any]], Any],
        on_log: Callable[[str, str], Any],
    ) -> Dict[str, Any]: ...
