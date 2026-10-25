from datetime import date, datetime, timedelta
from contextlib import asynccontextmanager
import secrets
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from portalocker.exceptions import LockException

from .backup import export_backup, verify_backup
from .model_gateway import UnconfiguredModel
from .models import CATEGORIES, TZ, CreateRecord, Decision, ProposeRevision
from .store import Store, StoreError
from .tracking_routes import register_tracking
from .tracking import TrackingService
from .configuration import ConfigService, register_configuration

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_day(value: str) -> date:
    today = datetime.now(TZ).date()
    aliases = {"今天": today, "今日": today, "昨天": today - timedelta(days=1), "明天": today + timedelta(days=1)}
    if value in aliases:
        return aliases[value]
    try:
        return date.fromisoformat(value.replace("年", "-").replace("月", "-").replace("日", ""))
    except ValueError:
        raise HTTPException(422, "日期请使用 YYYY-MM-DD、今天、昨天或明天。")


def create_app(data_dir: Path | None = None, frontend_dir: Path | None = None, port: int = 8765, enabled_plugins: list[str] | None = None, config_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.plugins.lifecycle('start')
        try:
            yield
        finally:
            app.state.plugins.lifecycle('stop')
    app = FastAPI(title="PersonalAI 本地记录", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    store = Store(data_dir or PROJECT_ROOT / "data")
    app.state.store = store
    app.state.port = port
    app.state.model = UnconfiguredModel()
    csrf = secrets.token_urlsafe(32)
    session = secrets.token_urlsafe(32)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{host}" for host in hosts}

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.headers.get("host", "") not in hosts:
            return JSONResponse({"detail": "仅允许本机地址访问"}, status_code=403)
        origin = request.headers.get("origin")
        if (origin is not None and origin not in origins) or request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "不接受其他网站发起的请求"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), csrf) or not secrets.compare_digest(request.cookies.get("personalai_session", ""), session):
                return JSONResponse({"detail": "会话已失效，请刷新页面后重试"}, status_code=403)
        blocked = app.state.plugins.blocked_path(request.url.path) if hasattr(app.state, 'plugins') else None
        if blocked:
            return JSONResponse({'detail': '该功能插件未启用：' + blocked}, status_code=409)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @app.exception_handler(StoreError)
    async def store_error(request, exc):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.exception_handler(LockException)
    async def lock_error(request, exc):
        return JSONResponse({"detail": "记录正由另一操作使用，请稍后重试；输入内容尚未丢弃。"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({"detail": "输入格式不正确，请检查日期、必填内容和字段范围。"}, status_code=422)

    @app.get("/api/session")
    def get_session():
        response = JSONResponse({"csrf_token": csrf})
        response.set_cookie("personalai_session", session, httponly=True, samesite="strict")
        return response

    @app.get("/api/status")
    def status():
        with store.mutex:
            store.reload()
            config = ConfigService(store).model('goal') if not store.errors else {'enabled': False, 'base_url': ''}
            try:
                model_ready = config['enabled'] and bool(ConfigService(store).key(config, app.state.vault))
            except StoreError:
                # A lost Windows key must not block access to local records or settings.
                model_ready = False
            return {"version": "0.3.0", "timezone": "Asia/Shanghai", "today": datetime.now(TZ).date().isoformat(),
                    "model": {"status": "configured" if model_ready else "not_configured", "message": "目标分析逐次确认；定时分析须单独授权数据范围。输入原文不会自动进行 AI 理解。"},
                    "storage": {"healthy": not store.errors, "errors": store.errors},
                    "user_files": store.user_files_status(),
                    "categories": CATEGORIES}

    @app.post("/api/records")
    def create_record(payload: CreateRecord):
        if payload.kind=='task' and not app.state.plugins.active('tracking'):
            raise StoreError('任务插件未启用。',409)
        return store.create(payload)

    @app.get("/api/records")
    def list_records(day: str | None = None, category: str | None = None,
                     kind: Literal["note", "task", "idea"] | None = None,
                     q: str = Query(default="", max_length=200)):
        target_day = parse_day(day) if day else None
        if category and category not in CATEGORIES:
            raise HTTPException(422, "未知类别")
        with store.mutex:
            store.reload()
            store.require_healthy()
            records = [r for r in store.records.values() if
                       (not target_day or r.date == target_day) and (not category or r.category == category)
                       and (not kind or r.kind == kind) and (not q or q.casefold() in r.text.casefold())]
            return {"records": sorted(records, key=lambda r: (r.date, r.updated_at, str(r.id)), reverse=True)}

    @app.get("/api/records/{record_id}")
    def get_record(record_id: UUID):
        with store.mutex:
            store.reload()
            return {"record": store.get(str(record_id)), "history": store.history[str(record_id)]}

    @app.post("/api/records/{record_id}/revisions")
    def propose(record_id: UUID, payload: ProposeRevision):
        with store.mutex:
            store.reload()
            if store.get(str(record_id)).kind=='task' and not app.state.plugins.active('tracking'):
                raise StoreError('任务插件未启用，历史只读。',409)
        return store.propose_revision(str(record_id), payload)

    @app.get("/api/proposals")
    def proposals():
        with store.mutex:
            store.reload()
            store.require_healthy()
            return {"proposals": sorted(store.proposals.values(), key=lambda p: p.created_at, reverse=True)}

    @app.post("/api/proposals/{proposal_id}/decision")
    def decide(proposal_id: UUID, payload: Decision):
        with store.mutex:
            store.reload(); store.require_healthy()
            proposal=store.proposals.get(str(proposal_id))
            if proposal and payload.decision=='accept' and not app.state.plugins.active('tracking') and (proposal.action=='create_task' or proposal.before and proposal.before.kind=='task'):
                raise StoreError('任务插件未启用，不能接受该修改。',409)
        return store.decide(str(proposal_id), payload)

    @app.get("/api/reports/daily")
    def daily(day: str = "今天"):
        target_day = parse_day(day)
        with store.mutex:
            store.reload()
            store.require_healthy()
            notes = [r for r in store.records.values() if r.date == target_day and r.kind == "note"]
            tasks = [r for r in store.records.values() if r.date == target_day and r.kind == "task"]
            groups = [{"category": category, "label": label,
                       "records": [r for r in notes if r.category == category],
                       "state": "recorded" if any(r.category == category for r in notes) else "unknown"}
                      for category, label in CATEGORIES.items() if category != "uncategorized"]
            return {"date": target_day, "title": "每日事实汇总", "groups": groups,
                    "uncategorized": [r for r in notes if r.category == "uncategorized"], "tasks": tasks,
                    "notice": "仅汇总你记录的内容，未由 AI 核实或分析；计划与事实分开，不根据缺失信息作评价。"}

    @app.post("/api/backups/export")
    def backup():
        raw = export_backup(store)
        verify_backup(raw)
        return Response(raw, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="personalai-{datetime.now(TZ):%Y%m%d-%H%M%S}.zip"'})

    @app.post("/api/backups/verify")
    async def verify(request: Request):
        # Streaming bound avoids buffering an arbitrarily large archive.
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 32 * 1024 * 1024:
                raise HTTPException(413, "本阶段校验上传限 32 MB")
            chunks.append(chunk)
        return verify_backup(b"".join(chunks))

    register_tracking(app, store, parse_day)
    register_configuration(app, store)
    from .scheduling import register_scheduling
    register_scheduling(app, store)
    from .plugins import register_plugins
    from .runtime import DEFAULT_PLUGINS
    register_plugins(app, store, DEFAULT_PLUGINS if enabled_plugins is None else enabled_plugins, config_path)
    from .integrations import register_integrations
    from .quick_entry import register_quick_entry
    register_integrations(app, store)
    register_quick_entry(app, store)
    frontend = frontend_dir or PROJECT_ROOT / "frontend" / "dist"
    if (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets", follow_symlink=False), name="assets")

    @app.get("/")
    def index():
        if not (frontend / "index.html").is_file():
            return JSONResponse({"detail": "界面尚未构建，请按使用说明安装并构建前端。"}, status_code=503)
        return FileResponse(frontend / "index.html")

    return app
