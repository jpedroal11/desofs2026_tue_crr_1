class TestIDOR:
    """SR-AUTHZ-02, SR-AUTHZ-04, MST-05"""

    def test_buyer_cannot_access_another_buyers_order(
        self, buyer_a_client, buyer_b_order_id
    ):
        response = buyer_a_client.get(
            f"/api/v1/orders/{buyer_b_order_id}"
        )
        assert response.status_code == 403

    def test_seller_cannot_modify_another_sellers_product(
        self, seller_a_client, seller_b_product_id
    ):
        response = seller_a_client.put(
            f"/api/v1/products/{seller_b_product_id}",
            json={"title": "hacked"}
        )
        assert response.status_code == 403

    def test_buyer_cannot_access_admin_endpoints(self, buyer_client):
        """SR-AUTHZ-01, MST-08"""
        assert buyer_client.get("/api/v1/users").status_code == 403
        assert buyer_client.get("/api/v1/audit-log").status_code == 403

    def test_role_field_cannot_be_self_assigned(
        self, buyer_client, seed_buyer
    ):
        """SR-AUTHZ-03, MST-07"""
        response = buyer_client.put(
            f"/api/v1/users/{seed_buyer['id']}",
            json={"role": "ADMIN"}
        )
        # Either rejected outright or field silently ignored
        if response.status_code == 200:
            assert response.json()["role"] != "ADMIN"
        else:
            assert response.status_code == 403