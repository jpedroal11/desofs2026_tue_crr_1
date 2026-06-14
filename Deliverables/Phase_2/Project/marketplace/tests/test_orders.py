import pytest
from main import app
from middleware.auth import get_current_user
from models.models import Role, User

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


def test_only_seller_can_change_order_status(client, seller_user, buyer_user):
    # Setup order from buyer and seller
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P6", "price": 10.0, "stock": 5})
    p6_id = res.json()["id"]
    client.patch(f"/products/{p6_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "A", "items": [{"product_id": p6_id, "quantity": 1}]})
    order_id = res.json()["id"]
    clear_auth(client)

    # Buyer cannot change status
    authenticate_as(client, buyer_user)
    res_buyer_status = client.patch(f"/orders/{order_id}", json={"status": "shipped"})
    assert res_buyer_status.status_code == 403
    clear_auth(client)

    # Seller can change status for their product order
    authenticate_as(client, seller_user)
    res_seller_status = client.patch(f"/orders/{order_id}", json={"status": "shipped"})
    assert res_seller_status.status_code == 200
    assert res_seller_status.json()["status"] == "shipped"
    clear_auth(client)


def test_shipping_address_only_editable_while_pending(client, seller_user, buyer_user):
    # Setup order
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "P7", "price": 10.0, "stock": 5})
    p7_id = res.json()["id"]
    client.patch(f"/products/{p7_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "Start", "items": [{"product_id": p7_id, "quantity": 1}]})
    order_id = res.json()["id"]
    clear_auth(client)

    # Seller marks order as shipped
    authenticate_as(client, seller_user)
    res_seller_status = client.patch(f"/orders/{order_id}", json={"status": "shipped"})
    assert res_seller_status.status_code == 200
    clear_auth(client)

    # Buyer tries to update shipping address -> forbidden
    authenticate_as(client, buyer_user)
    res_buyer_patch = client.patch(f"/orders/{order_id}", json={"shipping_address": "New Addr"})
    assert res_buyer_patch.status_code == 403
    clear_auth(client)


def test_order_cannot_span_multiple_sellers(client, seller_user, buyer_user, db_session):
    """Ensure an order can only contain products from a single seller."""
    # Create seller B
    seller_b = User(
        email="seller_b@example.com",
        username="seller_b",
        hashed_password="hashed_password",
    )
    seller_b.roles = [db_session.query(Role).filter(Role.name == "Seller").first()]
    db_session.add(seller_b)
    db_session.commit()
    db_session.refresh(seller_b)

    # Create products from seller A and seller B
    authenticate_as(client, seller_user)
    res_a = client.post("/products/", json={"name": "A1", "price": 10.0, "stock": 5})
    p_a_id = res_a.json()["id"]
    client.patch(f"/products/{p_a_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, seller_b)
    res_b = client.post("/products/", json={"name": "B1", "price": 20.0, "stock": 5})
    p_b_id = res_b.json()["id"]
    client.patch(f"/products/{p_b_id}/status", json={"status": "active"})
    clear_auth(client)

    # Buyer tries to order from both sellers -> should fail
    authenticate_as(client, buyer_user)
    payload = {
        "shipping_address": "123 Main St",
        "items": [
            {"product_id": p_a_id, "quantity": 1},
            {"product_id": p_b_id, "quantity": 1}
        ]
    }
    res = client.post("/orders/", json=payload)
    assert res.status_code == 400
    assert "same seller" in res.json()["detail"].lower()
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



def test_cannot_cancel_non_pending_order(client, seller_user, buyer_user):
    """MST-16: Can only cancel orders in pending state."""
    # Setup
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "CancelTestProd", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    client.patch(f"/products/{p_id}/status", json={"status": "active"})
    clear_auth(client)

    # Create order as buyer
    authenticate_as(client, buyer_user)
    res = client.post("/orders/", json={"shipping_address": "A", "items": [{"product_id": p_id, "quantity": 1}]})
    order_id = res.json()["id"]
    clear_auth(client)

    # Seller marks order as shipped
    authenticate_as(client, seller_user)
    res_ship = client.patch(f"/orders/{order_id}", json={"status": "shipped"})
    assert res_ship.status_code == 200
    clear_auth(client)

    # Buyer tries to cancel shipped order -> should fail
    authenticate_as(client, buyer_user)
    res_cancel = client.delete(f"/orders/{order_id}")
    assert res_cancel.status_code in (400, 422), f"Expected 400/422 but got {res_cancel.status_code}: {res_cancel.json()}"
    clear_auth(client)



def test_invoice_download_only_requester_can_access(client, seller_user, buyer_user, db_session):
    """MST-NEW-05: Only the buyer (or admin) can download an order's invoice."""
    # Create a second buyer in the DB
    buyer_b = User(email="buyer_b@example.com", username="buyer_b", hashed_password="hashed")
    buyer_b.roles = [db_session.query(Role).filter(Role.name == "Buyer").first()]
    db_session.add(buyer_b)
    db_session.commit()
    db_session.refresh(buyer_b)

    # Seller creates a product
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "InvoiceProd", "price": 5.0, "stock": 5})
    p_id = res.json()["id"]
    client.patch(f"/products/{p_id}/status", json={"status": "active"})
    clear_auth(client)

    # Buyer B places an order
    authenticate_as(client, buyer_b)
    order_res = client.post("/orders/", json={"shipping_address": "Addr", "items": [{"product_id": p_id, "quantity": 1}]})
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]
    clear_auth(client)

    # Buyer A (existing fixture) attempts to download Buyer B's invoice -> forbidden
    authenticate_as(client, buyer_user)
    r = client.get(f"/orders/{order_id}/invoice")
    assert r.status_code == 403
    clear_auth(client)


