"""Keep vault assertions on Linux without depending on Windows DPAPI."""
import os
import pytest


@pytest.fixture(autouse=True)
def isolated_server_key(tmp_path_factory, monkeypatch):
    if os.name != 'nt':
        path = tmp_path_factory.mktemp('vault-protection') / 'master.key'
        path.write_bytes(os.urandom(32))
        path.chmod(0o600)
        monkeypatch.setenv('PERSONALAI_MASTER_KEY_FILE', str(path))
