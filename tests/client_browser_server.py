"""Disposable owner-enabled server, never uses the formal data directory."""
import sys
import tempfile
from pathlib import Path
from personalai.access import Access
from personalai.store import Store
from personalai.__main__ import main

if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1] / '.cache' / 'client-e2e'
    root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='run-', dir=root))
    Access(Store(directory)).initialize('isolated-browser-test-password')
    sys.argv = [sys.argv[0], '--port', '19766', '--data-dir', str(directory)]
    main()
