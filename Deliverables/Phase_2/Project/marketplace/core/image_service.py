"""
Secure image management service.

Provides defence-in-depth validation for uploaded images:
  • Magic-byte inspection  (actual file content)
  • MIME-type allow-list    (HTTP Content-Type header)
  • Cross-check             (declared == detected)
  • File-size limit         (20 MB)
  • UUID-based file naming  (no user-controlled names on disk)
  • SHA-256 content hashing (integrity / deduplication)
  • Path-traversal prevention
  • Restrictive file permissions (0640)
"""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Tuple

# ── Configuration ─────────────────────────────────────────────────────────────

ALLOWED_MIME_TYPES: set[str] = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
}

MIME_TO_EXTENSION: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

MAX_FILE_SIZE: int = 20 * 1024 * 1024  # 20 MB
MAX_IMAGES_PER_PRODUCT: int = 5
UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "uploads")

# ── Magic-byte signatures ─────────────────────────────────────────────────────
# Each entry is (offset, magic_bytes, mime_type).
# Order matters: more specific signatures first.

_MAGIC_SIGNATURES: list[Tuple[int, bytes, str]] = [
    # PNG: 8-byte header
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    # JPEG: starts with FF D8 FF
    (0, b"\xff\xd8\xff", "image/jpeg"),
    # GIF: GIF87a or GIF89a
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    # WebP: RIFF....WEBP  (bytes 8-11 = "WEBP", but we also check RIFF at 0)
]


# ── Public API ────────────────────────────────────────────────────────────────


def validate_file_size(content: bytes) -> None:
    """Raise ``ValueError`` if *content* exceeds ``MAX_FILE_SIZE``."""
    if len(content) > MAX_FILE_SIZE:
        raise ValueError(
            f"File size {len(content)} bytes exceeds the "
            f"{MAX_FILE_SIZE} byte limit"
        )


def validate_mime_type(content_type: str | None) -> None:
    """Raise ``ValueError`` if the declared MIME type is not in the allow-list."""
    if content_type not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"MIME type '{content_type}' is not allowed. "
            f"Accepted types: {', '.join(sorted(ALLOWED_MIME_TYPES))}"
        )


def validate_magic_bytes(content: bytes) -> str:
    """Inspect the first bytes of *content* and return the detected MIME type.

    Raises ``ValueError`` if the content does not match any known signature.
    """
    if len(content) < 12:
        raise ValueError("File is too small to be a valid image")

    # Standard signatures
    for offset, magic, mime in _MAGIC_SIGNATURES:
        end = offset + len(magic)
        if content[offset:end] == magic:
            return mime

    # WebP needs a compound check: RIFF at 0 and WEBP at 8
    if content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"

    raise ValueError(
        "File content does not match any allowed image format "
        "(magic-byte validation failed)"
    )


def validate_content_type_matches(
    declared_mime: str | None, detected_mime: str
) -> None:
    """Raise ``ValueError`` if declared and detected MIME types disagree."""
    if declared_mime != detected_mime:
        raise ValueError(
            f"Declared Content-Type '{declared_mime}' does not match "
            f"detected file type '{detected_mime}'"
        )


def generate_uuid_filename(detected_mime: str) -> str:
    """Return a ``{uuid4}{ext}`` filename for the given MIME type."""
    ext = MIME_TO_EXTENSION.get(detected_mime)
    if ext is None:
        raise ValueError(f"No extension mapping for MIME type '{detected_mime}'")
    return f"{uuid.uuid4()}{ext}"


def compute_sha256(content: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of *content*."""
    return hashlib.sha256(content).hexdigest()


def _get_upload_dir() -> Path:
    """Return the resolved upload directory path."""
    return Path(UPLOAD_DIR).resolve()


def build_safe_path(filename: str) -> Path:
    """Resolve *filename* under ``UPLOAD_DIR`` and reject path-traversal attempts.

    Raises ``ValueError`` if the resolved path escapes the upload directory.
    """
    # Reject null bytes — they can truncate paths in C-based runtimes
    if "\x00" in filename:
        raise ValueError("Invalid filename: null bytes detected")

    upload_dir = _get_upload_dir()
    # Reject obvious traversal patterns before resolving
    if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
        raise ValueError("Invalid filename: path traversal detected")

    target = (upload_dir / filename).resolve()

    # Belt-and-suspenders: final resolved path must be inside upload_dir
    if not str(target).startswith(str(upload_dir)):
        raise ValueError("Invalid filename: path traversal detected")

    return target


def save_file(content: bytes, path: Path) -> None:
    """Write *content* to *path* atomically and set permissions to ``0640``.

    Uses write-to-temp-then-rename to avoid partial writes.
    Rejects symlink targets to prevent symlink-following attacks.
    """
    # Reject symlink targets — an attacker could plant a symlink to
    # redirect writes outside the upload directory
    if path.is_symlink():
        raise ValueError("Invalid target path: symlink detected")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_bytes(content)
        os.chmod(tmp_path, 0o640)
        tmp_path.rename(path)
        os.chmod(path, 0o640)
    except Exception:
        # Clean up temp file on failure
        tmp_path.unlink(missing_ok=True)
        raise


def delete_file(path: Path) -> None:
    """Remove the file at *path* after verifying it lives inside ``UPLOAD_DIR``."""
    upload_dir = _get_upload_dir()
    resolved = path.resolve()
    if not str(resolved).startswith(str(upload_dir)):
        raise ValueError("Cannot delete file outside of upload directory")
    resolved.unlink(missing_ok=True)


def validate_upload_filename(filename: str) -> None:
    """Reject filenames that contain path-traversal or injection patterns.

    Raises ``ValueError`` for filenames containing ``..``, null bytes,
    absolute path prefixes, or other dangerous patterns.
    This runs on the **user-supplied** original filename before any
    processing, providing an early-rejection layer.
    """
    if not filename:
        raise ValueError("Filename must not be empty")
    if "\x00" in filename:
        raise ValueError("Invalid filename: null bytes detected")
    if ".." in filename:
        raise ValueError("Invalid filename: path traversal detected")
    if filename.startswith("/") or filename.startswith("\\"):
        raise ValueError("Invalid filename: absolute path not allowed")


def sanitize_original_filename(filename: str) -> str:
    """Return a safe version of the user-provided original filename.

    Strips null bytes, path components, and limits length.
    """
    # Strip null bytes before any path processing
    safe = filename.replace("\x00", "")
    # Take only the basename (no directory components)
    safe = Path(safe).name
    # Limit length
    if len(safe) > 255:
        safe = safe[:255]
    return safe
