# Schemas Module

This folder contains Pydantic data validation schemas for request and response objects.

## Purpose

The `schemas` module defines the contract between the API client and server. These Pydantic models validate incoming request data and serialize outgoing responses, ensuring type safety and clear error messages.

## Files Overview

### `schemas.py`
- **Purpose**: Pydantic v2 models for request/response validation
- **Key Schemas** (organized by domain):

  **User Schemas**:
  - `UserRegister` - Registration request (email, username, password)
  - `UserLogin` - Login request (username/email, password)
  - `UserResponse` - User profile response (id, email, username, full_name, is_seller, created_at)
  - `UserUpdate` - Profile update request (full_name, etc.)

  **Product Schemas**:
  - `ProductCreate` - Product creation (name, description, price, stock)
  - `ProductUpdate` - Product update (name, description, price, stock)
  - `ProductResponse` - Product details (id, seller_id, name, price, stock, created_at)
  - `ProductListResponse` - Lightweight product listing (includes seller info)

  **Order Schemas**:
  - `OrderItemCreate` - Single order item (product_id, quantity)
  - `OrderCreate` - Order creation (items: List[OrderItemCreate], shipping_address)
  - `OrderResponse` - Order details (id, status, total_price, items, created_at)
  - `OrderStatusUpdate` - Update order status

  **Image Schemas**:
  - `ImageUploadResponse` - File upload response (image_id, url, uploaded_at)

  **Auth Response**:
  - `TokenResponse` - JWT response (access_token, token_type)

- **Features**:
  - Field validation (e.g., email format, positive prices)
  - Custom validators for business rules
  - Automatic documentation generation
  - Nested schema support for complex data

## Key Concepts

### Request vs Response Schemas
- **Request Schemas**: Used for `POST`/`PATCH` bodies
- **Response Schemas**: Used for API responses and documentation
- Different schemas allow for input validation while hiding sensitive fields in responses

### Validation Examples
```python
class ProductCreate(BaseModel):
    name: str  # Required string
    price: float = Field(..., gt=0)  # Must be > 0
    stock: int = Field(..., ge=0)    # Must be >= 0
    description: Optional[str] = None

class UserRegister(BaseModel):
    email: EmailStr  # Auto-validates email format
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8)
```

### Nested Schemas
```python
class OrderItemResponse(BaseModel):
    product_id: int
    product_name: str
    quantity: int
    unit_price: float

class OrderResponse(BaseModel):
    id: int
    user_id: int
    items: List[OrderItemResponse]  # Nested list
    total_price: float
    status: str
```

## Integration with Application

1. **Route Handlers**: Routers use request schemas in function parameters
   ```python
   @router.post("/products/")
   async def create_product(data: ProductCreate):
       # FastAPI automatically validates data against ProductCreate schema
   ```

2. **Response Documentation**: Response schemas appear in Swagger docs at `/docs`

3. **Type Safety**: Pydantic provides IDE autocompletion and type checking

4. **Error Responses**: Invalid data returns 422 Unprocessable Entity with field-level errors

## Common Tasks

### Adding a New Request Schema
```python
class NewFeatureCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    value: int = Field(..., ge=0)
    description: Optional[str] = None

    model_config = ConfigDict(json_schema_extra={
        "example": {
            "title": "My Item",
            "value": 100,
            "description": "An example item"
        }
    })
```

### Adding Validation Logic
```python
from pydantic import field_validator

class ProductCreate(BaseModel):
    name: str
    price: float
    
    @field_validator('price')
    @classmethod
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('Price must be positive')
        return v
```

### API Documentation
Pydantic schemas automatically generate:
- OpenAPI schema
- Request/response examples
- Field descriptions
- Type information

Visit `/docs` for interactive Swagger UI with live schema preview.

## Modification Guidelines

- **Adding fields**: Add to appropriate schema with type hints and validation rules
- **Changing validation**: Use `Field()` with constraints or custom validators
- **Hiding sensitive data**: Omit sensitive fields from response schemas
- **Documentation**: Add docstrings and `description` fields for clarity
- **Examples**: Use `json_schema_extra` for example payloads

## Best Practices

1. **Separate request from response**: Don't expose internal fields (timestamps, IDs, passwords)
2. **Validate early**: Use Pydantic to catch bad data at the API boundary
3. **Be explicit**: Use type hints, not `Any` (except where necessary)
4. **Document constraints**: Add descriptions for business rules (e.g., "must be > 0")
5. **Reuse schemas**: Compose schemas (e.g., `UserResponse` + additional fields = `UserWithOrdersResponse`)
