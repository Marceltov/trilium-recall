"""HTTP + MCP front of the recall engine, and the background sync loop.

Routes: GET /health (open), POST /recall (Claude Code hook), /mcp (MCP `recall` tool). The static
Bearer token is RECALL_LOGIN_PASSWORD. With RECALL_BASE_URL set, /mcp also takes OAuth tokens from a
login with that password (mcp-login-oauth) and the OAuth routes are open; /recall stays static-only.
"""

import asyncio
import contextlib
import hmac
import json
import logging
import os
import sys
import time

import anyio
import httpx
from fastmcp import FastMCP
from fastmcp.server.auth import OAuthProvider
from mcp_login_oauth import LoginField, LoginOAuthProvider, LoginRejected, build_store
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from config import DEFAULT_TOOL_DESCRIPTION, Config, ConfigError, load_config
from embed import Embedder
from index import Index
from rank import Hit, RankParams, rank
from render import fit, render
from sessions import SessionMemory
from skip import should_skip
from sync import Syncer
from trilium import EtapiClient

log = logging.getLogger("recall")

VERSION = os.environ.get("APP_VERSION", "dev")
NOTHING = "Nothing relevant in the notes for this query."


class UnknownInstance(ValueError):
    pass


class Engine:
    def __init__(self, config: Config, embedder: Embedder,
                 transports: dict[str, httpx.BaseTransport] | None = None):
        self.config = config
        self.embedder = embedder
        self.params = RankParams()
        self.sessions = SessionMemory()
        self.syncers: dict[str, Syncer] = {}
        self.ready: dict[str, bool] = {}
        for inst in config.instances:
            index = Index(config.data_dir / f"{inst.name}.db", embedder.name, embedder.dim)
            client = EtapiClient(inst.url, inst.etapi_token, transport=(transports or {}).get(inst.name))
            self.syncers[inst.name] = Syncer(inst.name, client, index, embedder)
            self.ready[inst.name] = False

    # -- search ------------------------------------------------------------------------------

    def recall(self, query: str, cwd: str | None = None, limit: int = 3, instance: str | None = None) -> list[Hit]:
        if instance and instance not in self.syncers:
            raise UnknownInstance(f"Unknown instance {instance!r}. Configured: {', '.join(self.syncers)}.")
        names = [instance] if instance else list(self.syncers)
        hits: list[Hit] = []
        for name in names:
            if name in self.syncers:
                hits += rank(name, self.syncers[name].index, self.embedder, query, cwd, self.params, limit)
        return sorted(hits, key=lambda h: -h.score)[:limit]

    # -- sync --------------------------------------------------------------------------------

    def _first_sync(self, name: str) -> None:
        syncer = self.syncers[name]
        index = syncer.index
        if index.needs_rebuild() or index.counts()[0] == 0:
            syncer.full_build()
        else:
            syncer.reconcile()
        if syncer.status.last_error is None:
            self.ready[name] = True

    def sync_all_once(self) -> None:
        for name in self.syncers:
            self._first_sync(name)

    def poll_once(self) -> None:
        for name, syncer in self.syncers.items():
            if not self.ready[name]:
                self._first_sync(name)
            else:
                syncer.poll()

    def reconcile_once(self) -> None:
        for syncer in self.syncers.values():
            syncer.reconcile()

    async def run_sync_forever(self) -> None:
        last_reconcile = time.monotonic()
        try:
            await anyio.to_thread.run_sync(self.sync_all_once)
        except Exception:  # an instance not marked ready is retried by poll_once below
            log.exception("first sync failed")
        while True:
            await asyncio.sleep(self.config.poll_seconds)
            try:
                if time.monotonic() - last_reconcile >= self.config.reconcile_seconds:
                    await anyio.to_thread.run_sync(self.reconcile_once)
                    last_reconcile = time.monotonic()
                else:
                    await anyio.to_thread.run_sync(self.poll_once)
            except Exception:  # never let the loop die; Syncer already records ETAPI errors
                log.exception("sync loop iteration failed")

    def health(self) -> dict:
        instances = {}
        for name, syncer in self.syncers.items():
            notes, sections = syncer.index.counts()
            st = syncer.status
            instances[name] = {"notes": notes, "sections": sections,
                               "last_ok": st.last_ok.isoformat() if st.last_ok else None,
                               "last_error": st.last_error}
        if any(v["last_error"] for v in instances.values()):
            status = "degraded"
        elif not all(self.ready.values()):
            status = "starting"
        else:
            status = "ok"
        return {"status": status, "instances": instances, "version": VERSION}


# -- auth ---------------------------------------------------------------------------------------

class BearerGate:
    """Pure ASGI (streamable HTTP must not be buffered). Without OAuth every path but /health needs the
    static token; with OAuth only /recall does, and FastMCP's auth guards /mcp."""

    def __init__(self, app, token: str, oauth: bool = False):
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.oauth = oauth

    def _gated(self, path: str) -> bool:
        return path == "/recall" if self.oauth else path != "/health"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and self._gated(scope["path"]):
            given = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(given, self.expected):
                response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


# -- app ----------------------------------------------------------------------------------------

