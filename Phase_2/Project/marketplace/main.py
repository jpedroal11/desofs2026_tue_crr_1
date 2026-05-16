import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import get_settings
from core.dependencies import engine
from models.models import Base
from routers import auth, users, products, orders, images

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup (dev convenience — production uses
    # database/script.sql or a future Alembic migration).
    Base.metadata.create_all(bind=engine)

    # Ensure upload directory exists with restricted permissions
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(upload_dir, 0o750)
    except (OSError, NotImplementedError):
        # Windows / non-POSIX filesystems may not support chmod — ignore
        pass

    yield


app = FastAPI(
    title="Marketplace API",
    description="A RESTful marketplace API with Users, Products, and Orders.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
)

# CORS — origins come from settings, comma-separated. In dev set
# CORS_ALLOW_ORIGINS="http://localhost:3000". Never combine "*" with
# allow_credentials=True (browsers reject that anyway).
_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(images.router)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Marketplace API is running"}
