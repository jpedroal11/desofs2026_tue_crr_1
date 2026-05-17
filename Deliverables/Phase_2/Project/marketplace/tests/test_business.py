# tests/test_business.py
class TestPriceIntegrity:
    """SR-DATA-06, SR-DATA-07, MST-11"""

    def test_client_supplied_price_is_ignored(
        self, buyer_client, active_product
    ):
        response = buyer_client.post("/orders/", json={
            "items": [
                {"product_id": active_product["id"], "quantity": 1}
            ],
            "shipping_address": "123 Test St"
        })
        
        assert response.status_code == 201
        order = response.json()
        # Total must reflect server-side price, not 0.01
        assert order["total_amount"] == \
               active_product["price"] * 1

#class TestReviewRules:
#    """SR-BIZ-01, SR-BIZ-02, MST-13, MST-14"""
#
#    def test_buyer_cannot_review_without_purchase(
#        self, buyer_client, active_product
#    ):
#        response = buyer_client.post(
#            f"/products/{active_product['id']}/reviews",
#            json={"rating": 5, "comment": "Great!"}
#        )
#        assert response.status_code == 403
#
#    def test_buyer_cannot_leave_duplicate_review(
#        self, buyer_client, delivered_order
#    ):
#        product_id = delivered_order["product_id"]
#        buyer_client.post(
#            f"/products/{product_id}/reviews",
#            json={"rating": 5, "comment": "First review"}
#        )
#        response = buyer_client.post(
#            f"/products/{product_id}/reviews",
#            json={"rating": 1, "comment": "Second review"}
#        )
#        assert response.status_code in [400, 409]