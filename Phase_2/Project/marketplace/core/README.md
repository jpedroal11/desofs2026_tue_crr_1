# Core Module

This folder contains essential application-level configurations and utilities that support the entire Marketplace API.

## Purpose

The `core` module provides cross-cutting concerns and foundational setup needed by routers, services, and models throughout the application. It centralizes configuration, dependency injection, security, and role-based access control.

## Files Overview

### `config.py`
- **Purpose**: Environment configuration and settings management
- **Key Features**:
  - Reads environment variables (DATABASE_URL, SECRET_KEY, CORS_ALLOW_ORIGINS, etc.)
  - Validates required settings at startup
  - Manages different environments (dev, test, production)
  - Provides database URL and API configurations
- **AI Context**: Any feature that needs app settings should import from this module to avoid hardcoding values

### `dependencies.py`
- **Purpose**: Dependency injection setup for the entire application
- **Key Features**:
  - Database engine initialization and session management
  - Password hashing utilities (using bcrypt)
  - JWT token creation and validation
  - Authorization dependency for protected routes
  - Database session provider for FastAPI dependency injection
- **AI Context**: When implementing route handlers that need DB access or authentication, use dependencies from this module

### `security.py`
- **Purpose**: Security utilities for the application
- **Key Features**:
  - JWT token signing and verification
  - Password hashing and validation
  - Bearer token extraction from Authorization headers
  - Token expiration handling
- **AI Context**: All authentication logic should use these utilities to maintain consistent security practices

### `roles.py`
- **Purpose**: Role-based access control (RBAC)
- **Key Features**:
  - Defines user roles (e.g., 'seller', 'buyer', 'admin')
  - Role validation decorators or checks
  - Permission helpers
- **AI Context**: When protecting endpoints, use role checks from this module

### `image_service.py`
- **Purpose**: Image upload and storage handling
- **Key Features**:
  - File upload validation (MIME type, size checks)
  - Secure file storage path management
  - Image URL generation
  - Optional cleanup of orphaned files
- **AI Context**: When adding image features to products or user profiles, use this service

## Integration Points

- **main.py** imports from `config.py` for app initialization
- **routers/** import from `dependencies.py` for route protection and DB access
- **services/** use `security.py` for token operations
- All modules reference `config.py` for environment settings

## Common Usage Examples

```python
# In a router or service:
from core.config import get_settings
from core.dependencies import get_db, get_current_user, hash_password, create_access_token
from core.security import verify_password
from core.roles import check_role

# Get settings
settings = get_settings()

# Use as dependency in FastAPI
@app.get("/endpoint")
async def my_endpoint(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    pass
```

## Modification Guidelines

- **Adding new settings**: Update `config.py` and `core/config.Settings` class
- **Adding security features**: Extend `security.py`
- **Adding roles**: Update `roles.py`
- **Adding dependencies**: Add new dependency functions to `dependencies.py`
