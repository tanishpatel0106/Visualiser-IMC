"""Compatibility package exposing backend/app as top-level ``app``.

This allows commands run from the repository root (e.g. ``uvicorn app.main:app``)
to resolve the backend package without requiring manual PYTHONPATH changes.
"""

from pathlib import Path

_backend_app = Path(__file__).resolve().parent.parent / "backend" / "app"
__path__ = [str(_backend_app)]
