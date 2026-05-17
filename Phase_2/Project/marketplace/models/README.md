# Models Module

This folder contains SQLAlchemy ORM models that define the database schema and application entities.

## Purpose

The `models` module defines the data structure of the Marketplace API. These SQLAlchemy models map Python classes to database tables, establishing relationships, constraints, and validation at the data layer.

## Files Overview

### `models.py`
- **Purpose**: SQLAlchemy ORM model definitions
- **Key Entities**:
  - **User**: Represents marketplace users (sellers and buyers)
    - Fields: id, email, username, password_hash, full_name, is_active, is_seller, created_at, updated_at
    - Relationships: products (if seller), orders (if buyer)
    - Soft-delete: is_active flag for logical deletion
  
  - **Product**: Represents items for sale
    - Fields: id, seller_id, name, description, price, stock, is_active, created_at, updated_at
    - Relationships: seller (User), order_items (OrderItem)
    - Constraints: Must have seller, positive price and stock
  
  - **Order**: Represents customer orders
    - Fields: id, user_id, status, total_price, shipping_address, created_at, updated_at
    - Relationships: user (User), items (OrderItem)
    - Status: pending, confirmed, shipped, delivered, cancelled
  
  - **OrderItem**: Junction table for Order-Product relationship
    - Fields: id, order_id, product_id, quantity, unit_price, subtotal
    - Relationships: order (Order), product (Product)
    - Handles many-to-many with pricing snapshots

- **Features**:
  - Timestamps: created_at and updated_at for audit trails
  - Foreign keys with cascading relationships
  - Soft deletes via is_active flag
  - Base model for common functionality

## Key Concepts

### Relationships
- **One-to-Many**: User ↔ Product, User ↔ Order
- **Many-to-Many**: Order ↔ Product (through OrderItem)

### Constraints
- NOT NULL fields for required attributes
- UNIQUE constraints on email and username
- Check constraints for valid values (e.g., stock >= 0)

### Soft Deletes
- Instead of DELETE, set `is_active = False`
- Preserves data for auditing and recovery
- Queries filter by `is_active = True` to exclude deleted records

## Integration with Application

1. **Database Setup**: `main.py` calls `Base.metadata.create_all()` to create tables
2. **ORM Queries**: `services/` and `routers/` use these models to query/modify data
3. **Schemas**: `schemas/schemas.py` converts between ORM models and Pydantic schemas
4. **Migrations**: In production, use these models with Alembic for version control

## Common Model Operations

### Querying
```python
from models.models import User, Product
from core.dependencies import get_db

db: Session = get_db()

# Find by ID
user = db.query(User).filter(User.id == 1).first()

# Filter multiple conditions
products = db.query(Product).filter(
    Product.is_active == True,
    Product.price >= 10,
    Product.stock > 0
).all()
```

### Creating Records
```python
new_user = User(
    email="user@example.com",
    username="username",
    password_hash=hash_password("secret"),
    full_name="John Doe"
)
db.add(new_user)
db.commit()
```

### Relationships
```python
# Access related objects
user = db.query(User).get(1)
products = user.products  # All products sold by this user

# Add related objects
new_product = Product(name="Laptop", price=999, stock=5)
user.products.append(new_product)
db.commit()
```

## Modification Guidelines

- **Adding new fields**: Update the model class, add to migration/`script.sql`
- **Adding relationships**: Use SQLAlchemy relationship syntax
- **Changing constraints**: Update model, regenerate schema
- **Schema sync**: Keep `models.py` and `database/script.sql` in sync
- **Tests**: Update test fixtures when models change

## Model Design Best Practices

- Use meaningful names that reflect business logic
- Include timestamps (created_at, updated_at) for audit trails
- Use soft deletes for data preservation
- Define foreign key relationships explicitly
- Add docstrings for complex model logic
