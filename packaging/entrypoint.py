"""PyInstaller entry point for the frozen PDFPad application."""

from gui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
