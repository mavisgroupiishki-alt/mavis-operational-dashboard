"""Authenticated cabinet HTML. The interface lives in static/cabinet.html."""
from pathlib import Path


def cabinet_html() -> str:
    return (Path(__file__).resolve().parent / "static" / "cabinet.html").read_text(encoding="utf-8")
