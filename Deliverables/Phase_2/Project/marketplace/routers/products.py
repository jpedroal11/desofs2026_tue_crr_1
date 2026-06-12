from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from core.dependencies import get_db
from middleware.auth import get_current_user
from models.models import Product, User, ProductStatus
from schemas.schemas import ProductCreate, ProductUpdate, ProductResponse, StockAdjustment, ProductStatusUpdate

import logging

router = APIRouter(prefix="/products", tags=["Products"])


@router.get("/", response_model=List[ProductResponse])
def list_products(
    skip: int = 0,
    limit: int = 20,
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    seller_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
):
    """List available products with optional filters."""
    query = db.query(Product).filter(Product.status == ProductStatus.active, Product.stock > 0)

    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    if seller_id is not None:
        query = query.filter(Product.seller_id == seller_id)

    return query.offset(skip).limit(limit).all()


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: UUID, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)):
    """Get a product by ID."""
    query = db.query(Product).filter(Product.id == product_id)

    if current_user.is_seller:
        query = query.filter(
            (Product.seller_id == current_user.id) | (Product.status == ProductStatus.active)
        )
    elif current_user.is_buyer:
        query = query.filter(Product.status == ProductStatus.active)

    product = query.first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    """Create a new product. Only sellers can create products."""
    if not current_user.is_seller:
        raise HTTPException(status_code=403, detail="Only sellers can create products")

    product = Product(**product_in.model_dump(), seller_id=current_user.id)
    db.add(product)
    db.commit()
    db.refresh(product)
    return product


@router.patch("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: UUID,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update a product. Only the seller who owns it can update it."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this product")

    for field, value in product_in.model_dump(exclude_unset=True).items():
        setattr(product, field, value)

    db.commit()
    db.refresh(product)
    return product


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a product (sets is_active=False)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to delete this product")

    product.status = ProductStatus.archived
    db.commit()


@router.patch("/{product_id}/status", response_model=ProductResponse)
def update_product_status(
    product_id: UUID,
    status_update: ProductStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update product status (e.g., draft -> active)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this product")

    product.status = status_update.status
    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/stock/add", response_model=ProductResponse)
def add_product_stock(
    product_id: UUID,
    adjustment: StockAdjustment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add stock to a product."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this product")

    product.stock += adjustment.quantity
    db.commit()
    db.refresh(product)
    return product


@router.post("/{product_id}/stock/reduce", response_model=ProductResponse)
def reduce_product_stock(
    product_id: UUID,
    adjustment: StockAdjustment,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reduce stock from a product (cannot go below 0)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.seller_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this product")

    if product.stock < adjustment.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    product.stock -= adjustment.quantity
    db.commit()
    db.refresh(product)
    return product
