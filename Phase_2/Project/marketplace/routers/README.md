# Routers Module

This folder contains FastAPI route handlers that define the API endpoints for the Marketplace.

## Purpose

The `routers` module implements the HTTP API interface for the application. Each router file corresponds to a business domain and handles CRUD operations, authentication, and business logic for that domain's endpoints.

## Files Overview

### `auth.py`
- **Purpose**: Authentication and user authorization endpoints
- **Endpoints**:
  - `POST /auth/register` - Register a new user (public)
  - `POST /auth/login` - Authenticate user, return JWT token (public)
  - `GET /auth/me` - Get current authenticated user profile (protected)
- **Key Logic**:
  - Input validation via Pydantic schemas
  - Password hashing before storage
  - JWT token generation on successful login
  - Session/token caching (if applicable)
- **AI Context**: Authentication logic should validate credentials against the User model and use security utilities from `core/security.py`

### `users.py`
- **Purpose**: User profile and account management
- **Endpoints**:
  - `GET /users/` - List all active users (public)
  - `GET /users/{id}` - Get user profile by ID (public)
  - `PATCH /users/{id}` - Update own profile (protected, owner only)
  - `DELETE /users/{id}` - Soft-delete own account (protected, owner only)
- **Key Logic**:
  - Ownership validation for updates/deletes
  - Soft-delete via is_active flag
  - Profile information masking for privacy
- **AI Context**: User updates should only allow the authenticated user to modify their own data

### `products.py`
- **Purpose**: Product catalog and inventory management
- **Endpoints**:
  - `GET /products/` - List products with filtering (public)
    - Filters: min_price, max_price, seller_id
  - `GET /products/{id}` - Get product details (public)
  - `POST /products/` - Create new product (protected, sellers only)
  - `PATCH /products/{id}` - Update product (protected, owner only)
  - `DELETE /products/{id}` - Soft-delete product (protected, owner only)
- **Key Logic**:
  - Stock validation and management
  - Seller ownership enforcement
  - Price and inventory constraints
  - Search and filtering capabilities
- **AI Context**: Product creation should validate seller status, and updates should enforce ownership and stock constraints

### `orders.py`
- **Purpose**: Order placement and management
- **Endpoints**:
  - `GET /orders/` - List user's own orders (protected)
  - `GET /orders/{id}` - Get order details (protected, owner only)
  - `POST /orders/` - Create new order (protected, validates stock)
  - `PATCH /orders/{id}` - Update order status or address (protected, owner only)
  - `DELETE /orders/{id}` - Cancel order and restore stock (protected, owner only)
- **Key Logic**:
  - Stock validation before order creation
  - Automatic stock deduction on order confirmation
  - Stock restoration on order cancellation
  - Order status workflow (pending → confirmed → shipped → delivered)
  - User isolation (customers only see their own orders)
- **AI Context**: Order operations must maintain data consistency—stock changes should be atomic with order creation

### `images.py`
- **Purpose**: Image upload and retrieval for products/users
- **Endpoints**:
  - `POST /images/upload` - Upload an image file (protected)
  - `GET /images/{image_id}` - Retrieve image (public, cached)
  - `DELETE /images/{image_id}` - Delete image (protected, owner only)
- **Key Logic**:
  - File type and size validation
  - Secure file storage
  - URL generation for access
  - Ownership enforcement
- **AI Context**: Image operations should use `core/image_service.py` for file handling and storage

## Architecture Pattern

Each router follows this structure:
```python
from fastapi import APIRouter, Depends, HTTPException
from middleware.auth import get_current_user
from models.models import User
from schemas.schemas import UserSchema
from services.auth_service import AuthService

router = APIRouter(prefix="/path", tags=["tag"])

@router.get("/")
async def list_items():
    """Public endpoint - no auth required"""
    pass

@router.post("/")
async def create_item(data: ItemSchema, current_user: User = Depends(get_current_user)):
    """Protected endpoint - requires authentication"""
    pass
```

## Integration Points

1. **main.py** imports and registers all routers
2. **middleware/auth.py** provides authentication dependencies
3. **models/models.py** defines the data entities
4. **schemas/schemas.py** provides request/response validation
5. **services/** implement business logic

## Common Route Patterns

### Protected Route (Authentication Required)
```python
@router.get("/profile")
async def get_profile(current_user: User = Depends(get_current_user)):
    return current_user
```

### Ownership Check
```python
@router.patch("/{item_id}")
async def update_item(item_id: int, data: UpdateSchema, current_user: User = Depends(get_current_user)):
    item = db.query(Item).get(item_id)
    if item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
```

### Filtered Listing
```python
@router.get("/")
async def list_items(skip: int = 0, limit: int = 10, filter_by: str = None):
    query = db.query(Item).filter(Item.is_active == True)
    if filter_by:
        query = query.filter(Item.field == filter_by)
    return query.offset(skip).limit(limit).all()
```

## Modification Guidelines

- **Adding new endpoints**: Create in appropriate router file or new router
- **Changing authentication**: Update dependency usage in route signatures
- **Adding business logic**: Implement in `services/` and call from router
- **Validation changes**: Update Pydantic schema in `schemas/schemas.py`
- **Error handling**: Use FastAPI `HTTPException` with appropriate status codes
