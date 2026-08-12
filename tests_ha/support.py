"""Writing a premise to disk.

The only thing this suite needs that ``tests/support.py`` does not already do:
that module builds documents, and an integration test needs them *on disk*,
because the whole subject is reading a directory.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.support import build_document


def write_recipe(path: Path, **kwargs: Any) -> dict:
    """Write one built recipe document to ``path``, and return what was written.

    Every argument is ``tests.support.build_document``'s. It goes out as JSON-LD
    and comes back through the real reader, which is that module's whole point: a
    premise no recipe file could hold is not a premise.
    """
    document = build_document(**kwargs)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return document
