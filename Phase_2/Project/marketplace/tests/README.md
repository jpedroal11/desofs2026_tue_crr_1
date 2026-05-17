# Tests Module

This folder contains pytest test suites for the Marketplace API.

## Purpose

The `tests` module provides automated testing coverage for all API endpoints, services, and business logic. Tests ensure code quality, catch regressions, and document expected behavior.

## Files Overview

### `conftest.py`
- **Purpose**: Pytest configuration and shared test fixtures
- **Key Fixtures**:
  - `client` - FastAPI TestClient for making test requests
  - `db` - Test database session (separate from production)
  - `test_user` - Pre-created test user for auth tests
  - `test_product` - Pre-created test product
  - `test_order` - Pre-created test order
  - `auth_headers` - Valid JWT headers for authenticated requests

- **Setup/Teardown**:
  - Creates test database on startup
  - Seeds fixture data
  - Cleans up after each test
  - Isolates tests from each other

- **Usage**: Fixtures are automatically available to all test files

### `test_auth.py`
- **Purpose**: Test authentication endpoints
- **Test Cases**:
  - User registration (success, email/username duplicate, invalid email)
  - User login (success, invalid credentials, inactive user)
  - Get current user profile (authenticated, unauthenticated)
  - JWT token validation and expiration
  - Bearer token extraction

- **AI Context**: When modifying auth logic, update tests first or after to ensure coverage

### `test_users.py`
- **Purpose**: Test user profile and account management
- **Test Cases**:
  - List users (pagination, filters)
  - Get user profile by ID (valid/invalid ID, soft-deleted users)
  - Update own profile (success, unauthorized, ownership check)
  - Soft-delete account (success, idempotency)
  - Permission checks (user can only update own profile)

- **AI Context**: Tests verify ownership enforcement and soft-delete behavior

### `test_products.py`
- **Purpose**: Test product catalog and inventory
- **Test Cases**:
  - List products (pagination, price filters, seller filters)
  - Get product details (valid/invalid ID, soft-deleted products)
  - Create product (success, seller-only check, validation)
  - Update product (success, ownership, stock constraints)
  - Delete product (soft-delete, restore)
  - Stock validation and constraints

- **AI Context**: Tests verify seller ownership and stock consistency

### `test_orders.py`
- **Purpose**: Test order placement and management
- **Test Cases**:
  - Create order (valid, insufficient stock, item validation)
  - Get orders (user isolation, pagination)
  - Update order status (valid transitions, ownership)
  - Cancel order (stock restoration, idempotency)
  - Order isolation (users see only their orders)
  - Total price calculation

- **AI Context**: Tests verify critical business logic: stock deduction and restoration

### `test_images.py`
- **Purpose**: Test image upload and retrieval
- **Test Cases**:
  - Upload image (valid file, size limits, type validation)
  - Retrieve image (public access, caching)
  - Delete image (ownership, cleanup)
  - Invalid uploads (unsupported types, too large)

- **AI Context**: Tests verify file security and storage

### `test_middleware_deps.py`
- **Purpose**: Test middleware and dependency injection
- **Test Cases**:
  - Authentication dependency (valid/invalid/expired tokens)
  - Role-based access (seller-only routes, user-only routes)
  - Database session injection
  - Error responses (401, 403)

- **AI Context**: Tests ensure middleware properly enforces permissions

## Test Structure

### Standard Test Pattern
```python
def test_get_user_success(client, test_user):
    """Test retrieving a user profile"""
    response = client.get(f"/users/{test_user.id}")
    assert response.status_code == 200
    assert response.json()["email"] == test_user.email

def test_get_user_not_found(client):
    """Test retrieving non-existent user"""
    response = client.get("/users/99999")
    assert response.status_code == 404

def test_update_user_unauthorized(client):
    """Test user cannot update another user's profile"""
    response = client.patch("/users/1", json={"full_name": "Hacker"})
    assert response.status_code == 401  # Not authenticated
```

### Using Fixtures
```python
def test_create_order_with_auth(client, test_user, test_product, auth_headers):
    """Test order creation with authentication"""
    response = client.post(
        "/orders/",
        json={"items": [{"product_id": test_product.id, "quantity": 2}]},
        headers=auth_headers
    )
    assert response.status_code == 201
```

## Running Tests

### Run All Tests
```bash
pytest
```

### Run Specific File
```bash
pytest tests/test_auth.py
```

### Run Specific Test
```bash
pytest tests/test_auth.py::test_register_success
```

### Run with Verbose Output
```bash
pytest -v
```

### Run with Coverage Report
```bash
pytest --cov=.
```

### Run with Stop on First Failure
```bash
pytest -x
```

## Test Isolation

- Each test function is independent
- Fixtures provide clean state (test database)
- Tests don't interfere with each other
- No test should depend on another test's state

## Test Coverage Guidelines

- **Happy path**: Test successful operation with valid data
- **Error cases**: Test error handling with invalid data
- **Edge cases**: Test boundary conditions (0 items, max values)
- **Permissions**: Test auth and ownership enforcement
- **Business logic**: Test complex operations (stock deduction, order workflow)

## Modification Guidelines

- **Adding tests**: Follow naming convention `test_<function>_<scenario>`
- **Testing new endpoints**: Create corresponding test file or extend existing
- **Fixtures**: Add to `conftest.py` for reuse across tests
- **Coverage**: Aim for >80% code coverage, critical paths >95%
- **Mocking**: Mock external APIs (HIBP password check, image upload services)

## Common Test Patterns

### Testing Authentication Required Endpoint
```python
def test_protected_endpoint_without_auth(client):
    response = client.get("/protected")
    assert response.status_code == 401

def test_protected_endpoint_with_auth(client, auth_headers):
    response = client.get("/protected", headers=auth_headers)
    assert response.status_code == 200
```

### Testing Ownership Enforcement
```python
def test_user_cannot_delete_others_product(client, test_user, other_user, product_owned_by_other, auth_headers_for_test_user):
    response = client.delete(f"/products/{product_owned_by_other.id}", headers=auth_headers_for_test_user)
    assert response.status_code == 403
```

### Testing Business Logic
```python
def test_order_deducts_stock(client, test_product):
    initial_stock = test_product.stock
    # Create order for 5 items
    # Verify stock decreased by 5
    assert test_product.stock == initial_stock - 5
```