def build_oauth_provider(config: Config, **overrides) -> LoginOAuthProvider:
    """OAuth login for /mcp whose password is RECALL_LOGIN_PASSWORD; the same password also works as a
    static Bearer token. Logins carry no grant: recall has nothing per client to hand to its tools. The
    store's key is the password, so changing it logs every client out."""
    expected = config.password.encode()

    async def check_login(form) -> dict:
        if hmac.compare_digest(form["password"].encode(), expected):
            return {}
        raise LoginRejected("Wrong password.")

    async def verify_static(token: str) -> dict | None:
        return {} if hmac.compare_digest(token.encode(), expected) else None

    args = dict(base_url=config.base_url,
                store=build_store(config.data_dir / "oauth", secret=config.password, salt="trilium-recall-oauth"),
                service_name="Wiki recall",
                fields=[LoginField("password", "Recall password", type="password", required=True)],
                check_login=check_login, verify_static=verify_static, token_prefix="rcl_")
    return LoginOAuthProvider(**{**args, **overrides})


def build_mcp(engine: Engine, auth: OAuthProvider | None = None) -> FastMCP:
    mcp = FastMCP("trilium-recall", auth=auth, instructions=engine.config.instructions)

    @mcp.tool(description=engine.config.tool_description)
    async def recall(query: str, limit: int = 3, instance: str | None = None) -> str:
        try:
            hits = await anyio.to_thread.run_sync(
                lambda: engine.recall(query, None, max(1, min(limit, 3)), instance))
        except UnknownInstance as e:
            return str(e)
        return render(hits) or NOTHING

    return mcp


def build_app(engine: Engine, background: bool = True, oauth_overrides: dict | None = None) -> BearerGate:
    """`oauth_overrides` passes provider arguments through, for tests (e.g. failed_login_delay=0)."""
    config = engine.config
    auth = build_oauth_provider(config, **(oauth_overrides or {})) if config.base_url else None
    mcp_app = build_mcp(engine, auth).http_app(path="/mcp", host_origin_protection=False)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse(engine.health())

    async def recall(request: Request) -> JSONResponse:
        try:
            body = json.loads(await request.body())
            prompt = body["prompt"]
            session_id, cwd = body.get("session_id"), body.get("cwd")
            if not isinstance(prompt, str) or not isinstance(session_id, str | None) or not isinstance(cwd, str | None):
                raise TypeError
        except (ValueError, KeyError, TypeError, AttributeError):
            return JSONResponse({"error": "body must be {prompt: str, session_id?: str, cwd?: str}"}, status_code=400)
        if reason := should_skip(prompt):
            return JSONResponse({"context": "", "skipped": reason})
        started = time.perf_counter()
        hits = await anyio.to_thread.run_sync(lambda: engine.recall(prompt, cwd))
        unseen = set(engine.sessions.peek(session_id, [h.note_id for h in hits]))
        # Remember only what the token budget let through; a dropped hit may come next time.
        text, shown = fit([h for h in hits if h.note_id in unseen])
        engine.sessions.record(session_id, [h.note_id for h in shown])
        ms = round((time.perf_counter() - started) * 1000, 1)
        log.info("recall hits=%d ms=%s", len(shown), ms)  # never log the prompt
        return JSONResponse({"context": text, "hits": [h.note_id for h in shown], "ms": ms})

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp_app.lifespan(app):
            task = asyncio.create_task(engine.run_sync_forever()) if background else None
            try:
                yield
            finally:
                if task:
                    task.cancel()

    app = Starlette(routes=[Route("/health", health), Route("/recall", recall, methods=["POST"]),
                            Mount("/", app=mcp_app)], lifespan=lifespan)
    return BearerGate(app, config.password, oauth=auth is not None)


def build_error_app(message: str) -> Starlette:
    """Started with a broken configuration: say what is wrong instead of dying silently."""
    mcp = FastMCP("trilium-recall")

    @mcp.tool(description=DEFAULT_TOOL_DESCRIPTION)
    def recall(query: str, limit: int = 3, instance: str | None = None) -> str:
        return f"The recall engine is not running: {message}"

    mcp_app = mcp.http_app(path="/mcp", host_origin_protection=False)

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "error", "error": message}, status_code=503)

    async def unavailable(_: Request) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=503)

    return Starlette(routes=[Route("/health", health), Route("/recall", unavailable, methods=["POST"]),
                            Mount("/", app=mcp_app)], lifespan=mcp_app.lifespan)


def main() -> None:
    import uvicorn

    from embed import OnnxEmbedder

    logging.basicConfig(level=os.environ.get("RECALL_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per ETAPI call drowns the log
    try:
        config = load_config(os.environ)
        if not (config.model_dir / "model.onnx").exists():
            raise ConfigError(f"embedding model not found in {config.model_dir}")
        app = build_app(Engine(config, OnnxEmbedder(config.model_dir)))
        host, port = config.host, config.port
    except (ConfigError, OSError) as e:
        log.error("startup failed: %s", e)
        app = build_error_app(str(e))
        host, port = os.environ.get("RECALL_HOST", "0.0.0.0"), int(os.environ.get("RECALL_PORT", "8082") or 8082)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    sys.exit(main())
