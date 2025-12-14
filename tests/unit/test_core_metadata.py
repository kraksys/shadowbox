from pathlib import Path

import pytest

import shadowbox.core.metadata as meta_mod
from shadowbox.core.metadata import MetadataExtractor


def test_extract_missing_file_returns_empty(tmp_path):
    extractor = MetadataExtractor()
    result = extractor.extract(str(tmp_path / "missing.txt"))
    assert result == {}


def test_extract_text_file_counts_lines_and_chars(tmp_path, monkeypatch):
    f = tmp_path / "sample.txt"
    f.write_text("line1\nline2\n")
    monkeypatch.setattr(
        meta_mod.mimetypes, "guess_type", lambda p: ("text/plain", None)
    )

    result = MetadataExtractor().extract(str(f))
    assert result["mime_type"] == "text/plain"
    assert result["extension"] == ".txt"
    assert result["line_count"] == 2
    assert result["char_count"] == len("line1\nline2\n")


def test_extract_zip_populates_counts(tmp_path, monkeypatch):
    zpath = tmp_path / "archive.zip"
    import zipfile

    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("a.txt", "hi")
        z.writestr("b.txt", "shadowbox test")

    monkeypatch.setattr(
        meta_mod.mimetypes, "guess_type", lambda p: ("application/zip", None)
    )
    result = MetadataExtractor().extract(str(zpath))

    assert result["file_count"] == 2
    assert result["uncompressed_size"] >= 7
    assert result["file_list_preview"] == ["a.txt", "b.txt"]


def test_extract_image_uses_pil(monkeypatch, tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"fakeimage")

    class FakeImg:
        width = 10
        height = 20
        format = "PNG"
        mode = "RGBA"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(meta_mod, "HAS_PIL", True)
    monkeypatch.setattr(
        meta_mod,
        "Image",
        type("X", (), {"open": lambda p: FakeImg()}),
        raising=False,
    )
    monkeypatch.setattr(
        meta_mod.mimetypes, "guess_type", lambda p: ("image/png", None)
    )

    result = MetadataExtractor().extract(str(f))
    assert result["width"] == 10
    assert result["height"] == 20
    assert result["format"] == "PNG"
    assert result["mode"] == "RGBA"


def test_extract_pdf_adds_metadata(monkeypatch, tmp_path):
    f = tmp_path / "file.pdf"
    f.write_bytes(b"fakepdf")

    class FakePdf:
        pages = [1, 2, 3]
        metadata = {"/Title": "Doc", "/Author": "Alice"}

    monkeypatch.setattr(meta_mod, "HAS_PDF", True)
    monkeypatch.setattr(
        meta_mod,
        "PyPDF2",
        type("X", (), {"PdfReader": lambda fh: FakePdf()}),
        raising=False,
    )
    monkeypatch.setattr(
        meta_mod.mimetypes,
        "guess_type",
        lambda p: ("application/pdf", None),
    )

    result = MetadataExtractor().extract(str(f))
    assert result["page_count"] == 3
    assert result["pdf_info"]["Title"] == "Doc"
    assert result["pdf_info"]["Author"] == "Alice"
