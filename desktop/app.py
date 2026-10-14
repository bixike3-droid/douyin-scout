"""Native desktop entry point."""
from pathlib import Path

from scout.desktop.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main(default_root=Path(__file__).resolve().parent / "userdata"))
