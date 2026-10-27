from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import init_probe_pool, router as api_router, shutdown_probe_pool
from .config import Settings, get_settings
from .events import EventBus
from .manager import JobManager
from .ratelimit import RateLimiter
from .store import Store

log = logging.getLogger("turbotube")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(handler)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.prepare_dirs()
    _configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        init_probe_pool(max_workers=min(8, getattr(settings, "max_concurrent_downloads", 4) + 2))
        bus = EventBus()
        bus.attach_loop(loop)
        store = Store(settings.data_path / "turbotube.db")
        manager = JobManager(settings, store, bus)
        app.state.settings = settings
        app.state.bus = bus
        app.state.store = store
        app.state.manager = manager
        log.info("TurboTube %s ready - downloads: %s", __version__, settings.download_path)
        if settings.auto_resume:
            resumed = manager.resume_interrupted()
            if resumed:
                log.info("Auto-resumed %s item(s)", resumed)
        try:
            yield
        finally:
            shutdown_future = loop.run_in_executor(None, manager.shutdown)
            try:
                await asyncio.wait_for(asyncio.shield(shutdown_future), timeout=10)
            except asyncio.TimeoutError:
                log.warning("Shutdown timed out — forcing exit")
            shutdown_probe_pool()
            store.close()

    app = FastAPI(
        title="TurboTube",
        version=__version__,
        description="High-performance YouTube downloader with parallel playlists and SSE progress.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=False,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    # Rate limiting
    rate_limiter = RateLimiter(max_requests=settings.rate_limit_rpm) if getattr(settings, "rate_limit_rpm", 0) > 0 else None

    @app.middleware("http")
    async def security_and_auth(request: Request, call_next):
        path = request.url.path
        if rate_limiter and path.startswith("/api") and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            if not rate_limiter.allow(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — try again shortly"},
                )

        if settings.api_key and path.startswith("/api") and path != "/api/health":
            supplied = (
                request.headers.get("x-api-key")
                or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                or request.query_params.get("key", "")
            )
            if not supplied or not hmac.compare_digest(supplied, settings.api_key):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or missing API key"},
                    headers={"WWW-Authenticate": "Bearer"},
                )

        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not path.startswith(("/docs", "/openapi.json", "/redoc")):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' https: data:; media-src 'self' https: blob:; "
                "connect-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'",
            )
        return response

    app.include_router(api_router)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")
    else:  # pragma: no cover - defensive
        @app.get("/")
        async def fallback() -> dict[str, str]:
            return {"app": "TurboTube", "message": "UI assets are missing"}

    return app


app = create_app()
