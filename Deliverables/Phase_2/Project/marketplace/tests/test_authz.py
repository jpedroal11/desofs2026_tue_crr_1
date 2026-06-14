class TestIDOR:
    """SR-AUTHZ-02, SR-AUTHZ-04, MST-05"""

    def test_buyer_cannot_access_another_buyers_order(
        self, buyer_a_client, buyer_b_order_id
    ):
        response = buyer_a_client.get(
            f"/orders/{buyer_b_order_id}"
        )
        assert response.status_code == 403

    def test_seller_cannot_modify_another_sellers_product(
        self, seller_a_client, seller_b_product_id
    ):
        response = seller_a_client.patch(
            f"/products/{seller_b_product_id}",
            json={"title": "hacked"}
        )
        assert response.status_code == 403

    def test_buyer_cannot_access_admin_endpoints(self, buyer_client):
        """SR-AUTHZ-01, MST-08"""
        response = buyer_client.post(
            f"/auth/user/register",
            json={"email": "test@example.com", "username": "testuser", "full_name": "Test User", "password": "password123", "roles": ["ADMIN"]}
        )
        assert response.status_code == 403

    def test_role_field_cannot_be_self_assigned(
        self, buyer_client, seed_buyer
    ):
        """SR-AUTHZ-03, MST-07"""
        response = buyer_client.patch(
            f"/users/{seed_buyer['id']}",
            json={"role": "ADMIN"}
        )
        # Either rejected outright or field silently ignored
        if response.status_code == 200:
            assert all(
                role.get("name") != "ADMIN"
                for role in response.json().get("roles", [])
            )
        else:
            assert response.status_code == 403