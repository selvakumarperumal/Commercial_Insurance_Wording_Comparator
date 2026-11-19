"""Saving uploaded PDFs where the worker can read them: UPLOAD_DIR/<user_id>/<job_id>/pdf_a.pdf and pdf_b.pdf."""

import shutil
from pathlib import Path

from fastapi import UploadFile

from commercial_insurance_wording_comparator.config import settings

READ_CHUNK = 1024 * 1024
PDF_MARKER = b"%PDF-"
MARKER_WINDOW = 1024


class UploadRejected(ValueError):
    """An upload is empty, not a PDF or too large; `status_code` is the HTTP status to answer with."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def job_folder(user_id: str, job_id: str) -> Path:
    """The absolute folder of one job's PDFs; absolute because the path is handed to the worker."""
    return settings.upload_dir.resolve() / user_id / job_id


async def save_pair(folder: Path, pdf_a: UploadFile, pdf_b: UploadFile) -> tuple[Path, Path]:
    """Save both uploads into `folder`; if anything fails, the folder is removed again."""
    folder.mkdir(parents=True)
    path_a = folder / "pdf_a.pdf"
    path_b = folder / "pdf_b.pdf"

    try:
        await _save_pdf(pdf_a, path_a, "pdf_a")
        await _save_pdf(pdf_b, path_b, "pdf_b")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    return path_a, path_b


async def _save_pdf(upload: UploadFile, path: Path, field: str) -> None:
    """Write one upload to `path` in chunks; raise UploadRejected if it is empty, not a PDF or too large."""
    limit = settings.max_pdf_bytes
    size = 0

    with path.open("wb") as out:
        while chunk := await upload.read(READ_CHUNK):
            if size == 0 and PDF_MARKER not in chunk[:MARKER_WINDOW]:
                raise UploadRejected(f"{field} is not a PDF")
            size += len(chunk)
            if size > limit:
                raise UploadRejected(f"{field} is larger than {settings.max_pdf_mb} MB", status_code=413)
            out.write(chunk)

    if size == 0:
        raise UploadRejected(f"{field} is empty")
