import pytest
from fastapi.testclient import TestClient
from main import app
from core.dependencies import SessionLocal, get_db
import sys

client = TestClient(app)

def _payload(email="bob@x.com", username="bob", password="Str0ng!Password123", role="Buyer"):
    return {
        "email": email,
        "username": username,
        "full_name": "Test User",
        "password": password,
        "roles": [role],
    }

print("Registering...")
r1 = client.post("/auth/register", json=_payload())
print(r1.status_code, r1.json())

print("Requesting token...")
r2 = client.post("/auth/password-reset/request", json={"email": "bob@x.com"})
print(r2.status_code, r2.json())

token = r2.json().get("_dev_token")
print("Token is:", token)

print("Confirming...")
r3 = client.post("/auth/password-reset/confirm", json={"token": token, "new_password": "BreachedPassword123!"})
print(r3.status_code, r3.json())

