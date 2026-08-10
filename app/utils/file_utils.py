"""Safe, bounded upload-file handling."""

from __future__ import annotations

import asyncio
import codecs
import unicodedata
import zipfile
import zlib
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import settings

UPLOAD_DIR = Path("data/raw")
UPLOAD_READ_CHUNK_BYTES = 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx"}
MAX_UPLOAD_RELATIVE_PATH_LENGTH = 1024
MAX_UPLOAD_RELATIVE_PATH_DEPTH = 64
MAX_UPLOAD_PATH_SEGMENT_LENGTH = 255


class UploadTooLargeError(ValueError):
    """Raised after a streamed upload exceeds the configured byte limit."""

    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        super().__init__(f"Upload exceeds the {max_bytes}-byte size limit")


def _original_basename(filename: str | None) -> str:
    basename = Path((filename or "").replace("\\", "/")).name
    if not basename:
        raise ValueError("Uploaded file must have a filename")
    return basename


def validate_file_extension(filename: str | None) -> None:
    suffix = Path(_original_basename(filename)).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix}")


def normalize_upload_relative_path(
    relative_path: str | None,
    *,
    original_filename: str | None = None,
) -> str:
    """Validate a browser-provided logical path without using it on disk.

    Folder uploads use this normalized relative path as their stable document
    identity and display source. Uploaded bytes are still stored under a UUID
    inside ``data/raw``; this value must never become a filesystem target.
    """
    raw_path = relative_path or original_filename or ""
    normalized = unicodedata.normalize("NFC", str(raw_path)).replace("\\", "/")
    if not normalized or "\0" in normalized:
        raise ValueError("Uploaded file must have a valid relative path")
    if len(normalized) > MAX_UPLOAD_RELATIVE_PATH_LENGTH:
        raise ValueError("Uploaded relative path is too long")
    if normalized.startswith("/"):
        raise ValueError("Uploaded path must be relative")

    segments = normalized.split("/")
    if (
        len(segments) > MAX_UPLOAD_RELATIVE_PATH_DEPTH
        or any(
            not segment
            or segment in {".", ".."}
            or len(segment) > MAX_UPLOAD_PATH_SEGMENT_LENGTH
            for segment in segments
        )
    ):
        raise ValueError("Uploaded relative path contains an unsafe segment")
    if len(segments[0]) >= 2 and segments[0][0].isalpha() and segments[0][1] == ":":
        raise ValueError("Uploaded path must not contain a drive prefix")

    basename = segments[-1]
    if original_filename is not None:
        expected_basename = unicodedata.normalize(
            "NFC",
            _original_basename(original_filename),
        )
        if basename != expected_basename:
            raise ValueError(
                "Uploaded relative path must end with the uploaded filename"
            )
    validate_file_extension(basename)
    return "/".join(segments)


def build_safe_filename(original_filename: str) -> str:
    suffix = Path(_original_basename(original_filename)).suffix.lower()
    return f"{uuid4().hex}{suffix}"


def _is_safe_upload_path(file_path: str | Path) -> bool:
    candidate = Path(file_path).expanduser().resolve(strict=False)
    root = UPLOAD_DIR.expanduser().resolve(strict=False)
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def remove_upload_file(file_path: str | Path | None) -> bool:
    """Remove one exact UUID upload without accepting paths outside data/raw."""
    if not file_path:
        return False
    candidate = Path(file_path)
    if not _is_safe_upload_path(candidate):
        return False
    if not candidate.exists() or not candidate.is_file():
        return False
    candidate.unlink()
    return True


def validate_file_content(
    file_path: str | Path,
    original_filename: str,
) -> None:
    """Reject obvious extension spoofing before a loader sees the file."""
    path = Path(file_path)
    suffix = Path(_original_basename(original_filename)).suffix.lower()
    if suffix == ".pdf":
        with path.open("rb") as source:
            if source.read(5) != b"%PDF-":
                raise ValueError("Invalid PDF content")
        return

    if suffix == ".docx":
        try:
            if not zipfile.is_zipfile(path):
                raise ValueError("Invalid DOCX content")
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("Invalid DOCX content")
                # Opening the required member verifies that its local header and
                # compression stream are readable without loading the document.
                with archive.open("word/document.xml") as document_xml:
                    document_xml.read(1)
        except (
            OSError,
            RuntimeError,
            zipfile.BadZipFile,
            KeyError,
            EOFError,
            zlib.error,
        ) as error:
            raise ValueError("Invalid DOCX content") from error
        return

    if suffix in {".txt", ".md", ".markdown"}:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        try:
            with path.open("rb") as source:
                for chunk in iter(
                    lambda: source.read(UPLOAD_READ_CHUNK_BYTES),
                    b"",
                ):
                    decoder.decode(chunk, final=False)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError as error:
            raise ValueError("Text documents must be valid UTF-8") from error


async def save_upload_file(
    file: UploadFile,
    *,
    max_bytes: int | None = None,
) -> str:
    """Stream an upload to disk while enforcing a hard byte limit."""
    original_filename = _original_basename(file.filename)
    validate_file_extension(original_filename)
    limit = settings.upload_max_bytes if max_bytes is None else max_bytes
    if limit <= 0:
        raise ValueError("Upload size limit must be greater than zero")

    await asyncio.to_thread(UPLOAD_DIR.mkdir, parents=True, exist_ok=True)
    file_path = UPLOAD_DIR / build_safe_filename(original_filename)
    total = 0
    destination = None
    try:
        destination = await asyncio.to_thread(file_path.open, "xb")
        while True:
            chunk = await file.read(UPLOAD_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise UploadTooLargeError(limit)
            await asyncio.to_thread(destination.write, chunk)
        await asyncio.to_thread(destination.close)
        destination = None
        await asyncio.to_thread(
            validate_file_content,
            file_path,
            original_filename,
        )
    except Exception:
        if destination is not None:
            await asyncio.to_thread(destination.close)
        await asyncio.to_thread(remove_upload_file, file_path)
        raise
    return str(file_path)
