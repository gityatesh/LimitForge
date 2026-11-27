"""Creates the FastAPI app and plugs in every router under /api/v1."""
import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.errors import register_error_handlers
from app.routers import admin, auth, profile, rules, applications

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Finora API",
    version="2.0.0",
    description="Finora: credit decision and risk management platform (academic prototype, synthetic data only).",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)

api = APIRouter(prefix="/api/v1")
for module in (auth, admin, profile, rules, applications):
    api.include_router(module.router)
app.include_router(api)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}