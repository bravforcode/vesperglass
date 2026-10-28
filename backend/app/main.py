"""
Stocknomist Main FastAPI Application.
Integrates API routers, CORS middleware, and static hosting of compiled Vite React SPA
with HTML5 SPA fallback routing.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router as api_router, get_screener_service
from backend.app.config import settings

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for initialization and cleanup."""
    logger.info("Initializing Stocknomist Quant Screener Engine...")
    try:
        # Pre-warm screener service
        service = get_screener_service()
        logger.info(f"Screener Service ready. Universe size: {len(service.cache.get_universe_constituents())}")
    except Exception as e:
        logger.error(f"Error during screener initialization: {e}")
    yield
    logger.info("Shutting down Stocknomist...")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Stocknomist: Tokenomist.ai-inspired Quantitative US Equity Swing Trading Screener",
    lifespan=lifespan,
)

# -----------------------------------------------------------------------------
# CORS Middleware
# -----------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Root-level Health Check (Docker HEALTHCHECK & Caddy bypass compatibility)
# -----------------------------------------------------------------------------
@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
def root_health():
    """Uptime health check probe."""
    return {
        "status": "ok",
        "version": settings.APP_VERSION,
        "cache_timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# -----------------------------------------------------------------------------
# Mount API Router (/api)
# -----------------------------------------------------------------------------
app.include_router(api_router, prefix="/api", tags=["Stocknomist API"])


# -----------------------------------------------------------------------------
# Static Frontend SPA Mount & Fallback Routing
# -----------------------------------------------------------------------------
class ImmutableStaticFiles(StaticFiles):
    """Static asset handler injecting immutable Cache-Control headers for Vite hashed bundles."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


dist_dir = settings.FRONTEND_DIST

if dist_dir.exists() and (dist_dir / "index.html").exists():
    assets_dir = dist_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", ImmutableStaticFiles(directory=str(assets_dir)), name="assets")

    @app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def serve_spa(full_path: str):
        # Prevent intercepting /api or /health routes
        if full_path.startswith("api/") or full_path == "health" or full_path.startswith("health/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # Block traversal patterns, NTFS alternate data streams (::$DATA), colons, and sensitive OS file probes
        path_lower = full_path.lower()
        forbidden_probes = ["etc/", "passwd", "windows", "system32", "proc/", "sys/"]
        if ".." in full_path or ":" in full_path or "\0" in full_path or any(probe in path_lower for probe in forbidden_probes):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        # Prevent path traversal outside dist_dir (CWE-22)
        try:
            target_file = (dist_dir / full_path).resolve()
            if not target_file.is_relative_to(dist_dir.resolve()):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        except (ValueError, Exception):
            return JSONResponse(status_code=404, content={"detail": "Not found"})

        if target_file.is_file():
            # Immutable caching for static assets
            headers = {}
            if full_path.startswith("assets/"):
                headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return FileResponse(str(target_file), headers=headers)

        # Fallback to SPA index.html for client-side routing
        return FileResponse(str(dist_dir / "index.html"))
else:
    @app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    def root_fallback():
        return {
            "message": "Stocknomist API active. Frontend assets not yet built.",
            "version": settings.APP_VERSION,
            "docs": "/docs",
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
