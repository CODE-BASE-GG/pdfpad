#!/usr/bin/env python3
"""Air-gap validation checks for PDFPad's core conversion library.

The script exercises every feature area on generated inputs, including a
many-page PDF, an AES-256 encrypted PDF, large images, cancellation, and
repeated runs. It also audits temporary-file cleanup. It performs no network
access and is intended to run inside an isolated network namespace:

    unshare -Urn .venv/bin/python packaging/airgap_checks.py

Run it from the project root (or pass ``--project-root``). It uses only the
bundled Python wheels; no system conversion binaries are required for the core
checks. LibreOffice is exercised only when a backend is already present.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _add_project_root() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))


def _make_pdf(path: Path, pages: int, password: str | None = None) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for index in range(pages):
        # Vary the page size a little so rendering and compression are not
        # tested against a single trivial geometry.
        width = 612 + (index % 3) * 6
        height = 792 + (index % 5) * 4
        writer.add_blank_page(width=width, height=height)
    writer.add_metadata({"/Title": "PDFPad air-gap fixture"})
    if password is not None:
        writer.encrypt(password, algorithm="AES-256")
    with path.open("wb") as handle:
        writer.write(handle)
    return path


def _make_noise_image(path: Path, size: tuple[int, int], seed: int) -> Path:
    from PIL import Image

    image = Image.effect_noise(size, 48 + seed).convert("RGB")
    image.save(path, format="JPEG", quality=85)
    image.close()
    return path


class Checks:
    def __init__(self) -> None:
        self.results: list[tuple[str, bool, str]] = []

    def run(self, name: str, function) -> bool:
        started = time.monotonic()
        try:
            detail = function() or ""
            ok = True
        except Exception as exc:  # noqa: BLE001 - validation reports all failures
            detail = f"{type(exc).__name__}: {exc}"
            ok = False
        elapsed = time.monotonic() - started
        self.results.append((name, ok, detail))
        status = "ok" if ok else "FAILED"
        suffix = f"  ({detail})" if detail else ""
        print(f"{status:6}  {name:38} {elapsed:6.2f}s{suffix}")
        return ok

    def require(self, name: str, condition: bool, detail: str = "") -> bool:
        def check() -> str:
            if not condition:
                raise AssertionError(detail or "condition was false")
            return detail

        return self.run(name, check)

    @property
    def failed(self) -> list[str]:
        return [name for name, ok, _ in self.results if not ok]


def validate(root: Path, pages: int, scratch: Path, include_office: bool) -> Checks:
    _add_project_root()

    from PIL import Image
    from pypdf import PdfReader

    from core.compress import compress_pdf
    from core.errors import EncryptedPdfError, OperationCancelled, PdfOperationError
    from core.images import images_to_pdf
    from core.markdown import extract_markdown, extract_markdown_to_file
    from core.office import office_available, office_info, office_to_pdf
    from core.pages import (
        extract_pages,
        merge_pdfs,
        page_count,
        rotate_pages,
        split_pdf,
    )
    from core.ranges import parse_ranges
    from core.render import render_page_image, render_pages, render_thumbnails
    from core.text import extract_text, extract_text_to_file

    checks = Checks()

    # -- fixtures ---------------------------------------------------------
    large = _make_pdf(root / "large.pdf", pages)
    small = _make_pdf(root / "small.pdf", 3)
    encrypted = _make_pdf(root / "encrypted.pdf", 4, password="correct horse")
    images = [
        _make_noise_image(root / f"noise-{index}.jpg", (1200, 1600), index)
        for index in range(3)
    ]

    checks.require("large PDF created", large.stat().st_size > 0, f"{pages} pages")
    checks.require(
        "page-range grammar",
        parse_ranges("1-3,2,10-", pages) == [0, 1, 2] + list(range(9, pages)),
    )

    # -- page operations --------------------------------------------------
    def check_extract() -> str:
        output = extract_pages(large, [0, 4, 9, pages - 1], root / "extracted.pdf")
        assert page_count(output) == 4
        return "4 of {}".format(pages)

    checks.run("extract pages", check_extract)

    def check_split() -> str:
        outputs = split_pdf(large, root / "split", chunk_size=25)
        assert len(outputs) == (pages + 24) // 25
        assert all(page_count(path) > 0 for path in outputs)
        return f"{len(outputs)} chunks"

    checks.run("split pages", check_split)

    def check_merge() -> str:
        first = sorted((root / "split").iterdir(), key=lambda path: path.name)[0]
        output = merge_pdfs(
            [root / "extracted.pdf", first], root / "merged.pdf"
        )
        assert page_count(output) == 4 + min(25, pages)
        return f"{page_count(output)} pages"

    checks.run("merge PDFs", check_merge)

    def check_rotate() -> str:
        output = rotate_pages(large, root / "rotated.pdf", 180)
        rotation = PdfReader(str(output)).pages[0].rotation
        assert rotation % 360 == 180
        return f"rotation {rotation}"

    checks.run("rotate pages", check_rotate)

    # -- rendering --------------------------------------------------------
    def check_render_pages() -> str:
        outputs = render_pages(
            large,
            root / "renders",
            indices=range(5),
            dpi=72,
            image_format="png",
            prefix="large",
        )
        assert len(outputs) == 5
        assert all(path.stat().st_size > 0 for path in outputs)
        return f"{len(outputs)} PNGs"

    checks.run("PDF -> PNG pages", check_render_pages)

    def check_render_jpeg() -> str:
        outputs = render_pages(
            large,
            root / "renders-jpeg",
            indices=[0, 1],
            dpi=96,
            image_format="jpeg",
            quality=80,
            prefix="large",
        )
        assert len(outputs) == 2
        return "2 JPEGs"

    checks.run("PDF -> JPEG pages", check_render_jpeg)

    def check_thumbnails() -> str:
        thumbs = render_thumbnails(large, max_pages=8, max_size=128)
        try:
            assert len(thumbs) == 8
            assert all(image.width <= 128 and image.height <= 128 for image in thumbs)
        finally:
            for image in thumbs:
                image.close()
        return "8 thumbnails"

    checks.run("PDF thumbnails", check_thumbnails)

    # -- images -> PDF ----------------------------------------------------
    def check_images_to_pdf() -> str:
        output = images_to_pdf(
            images,
            root / "images.pdf",
            page_size="a4",
            fit="contain",
            dpi=150,
            quality=85,
        )
        assert page_count(output) == 3
        return f"{output.stat().st_size // 1024} KiB"

    checks.run("images -> PDF (A4 contain)", check_images_to_pdf)

    def check_images_cover() -> str:
        output = images_to_pdf(
            images[:2],
            root / "images-cover.pdf",
            page_size="letter",
            fit="cover",
            dpi=150,
        )
        assert page_count(output) == 2
        return "letter cover"

    checks.run("images -> PDF (letter cover)", check_images_cover)

    # -- text and Markdown ------------------------------------------------
    def check_text() -> str:
        text = extract_text(large)
        output = extract_text_to_file(large, root / "large.txt", indices=[0, 1])
        assert output.is_file()
        assert output.read_text(encoding="utf-8").strip() == ""
        return f"{len(text)} chars (blank pages)"

    checks.run("PDF -> text", check_text)

    def check_markdown() -> str:
        markdown = extract_markdown(large)
        output = extract_markdown_to_file(large, root / "large.md", indices=[0, 1])
        assert output.is_file()
        assert output.read_text(encoding="utf-8").strip() == ""
        return f"{len(markdown)} chars (blank pages)"

    checks.run("PDF -> Markdown", check_markdown)

    # -- compression ------------------------------------------------------
    def check_lossless() -> str:
        output = compress_pdf(large, root / "large-lossless.pdf", mode="lossless")
        assert page_count(output) == pages
        return f"{large.stat().st_size // 1024} -> {output.stat().st_size // 1024} KiB"

    checks.run("compress lossless", check_lossless)

    def check_rasterize() -> str:
        output = compress_pdf(
            small,
            root / "small-rasterized.pdf",
            mode="rasterize",
            dpi=96,
            quality=80,
        )
        assert page_count(output) == 3
        return f"{output.stat().st_size // 1024} KiB"

    checks.run("compress rasterize", check_rasterize)

    def check_repeat() -> str:
        target = root / "repeat.pdf"
        first = compress_pdf(small, target, mode="lossless")
        first_size = first.stat().st_size
        second = compress_pdf(small, target, mode="lossless")
        assert second.stat().st_size == first_size
        return "identical output"

    checks.run("repeated run", check_repeat)

    # -- encrypted PDFs ---------------------------------------------------
    def check_encrypted_read() -> str:
        assert page_count(encrypted, "correct horse") == 4
        return "4 pages"

    checks.run("encrypted: page count", check_encrypted_read)

    def check_encrypted_ops() -> str:
        extracted = extract_pages(
            encrypted, [0, 2], root / "encrypted-extract.pdf", password="correct horse"
        )
        assert page_count(extracted) == 2
        rendered = render_page_image(
            encrypted, 0, dpi=72, password="correct horse"
        )
        assert rendered.width > 0
        rendered.close()
        text = extract_text(encrypted, password="correct horse")
        markdown = extract_markdown(encrypted, password="correct horse")
        compressed = compress_pdf(
            encrypted,
            root / "encrypted-compressed.pdf",
            password="correct horse",
        )
        assert page_count(compressed, "correct horse") == 4
        return f"text {len(text)}, md {len(markdown)}"

    checks.run("encrypted: extract/render/text/md/compress", check_encrypted_ops)

    def check_encrypted_rejected() -> str:
        for password in (None, "wrong password"):
            try:
                page_count(encrypted, password)
            except EncryptedPdfError:
                continue
            raise AssertionError(f"accepted password {password!r}")
        return "missing and wrong rejected"

    checks.run("encrypted: bad password rejected", check_encrypted_rejected)

    # -- cancellation and atomic safety ----------------------------------
    def check_cancel() -> str:
        target = root / "cancelled.pdf"
        try:
            extract_pages(
                large,
                [0, 1, 2],
                target,
                cancel=lambda: True,
            )
        except OperationCancelled:
            pass
        else:
            raise AssertionError("cancellation was ignored")
        assert not target.exists(), "cancelled output was created"
        return "no output"

    checks.run("cancellation leaves no output", check_cancel)

    def check_atomic_failure() -> str:
        before = large.stat().st_size
        try:
            compress_pdf(large, large, mode="lossless")
        except PdfOperationError:
            pass
        else:
            raise AssertionError("overwriting the input was allowed")
        assert large.stat().st_size == before
        assert page_count(large) == pages
        return "input intact"

    checks.run("atomic failure preserves input", check_atomic_failure)

    # -- optional Office backend -----------------------------------------
    if include_office:
        def check_office() -> str:
            if not office_available():
                return "skipped: no LibreOffice backend"
            info = office_info()
            source = root / "airgap.rtf"
            source.write_text(
                r"{\rtf1\ansi\deff0 {\fonttbl {\f0 DejaVu Sans;}}"
                r"\f0\fs24 PDFPad air-gap Office check.}",
                encoding="ascii",
            )
            outputs = office_to_pdf([source], root / "office-out", timeout=120)
            assert len(outputs) == 1
            assert page_count(outputs[0]) == 1
            return f"{info.source}: {info.version or 'unknown version'}"

        checks.run("Office -> PDF (optional backend)", check_office)

    # -- cleanup audit ----------------------------------------------------
    def check_scratch_clean() -> str:
        leftovers = sorted(scratch.iterdir())
        assert not leftovers, f"scratch leftovers: {[p.name for p in leftovers]}"
        return "temporary directory empty"

    checks.run("temporary files cleaned", check_scratch_clean)

    def check_atomic_clean() -> str:
        stray = [
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.name.startswith(".")
            and path.suffix in {".tmp", ".txt"}
        ]
        assert not stray, f"atomic temp leftovers: {[p.name for p in stray]}"
        return "no .tmp files"

    checks.run("atomic temp files cleaned", check_atomic_clean)

    return checks


def main(argv: list[str] | None = None) -> int:
    global PROJECT_ROOT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="PDFPad source tree",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=150,
        help="page count for the large fixture, at least 10 (default: 150)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="keep the work tree under this directory (default: a temp dir)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the work tree for inspection",
    )
    parser.add_argument(
        "--no-office",
        action="store_true",
        help="skip the optional LibreOffice conversion check",
    )
    args = parser.parse_args(argv)

    if args.pages < 10:
        parser.error("--pages must be >= 10")

    PROJECT_ROOT = args.project_root.resolve()
    _add_project_root()

    if args.workdir is not None:
        root = args.workdir.resolve()
        root.mkdir(parents=True, exist_ok=True)
        scratch = root / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        cleanup_root = not args.keep
    else:
        root = Path(tempfile.mkdtemp(prefix="pdfpad-airgap-"))
        scratch = root / "tmp"
        scratch.mkdir(parents=True, exist_ok=True)
        cleanup_root = not args.keep

    # Route every library-created temporary file through the audited directory.
    os.environ["TMPDIR"] = str(scratch)
    tempfile.tempdir = str(scratch)

    print(f"PDFPad air-gap checks")
    print(f"  project: {PROJECT_ROOT}")
    print(f"  work:    {root}")
    print(f"  scratch: {scratch}")
    print()

    try:
        checks = validate(
            root,
            args.pages,
            scratch,
            include_office=not args.no_office,
        )
    finally:
        if cleanup_root and args.workdir is None:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    print()
    if checks.failed:
        print(f"FAILED: {len(checks.failed)} check(s): {', '.join(checks.failed)}")
        return 1
    print(f"All {len(checks.results)} air-gap checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
