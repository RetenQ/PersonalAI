"""Run the real application against a fresh, isolated browser-test directory."""
import sys
import json
import tempfile
from pathlib import Path

from personalai.__main__ import main


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    cache = root / ".cache" / "browser-e2e"
    cache.mkdir(parents=True, exist_ok=True)
    data = tempfile.mkdtemp(prefix="run-", dir=cache)
    # Keep failed-run evidence for inspection; never reuse or touch formal data/.
    from personalai.runtime import DEFAULT_PLUGINS
    config = Path(data).parent / (Path(data).name + '-server.json')
    config.write_text(json.dumps({'plugins': DEFAULT_PLUGINS + ['example']}), encoding='utf-8')
    sys.argv = [sys.argv[0], "--port", "19765", "--data-dir", data, "--config", str(config)]
    main()
