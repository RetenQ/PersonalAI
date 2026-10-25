import io
import json
import socket
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from personalai.app import create_app, parse_day
from personalai.backup import export_backup, restore_backup, validate_archive, verify_backup
from personalai.model_gateway import ModelUnavailable, UnconfiguredModel, Understanding
from personalai.models import CATEGORIES, TZ, CreateRecord, Decision, ProposeRevision, RecordFields
from personalai.store import Store, StoreError, digest


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


def new_record(store, **changes):
    return store.create(CreateRecord(request_id=uuid4(), text="虚构样例：午后散步，读完一节课程。", date="2026-10-23", **changes))["record"]


def revision(store, record, text="虚构样例：实际散步 15 分钟。", **changes):
    return store.propose_revision(record["id"], ProposeRevision(request_id=uuid4(), expected_version=record["version"], text=text,
                                  date=record["date"], category=record["category"], reason="用户更正", **changes))["proposal"]


def decision(store, proposal, accept=True, request_id=None):
    return store.decide(proposal["id"], Decision(request_id=request_id or uuid4(), decision="accept" if accept else "reject"))


def test_restart_preserves_raw_unknown_fields_and_category(store):
    record = new_record(store)
    loaded = Store(store.root).get(record["id"])
    assert loaded.text == record["text"]
    assert loaded.processing == "not_analyzed"
    assert loaded.category == "uncategorized"
    assert "calories" not in loaded.model_dump()
    assert "sleep_hours" not in loaded.model_dump()
    assert "午后散步" in next(store.events_dir.glob("*.md")).read_text(encoding="utf-8")


@pytest.mark.parametrize("category", list(CATEGORIES))
def test_sparse_categories(store, category):
    assert new_record(store, category=category)["category"] == category


def test_request_idempotency_and_conflicting_payload(store):
    request = CreateRecord(request_id=uuid4(), text="测试记录", date="2026-10-23")
    first = store.create(request)
    assert Store(store.root).create(request) == first
    assert len(list(store.events_dir.glob("*.md"))) == 1
    with pytest.raises(StoreError, match="不同内容"):
        store.create(request.model_copy(update={"text": "不同输入"}))


def test_revision_requires_confirmation_and_keeps_history(store):
    record = new_record(store, kind="task")
    proposal = revision(store, record)
    assert store.get(record["id"]).text == record["text"]
    key = uuid4()
    result = decision(store, proposal, request_id=key)
    assert result["record"]["version"] == 2
    assert result["record"]["previous_version"] == 1
    assert store.get(record["id"]).text == proposal["after"]["text"]
    assert decision(store, proposal, request_id=key) == result
    restored = Store(store.root)
    assert len(restored.history[record["id"]]) == 2
    assert restored.proposals[proposal["id"]].status == "accepted"


def test_stale_confirmation_cannot_overwrite(store):
    record = new_record(store, kind="task")
    first = revision(store, record, text="新版任务")
    old = revision(store, record, text="旧的修改建议")
    decision(store, first)
    with pytest.raises(StoreError, match="已过期"):
        decision(store, old)
    assert store.get(record["id"]).text == "新版任务"
    assert store.proposals[old["id"]].status == "pending"
    decision(store, old, False)
    assert store.proposals[old["id"]].status == "rejected"


def test_mock_model_ambiguous_intent_only_proposes_then_rejects(store):
    # A validated test fixture, never injected into the production gateway.
    output = Understanding.model_validate({"items": [{"intent": "possible_task", "text": "以后有空学 Blender", "date": "2026-10-23", "evidence": "以后有空学 Blender"}]})
    item = output.items[0]
    fields = RecordFields(**item.model_dump(exclude={"intent", "evidence"}))
    proposal = store.propose_intent(uuid4(), fields, "create_task", "用户需决定是否列为任务")["proposal"]
    assert not store.records
    decision(store, proposal, False)
    assert not Store(store.root).records
    accepted = store.propose_intent(uuid4(), fields, "create_idea", "用户选择存为想法")["proposal"]
    result = decision(store, accepted)
    assert result["record"]["kind"] == "idea"
    assert result["record"]["source"] == "confirmed_suggestion"


