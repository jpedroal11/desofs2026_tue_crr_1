# Middleware Module

This folder contains custom middleware that processes HTTP requests and responses for the Marketplace API.

## Purpose

The `middleware` module implements cross-cutting request/response concerns that apply to all or specific routes. Middleware in FastAPI intercepts requests before they reach route handlers and can modify responses before they're sent to clients.

## Files Overview

### `auth.py`
- **Purpose**: Authentication middleware for protecting routes
- **Key Features**:
  - JWT token extraction from Authorization header
  - Token validation and verification
  - User context injection into requests
  - Role-based access control checks
  - Error handling for invalid/expired tokens
- **Usage**:
  - Used via FastAPI `Depends()` in protected routes
  - Validates Bearer tokens before allowing access
  - Returns 401 Unauthorized or 403 Forbidden for invalid/insufficient permissions
- **AI Context**: When protecting a route, use the dependency from this middleware instead of implementing auth logic in the route handler

## Architecture

Middleware in FastAPI:
1. Receives the incoming HTTP request
2. Performs validation/enrichment (e.g., extract user from token)
3. Passes control to the route handler
4. Optionally modifies the response

## Integration with Application

### In FastAPI
```python
# main.py may add middleware globally for all routes:
app.add_middleware(SomeMiddleware)

# Or use middleware as dependencies in specific routes:
@app.get("/protected")
async def protected_route(current_user = Depends(get_current_user)):
    return {"user": current_user}
```

### Example: Auth Middleware Usage
```python
from middleware.auth import get_current_user

@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    # current_user is automatically extracted and validated
    return current_user
```

## Common Tasks

### Adding New Middleware

1. Create a new file in the `middleware/` folder
2. Implement middleware function with FastAPI-compatible signature
3. Register in `main.py` using `app.add_middleware()` or as route dependencies

### Protecting a Route

```python
from middleware.auth import get_current_user

@router.patch("/{user_id}")
async def update_user(user_id: int, updates: UserUpdate, 
                      current_user = Depends(get_current_user)):
    # Only authenticated users can reach here
    if current_user.id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized")
```

### Debugging Middleware

- Check token format in Authorization header: `Bearer <token>`
- Verify token expiration: check JWT payload
- Ensure role checks are correct in `auth.py`

## Modification Guidelines

- **Adding auth checks**: Extend `auth.py` with additional validation
- **Adding logging/monitoring**: Create new middleware for request/response logging
- **Adding CORS or headers**: Register appropriate middleware in `main.py`
- **Performance optimizations**: Add caching or rate-limiting middleware here
