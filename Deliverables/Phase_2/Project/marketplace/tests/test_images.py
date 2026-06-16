"""Tests for secure image upload, serving, and deletion."""

import hashlib
import io
import os
import uuid
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
        assert res.status_code == 422
        assert "magic-byte" in res.json()["detail"].lower() or "does not match" in res.json()["detail"].lower()
        clear_auth(client)

    def test_reject_wrong_content_type(self, client, seller_user, jpeg_bytes):
        """Valid JPEG sent with wrong Content-Type header must be rejected."""
        product_id = _create_product(client, seller_user)
        files = {"file": ("photo.png", io.BytesIO(jpeg_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 422
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
        assert "maximum images per product exceeded" in res.json()["detail"].lower()
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
    """Defence against path-traversal uploads.

    Attack vectors tested:
      1. Classic ``../`` directory traversal in the uploaded filename.
      2. Null-byte injection (``\\x00``) to truncate the path.
      3. Symlink target — a pre-planted symlink inside the upload dir.

    Expected outcomes:
      • Files are always stored with a UUID name.
      • No files are written outside the storage root.
      • HTTP 422 is returned for malicious filenames.
    """

    # ── 1. Classic directory-traversal filenames ──────────────────────────

    @pytest.mark.parametrize(
        "malicious_name",
        [
            "../../../etc/passwd",
            "..\\..\\..\\etc\\passwd",
            "foo/../../../etc/passwd",
            "../upload_escape.jpg",
        ],
    )
    def test_upload_rejects_traversal_filename(
        self, client, seller_user, jpeg_bytes, malicious_name
    ):
        """Upload with ``../`` in filename must return 422."""
        product_id = _create_product(client, seller_user)
        files = {
            "file": (malicious_name, io.BytesIO(jpeg_bytes), "image/jpeg")
        }
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 422, (
            f"Expected 422 for filename '{malicious_name}', got {res.status_code}"
        )
        clear_auth(client)

    def test_traversal_upload_writes_no_file_outside_root(
        self, client, seller_user, jpeg_bytes, tmp_upload_dir
    ):
        """Even if the request is rejected, nothing should be written outside uploads/."""
        product_id = _create_product(client, seller_user)
        # Attempt the upload
        files = {
            "file": ("../../../etc/passwd", io.BytesIO(jpeg_bytes), "image/jpeg")
        }
        client.post(f"/products/{product_id}/images", files=files)

        # Verify nothing landed outside the upload dir
        parent = tmp_upload_dir.parent
        for child in parent.iterdir():
            assert child.name == tmp_upload_dir.name or child.name.startswith(
                "."
            ), f"Unexpected file outside upload root: {child}"
        clear_auth(client)

    # ── 2. Null-byte injection ────────────────────────────────────────────

    @pytest.mark.parametrize(
        "null_name",
        [
            "image.jpg\x00.sh",
            "\x00malicious.jpg",
            "photo\x00../../../etc/passwd",
        ],
    )
    def test_validate_rejects_null_byte_filename_at_service_layer(
        self, null_name
    ):
        """validate_upload_filename must reject null-byte filenames.

        Note: The HTTP multipart layer strips null bytes before they reach
        the endpoint, so we test at the service layer for defence-in-depth.
        """
        with pytest.raises(ValueError, match="null bytes"):
            image_service.validate_upload_filename(null_name)

    def test_null_byte_filename_stripped_by_sanitize(self):
        """sanitize_original_filename must strip null bytes even if they
        somehow reach the sanitisation step."""
        result = image_service.sanitize_original_filename("image\x00.jpg")
        assert "\x00" not in result
        assert result == "image.jpg"

    def test_build_safe_path_rejects_null_byte_in_filename(self):
        """build_safe_path must reject filenames containing null bytes."""
        with pytest.raises(ValueError, match="null bytes"):
            image_service.build_safe_path("test\x00file.jpg")

    # ── 3. Symlink target attack ──────────────────────────────────────────

    def test_save_rejects_symlink_target(self, tmp_upload_dir, jpeg_bytes):
        """If a symlink already exists at the target path, save_file must refuse."""
        from pathlib import Path

        # Plant a symlink inside the upload dir pointing outside
        symlink_path = tmp_upload_dir / "evil_link.jpg"
        outside_target = tmp_upload_dir.parent / "pwned.txt"
        symlink_path.symlink_to(outside_target)

        with pytest.raises(ValueError, match="symlink detected"):
            image_service.save_file(jpeg_bytes, symlink_path)

        # The outside target must NOT have been created
        assert not outside_target.exists(), (
            "File was written through symlink to outside target!"
        )

    # ── 4. UUID naming guarantee ──────────────────────────────────────────

    def test_uploaded_file_gets_uuid_name_not_original(
        self, client, seller_user, jpeg_bytes
    ):
        """Even with a malicious-looking (but valid) original name, the
        stored filename is always a UUID."""
        product_id = _create_product(client, seller_user)
        files = {
            "file": ("my_photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")
        }
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        stored_name = res.json()["filename"]
        stem = stored_name.rsplit(".", 1)[0]
        parsed = uuid.UUID(stem, version=4)
        assert str(parsed) == stem, "Stored filename is not a valid UUID"
        clear_auth(client)

    # ── 5. Existing serve-side traversal tests ────────────────────────────

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
        authenticate_as(client, seller_user)
        serve_res = client.get(f"/products/{product_id}/images/{filename}")
        assert serve_res.status_code == 200
        assert serve_res.headers["content-type"] == "image/jpeg"
        clear_auth(client)

    # ── 6. Unit-level tests for build_safe_path and validate_upload_filename ──

    def test_build_safe_path_rejects_null_bytes(self):
        """build_safe_path must reject null-byte filenames."""
        with pytest.raises(ValueError, match="null bytes"):
            image_service.build_safe_path("file\x00.jpg")

    def test_validate_upload_filename_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            image_service.validate_upload_filename("")

    def test_validate_upload_filename_rejects_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            image_service.validate_upload_filename("../../../etc/passwd")

    def test_validate_upload_filename_rejects_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            image_service.validate_upload_filename("file\x00.sh")

    def test_validate_upload_filename_rejects_absolute(self):
        with pytest.raises(ValueError, match="absolute"):
            image_service.validate_upload_filename("/etc/passwd")

    def test_sanitize_strips_null_bytes(self):
        result = image_service.sanitize_original_filename("photo\x00.jpg")
        assert "\x00" not in result
        assert result == "photo.jpg"


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

        expected = "0666" if os.name == "nt" else "0640"

        assert mode == expected, (
            f"Expected {oct(expected)}, got {oct(mode)}"
        )
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

    def test_serve_image_value_error(self, client, seller_user, monkeypatch):
        authenticate_as(client, seller_user)
        def mock_build(*args, **kwargs):
            raise ValueError("Mock bad path")
        monkeypatch.setattr(image_service, "build_safe_path", mock_build)
        
        product_uuid = uuid.uuid4()
        res = client.get(f"/products/{product_uuid}/images/test.jpg")
        assert res.status_code == 400
        clear_auth(client)

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


class TestPathExclusionInAPI:

    def test_no_internal_pathways_leaked_in_responses(self, client, seller_user, jpeg_bytes):
        # 1. Create a product
        product_id = _create_product(client, seller_user)

        # 2. Upload an image
        authenticate_as(client, seller_user)
        files = {"file": ("my_original_photo.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        upload_res = client.post(f"/products/{product_id}/images", files=files)
        assert upload_res.status_code == 201
        upload_data = upload_res.json()
        
        # Verify upload response JSON payload
        self._verify_no_paths_in_dict(upload_data)

        # 3. Transition product to active status so it is publicly retrievable
        res_act = client.patch(f"/products/{product_id}/status", json={"status": "active"})
        assert res_act.status_code == 200

        # 4. Request product details
        res_prod = client.get(f"/products/{product_id}")
        assert res_prod.status_code == 200
        prod_data = res_prod.json()
        self._verify_no_paths_in_dict(prod_data)

        # 4. Request image metadata list
        res_meta = client.get(f"/products/{product_id}/images")
        assert res_meta.status_code == 200
        meta_data = res_meta.json()
        assert isinstance(meta_data, list)
        for img_entry in meta_data:
            self._verify_no_paths_in_dict(img_entry)

        # 5. Verify that even if the database has path characters, the Pydantic schema excludes them!
        from models.models import ProductImage
        from schemas.schemas import ProductImageResponse
        import datetime
        mock_db_img = ProductImage(
            id=uuid.uuid4(),
            product_id=uuid.uuid4(),
            filename="/var/www/uploads/random_uuid.jpg",
            original_filename="nested/dir/my_photo.jpg",
            mime_type="image/jpeg",
            file_size=1024,
            sha256_hash="dummy_hash",
            uploaded_at=datetime.datetime.now(datetime.UTC)
        )
        response_schema = ProductImageResponse.model_validate(mock_db_img)
        serialized_data = response_schema.model_dump()
        
        # Verify that the schema stripped the pathways!
        assert "/" not in serialized_data["filename"]
        assert "\\" not in serialized_data["filename"]
        assert "/" not in serialized_data["original_filename"]
        assert "\\" not in serialized_data["original_filename"]
        assert "var" not in serialized_data["filename"]
        assert "uploads" not in serialized_data["filename"]
        assert "dir" not in serialized_data["original_filename"]
        
        clear_auth(client)

    def _verify_no_paths_in_dict(self, data):
        """Recursively check that absolutely no path characters indicating internal directory
        topology are leaked in any string fields, except for the standard media types (mime_type).
        """
        if isinstance(data, dict):
            for k, v in data.items():
                if k == "mime_type":
                    # Mime type like image/jpeg is allowed to have a slash
                    continue
                if isinstance(v, str):
                    # Assert no slashes, backslashes, or system directory paths
                    assert "/" not in v, f"Field '{k}' leaked path separator '/': {v}"
                    assert "\\" not in v, f"Field '{k}' leaked path separator '\\': {v}"
                    # Check common system directories
                    for forbidden in ["/var", "/tmp", "uploads", "/www"]:
                        assert forbidden not in v, f"Field '{k}' leaked system directory '{forbidden}': {v}"
                elif isinstance(v, (dict, list)):
                    self._verify_no_paths_in_dict(v)
        elif isinstance(data, list):
            for item in data:
                self._verify_no_paths_in_dict(item)
class TestFilePermissions:

    def test_uploaded_image_permissions(self, client, seller_user, jpeg_bytes, tmp_upload_dir):
        import stat
        product_id = _create_product(client, seller_user)
        files = {"file": ("permissions_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201

        filename = res.json()["filename"]
        file_path = tmp_upload_dir / filename
        assert file_path.exists()

        # Retrieve the absolute path
        abs_path = str(file_path.resolve())

        # Programmatically evaluate the file status bits
        mode = stat.S_IMODE(os.stat(abs_path).st_mode)

        # Assert that the octal mask matches exactly 0o640
        assert mode == 0o640
        clear_auth(client)
class TestMST18Security:

    def test_upload_php_renamed_to_png(self, client, seller_user):
        product_id = _create_product(client, seller_user)
        php_content = b"<?php phpinfo(); ?>"
        files = {"file": ("malicious.png", io.BytesIO(php_content), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 422
        clear_auth(client)

    def test_upload_png_with_embedded_php(self, client, seller_user, png_bytes):
        product_id = _create_product(client, seller_user)
        bad_content = png_bytes + b"<?php phpinfo(); ?>"
        files = {"file": ("malicious.png", io.BytesIO(bad_content), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 422
        clear_auth(client)

    def test_upload_completely_valid_png(self, client, seller_user, png_bytes):
        product_id = _create_product(client, seller_user)
        files = {"file": ("valid.png", io.BytesIO(png_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        clear_auth(client)


class TestMST19Security:

    def test_upload_exactly_10_images_and_fail_11th(self, client, seller_user, png_bytes):
        product_id = _create_product(client, seller_user)
        authenticate_as(client, seller_user)
        
        # Upload 10 images successfully
        for i in range(10):
            files = {"file": (f"img_{i}.png", io.BytesIO(png_bytes), "image/png")}
            res = client.post(f"/products/{product_id}/images", files=files)
            assert res.status_code == 201, f"Failed at upload {i+1}"
            
        # Attempt 11th upload
        files = {"file": ("img_11.png", io.BytesIO(png_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 400
        assert "maximum images per product exceeded" in res.json()["detail"].lower()
        clear_auth(client)


class TestMST20Security:

    def test_raw_access_blocked_returns_404(self, client, seller_user, buyer_user, png_bytes):
        # 1. Successful upload
        product_id = _create_product(client, seller_user)
        files = {"file": ("test.png", io.BytesIO(png_bytes), "image/png")}
        res = client.post(f"/products/{product_id}/images", files=files)
        assert res.status_code == 201
        filename = res.json()["filename"]
        
        # Clear auth
        clear_auth(client)
        
        # 2. Attempt raw direct access - must return 404
        raw_res = client.get(f"/images/{filename}")
        assert raw_res.status_code == 404
        
        # 3. Attempt authenticated endpoint without auth - must fail with 401
        auth_res_no_login = client.get(f"/products/{product_id}/images/{filename}")
        assert auth_res_no_login.status_code == 401
        
        # 4. Attempt with seller (owner) - must succeed (200)
        authenticate_as(client, seller_user)
        auth_res_seller = client.get(f"/products/{product_id}/images/{filename}")
        assert auth_res_seller.status_code == 200
        assert auth_res_seller.headers["content-type"] == "image/png"
        clear_auth(client)

        # 5. Attempt with buyer when product is active - must fail with 403 because product is draft
        authenticate_as(client, buyer_user)
        auth_res_buyer_draft = client.get(f"/products/{product_id}/images/{filename}")
        assert auth_res_buyer_draft.status_code == 403
        clear_auth(client)


class TestImageUploadLimitsAsync:

    @pytest.mark.asyncio
    async def test_upload_exceeds_10mb_async(self, seller_user):
        """Test that a file payload exceeding 10MB (11MB) is immediately rejected with HTTP 422."""
        from httpx import AsyncClient, ASGITransport
        from main import app
        from middleware.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: seller_user

        big_content = b"a" * (11 * 1024 * 1024)
        files = {"file": ("big_image.png", big_content, "image/png")}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            product_res = await client.post(
                "/products/",
                json={"name": "Async Size Limit Prod", "price": 19.99, "stock": 10}
            )
            assert product_res.status_code == 201
            product_id = product_res.json()["id"]

            upload_res = await client.post(f"/products/{product_id}/images", files=files)
            assert upload_res.status_code == 422
            assert "exceeds maximum allowed size of 10 MB" in upload_res.json()["detail"]

        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_upload_valid_5mb_async(self, seller_user, png_bytes):
        """Test that a valid 5MB PNG file succeeds with HTTP 201/200."""
        from httpx import AsyncClient, ASGITransport
        from main import app
        from middleware.auth import get_current_user

        app.dependency_overrides[get_current_user] = lambda: seller_user

        five_mb_content = png_bytes + b"\x00" * (5 * 1024 * 1024 - len(png_bytes))
        files = {"file": ("valid_5mb.png", five_mb_content, "image/png")}

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            product_res = await client.post(
                "/products/",
                json={"name": "Async 5MB Prod", "price": 9.99, "stock": 5}
            )
            assert product_res.status_code == 201
            product_id = product_res.json()["id"]

            upload_res = await client.post(f"/products/{product_id}/images", files=files)
            assert upload_res.status_code in (200, 201)
            data = upload_res.json()
            assert data["mime_type"] == "image/png"
            assert data["original_filename"] == "valid_5mb.png"

        app.dependency_overrides.clear()


class TestImageIntegritySecurity:

    def test_image_integrity_failure_blocks_download(self, client, seller_user, jpeg_bytes, tmp_upload_dir):
        # 1. Write an integration test that uploads a valid image and saves its metadata
        product_id = _create_product(client, seller_user)
        files = {"file": ("integrity_test.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")}
        authenticate_as(client, seller_user)
        upload_res = client.post(f"/products/{product_id}/images", files=files)
        assert upload_res.status_code == 201
        data = upload_res.json()
        filename = data["filename"]

        # 2. Verify file exists on disk
        file_path = tmp_upload_dir / filename
        assert file_path.exists()

        # 3. Manually modify the file content on disk (tampering)
        file_path.write_bytes(b"tampered image data")

        # 4. Attempt to download the image through the authenticated API endpoint
        serve_res = client.get(f"/products/{product_id}/images/{filename}")

        # 5. Assert that the system blocks the download and returns the expected data integrity error (500)
        assert serve_res.status_code == 500
        assert "integrity" in serve_res.json()["detail"].lower()
        clear_auth(client)