def test_model_unavailable_does_not_invent_results():
    with pytest.raises(ModelUnavailable, match="模型尚未配置"):
        UnconfiguredModel().understand("虚构输入")
    with pytest.raises(ModelUnavailable):
        UnconfiguredModel().generate_report([])
    with pytest.raises(ValidationError):
        Understanding.model_validate({"items": [{"intent": "fact", "text": "", "date": "not-date"}]})


def test_interrupted_write_does_not_commit_and_retry_safe(store, monkeypatch):
    request = CreateRecord(request_id=uuid4(), text="中断测试", date="2026-10-23")
    import personalai.store as module
    original = module.os.replace
    def interrupted(*args):
        raise OSError("simulated disk error")
    monkeypatch.setattr(module.os, "replace", interrupted)
    with pytest.raises(StoreError, match="保存失败"):
        store.create(request)
    assert not Store(store.root).records
    assert not list(store.events_dir.glob("*.tmp"))
    monkeypatch.setattr(module.os, "replace", original)
    store.create(request)
    store.create(request)
    assert len(store.records) == 1


def test_concurrent_instances_serialize_writes(store):
    other = Store(store.root)
    request = CreateRecord(request_id=uuid4(), text="重复提交", date="2026-10-23")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda s: s.create(request), [store, other]))
    assert results[0] == results[1]
    assert Store(store.root).sequence == 1


@pytest.mark.parametrize("mode", ["body", "metadata", "missing-middle"])
def test_corruption_fails_closed(store, mode):
    new_record(store)
    new_record(store)
    new_record(store)
    files = sorted(store.events_dir.glob("*.md"))
    if mode == "missing-middle":
        files[1].unlink()
    else:
        raw = files[-1].read_bytes()
        files[-1].write_bytes(raw + b"corrupt" if mode == "body" else raw.replace(b'"sequence": 3', b'"sequence": 7'))
    loaded = Store(store.root)
    assert loaded.errors
    with pytest.raises(StoreError):
        new_record(loaded)
    with pytest.raises(StoreError):
        export_backup(loaded)


def test_backup_restore_matches_every_event_and_prevents_overwrite(store, tmp_path):
    record = new_record(store)
    decision(store, revision(store, record))
    raw = export_backup(store)
    assert verify_backup(raw) == {"verified": True, "records": 1, "events": 3, "message": "已在独立临时目录恢复并通过完整性校验；当前数据未修改。"}
    restored = restore_backup(raw, tmp_path / "restored")
    assert restored.records == store.records
    assert restored.proposals == store.proposals
    for original, copy in zip(store.files, restored.files, strict=True):
        assert original.read_bytes() == copy.read_bytes()
    with pytest.raises(StoreError, match="不允许覆盖"):
        restore_backup(raw, store.root)


