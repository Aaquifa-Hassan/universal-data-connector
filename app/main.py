
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.routers import health, data
from app.utils.logging import configure_logging
from app.services.rate_limiter import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

configure_logging()

app = FastAPI(title="Universal Data Connector")

# --- Rate limiting setup ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")

# --- Core routers ---
app.include_router(health.router)
app.include_router(data.router)

from app.routers import llm
app.include_router(llm.router)

from app.routers import export
app.include_router(export.router)

# --- Bonus feature routers ---
from app.routers import cache_router
app.include_router(cache_router.router)

from app.routers import stream
app.include_router(stream.router)

from app.routers import webhooks
app.include_router(webhooks.router)