def test_invalid_order_status_transition_rejected(client, seller_user, buyer_user):
    """MST-15: Invalid order status transitions must be rejected."""
    # Create product and order
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "StatusProd", "price": 10.0, "stock": 5})
    p_id = res.json()["id"]
    client.patch(f"/products/{p_id}/status", json={"status": "active"})
    clear_auth(client)

    authenticate_as(client, buyer_user)
    order_res = client.post("/orders/", json={"shipping_address": "Addr", "items": [{"product_id": p_id, "quantity": 1}]})
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]
    clear_auth(client)

    # Seller marks order as delivered
    authenticate_as(client, seller_user)
    r1 = client.patch(f"/orders/{order_id}", json={"status": "delivered"})
    assert r1.status_code == 200
    clear_auth(client)

    # Attempt to revert to pending (invalid backward transition) -> should be rejected
    authenticate_as(client, seller_user)
    r2 = client.patch(f"/orders/{order_id}", json={"status": "pending"})
    assert r2.status_code in (400, 422)
    clear_auth(client)


def test_generated_pdf_permissions(client, seller_user, buyer_user, db_session):
    import stat
    from services.invoice_service import invoice_path_for_order
    from models.models import Order

    # Seller creates a product
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "InvoiceProd", "price": 5.0, "stock": 5})
    p_id = res.json()["id"]
    client.patch(f"/products/{p_id}/status", json={"status": "active"})
    clear_auth(client)

    # Buyer places an order
    authenticate_as(client, buyer_user)
    order_res = client.post("/orders/", json={"shipping_address": "Addr", "items": [{"product_id": p_id, "quantity": 1}]})
    assert order_res.status_code == 201
    order_id = order_res.json()["id"]

    # Download invoice -> triggers PDF generation
    r = client.get(f"/orders/{order_id}/invoice")
    assert r.status_code == 200
    clear_auth(client)

    # Find file path and verify permissions
    import os
    import uuid as std_uuid
    order = db_session.query(Order).filter(Order.id == std_uuid.UUID(order_id)).first()
    path = invoice_path_for_order(order)
    assert os.path.exists(path)

    # Programmatically evaluate file status bits
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o640

    # Cleanup generated invoice file
    try:
        os.unlink(path)
    except Exception:
        pass
