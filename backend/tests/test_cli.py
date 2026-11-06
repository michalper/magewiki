import subprocess
import sys
from pathlib import Path


def test_cli_scan_demo_store(demo_store_path: Path):
    # Run as a real subprocess (not an in-process import) so it gets its own
    # asyncio event loop and database connection pool, independent of
    # whatever loop the rest of the pytest session's async tests are using.
    result = subprocess.run(
        [sys.executable, "-m", "app.cli", "scan", str(demo_store_path.resolve())],
        check=False,  # asserted explicitly below, with stderr in the failure message
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert result.returncode == 0, result.stderr
    assert "Vendor_Module" in result.stdout
    assert "modules_found=1" in result.stdout
