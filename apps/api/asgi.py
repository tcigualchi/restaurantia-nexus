"""Vercel entrypoint for the API service (vercel.json → services.api.entrypoint = "asgi:app").

Docker and local runs use ``nexus.main:app`` directly. This shim only makes the ``src/``
layout importable when Vercel loads the function from the service root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from nexus.main import app  # noqa: E402

__all__ = ["app"]