def make_archive(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, raw in files.items():
            archive.writestr(name, raw)
        archive.writestr("manifest.json", json.dumps({"format": 1, "files": {name: digest(raw) for name, raw in files.items()}}))
    return out.getvalue()


@pytest.mark.parametrize("filename", ["../secret.md", "events/../../secret.md", "C:/secret.md", "events\\evil.md", "/events/evil.md"])
def test_backup_path_traversal_rejected(filename):
    with pytest.raises(StoreError, match="备份校验失败"):
        validate_archive(make_archive({filename: b"bad"}))


def test_backup_checksum_and_history_validation(store, tmp_path):
    new_record(store)
    raw = export_backup(store)
    archive = zipfile.ZipFile(io.BytesIO(raw))
    changed = io.BytesIO()
    with zipfile.ZipFile(changed, "w") as target:
        for name in archive.namelist():
            target.writestr(name, archive.read(name) + (b"changed" if name.endswith(".md") else b""))
    with pytest.raises(StoreError):
        verify_backup(changed.getvalue())
    with pytest.raises(StoreError):
        restore_backup(make_archive({"events/bad.md": b"malformed"}), tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


@pytest.fixture
def client(tmp_path):
    public = tmp_path / "public"
    public.mkdir()
    (public / "index.html").write_text("<html>test fixture</html>")
    app = create_app(tmp_path / "api-data", public)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        csrf = client.get("/api/session").json()["csrf_token"]
        client.headers["X-CSRF-Token"] = csrf
        yield client


def test_api_create_filter_report_revision(client):
    payload = {"request_id": str(uuid4()), "text": "虚构样例：午餐吃了米饭", "date": "2026-10-23", "category": "diet"}
    saved = client.post("/api/records", json=payload)
    assert saved.status_code == 200
    entry = saved.json()["record"]
    assert client.post("/api/records", json=payload).json() == saved.json()
    assert len(client.get("/api/records?q=米饭&category=diet&day=2026-10-23").json()["records"]) == 1
    assert not client.get("/api/records?q=不存在").json()["records"]
    task = {**payload, "request_id": str(uuid4()), "kind": "task", "text": "计划散步", "category": "exercise"}
    client.post("/api/records", json=task)
    report = client.get("/api/reports/daily?day=2026-10-23").json()
    assert report["tasks"][0]["text"] == "计划散步"
    exercise = next(g for g in report["groups"] if g["category"] == "exercise")
    assert exercise["state"] == "unknown"
    assert not exercise["records"]
    assert next(g for g in report["groups"] if g["category"] == "diet")["records"][0]["id"] == entry["id"]
    response = client.post(f'/api/records/{entry["id"]}/revisions', json={"request_id": str(uuid4()), "expected_version": 1, "text": "更正：面条", "date": "2026-10-23", "category": "diet", "reason": "修正"})
    proposal = response.json()["proposal"]
    assert client.get(f'/api/records/{entry["id"]}').json()["record"]["text"] == payload["text"]
    assert client.post(f'/api/proposals/{proposal["id"]}/decision', json={"request_id": str(uuid4()), "decision": "accept"}).status_code == 200
    assert len(client.get(f'/api/records/{entry["id"]}').json()["history"]) == 2


def test_local_security_csrf_and_private_paths(client):
    assert client.get("/").status_code == 200
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/records", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/session", headers={"Origin": "null"}).status_code == 403
    assert client.get("/api/records", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert client.post("/api/backups/export", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    client.cookies.clear()
    assert client.post("/api/backups/export").status_code == 403
    for path in ["/personal/USER_PROFILE.md", "/docs/REQUIREMENTS.md", "/data/events", "/.env", "/AGENTS.md", "/assets/../../personal/USER_PROFILE.md"]:
        assert client.get(path).status_code == 404


def test_api_backup_verification_and_corruption(client):
    raw = client.post("/api/backups/export")
    assert raw.status_code == 200
    assert client.post("/api/backups/verify", content=raw.content).json()["verified"]
    assert client.post("/api/backups/verify", content=b"bad zip").status_code == 422
    store = client.app.state.store
    (store.events_dir / "bad.md").write_text("broken")
    assert not client.get("/api/status").json()["storage"]["healthy"]
    assert client.get("/api/records").status_code == 503
    assert client.get("/api/reports/daily").status_code == 503


def test_model_status_and_invalid_inputs(client):
    assert client.get("/api/status").json()["model"]["status"] == "not_configured"
    assert client.get("/api/records?day=garbage").status_code == 422
    assert client.get("/api/records?category=unknown").status_code == 422
    assert client.post("/api/records", json={"request_id": str(uuid4()), "text": " ", "date": "2026-10-23"}).status_code == 422


def test_chinese_dates_in_shanghai():
    today = datetime.now(TZ).date()
    assert parse_day("今天") == today
    assert parse_day("昨天") == today - timedelta(days=1)
    assert parse_day("明天") == today + timedelta(days=1)
    assert str(parse_day("2026年10月23日")) == "2026-10-23"


def test_occupied_port_has_clear_error(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]
        result = subprocess.run([sys.executable, "-m", "personalai", "--port", str(port), "--data-dir", str(tmp_path / "unused")], capture_output=True, text=True, encoding="utf-8", errors="replace", env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}, timeout=15)
    assert result.returncode == 1
    assert "已被占用" in result.stderr
    assert not (tmp_path / "unused").exists()
