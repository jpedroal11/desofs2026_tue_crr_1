from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List

from core.dependencies import get_db, get_current_user
from core import image_service
from models.models import Product, ProductImage, User
from schemas.schemas import ProductImageResponse

router = APIRouter(tags=["Images"])


@router.post(
    "/products/{product_id}/images",
    response_model=ProductImageResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload an image for a product. Only the product owner (seller) can upload."""
    # ── Ownership check ───────────────────────────────────────────────────
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not allowed to upload images for this product"
        )

    # ── Image count limit ─────────────────────────────────────────────────
    current_count = (
        db.query(ProductImage).filter(ProductImage.product_id == product_id).count()
    )
    if current_count >= image_service.MAX_IMAGES_PER_PRODUCT:
        raise HTTPException(
            status_code=400,
            detail=f"Product already has the maximum of "
            f"{image_service.MAX_IMAGES_PER_PRODUCT} images",
        )

    # ── Read content ──────────────────────────────────────────────────────
    content = file.file.read()

    # ── Validation pipeline ───────────────────────────────────────────────
    try:
        image_service.validate_file_size(content)
        image_service.validate_mime_type(file.content_type)
        detected_mime = image_service.validate_magic_bytes(content)
        image_service.validate_content_type_matches(file.content_type, detected_mime)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Generate safe filename & hash ─────────────────────────────────────
    uuid_filename = image_service.generate_uuid_filename(detected_mime)
    sha256_hash = image_service.compute_sha256(content)
    original_name = image_service.sanitize_original_filename(file.filename or "unknown")

    # ── Persist to disk ───────────────────────────────────────────────────
    try:
        safe_path = image_service.build_safe_path(uuid_filename)
        image_service.save_file(content, safe_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save image: {exc}"
        )

    # ── Persist metadata to DB ────────────────────────────────────────────
    db_image = ProductImage(
        product_id=product_id,
        filename=uuid_filename,
        original_filename=original_name,
        mime_type=detected_mime,
        file_size=len(content),
        sha256_hash=sha256_hash,
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)

    return db_image


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
def list_product_images(product_id: int, db: Session = Depends(get_db)):
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
    product_id: int,
    image_id: int,
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
