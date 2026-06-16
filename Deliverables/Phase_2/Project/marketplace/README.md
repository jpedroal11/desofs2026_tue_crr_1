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

## Running the app

All commands run from the `marketplace/` directory. There are two Docker stacks
that share the same `Dockerfile` and application code:

| Stack | Command | URL | Use it to |
|---|---|---|---|
| **Dev** | `docker compose -f docker-compose.dev.yml up --build` | http://localhost:8000/docs | Develop & test — Swagger enabled, plain HTTP, no proxy |
| **Prod** | `docker compose -f docker-compose.prod.yml up --build` | https://localhost/ | Verify the hardened edge — Nginx TLS, HSTS, CSP; `/docs` disabled |

Stop a stack with `docker compose -f <file> down` (add `-v` to also remove its
database volume).

### Dev stack (day-to-day development)

```bash
docker compose -f docker-compose.dev.yml up --build
# → http://localhost:8000/docs  (Swagger UI)
```

Publishes the app on `:8000` over HTTP with `APP_ENV=development`. Sensible
defaults are baked in, so it runs with no `.env`. Postgres is exposed on `:5432`
for a local DB client.

### Prod stack (TLS reverse proxy)

```bash
cp .env.example .env          # fill in real secrets
./nginx/generate-dev-certs.sh # self-signed staging certs (or mount real ones)
docker compose -f docker-compose.prod.yml up --build
# → https://localhost/  (accept the self-signed cert warning)
```

Only Nginx is exposed (ports 80/443); the app and database stay on an internal
network. Nginx terminates TLS, redirects HTTP→HTTPS, and sets HSTS + security
headers. `/docs` is **off** by default (`APP_ENV` defaults to `production`); see
[nginx/README.md](nginx/README.md) for details and production certificates.

> **Why `/docs` is blank behind the prod proxy:** the strict
> `Content-Security-Policy` blocks Swagger's CDN assets by design. Use the dev
> stack for interactive API exploration.

### Without Docker (local Python)

```bash
pip install -r requirements.txt
# SECRET_KEY and DATABASE_URL are REQUIRED — the app refuses to start without them.
export SECRET_KEY="$(openssl rand -hex 32)"
export DATABASE_URL="sqlite:///./dev.db"   # or a postgres URL
export APP_ENV=development
uvicorn main:app --reload                  # → http://localhost:8000/docs
```

## Environment Variables

`SECRET_KEY` and `DATABASE_URL` are **required** — there are no insecure
fallback defaults, so the app will not start if they are unset. See
[.env.example](.env.example) for the full list used by the Docker stacks.

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | ✅ | JWT signing secret (≥32 bytes — `openssl rand -hex 32`) |
| `DATABASE_URL` | ✅ | SQLAlchemy connection string (e.g. `postgresql+psycopg2://…` or `sqlite:///./dev.db`) |
| `APP_ENV` | — | `development` enables `/docs`; defaults to `production` (docs off) |
| `CORS_ALLOW_ORIGINS` | — | Comma-separated allowed origins (empty = none) |

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
| GET | `/users/` | ✅ Admin | List all active users |
| GET | `/users/{id}` | ✅ Owner/Admin | Get user by ID |
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
  -d '{"email":"seller@shop.com","username":"seller1","password":"secret123"}'

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
