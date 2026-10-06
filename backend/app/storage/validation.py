"""Validation des téléversements : extension autorisée, taille, signature (magic bytes)."""
from dataclasses import dataclass
import os

TEXT_EXT = {"txt", "csv", "json", "ts", "js", "py", "java", "php", "html", "css", "sql", "md"}
BINARY_EXT = {"pdf", "docx", "xlsx", "zip", "png", "jpg", "jpeg", "webp"}
ALLOWED = TEXT_EXT | BINARY_EXT
_MAGIC = {
    "pdf": [b"%PDF-"], "png": [b"\x89PNG\r\n\x1a\n"], "jpg": [b"\xff\xd8\xff"], "jpeg": [b"\xff\xd8\xff"],
    "webp": [b"RIFF"], "zip": [b"PK\x03\x04"], "docx": [b"PK\x03\x04"], "xlsx": [b"PK\x03\x04"],
}


class InvalidUpload(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


@dataclass(frozen=True)
class Checked:
    ext: str
    is_text: bool


def validate_upload(filename: str, data: bytes, max_bytes: int) -> Checked:
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    if ext not in ALLOWED:
        raise InvalidUpload("UNSUPPORTED_TYPE", f"Extension .{ext or '?'} non prise en charge")
    if not data:
        raise InvalidUpload("EMPTY_FILE", "Le fichier est vide")
    if len(data) > max_bytes:
        raise InvalidUpload("FILE_TOO_LARGE", f"Taille maximale: {max_bytes // (1024 * 1024)} Mo")
    if ext in _MAGIC and not any(data.startswith(m) for m in _MAGIC[ext]):
        raise InvalidUpload("CONTENT_MISMATCH", "Le contenu ne correspond pas à l'extension")
    if ext == "webp" and data[8:12] != b"WEBP":
        raise InvalidUpload("CONTENT_MISMATCH", "Le contenu ne correspond pas à l'extension")
    if ext in TEXT_EXT:
        if b"\x00" in data[:4096]:
            raise InvalidUpload("CONTENT_MISMATCH", "Fichier texte attendu")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidUpload("BAD_ENCODING", "Le fichier texte doit être en UTF-8")
    return Checked(ext, ext in TEXT_EXT)
