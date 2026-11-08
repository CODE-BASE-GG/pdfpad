"""A fake LibreOffice executable used by the Office conversion tests.

The real LibreOffice is an optional add-on, so the test suite must never depend
on it. :func:`make_fake_office` writes a small executable shell shim that runs
this module with the current Python interpreter. Behaviour is selected through
environment variables, which lets one helper cover success, failure, timeout,
cancellation, and unexpected-output cases.

Environment variables read by the fake:

``FAKE_OFFICE_TEMPLATE``
    Path to a PDF copied into the output directory (required on success).
``FAKE_OFFICE_BEHAVIOR``
    ``success`` (default), ``fail``, ``no-output``, ``multi-output``,
    ``wrong-name``, ``sleep``, or ``ignore-sigterm``.
``FAKE_OFFICE_SLEEP``
    Seconds to sleep for the ``sleep``/``ignore-sigterm`` behaviours.
``FAKE_OFFICE_LOG``
    Path of a JSON-lines file that records every invocation's arguments.
``FAKE_OFFICE_SENTINEL``
    Path of a marker file written after a successful conversion. Tests use it
    to cancel deterministically once the first document is on disk.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

BEHAVIORS = frozenset(
    {
        "success",
        "fail",
        "no-output",
        "multi-output",
        "wrong-name",
        "sleep",
        "ignore-sigterm",
    }
)


def _parse(argv: list[str]) -> tuple[str | None, str | None, list[str]]:
    """Extract ``--outdir``, ``--convert-to`` and the positional inputs."""
    outdir: str | None = None
    convert: str | None = None
    inputs: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--outdir":
            index += 1
            if index < len(argv):
                outdir = argv[index]
        elif arg == "--convert-to":
            index += 1
            if index < len(argv):
                convert = argv[index]
        elif not arg.startswith("-"):
            inputs.append(arg)
        index += 1
    return outdir, convert, inputs


def main(argv: list[str]) -> int:
    log = os.environ.get("FAKE_OFFICE_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(argv) + "\n")

    if "--version" in argv:
        print("LibreOffice Fake 1.0")
        return 0

    behavior = os.environ.get("FAKE_OFFICE_BEHAVIOR", "success")
    if behavior not in BEHAVIORS:
        print(f"unknown fake behavior: {behavior}", file=sys.stderr)
        return 2

    if behavior == "ignore-sigterm":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        behavior = "sleep"

    if behavior == "fail":
        print("fake conversion failure", file=sys.stderr)
        return 1

    if behavior == "sleep":
        time.sleep(float(os.environ.get("FAKE_OFFICE_SLEEP", "30")))

    outdir, convert, inputs = _parse(argv)
    if outdir is None or not inputs:
        print("missing --outdir or input file", file=sys.stderr)
        return 2
    if convert != "pdf":
        print(f"unexpected --convert-to value: {convert!r}", file=sys.stderr)
        return 2

    if behavior == "no-output":
        return 0

    template = Path(os.environ["FAKE_OFFICE_TEMPLATE"])
    destination = Path(outdir)
    stem = Path(inputs[-1]).stem

    if behavior == "wrong-name":
        names = ["Converted.pdf"]
    elif behavior == "multi-output":
        names = ["extra.pdf", "extra2.pdf"]
    else:
        names = [f"{stem}.pdf"]

    for name in names:
        shutil.copyfile(template, destination / name)

    sentinel = os.environ.get("FAKE_OFFICE_SENTINEL")
    if sentinel:
        Path(sentinel).touch(exist_ok=True)

    print(f"convert {inputs[-1]} -> {destination}")
    return 0


def make_fake_office(directory: str | Path, name: str = "soffice") -> Path:
    """Write an executable fake LibreOffice into *directory* and return it."""
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    executable = target_dir / name
    module = Path(__file__).resolve()
    executable.write_text(
        "#!/bin/sh\n"
        f'exec "{sys.executable}" "{module}" "$@"\n',
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
