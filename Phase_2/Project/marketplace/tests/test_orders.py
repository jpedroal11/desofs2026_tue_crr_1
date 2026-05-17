import pytest
from main import app
from middleware.auth import get_current_user

def authenticate_as(client, user):
    app.dependency_overrides[get_current_user] = lambda: user

def clear_auth(client):
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

def test_list_my_orders(client, buyer_user):
    authenticate_as(client, buyer_user)
    res = client.get("/orders/")
    assert res.status_code == 200
    assert res.json() == []
    clear_auth(client)

def test_create_order_happy_path(client, seller_user, buyer_user):
    # 1. Create a product as seller
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P1", "price": 10.0, "stock": 5})
    assert res.status_code == 201
    p1_id = res.json()["id"]
    client.patch(f"/products/{p1_id}/status", json={"status": "active"})
    clear_auth(client)

    # 2. Create order as buyer
    authenticate_as(client, buyer_user)
    payload = {
        "shipping_address": "123 Main St",
        "items": [
            {"product_id": p1_id, "quantity": 2}
        ]
    }
    res = client.post("/orders/", json=payload)
    assert res.status_code == 201
    order_data = res.json()
    assert order_data["total_amount"] == 20.0
    assert order_data["shipping_address"] == "123 Main St"
    order_id = order_data["id"]

    # Verify stock deducted
    res_product = client.get(f"/products/{p1_id}")
    assert res_product.json()["stock"] == 3

    # List orders
    res_list = client.get("/orders/")
    assert len(res_list.json()) == 1

    # Get specific order
    res_get = client.get(f"/orders/{order_id}")
    assert res_get.status_code == 200
    assert res_get.json()["id"] == order_id
    clear_auth(client)

def test_create_order_errors(client, seller_user, buyer_user):
    # Setup product
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P2", "price": 10.0, "stock": 2})
    p2_id = res.json()["id"]
    client.patch(f"/products/{p2_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    
    # 1. No items
    res = client.post("/orders/", json={"shipping_address": "X", "items": []})
    assert res.status_code == 400

    # 2. Product not found
    res = client.post("/orders/", json={"shipping_address": "X", "items": [{"product_id": "00000000-0000-0000-0000-000000000000", "quantity": 1}]})
    assert res.status_code == 404

    # 3. Insufficient stock
    res = client.post("/orders/", json={"shipping_address": "X", "items": [{"product_id": p2_id, "quantity": 5}]})
    assert res.status_code == 400

    clear_auth(client)

def test_order_auth_errors(client, seller_user, buyer_user):
    # Setup order
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P3", "price": 10.0, "stock": 5})
    p3_id = res.json()["id"]
    client.patch(f"/products/{p3_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "A", "items": [{"product_id": p3_id, "quantity": 1}]})
    order_id = res.json()["id"]
    clear_auth(client)

    # Access as seller (who is not the buyer)
    authenticate_as(client, seller_user)
    assert client.get(f"/orders/{order_id}").status_code == 403
    assert client.patch(f"/orders/{order_id}", json={"shipping_address": "B"}).status_code == 403
    assert client.delete(f"/orders/{order_id}").status_code == 403
    clear_auth(client)

    # Access non-existent
    authenticate_as(client, buyer_user)
    assert client.get("/orders/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.patch("/orders/00000000-0000-0000-0000-000000000000", json={"shipping_address": "B"}).status_code == 404
    assert client.delete("/orders/00000000-0000-0000-0000-000000000000").status_code == 404
    clear_auth(client)

def test_update_order(client, seller_user, buyer_user):
    # Setup
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P4", "price": 10.0, "stock": 5})
    p4_id = res.json()["id"]
    client.patch(f"/products/{p4_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "A", "items": [{"product_id": p4_id, "quantity": 1}]})
    order_id = res.json()["id"]

    res_patch = client.patch(f"/orders/{order_id}", json={"shipping_address": "New Address"})
    assert res_patch.status_code == 200
    assert res_patch.json()["shipping_address"] == "New Address"
    clear_auth(client)

def test_cancel_order(client, seller_user, buyer_user):
    # Setup
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P5", "price": 10.0, "stock": 5})
    p5_id = res.json()["id"]
    client.patch(f"/products/{p5_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "A", "items": [{"product_id": p5_id, "quantity": 1}]})
    order_id = res.json()["id"]

    res_cancel = client.delete(f"/orders/{order_id}")
    assert res_cancel.status_code == 204

    # Verify stock restored
    res_product = client.get(f"/products/{p5_id}")
    assert res_product.json()["stock"] == 5

    # Cannot cancel cancelled order
    res_cancel_again = client.delete(f"/orders/{order_id}")
    assert res_cancel_again.status_code == 400
    clear_auth(client)
