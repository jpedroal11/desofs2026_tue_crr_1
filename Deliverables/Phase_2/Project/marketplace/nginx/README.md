# Nginx reverse proxy (TLS termination)

Nginx sits in front of the FastAPI app and is the only service exposed to the
network. It terminates TLS, redirects HTTP→HTTPS, sets HSTS and hardening
headers, and proxies to the app over the internal Docker network.

## What it enforces

- **HTTP→HTTPS**: all port-80 traffic gets a `301` to `https://` (except the
  ACME challenge path used for Let's Encrypt).
- **TLS**: TLSv1.2 + TLSv1.3 only, modern cipher suite, sessions cached, tickets off.
- **HSTS**: `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload`.
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer`, a strict `Content-Security-Policy`, and
  `server_tokens off` (no version leak).
- **Body limit**: `client_max_body_size 10m`, matching the app's image-upload cap.

## Local / staging certificates (self-signed)

```sh
./nginx/generate-dev-certs.sh
```

Writes `nginx/certs/fullchain.pem` and `nginx/certs/privkey.pem` (gitignored).
Clients will warn about the self-signed cert — that is expected for staging.

## Run the stack

```sh
cp .env.example .env        # fill in real secrets
./nginx/generate-dev-certs.sh
docker compose -f docker-compose.prod.yml up --build
```

Then browse to `https://localhost/` (accept the staging cert warning) or
`https://localhost/docs` if `APP_ENV` is not `production`.

## Production certificates

Do **not** ship the self-signed cert. Use a CA-issued certificate:

1. **Let's Encrypt (recommended)** — add a `certbot` container that writes to a
   shared volume and serves the `/.well-known/acme-challenge/` path (already
   passed through in `nginx.conf`). Point `ssl_certificate` /
   `ssl_certificate_key` at the issued `fullchain.pem` / `privkey.pem`.
2. **Provided cert** — mount your CA cert chain and key over
   `/etc/nginx/certs/fullchain.pem` and `/etc/nginx/certs/privkey.pem`.

Only submit a domain to the HSTS preload list once HTTPS is permanent — the
`preload` directive is hard to reverse.

## Notes

- The app trusts `X-Forwarded-Proto` / `X-Forwarded-For` from the proxy; the
  Dockerfile already runs uvicorn with `--forwarded-allow-ips *`.
- `sslmode=require` on the DB connection is a separate task (Postgres TLS); the
  app↔DB hop is currently on the internal network only.
