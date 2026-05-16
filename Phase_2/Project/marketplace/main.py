from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
from pathlib import Path

from core.dependencies import engine
from models.models import Base
from routers import auth, users, products, orders, images


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create all tables on startup
    Base.metadata.create_all(bind=engine)
    # Ensure upload directory exists with restricted permissions
    upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(upload_dir, 0o750)
    yield


app = FastAPI(
    title="Marketplace API",
    description="A RESTful marketplace API with Users, Products, and Orders.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(products.router)
app.include_router(orders.router)
app.include_router(images.router)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "message": "Marketplace API is running"}
