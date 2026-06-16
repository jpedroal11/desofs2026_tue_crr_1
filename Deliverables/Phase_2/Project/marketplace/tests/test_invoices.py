import os
import pytest
from main import app
from middleware.auth import get_current_user
from services.invoice_service import invoice_path_for_order
from models.models import Order
from uuid import UUID

def authenticate_as(client, user):
    app.dependency_overrides[get_current_user] = lambda: user

def clear_auth(client):
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]

def test_invoice_generation_ssti_protection(client, seller_user, buyer_user, db_session):
    # 1. Create a product with SSTI payload in name as seller
    authenticate_as(client, seller_user)
    res = client.post(
        "/products/",
        json={"name": "Product Title {{7*7}}", "price": 15.0, "stock": 10}
    )
    assert res.status_code == 201
    product_id = res.json()["id"]
    
    # Activate the product
    res_status = client.patch(f"/products/{product_id}/status", json={"status": "active"})
    assert res_status.status_code == 200
    clear_auth(client)

    # 2. Place an order with SSTI payload in shipping address as buyer
    authenticate_as(client, buyer_user)
    payload = {
        "shipping_address": "Shipping Address {{7*7}}",
        "items": [
            {"product_id": product_id, "quantity": 1}
        ]
    }
    res_order = client.post("/orders/", json=payload)
    assert res_order.status_code == 201
    order_id = res_order.json()["id"]
    clear_auth(client)

    # 3. Seller confirms the order (triggering invoice generation)
    authenticate_as(client, seller_user)
    res_confirm = client.patch(f"/orders/{order_id}", json={"status": "confirmed"})
    assert res_confirm.status_code == 200
    clear_auth(client)

    # 4. Fetch the order from the DB to locate the generated invoice PDF
    order = db_session.query(Order).filter(Order.id == UUID(order_id)).first()
    assert order is not None
    assert order.invoice_filename is not None

    pdf_path = invoice_path_for_order(order)
    assert os.path.exists(pdf_path)

    # 5. Read and verify the PDF content
    with open(pdf_path, "rb") as f:
        pdf_content = f.read()

    import re
    # Extract only the literal text strings drawn in the PDF
    pdf_strings = re.findall(b"\\((.*?)\\)", pdf_content)
    pdf_texts = [s.decode("utf-8", errors="ignore") for s in pdf_strings]

    # The payload {{7*7}} is sanitized by stripping `{`, `}`, `%`, so it becomes "7*7"
    assert any("7*7" in text for text in pdf_texts)
    # It must NOT be executed to "49"
    assert not any("49" in text for text in pdf_texts)

    # Clean up the generated invoice PDF
    try:
        os.unlink(pdf_path)
    except OSError:
        pass
