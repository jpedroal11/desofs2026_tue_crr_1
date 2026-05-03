# Marketplace API

A production-ready RESTful API built with FastAPI for managing a marketplace with Users, Products, and Orders.

## Features

- **JWT Authentication** — Register, login, and protect routes with Bearer tokens
- **Users** — Registration, profile management, soft-delete
- **Products** — CRUD with stock management, price filters, seller ownership
- **Orders** — Place orders with automatic stock deduction, cancel with stock restore
- **SQLAlchemy ORM** — SQLite by default, swap to PostgreSQL via env var
- **Pydantic v2** — Full request/response validation with clear error messages
- **Auto Docs** — Swagger UI at `/docs`, ReDoc at `/redoc`

## Project Structure

```
marketplace/
├── main.py                  # App entry point, router registration
├── requirements.txt
├── core/
│   └── dependencies.py      # DB session, password hashing, JWT, auth dependency
├── models/
│   └── models.py            # SQLAlchemy ORM models
├── schemas/
│   └── schemas.py           # Pydantic request/response schemas
└── routers/
    ├── auth.py              # POST /auth/register, /auth/login, GET /auth/me
    ├── users.py             # GET/PATCH/DELETE /users
    ├── products.py          # GET/POST/PATCH/DELETE /products
    └── orders.py            # GET/POST/PATCH/DELETE /orders
```

## Setup & Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the server (from the marketplace/ directory)
uvicorn main:app --reload

# 3. Open interactive docs
open http://localhost:8000/docs
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./marketplace.db` | Database connection string |
| `SECRET_KEY` | (insecure default) | JWT signing secret — **change in production!** |

### PostgreSQL example

```bash
export DATABASE_URL="postgresql://user:password@localhost/marketplace"
```

## API Endpoints

### Authentication
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/auth/register` | ❌ | Register a new user |
| POST | `/auth/login` | ❌ | Login, returns JWT token |
| GET | `/auth/me` | ✅ | Get current user info |

### Users
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/users/` | ❌ | List all active users |
| GET | `/users/{id}` | ❌ | Get user by ID |
| PATCH | `/users/{id}` | ✅ | Update own profile |
| DELETE | `/users/{id}` | ✅ | Soft-delete own account |

### Products
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/products/` | ❌ | List products (supports `min_price`, `max_price`, `seller_id` filters) |
| GET | `/products/{id}` | ❌ | Get product by ID |
| POST | `/products/` | ✅ Seller | Create a product |
| PATCH | `/products/{id}` | ✅ Owner | Update own product |
| DELETE | `/products/{id}` | ✅ Owner | Soft-delete own product |

### Orders
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/orders/` | ✅ | List own orders |
| GET | `/orders/{id}` | ✅ | Get own order by ID |
| POST | `/orders/` | ✅ | Place an order (validates & deducts stock) |
| PATCH | `/orders/{id}` | ✅ | Update status or shipping address |
| DELETE | `/orders/{id}` | ✅ | Cancel pending/confirmed order (restores stock) |

## Example Flow

```bash
# 1. Register a seller
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"seller@shop.com","username":"seller1","password":"secret123","is_seller":true}'

# 2. Login
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -d "username=seller1&password=secret123" | jq -r .access_token)

# 3. Create a product
curl -X POST http://localhost:8000/products/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Laptop","price":999.99,"stock":10}'

# 4. Register a buyer and place an order
curl -X POST http://localhost:8000/orders/ \
  -H "Authorization: Bearer $BUYER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"shipping_address":"123 Main St","items":[{"product_id":1,"quantity":2}]}'
```
