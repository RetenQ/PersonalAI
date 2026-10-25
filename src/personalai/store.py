"""Append-only, checksummed Markdown transactions; indexes are disposable."""
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

import portalocker

from .models import CreateRecord, Decision, Event, Proposal, ProposeRevision, Record, RecordFields, now
from .tracking_models import Entity, EventV2
from .extensions import PluginEntity, EventV3


class StoreError(Exception):
    def __init__(self, message: str, status: int = 409):
        self.message, self.status = message, status
        super().__init__(message)


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encode_event(event: Event) -> bytes:
    payload = event.model_dump(mode="json")
    envelope = {"checksum": digest(canonical(payload)), "event": payload}
    readable = []
    for record in event.records:
        readable.append(f"## 记录 {record.id} · 修订 {record.version}\n\n日期：{record.date} · 类型：{record.kind} · 来源：{record.source}\n\n{record.text}")
    for proposal in event.proposals:
        readable.append(f"## 确认事项 {proposal.id}\n\n状态：{proposal.status}\n\n理由：{proposal.reason}\n\n拟保存内容：\n\n{proposal.after.text}")
    for entity in getattr(event, 'entities', []):
        readable.append(f"## {entity.kind} {entity.id} · 修订 {entity.version}\n\n" + json.dumps(entity.data, ensure_ascii=False, indent=2))
    body = "\n\n".join(readable)
    return ("---\n" + json.dumps(envelope, ensure_ascii=False, indent=2) + "\n---\n\n# PersonalAI 修订日志\n\n" + body + "\n").encode("utf-8")


