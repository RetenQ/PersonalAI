"""Local service configuration; CLI > selected JSON file > defaults."""
import json
from pathlib import Path
from pydantic import Field
from .models import StrictModel

DEFAULT_PLUGINS = ['tracking', 'journal', 'analysis', 'dashboard', 'exchange']
class RuntimeConfig(StrictModel):
    host: str = '127.0.0.1'
    port: int = Field(default=8765, ge=1024, le=65535)
    data_dir: str | None = None
    plugins: list[str] = Field(default_factory=lambda: DEFAULT_PLUGINS.copy())

def load_runtime(path=None, *, port=None, data_dir=None):
    raw = {}
    if path:
        location = Path(path).resolve()
        raw = json.loads(location.read_text(encoding='utf-8-sig'))
        if raw.get('data_dir') and not Path(raw['data_dir']).is_absolute():
            raw['data_dir'] = str((location.parent / raw['data_dir']).resolve())
    if port is not None:
        raw['port'] = port
    if data_dir is not None:
        raw['data_dir'] = str(Path(data_dir).resolve())
    config = RuntimeConfig.model_validate(raw)
    if config.host != '127.0.0.1' or len(config.plugins) != len(set(config.plugins)):
        raise ValueError('只允许本机地址，插件编号不可重复。')
    return config
