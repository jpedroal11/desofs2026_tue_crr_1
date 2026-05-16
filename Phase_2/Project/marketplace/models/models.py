from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Enum, Text, Table
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum

Base = declarative_base()

user_roles_table = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)
    users = relationship("User", secondary=user_roles_table, back_populates="roles")


class OrderStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    shipped = "shipped"
    delivered = "delivered"
    cancelled = "cancelled"


class ProductStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    archived = "archived"



class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    products = relationship("Product", back_populates="seller")
    orders = relationship("Order", back_populates="buyer")
    roles = relationship("Role", secondary=user_roles_table, back_populates="users")

    @property
    def is_seller(self) -> bool:
        return any(role.name.lower() == "seller" for role in self.roles)

    @property
    def is_admin(self) -> bool:
        return any(role.name.lower() == "administrator" for role in self.roles)

    @property
    def is_buyer(self) -> bool:
        return any(role.name.lower() == "buyer" for role in self.roles)

    def has_role(self, role_name: str) -> bool:
        return any(role.name.lower() == role_name.lower() for role in self.roles)


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    description = Column(Text, nullable=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    status = Column(Enum(ProductStatus), default=ProductStatus.draft)
    seller_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    seller = relationship("User", back_populates="products")
    order_items = relationship("OrderItem", back_populates="product")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(Enum(OrderStatus), default=OrderStatus.pending)
    total_amount = Column(Float, default=0.0)
    shipping_address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    buyer = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)

    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class ProductImage(Base):
    __tablename__ = "product_images"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    filename = Column(String, unique=True, nullable=False)       # UUID-based filename on disk
    original_filename = Column(String, nullable=False)            # Sanitized original name
    mime_type = Column(String, nullable=False)
    file_size = Column(Integer, nullable=False)                   # bytes
    sha256_hash = Column(String(64), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="images")
