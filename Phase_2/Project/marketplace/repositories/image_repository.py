import uuid
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.models import ProductImage, Product

def count_by_product(db: Session, product_id: int) -> int:
    return db.query(ProductImage).filter(ProductImage.product_id == product_id).count()

def total_storage_by_seller(db: Session, seller_id: uuid.UUID) -> int:
    result = (
        db.query(func.coalesce(func.sum(ProductImage.file_size), 0))
        .join(Product, ProductImage.product_id == Product.id)
        .filter(Product.seller_id == seller_id)
        .scalar()
    )
    return result or 0
