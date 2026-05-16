import pytest
from main import app
from middleware.auth import get_current_user
from models.models import ProductStatus

def authenticate_as(client, user):
    app.dependency_overrides[get_current_user] = lambda: user

def clear_auth(client):
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

def test_create_product(client, seller_user):
    authenticate_as(client, seller_user)
    payload = {
        "name": "Test Product",
        "description": "A great product",
        "price": 99.99,
        "stock": 0
    }
    response = client.post("/products/", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Product"
    assert data["status"] == "draft"  # Default status
    assert data["stock"] == 0
    clear_auth(client)

def test_update_product_status(client, seller_user):
    authenticate_as(client, seller_user)
    # Create product
    payload = {"name": "Status Product", "price": 10.0, "stock": 0}
    res = client.post("/products/", json=payload)
    product_id = res.json()["id"]
    
    # Transition to active
    response = client.patch(f"/products/{product_id}/status", json={"status": "active"})
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    clear_auth(client)

def test_list_active_products_in_stock(client, seller_user):
    authenticate_as(client, seller_user)
    # 1. Draft product (should not appear)
    client.post("/products/", json={"name": "P1", "price": 10, "stock": 10})
    
    # 2. Active but no stock (should not appear)
    res2 = client.post("/products/", json={"name": "P2", "price": 10, "stock": 0})
    p2_id = res2.json()["id"]
    client.patch(f"/products/{p2_id}/status", json={"status": "active"})
    
    # 3. Active with stock (should appear)
    res3 = client.post("/products/", json={"name": "P3", "price": 10, "stock": 5})
    p3_id = res3.json()["id"]
    client.patch(f"/products/{p3_id}/status", json={"status": "active"})

    clear_auth(client)

    response = client.get("/products/")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "P3"

def test_stock_management(client, seller_user):
    authenticate_as(client, seller_user)
    # Create product
    res = client.post("/products/", json={"name": "Stock Product", "price": 10.0, "stock": 10})
    product_id = res.json()["id"]

    # Add stock
    res_add = client.post(f"/products/{product_id}/stock/add", json={"quantity": 5})
    assert res_add.status_code == 200
    assert res_add.json()["stock"] == 15

    # Reduce stock
    res_reduce = client.post(f"/products/{product_id}/stock/reduce", json={"quantity": 10})
    assert res_reduce.status_code == 200
    assert res_reduce.json()["stock"] == 5

    # Reduce below zero
    res_fail = client.post(f"/products/{product_id}/stock/reduce", json={"quantity": 10})
    assert res_fail.status_code == 400
    assert res_fail.json()["detail"] == "Insufficient stock"
    
    # Invalid stock adjustment (quantity <= 0)
    res_invalid = client.post(f"/products/{product_id}/stock/add", json={"quantity": -5})
    assert res_invalid.status_code == 422 # Pydantic validation error

    clear_auth(client)

def test_delete_product(client, seller_user):
    authenticate_as(client, seller_user)
    # Create product
    res = client.post("/products/", json={"name": "Delete Product", "price": 10.0, "stock": 10})
    product_id = res.json()["id"]

    # Delete product
    del_res = client.delete(f"/products/{product_id}")
    assert del_res.status_code == 204

    # Verify status is archived
    get_res = client.get(f"/products/{product_id}")
    assert get_res.status_code == 200
    assert get_res.json()["status"] == "archived"

    clear_auth(client)

def test_list_products_filters(client, seller_user):
    authenticate_as(client, seller_user)
    
    # P1: $10, P2: $20, P3: $30
    res1 = client.post("/products/", json={"name": "P1", "price": 10.0, "stock": 5})
    res2 = client.post("/products/", json={"name": "P2", "price": 20.0, "stock": 5})
    res3 = client.post("/products/", json={"name": "P3", "price": 30.0, "stock": 5})
    
    client.patch(f"/products/{res1.json()['id']}/status", json={"status": "active"})
    client.patch(f"/products/{res2.json()['id']}/status", json={"status": "active"})
    client.patch(f"/products/{res3.json()['id']}/status", json={"status": "active"})
    clear_auth(client)

    # Test min_price
    res_min = client.get("/products/?min_price=15")
    assert len(res_min.json()) >= 2
    for p in res_min.json(): assert p["price"] >= 15

    # Test max_price
    res_max = client.get("/products/?max_price=25")
    for p in res_max.json(): assert p["price"] <= 25

    # Test seller_id
    res_seller = client.get(f"/products/?seller_id={seller_user.id}")
    assert len(res_seller.json()) >= 3

def test_create_product_forbidden(client, buyer_user):
    authenticate_as(client, buyer_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    assert res.status_code == 403
    clear_auth(client)

def test_update_product(client, seller_user, buyer_user):
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]

    # Valid update
    res_up = client.patch(f"/products/{p_id}", json={"name": "P_updated"})
    assert res_up.status_code == 200
    assert res_up.json()["name"] == "P_updated"
    clear_auth(client)

    # Forbidden
    authenticate_as(client, buyer_user)
    res_403 = client.patch(f"/products/{p_id}", json={"name": "P_bad"})
    assert res_403.status_code == 403
    clear_auth(client)

    # Not found
    authenticate_as(client, seller_user)
    res_404 = client.patch("/products/9999", json={"name": "P_bad"})
    assert res_404.status_code == 404
    clear_auth(client)

def test_delete_product_forbidden_404(client, seller_user, buyer_user):
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    clear_auth(client)

    # Forbidden
    authenticate_as(client, buyer_user)
    res_403 = client.delete(f"/products/{p_id}")
    assert res_403.status_code == 403
    clear_auth(client)

    # Not found
    authenticate_as(client, seller_user)
    res_404 = client.delete("/products/9999")
    assert res_404.status_code == 404
    clear_auth(client)

def test_update_product_status_forbidden_404(client, seller_user, buyer_user):
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    clear_auth(client)

    authenticate_as(client, buyer_user)
    assert client.patch(f"/products/{p_id}/status", json={"status": "active"}).status_code == 403
    clear_auth(client)

    authenticate_as(client, seller_user)
    assert client.patch("/products/9999/status", json={"status": "active"}).status_code == 404
    clear_auth(client)

def test_stock_add_forbidden_404(client, seller_user, buyer_user):
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    clear_auth(client)

    authenticate_as(client, buyer_user)
    assert client.post(f"/products/{p_id}/stock/add", json={"quantity": 1}).status_code == 403
    clear_auth(client)

    authenticate_as(client, seller_user)
    assert client.post("/products/9999/stock/add", json={"quantity": 1}).status_code == 404
    clear_auth(client)

def test_stock_reduce_forbidden_404(client, seller_user, buyer_user):
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    clear_auth(client)

    authenticate_as(client, buyer_user)
    assert client.post(f"/products/{p_id}/stock/reduce", json={"quantity": 1}).status_code == 403
    clear_auth(client)

    authenticate_as(client, seller_user)
    assert client.post("/products/9999/stock/reduce", json={"quantity": 1}).status_code == 404
    clear_auth(client)
