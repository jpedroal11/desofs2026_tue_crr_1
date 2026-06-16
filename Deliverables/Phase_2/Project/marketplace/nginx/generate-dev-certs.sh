#!/usr/bin/env sh
# Generate a SELF-SIGNED TLS certificate for local/staging use only.
#
# Production MUST use a CA-issued certificate (e.g. Let's Encrypt) — see
# nginx/README.md. Browsers and clients will warn on self-signed certs; that is
# expected for staging.
#
# The subject and SANs are supplied via a temporary openssl config file rather
# than -subj/-addext so the script behaves the same on Linux, macOS, and
# Windows Git Bash (which otherwise rewrites the POSIX-looking -subj string).
set -e

CERT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/certs"
mkdir -p "$CERT_DIR"

CONF="$(mktemp)"
trap 'rm -f "$CONF"' EXIT
cat > "$CONF" <<'EOF'
[req]
distinguished_name = dn
x509_extensions    = v3_req
prompt             = no
[dn]
C  = PT
ST = Porto
L  = Porto
O  = SecureMarket
CN = localhost
[v3_req]
subjectAltName = @alt
[alt]
DNS.1 = localhost
IP.1  = 127.0.0.1
EOF

openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
  -keyout "$CERT_DIR/privkey.pem" \
  -out "$CERT_DIR/fullchain.pem" \
  -config "$CONF"

chmod 600 "$CERT_DIR/privkey.pem"
echo "Self-signed certificate written to $CERT_DIR (fullchain.pem, privkey.pem)"
