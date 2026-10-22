"""FastAPI application entry point: ``uvicorn app.main:app`` from the ``backend`` folder."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.config import get_settings, load_rule_config
from app.core.errors import AppError
from app.rules.loader import load_ruleset

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

# Fail fast on a malformed rule configuration instead of at the first processing job.
_ruleset = load_ruleset(load_rule_config(settings.rule_config_path))
log.info(
    "Loaded rule configuration version %s: %d rules (%d executable)",
    _ruleset.version, len(_ruleset.rules), len(_ruleset.executable),
)

app = FastAPI(
    title=settings.app_name,
    version=settings.api_version,
    description="T-number and Site ID derivation service. Data is processed locally and kept in memory only.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.message, "details": exc.details})


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_: Request, exc: RequestValidationError):
    details = [f"{'.'.join(str(p) for p in e.get('loc', [])[1:])}: {e.get('msg')}" for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": "invalid_request", "message": "The request is invalid.", "details": details})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):
    log.error("Unhandled error: %s", type(exc).__name__)
    log.debug("Unhandled error traceback", exc_info=exc)
    return JSONResponse(status_code=500, content={"error": "internal_error", "message": "An internal error occurred.", "details": []})


app.include_router(router)


@app.get("/", include_in_schema=False)
def root():
    return {"service": settings.app_name, "health": "/api/health", "api_docs": "/docs"}