def decode_event(data: bytes) -> Event:
    text = data.decode("utf-8")
    if not text.startswith("---\n"):
        raise ValueError("missing metadata")
    envelope = json.loads(text.split("\n---\n", 1)[0][4:])
    if digest(canonical(envelope["event"])) != envelope["checksum"]:
        raise ValueError("checksum mismatch")
    event_type = {1: Event, 2: EventV2, 3: EventV3}.get(envelope['event'].get('schema_version', 1))
    if event_type is None:
        raise ValueError('unsupported event version')
    event = event_type.model_validate(envelope["event"])
    if encode_event(event) != data:
        raise ValueError("content changed or noncanonical")
    return event


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.events_dir = self.root / "events"
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.mutex = threading.RLock()
        self.user_files_error = ''
        self.rebuild_user_files()

    def _sync_user_files(self):
        from .user_files import publish
        if self.errors:
            self.user_files_error = '原始记录校验失败，已暂停整理可读资料。请先恢复有效记录。'
            return
        try:
            publish(self)
            self.user_files_error = ''
        except OSError:
            # The authoritative event may already be durable: never report it as lost.
            self.user_files_error = '原始记录已保留，但可读资料整理失败。请检查目录权限、空间或链接路径，再重新整理。'

    def rebuild_user_files(self):
        with self.mutex, portalocker.Lock(str(self.root / '.write.lock'), timeout=10):
            self.reload()
            self._sync_user_files()
            return self.user_files_status()

    def user_files_status(self):
        from .user_files import status
        return status(self)

    def reload(self):
        with self.mutex:
            self.records: dict[str, Record] = {}
            self.proposals: dict[str, Proposal] = {}
            self.history: dict[str, list[Record]] = {}
            self.entities: dict[str, Entity] = {}
            self.entity_history: dict[str, list[Entity]] = {}
            self.requests: dict[str, Event] = {}
            self.files: list[Path] = []
            self.errors: list[str] = []
            self.sequence = 0
            self.last_hash = None
            for path in sorted(self.events_dir.glob("*.md")):
                try:
                    if path.is_symlink():
                        raise ValueError("symlink is not supported")
                    raw = path.read_bytes()
                    event = decode_event(raw)
                    if event.sequence != self.sequence + 1 or event.previous_hash != self.last_hash:
                        raise ValueError("broken history chain")
                    if path.name != f"{event.sequence:012d}_{event.request_id}.md":
                        raise ValueError("unexpected filename")
                    if str(event.request_id) in self.requests:
                        raise ValueError("duplicate request")
                    for record in event.records:
                        previous = self.records.get(str(record.id))
                        if record.version != (previous.version + 1 if previous else 1):
                            raise ValueError("invalid revision")
                        if record.previous_version != (previous.version if previous else None):
                            raise ValueError("invalid revision reference")
                    for record in event.records:
                        key = str(record.id)
                        self.records[key] = record
                        self.history.setdefault(key, []).append(record)
                    for proposal in event.proposals:
                        self.proposals[str(proposal.id)] = proposal
                    for entity in getattr(event, 'entities', []):
                        previous = self.entities.get(entity.id)
                        if entity.version != (previous.version + 1 if previous else 1) or (previous and entity.kind != previous.kind):
                            raise ValueError('invalid entity revision')
                        self.entities[entity.id] = entity
                        self.entity_history.setdefault(entity.id, []).append(entity)
                    self.sequence = event.sequence
                    self.last_hash = digest(raw)
                    self.requests[str(event.request_id)] = event
                    self.files.append(path)
                except (OSError, ValueError, KeyError, TypeError):
                    self.errors.append(f"记录文件无法校验：{path.name}。已暂停读取与写入，请从已验证备份恢复。")
                    break

    def require_healthy(self):
        if self.errors:
            raise StoreError(self.errors[0], 503)

    def get(self, record_id: str) -> Record:
        self.require_healthy()
        record = self.records.get(record_id)
        if not record:
            raise StoreError("未找到这条记录", 404)
        return record

    def transaction(self, request_id, operation: str, payload: dict, prepare, *, extension=False):
        fingerprint = digest(canonical({"operation": operation, "payload": payload}))
        with self.mutex, portalocker.Lock(str(self.root / ".write.lock"), timeout=10):
            self.reload()
            self.require_healthy()
            previous = self.requests.get(str(request_id))
            if previous:
                if previous.fingerprint != fingerprint:
                    raise StoreError("同一个请求编号对应了不同内容，请刷新后重新提交。")
                self._sync_user_files()
                return previous.result
            prepared = prepare()
            records, proposals, result = prepared[:3]
            event_type = (EventV3 if any(isinstance(e, PluginEntity) for e in prepared[3]) else EventV2) if extension else Event
            extra = {'entities': prepared[3]} if extension else {}
            event = event_type(sequence=self.sequence + 1, request_id=request_id,
                          fingerprint=fingerprint, timestamp=now(), previous_hash=self.last_hash,
                          records=records, proposals=proposals, result=result, **extra)
            raw = encode_event(event)
            target = self.events_dir / f"{event.sequence:012d}_{request_id}.md"
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.events_dir, suffix=".tmp", delete=False) as handle:
                    temp = Path(handle.name)
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp, target)
            except OSError as exc:
                raise StoreError("保存失败，未确认落盘。请保留输入并重试；相同请求不会重复保存。", 503) from exc
            finally:
                if temp and temp.exists():
                    temp.unlink(missing_ok=True)
            self.reload()
            self.require_healthy()
            self._sync_user_files()
            return result

    def create(self, request: CreateRecord):
        def prepare():
            record = Record(**request.model_dump(exclude={"request_id"}), id=uuid4(), version=1,
                            created_at=now(), updated_at=now())
            return [record], [], {"record": record.model_dump(mode="json")}
        return self.transaction(request.request_id, "create", request.model_dump(mode="json"), prepare)

    def propose_revision(self, record_id: str, request: ProposeRevision):
        def prepare():
            before = self.get(record_id)
            if before.version != request.expected_version:
                raise StoreError("记录已变化，请刷新并基于最新版本重新提出修改。")
            after = RecordFields(**request.model_dump(include={"text", "date", "category", "status"}))
            proposal = Proposal(id=uuid4(), action="revise", target_id=before.id,
                                expected_version=before.version, before=before, after=after,
                                reason=request.reason, created_at=now())
            return [], [proposal], {"proposal": proposal.model_dump(mode="json")}
        return self.transaction(request.request_id, f"revise:{record_id}", request.model_dump(mode="json"), prepare)

    def propose_intent(self, request_id, fields: RecordFields, action: str, reason: str):
        """For a future validated gateway; always proposes, never creates a task."""
        def prepare():
            proposal = Proposal(id=uuid4(), action=action, after=fields, reason=reason, created_at=now())
            return [], [proposal], {"proposal": proposal.model_dump(mode="json")}
        return self.transaction(request_id, "intent", {"fields": fields.model_dump(mode="json"), "action": action, "reason": reason}, prepare)

    def decide(self, proposal_id: str, request: Decision):
        def prepare():
            proposal = self.proposals.get(proposal_id)
            if not proposal:
                raise StoreError("未找到这个确认事项", 404)
            if proposal.status != "pending":
                raise StoreError("这个事项已经处理，请刷新查看结果。")
            records = []
            updated = proposal.model_copy(deep=True)
            if request.decision == "accept":
                if proposal.action == "revise":
                    before = self.get(str(proposal.target_id))
                    if before.version != proposal.expected_version:
                        raise StoreError("原记录已更新，这个修改提案已过期；请拒绝旧提案并重新提出。")
                    record = Record(**{
                        **before.model_dump(), **proposal.after.model_dump(),
                        "version": before.version + 1, "previous_version": before.version, "updated_at": now(),
                    })
                else:
                    record = Record(**proposal.after.model_dump(), id=uuid4(),
                                    kind="task" if proposal.action == "create_task" else "idea",
                                    version=1, created_at=now(), updated_at=now(), source="confirmed_suggestion")
                records.append(record)
                updated.result_id = record.id
                updated.status = "accepted"
            else:
                updated.status = "rejected"
            updated.decided_at = now()
            result = {"proposal": updated.model_dump(mode="json"), "record": records[0].model_dump(mode="json") if records else None}
            return records, [updated], result
        return self.transaction(request.request_id, f"decide:{proposal_id}", request.model_dump(mode="json"), prepare)
