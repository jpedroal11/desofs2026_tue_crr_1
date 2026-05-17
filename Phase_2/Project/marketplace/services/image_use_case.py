from fastapi import HTTPException
from sqlalchemy.orm import Session
from models.models import Product, User, ProductImage
from core import image_service
from repositories import image_repository

def upload_product_image(
    db: Session,
    product_id: int,
    current_user: User,
    file_content: bytes,
    filename: str,
    content_type: str,
) -> ProductImage:
    # ── Ownership verification ─────────────────────────────────────────────
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=403, detail="Not allowed to upload images for this product"
        )

    # ── Validation pipeline ────────────────────────────────────────────────
    try:
        image_service.validate_file_size(file_content)
        image_service.validate_mime_type(content_type)
        detected_mime = image_service.validate_magic_bytes(file_content)
        image_service.validate_content_type_matches(content_type, detected_mime)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Image count limit ──────────────────────────────────────────────────
    current_count = image_repository.count_by_product(db, product_id)
    if current_count >= 10:
        raise HTTPException(
            status_code=400,
            detail="Maximum number of images per product reached (10)",
        )

    # ── Storage quota limit ────────────────────────────────────────────────
    total_storage = image_repository.total_storage_by_seller(db, current_user.id)
    if total_storage + len(file_content) > 200 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Storage quota exceeded. Maximum 200 MB per seller.",
        )

    # ── Generate safe filename & hash ──────────────────────────────────────
    uuid_filename = image_service.generate_uuid_filename(detected_mime)
    sha256_hash = image_service.compute_sha256(file_content)
    original_name = image_service.sanitize_original_filename(filename or "unknown")

    # ── Persist to disk ────────────────────────────────────────────────────
    try:
        safe_path = image_service.build_safe_path(uuid_filename)
        image_service.save_file(file_content, safe_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Failed to save image: {exc}"
        )

    # ── Persist metadata to DB ─────────────────────────────────────────────
    db_image = ProductImage(
        product_id=product_id,
        filename=uuid_filename,
        original_filename=original_name,
        mime_type=detected_mime,
        file_size=len(file_content),
        sha256_hash=sha256_hash,
    )
    db.add(db_image)
    db.commit()
    db.refresh(db_image)

    return db_image
