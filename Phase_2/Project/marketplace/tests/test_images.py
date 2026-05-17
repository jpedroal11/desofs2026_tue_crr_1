"""Tests for secure image upload, serving, and deletion."""

import hashlib
import io
import os
from uuid import UUID

import pytest
from main import app
from middleware.auth import get_current_user
from core import image_service


def authenticate_as(client, user):
    app.dependency_overrides[get_current_user] = lambda: user


def clear_auth(client):
    if get_current_user in app.dependency_overrides:
        del app.dependency_overrides[get_current_user]


def _create_product(client, seller_user):
    """Helper: create a draft product and return its ID."""
    authenticate_as(client, seller_user)
    res = client.post("/products/", json={"name": "Img Product", "price": 10.0, "stock": 5})
    assert res.status_code == 201
    return res.json()["id"]


# ── Upload: happy paths ──────────────────────────────────────────────────────


class TestUploadValidImages:

    def test_upload_jpeg(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        data = res.json()
        assert data["mime_type"] == "image/jpeg"
        assert data["filename"].endswith(".jpg")
        assert data["original_filename"] == "photo.jpg"
        assert data["sha256_hash"] == hashlib.sha256(jpeg_bytes).hexdigest()
        clear_auth(client)

    def test_upload_png(self, client, seller_user, png_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("image.png", io.BytesIO(png_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        assert res.json()["mime_type"] == "image/png"
        assert res.json()["filename"].endswith(".png")
        clear_auth(client)

    def test_upload_gif(self, client, seller_user, gif_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("anim.gif", io.BytesIO(gif_bytes), "image/gif")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        assert res.json()["mime_type"] == "image/gif"
        clear_auth(client)


# ── Upload: validation failures ──────────────────────────────────────────────


class TestUploadValidationFailures:

    def test_reject_bad_magic_bytes(self, client, seller_user):
        """An .exe disguised as .jpg must be rejected."""
        product_id = _create_product(client, seller_user)
        fake_content = b"MZ" + b"\x00" * 100  # PE/EXE header
        files = {"file": ("malware.jpg", io.BytesIO(fake_content), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "magic-byte" in res.json()["detail"].lower() or "does not match" in res.json()["detail"].lower()
        clear_auth(client)

    def test_reject_wrong_content_type(self, client, seller_user, jpeg_bytes):
        """Valid JPEG sent with wrong Content-Type header must be rejected."""
        product_id = _create_product(client, seller_user)
        files = {"file": ("photo.png", io.BytesIO(jpeg_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "does not match" in res.json()["detail"].lower()
        clear_auth(client)

    def test_reject_disallowed_mime(self, client, seller_user):
        """application/pdf must be rejected."""
        product_id = _create_product(client, seller_user)
        pdf_bytes = b"%PDF-1.4" + b"\x00" * 100
        files = {"file": ("doc.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "not allowed" in res.json()["detail"].lower()
        clear_auth(client)

    def test_upload_rejects_file_over_10mb(self, client, seller_user):
        product_id = _create_product(client, seller_user)
        # Create a file of 10 MB + 1 byte
        big_content = b"a" * (10 * 1024 * 1024 + 1)
        files = {"file": ("big.jpg", io.BytesIO(big_content), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 422
        assert "exceeds maximum allowed size of 10 MB" in res.json()["detail"]
        clear_auth(client)

    def test_upload_rejects_at_10_images(self, client, seller_user, db_session, jpeg_bytes):
        from models.models import ProductImage
        product_id = _create_product(client, seller_user)
        product_uuid = UUID(product_id)

        # Create 10 existing image records in DB
        for i in range(10):
            img = ProductImage(
                product_id=product_uuid,
                filename=f"test_{i}.jpg",
                original_filename=f"test_{i}.jpg",
                mime_type="image/jpeg",
                file_size=1024,
                sha256_hash="dummy"
            )
            db_session.add(img)
        db_session.commit()
        
        authenticate_as(client, seller_user)
        files = {"file": ("img_extra.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "Maximum number of images per product reached (10)" in res.json()["detail"]
        clear_auth(client)

    def test_upload_rejects_when_quota_exceeded(self, client, seller_user, jpeg_bytes, monkeypatch):
        product_id = _create_product(client, seller_user)
        from repositories import image_repository
        monkeypatch.setattr(image_repository, "total_storage_by_seller", lambda *args: 200 * 1024 * 1024)
        
        files = {"file": ("quota.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "Storage quota exceeded. Maximum 200 MB per seller." in res.json()["detail"]
        clear_auth(client)

    def test_upload_succeeds_just_under_quota(self, client, seller_user, jpeg_bytes, monkeypatch):
        product_id = _create_product(client, seller_user)
        from repositories import image_repository
        
        half_mb = int(0.5 * 1024 * 1024)
        mock_storage = 199 * 1024 * 1024
        monkeypatch.setattr(image_repository, "total_storage_by_seller", lambda *args: mock_storage)
        
        padded_jpeg = jpeg_bytes[:-2] + b"\x00" * (half_mb - len(jpeg_bytes)) + b"\xff\xd9"
        files = {"file": ("under_quota.jpg", io.BytesIO(padded_jpeg), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        clear_auth(client)

    def test_file_size_bytes_persisted(self, client, seller_user, jpeg_bytes, db_session):
        product_id = _create_product(client, seller_user)
        files = {"file": ("persisted.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        
        from models.models import ProductImage
        image_id = res.json()["id"]
        db_img = db_session.query(ProductImage).filter_by(id=UUID(image_id)).first()
        assert db_img is not None
        assert db_img.file_size == len(jpeg_bytes)
        clear_auth(client)


# ── UUID naming ──────────────────────────────────────────────────────────────


class TestUUIDNaming:

    def test_filename_is_uuid(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("my_photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        filename = res.json()["filename"]
        name_part = filename.rsplit(".", 1)[0]
        # Should be a valid UUID4
        parsed = uuid.UUID(name_part, version=4)
        assert str(parsed) == name_part
        clear_auth(client)

    def test_original_filename_preserved(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("my_original_photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        assert res.json()["original_filename"] == "my_original_photo.jpg"
        clear_auth(client)


# ── SHA-256 hashing ──────────────────────────────────────────────────────────


class TestSHA256:

    def test_sha256_matches_content(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("hash_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        expected = hashlib.sha256(jpeg_bytes).hexdigest()
        assert res.json()["sha256_hash"] == expected
        clear_auth(client)

    def test_same_content_same_hash(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)

        files1 = {"file": ("a.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res1 = client.post(f"/products/{product_id}/images", files=files1)
        files2 = {"file": ("b.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res2 = client.post(f"/products/{product_id}/images", files=files2)

        assert res1.json()["sha256_hash"] == res2.json()["sha256_hash"]
        # But filenames must differ (different UUIDs)
        assert res1.json()["filename"] != res2.json()["filename"]
        clear_auth(client)


# ── Path traversal prevention ────────────────────────────────────────────────


class TestPathTraversal:

    def test_reject_dotdot_in_serve(self, client):
        res = client.get("/images/../../etc/passwd")
        assert res.status_code in (400, 404)

    def test_reject_absolute_path_in_serve(self, client):
        res = client.get("/images//etc/passwd")
        assert res.status_code in (400, 404)

    def test_serve_valid_uuid_filename(self, client, seller_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("serve_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        upload_res = client.post(f"/products/{product_id}/images", files=files)
        assert upload_res.status_code == 201

        filename = upload_res.json()["filename"]
        serve_res = client.get(f"/images/{filename}")
        assert serve_res.status_code == 200
        assert serve_res.headers["content-type"] == "image/jpeg"
        clear_auth(client)


# ── File permissions ─────────────────────────────────────────────────────────


class TestFilePermissions:

    def test_uploaded_file_has_0640(self, client, seller_user, jpeg_bytes, tmp_upload_dir):
        product_id = _create_product(client, seller_user)
        files = {"file": ("perms.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        filename = res.json()["filename"]
        file_path = tmp_upload_dir / filename
        mode = oct(file_path.stat().st_mode)[-4:]
        assert mode == "0640", f"Expected 0640, got {mode}"
        clear_auth(client)


# ── Authorization ────────────────────────────────────────────────────────────


class TestAuthorization:

    def test_buyer_cannot_upload(self, client, seller_user, buyer_user, jpeg_bytes):
        product_id = _create_product(client, seller_user)
        authenticate_as(client, buyer_user)
        files = {"file": ("nope.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 403
        clear_auth(client)

    def test_non_owner_cannot_delete(self, client, seller_user, buyer_user, jpeg_bytes, db_session):
        from models.models import User as UserModel
        product_id = _create_product(client, seller_user)

        # Upload as owner
        files = {"file": ("del_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        image_id = res.json()["id"]

        # Create a second seller
        other_seller = UserModel(
            email="other@example.com", username="other_seller",
            hashed_password="hashed",
        )
        db_session.add(other_seller)
        db_session.commit()
        db_session.refresh(other_seller)

        authenticate_as(client, other_seller)
        del_res = client.delete(f"/products/{product_id}/images/{image_id}")
        assert del_res.status_code == 403
        clear_auth(client)


# ── Deletion ─────────────────────────────────────────────────────────────────


class TestDeletion:

    def test_delete_removes_file_and_db_record(
        self, client, seller_user, jpeg_bytes, tmp_upload_dir
    ):
        product_id = _create_product(client, seller_user)
        files = {"file": ("to_delete.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        image_id = res.json()["id"]
        filename = res.json()["filename"]

        # File should exist
        assert (tmp_upload_dir / filename).exists()

        # Delete
        del_res = client.delete(f"/products/{product_id}/images/{image_id}")
        assert del_res.status_code == 204

        # File should be gone
        assert not (tmp_upload_dir / filename).exists()

        # Serving should 404
        serve_res = client.get(f"/images/{filename}")
        assert serve_res.status_code == 404
        clear_auth(client)


# ── List images ──────────────────────────────────────────────────────────────


class TestListImages:

    def test_list_product_images(self, client, seller_user, jpeg_bytes, png_bytes):
        product_id = _create_product(client, seller_user)

        client.post(f"/products/{product_id}/images", files={"file": ("a.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")})
        client.post(f"/products/{product_id}/images", files={"file": ("b.png", io.BytesIO(png_bytes), "image/png")})

        clear_auth(client)  # listing is public
        res = client.get(f"/products/{product_id}/images")
        assert res.status_code == 200
        assert len(res.json()) == 2

class TestImageExceptions:
    def test_upload_image_product_not_found(self, client, seller_user, jpeg_bytes):
        authenticate_as(client, seller_user)
        files = {"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post("/products/00000000-0000-0000-0000-000000000000/images", files=files)
        assert res.status_code == 404
        clear_auth(client)

    def test_upload_image_save_value_error(self, client, seller_user, jpeg_bytes, monkeypatch):
        product_id = _create_product(client, seller_user)
        files = {"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        
        def mock_save(*args, **kwargs):
            raise ValueError("Mock value error")
        monkeypatch.setattr(image_service, "save_file", mock_save)
        
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert res.json()["detail"] == "Mock value error"
        clear_auth(client)

    def test_upload_image_save_os_error(self, client, seller_user, jpeg_bytes, monkeypatch):
        product_id = _create_product(client, seller_user)
        files = {"file": ("photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        
        def mock_save(*args, **kwargs):
            raise OSError("Mock OS error")
        monkeypatch.setattr(image_service, "save_file", mock_save)
        
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 500
        assert "Mock OS error" in res.json()["detail"]
        clear_auth(client)

    def test_serve_image_value_error(self, client, monkeypatch):
        def mock_build(*args, **kwargs):
            raise ValueError("Mock bad path")
        monkeypatch.setattr(image_service, "build_safe_path", mock_build)
        
        res = client.get("/images/test.jpg")
        assert res.status_code == 400

    def test_list_product_images_404(self, client):
        res = client.get("/products/00000000-0000-0000-0000-000000000000/images")
        assert res.status_code == 404

    def test_delete_product_image_404_product(self, client, seller_user):
        authenticate_as(client, seller_user)
        res = client.delete(
            "/products/00000000-0000-0000-0000-000000000000"
            "/images/00000000-0000-0000-0000-000000000000"
        )
        assert res.status_code == 404
        clear_auth(client)

    def test_delete_product_image_404_image(self, client, seller_user):
        product_id = _create_product(client, seller_user)
        res = client.delete(
            f"/products/{product_id}/images/00000000-0000-0000-0000-000000000000"
        )
        assert res.status_code == 404
        clear_auth(client)

    def test_delete_product_image_os_error(self, client, seller_user, jpeg_bytes, monkeypatch):
        product_id = _create_product(client, seller_user)
        files = {"file": ("del_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        image_id = res.json()["id"]

        def mock_delete(*args, **kwargs):
            raise OSError("Mock OS error")
        monkeypatch.setattr(image_service, "delete_file", mock_delete)
        
        # It should pass (error is ignored)
        del_res = client.delete(f"/products/{product_id}/images/{image_id}")
        assert del_res.status_code == 204
        clear_auth(client)
