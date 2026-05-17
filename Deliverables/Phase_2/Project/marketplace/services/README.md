# Services Module

This folder contains business logic and service classes that handle complex operations beyond simple CRUD.

## Purpose

The `services` module implements the core business logic of the Marketplace API. Services act as a layer between routers (HTTP handlers) and models (database), encapsulating domain logic, validation, and external integrations.

## Files Overview

### `auth_service.py`
- **Purpose**: Authentication and authorization business logic
- **Key Functions/Classes**:
  - `register_user()` - Create new user account
    - Validates email/username uniqueness
    - Hashes password using bcrypt
    - Assigns default role (buyer)
    - Returns user with token
  
  - `authenticate_user()` - Verify credentials
    - Validates username and password
    - Checks user is_active status
    - Returns JWT token on success
    - Raises error on invalid credentials
  
  - `get_current_user()` - Extract user from token
    - Validates JWT signature and expiration
    - Returns authenticated user
    - Used as dependency in protected routes
  
  - `verify_password()` / `hash_password()` - Password utilities
    - Bcrypt hashing for storage
    - Constant-time comparison for verification

- **AI Context**: When implementing authentication features, use this service instead of handling JWT/passwords in routers

### `pwned.py`
- **Purpose**: Password security validation against known breaches
- **Key Functions**:
  - `check_password_pwned()` - Verify password against Have I Been Pwned database
    - API integration with HIBP service
    - Checks if password appears in known breaches
    - Returns True if password is compromised
  
  - `validate_password_strength()` - Local validation
    - Minimum length checks
    - Character variety requirements
    - Common pattern detection

- **Usage**: Called during user registration to enforce strong password policies
- **AI Context**: Always validate passwords during registration to prevent weak/breached passwords

## Architecture Pattern

Services follow this structure:
```python
class AuthService:
    def __init__(self, db: Session):
        self.db = db
    
    def register_user(self, email: str, username: str, password: str) -> User:
        """Business logic for user registration"""
        # Validate
        # Hash password
        # Create user
        # Return result
    
    def authenticate_user(self, username: str, password: str) -> str:
        """Business logic for authentication"""
        # Validate credentials
        # Generate token
        # Return token
```

## Integration with Application

```
routers/         →  services/        →  models/  →  database
(HTTP handlers)      (business logic)     (ORM)       (schema)

@router.post("/register")
async def register(data: UserRegister) → AuthService.register_user() → User model
```

### Flow Example: User Registration
1. Router receives POST request with `UserRegister` schema
2. Router calls `AuthService.register_user()`
3. Service validates email/username uniqueness against User model
4. Service hashes password
5. Service creates User record in database
6. Service generates JWT token
7. Router returns response with token

## Common Tasks

### Implementing a Business Logic Service

```python
from core.dependencies import get_db
from models.models import Product, Order, OrderItem
from sqlalchemy import Session

class OrderService:
    def __init__(self, db: Session):
        self.db = db
    
    def create_order(self, user_id: int, items: List[OrderItemCreate]) -> Order:
        """Create order with stock validation and deduction"""
        # Validate stock for all items
        for item in items:
            product = self.db.query(Product).get(item.product_id)
            if not product or product.stock < item.quantity:
                raise ValueError(f"Insufficient stock for product {item.product_id}")
        
        # Create order
        order = Order(user_id=user_id, status="pending")
        
        # Create order items and deduct stock
        for item in items:
            product = self.db.query(Product).get(item.product_id)
            order_item = OrderItem(
                product_id=item.product_id,
                quantity=item.quantity,
                unit_price=product.price
            )
            order.items.append(order_item)
            product.stock -= item.quantity
        
        self.db.add(order)
        self.db.commit()
        return order
```

### Using a Service in a Router

```python
from services.auth_service import AuthService
from core.dependencies import get_db

@router.post("/register")
async def register(data: UserRegister, db: Session = Depends(get_db)):
    service = AuthService(db)
    user = service.register_user(data.email, data.username, data.password)
    return {"user": user, "token": user.token}
```

## Service Responsibilities

✅ **Should Handle**:
- Complex multi-step operations (e.g., order with stock management)
- External API integrations (e.g., password breach checking)
- Validation and business rule enforcement
- Data transformation and aggregation
- Error handling and logging

❌ **Should NOT Handle**:
- HTTP routing (belongs in routers/)
- Database schema (belongs in models/)
- Request/response serialization (belongs in schemas/)
- Infrastructure concerns (logging, monitoring)

## Modification Guidelines

- **Adding new business logic**: Create new service class
- **Complex operations**: Break into smaller service methods
- **Shared utilities**: Create utility functions in existing services
- **Testing**: Services should be testable with mocked DB
- **External APIs**: Isolate API calls in dedicated methods

## Common External Integrations

- **Password validation**: `pwned.py` → Have I Been Pwned API
- **Payment processing**: Future service for order payment
- **Email notifications**: Future service for order updates
- **Image processing**: `core/image_service.py` for uploads
