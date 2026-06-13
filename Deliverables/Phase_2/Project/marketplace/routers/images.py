from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from core.dependencies import get_db
from middleware.auth import get_current_user
from core import image_service
from models.models import Product, ProductImage, User
from schemas.schemas import ProductImageResponse
from services import image_use_case

router = APIRouter(tags=["Images"])


@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_product_image(
    product_id: UUID,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload an image for a product. Only the product owner (seller) can upload."""
    
    # ── Filename safety check ────────────────────────────────────────────
    try:
        image_service.validate_upload_filename(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # ── Read content ──────────────────────────────────────────────────────
    content = file.file.read()

    # ── File size limit (10MB) before any other processing ────────────────
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=422,
            detail="File exceeds maximum allowed size of 10 MB"
        )
        
    return image_use_case.upload_product_image(
        db=db,
        product_id=product_id,
        current_user=current_user,
        file_content=content,
        filename=file.filename,
        content_type=file.content_type,
    )


@router.get("/images/{filename}")
def serve_image(filename: str):
    """Serve an uploaded image by its UUID filename."""
    # ── Path-safety validation ────────────────────────────────────────────
    try:
        safe_path = image_service.build_safe_path(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not safe_path.is_file():
        raise HTTPException(status_code=404, detail="Image not found")

    # Determine media type from extension
    suffix = safe_path.suffix.lower()
    ext_to_mime = {v: k for k, v in image_service.MIME_TO_EXTENSION.items()}
    media_type = ext_to_mime.get(suffix, "application/octet-stream")

    return FileResponse(safe_path, media_type=media_type)


@router.get(
    "/products/{product_id}/images",
    response_model=List[ProductImageResponse],
)
def list_product_images(product_id: UUID, db: Session = Depends(get_db)):
    """List all images for a product."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return (
        db.query(ProductImage)
        .filter(ProductImage.product_id == product_id)
        .all()
    )


@router.delete(
    "/products/{product_id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_product_image(
    product_id: UUID,
    image_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a product image. Only the product owner can delete."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not allowed to delete images for this product"
        )

    db_image = (
        db.query(ProductImage)
        .filter(
            ProductImage.id == image_id,
            ProductImage.product_id == product_id,
        )
        .first()
    )
    if not db_image:
        raise HTTPException(status_code=404, detail="Image not found")

    # ── Remove file from disk ─────────────────────────────────────────────
    try:
        file_path = image_service.build_safe_path(db_image.filename)
        image_service.delete_file(file_path)
    except (ValueError, OSError):
        pass  # File may already be gone; still remove DB record

    db.delete(db_image)
    db.commit()
