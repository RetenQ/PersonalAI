"""Portable snapshots; restoration only into a new, empty destination."""
import io
import json
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import portalocker

from .models import now
from .store import Store, StoreError, digest
from .user_files import FOLDERS, render_user_files


def export_backup(store: Store) -> bytes:
    with store.mutex, portalocker.Lock(str(store.root / ".write.lock"), timeout=10):
        store.reload()
        store.require_healthy()
        files = {f"events/{path.name}": path.read_bytes() for path in store.files}
        files.update({'user/' + name: raw for name, raw in render_user_files(store).items()})
        manifest = {"format": 2, "created_at": now(), "files": {name: digest(raw) for name, raw in files.items()}}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, raw in files.items():
                archive.writestr(name, raw)
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return output.getvalue()


def validate_archive(raw: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            if len({i.filename for i in infos}) != len(infos):
                raise ValueError("duplicate archive entries")
            if sum(i.file_size for i in infos) > 256 * 1024 * 1024:
                raise ValueError("archive exceeds milestone size limit")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["format"] not in {1, 2} or not isinstance(manifest["files"], dict):
                raise ValueError("unsupported archive")
            if set(archive.namelist()) != {"manifest.json", *manifest["files"]}:
                raise ValueError("unexpected files")
            if manifest['format'] == 2 and 'user/README.md' not in manifest['files']:
                raise ValueError('missing readable directory')
            result = {}
            for name, checksum in manifest["files"].items():
                path = Path(name)
                event_path = len(path.parts) == 2 and path.parts[0] == 'events'
                user_path = manifest['format'] == 2 and (name == 'user/README.md' or
                    len(path.parts) == 3 and path.parts[0] == 'user' and path.parts[1] in FOLDERS)
                if "\\" in name or ":" in name or path.is_absolute() or not (event_path or user_path) or path.suffix != ".md" or ".." in path.parts:
                    raise ValueError("invalid path")
                data = archive.read(name)
                if digest(data) != checksum:
                    raise ValueError("checksum mismatch")
                result[name] = data
            return result
    except (zipfile.BadZipFile, KeyError, ValueError, TypeError, OSError, RuntimeError) as exc:
        raise StoreError("备份校验失败：文件损坏、清单不一致或格式不支持。", 422) from exc


def restore_backup(raw: bytes, destination: Path) -> Store:
    destination = destination.resolve()
    if destination.exists():
        raise StoreError("恢复目标必须是尚不存在的新目录，不允许覆盖已有数据。", 409)
    files = validate_archive(raw)
    with TemporaryDirectory(prefix="personalai-restore-") as temporary:
        staging = Path(temporary) / "data"
        for name, data in files.items():
            if not name.startswith('events/'):
                continue
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        store = Store(staging)
        store.require_healthy()
        readable = {name.removeprefix('user/'): value for name, value in files.items() if name.startswith('user/')}
        if readable and readable != render_user_files(store):
            raise StoreError('备份中的可读资料与原始记录不一致，未恢复。', 422)
        if not store.user_files_status()['healthy']:
            raise StoreError('恢复时无法生成可读资料，请检查目标目录和空间。', 503)
        shutil.copytree(staging, destination)
    return Store(destination)


def verify_backup(raw: bytes) -> dict:
    with TemporaryDirectory(prefix="personalai-verify-") as temporary:
        restored = restore_backup(raw, Path(temporary) / "restored")
        return {"verified": True, "records": len(restored.records), "events": restored.sequence,
                "message": "已在独立临时目录恢复并通过完整性校验；当前数据未修改。"}


if __name__ == "__main__":
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="验证备份，或恢复到一个尚不存在的新目录。")
    parser.add_argument("archive", type=Path)
    parser.add_argument("--restore-to", type=Path)
    args = parser.parse_args()
    try:
        raw = args.archive.read_bytes()
        if args.restore_to:
            result = restore_backup(raw, args.restore_to)
            print(f"已恢复到新目录：{result.root}；原运行数据未修改。记录数：{len(result.records)}")
        else:
            print(json.dumps(verify_backup(raw), ensure_ascii=False, indent=2))
    except (StoreError, OSError) as exc:
        print(f"操作失败：{exc}")
        raise SystemExit(1)
