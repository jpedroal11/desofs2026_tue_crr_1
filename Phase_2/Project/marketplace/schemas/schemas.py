from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
from models.models import OrderStatus, ProductStatus


class RoleResponse(BaseModel):
    id: int
    name: str

    model_config = {"from_attributes": True}


# ── User Schemas ──────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None


class UserCreate(UserBase):
    password: str
    roles: Optional[List[str]] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime
    roles: List[RoleResponse] = []

    model_config = {"from_attributes": True}


# ── Product Schemas ───────────────────────────────────────────────────────────

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    stock: int = 0

    @field_validator("price")
    @classmethod
    def price_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Price must be positive")
        return v

    @field_validator("stock")
    @classmethod
    def stock_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Stock cannot be negative")
        return v


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    stock: Optional[int] = None
    status: Optional[ProductStatus] = None


class ProductStatusUpdate(BaseModel):
    status: ProductStatus


class StockAdjustment(BaseModel):
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Quantity must be positive")
        return v


class ProductImageResponse(BaseModel):
    id: int
    filename: str
    original_filename: str
    mime_type: str
    file_size: int
    sha256_hash: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class ProductResponse(ProductBase):
    id: int
    status: ProductStatus
    seller_id: int
    created_at: datetime
    updated_at: datetime
    images: List[ProductImageResponse] = []

    model_config = {"from_attributes": True}


# ── Order Schemas ─────────────────────────────────────────────────────────────

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int

    @field_validator("quantity")
    @classmethod
    def quantity_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Quantity must be at least 1")
        return v


class OrderItemResponse(BaseModel):
    id: int
    product_id: int
    quantity: int
    unit_price: float

    model_config = {"from_attributes": True}


class OrderCreate(BaseModel):
    shipping_address: Optional[str] = None
    items: List[OrderItemCreate]


class OrderUpdate(BaseModel):
    status: Optional[OrderStatus] = None
    shipping_address: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    buyer_id: int
    status: OrderStatus
    total_amount: float
    shipping_address: Optional[str]
    items: List[OrderItemResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Auth Schemas ──────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: Optional[int] = None
