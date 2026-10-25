"""Run the real application against a fresh, isolated browser-test directory."""
import sys
import tempfile
from pathlib import Path

from personalai.__main__ import main


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    cache = root / ".cache" / "browser-e2e"
    cache.mkdir(parents=True, exist_ok=True)
    data = tempfile.mkdtemp(prefix="run-", dir=cache)
    # Keep failed-run evidence for inspection; never reuse or touch formal data/.
    sys.argv = [sys.argv[0], "--port", "19765", "--data-dir", data]
    main()
