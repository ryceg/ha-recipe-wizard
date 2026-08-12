"""Names shared across the integration's modules.

Deliberately free of ``homeassistant`` imports so that ``__init__.py`` can import
it at module scope without breaking ADR 0002 — the glue needs ``DOMAIN`` and the
config key before it has imported anything from Home Assistant.
"""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "recipe_wizard"

#: The one thing there is to configure: which directory the recipes live in.
CONF_RECIPES_DIR = "recipes_dir"

#: How often to look for a recipe that was added or edited outside Home
#: Assistant. Generous on purpose: recipes are written by a person with a text
#: editor and the enrichment loop, so minutes-scale latency is invisible, and
#: the interval only *stats* the files (see ``loader.library_fingerprint``) —
#: parsing happens when a mtime has actually moved.
UPDATE_INTERVAL = timedelta(minutes=15)
