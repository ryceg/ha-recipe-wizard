"""What a maintainer needs to see, and nothing a cook would mind publishing.

Gold ``diagnostics``. A diagnostics download is attached to a public issue by a
user who has not read it, so the usual shape of one of these -- dump everything,
then run it past ``async_redact_data`` -- is the wrong shape here. There are no
credentials to redact; **the sensitive thing is the recipes themselves**, which
are the user's own writing and quite often somebody else's copyright. So this
module redacts nothing, because it never gathers anything to redact.

The line is drawn at *content*: counts, shapes, paths, the config entry's own
settings, and the validator's stable codes are in; ingredient rows, step text,
recipe names and quantities are out. Two consequences a reader might otherwise
try to undo:

* **Recipe and node ids are published, message text is not.** A finding's
  ``code`` and ``node`` are the machine-readable half and are exactly what an
  issue report needs -- ``unresolved-mass`` on ``#milk`` is diagnosable, and the
  recipe id names the file. ``Finding.message`` is prose, and several rules build
  it by interpolating strings out of the document, so it is the one field that
  could carry a line of somebody's recipe into a public bug report. It is left
  out rather than filtered, because filtering prose is a judgement that has to be
  right every time a rule is added.
* **The cook-along cursor is included as a position, not as a step.** ``recipe_id``
  and a step number say what the entry is doing; resolving them into the step's
  words would put the recipe back in.

Everything here is read off objects already in memory, so nothing blocks and no
executor hop is needed -- with the one exception of the validator, which walks
every document and therefore goes through ``async_add_executor_job`` like every
other call into the library.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from homeassistant.core import HomeAssistant

from .const import CONF_RECIPES_DIR
from .core.library import Library
from .core.validate import Finding, validate_library
from .coordinator import RecipeWizardConfigEntry
from .cursor import saved_cursor


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RecipeWizardConfigEntry
) -> dict[str, Any]:
    """The entry, the library it loaded, and what the validator makes of it."""
    coordinator = entry.runtime_data.coordinator
    library = coordinator.data
    findings = await hass.async_add_executor_job(validate_library, library)
    saved = saved_cursor(entry)

    return {
        "entry": {
            # The one configured setting. A path rather than a secret, and the
            # first thing to ask about when nothing loads.
            "recipes_dir": entry.data.get(CONF_RECIPES_DIR),
            "options_keys": sorted(entry.options),
            "version": entry.version,
            "minor_version": entry.minor_version,
            "source": entry.source,
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            # The loader's own classification plus the file it names -- which is
            # the whole reason ``loader.py`` exists -- and never a traceback.
            "last_error": _error(coordinator.last_exception),
            "update_interval_seconds": (
                None
                if coordinator.update_interval is None
                else coordinator.update_interval.total_seconds()
            ),
        },
        "library": _library(library),
        "cook_along": {
            # Whether one is running, and where in it. Not which step, in words.
            "running": saved.running,
            "recipe_id": saved.recipe_id,
            "batches": saved.batches,
            "cursor": saved.cursor,
            "started_at": None if saved.started_at is None else saved.started_at.isoformat(),
        },
        "findings": _findings(findings),
    }


def _library(library: Library) -> dict[str, Any]:
    """Shape, not content: how many of each thing, and how far they are lifted.

    The enrichment histogram is the single most useful number in this file. Most
    reports about a recipe "not working" are a level-0 scrape being asked to do a
    level-3 thing, and the distribution says that at a glance without anybody
    having to name a recipe.
    """
    levels = Counter(recipe.enrichment_level for recipe in library)
    return {
        "recipes": len(library.recipes),
        "families": len(library.families),
        "foods": len(library.foods),
        "variants": sum(1 for recipe in library if recipe.is_variant_of),
        "with_components": sum(1 for recipe in library if recipe.components),
        "enrichment_levels": {str(level): levels[level] for level in sorted(levels)},
    }


def _findings(findings: list[Finding]) -> dict[str, Any]:
    """Every finding as level, code, recipe and node -- and a roll-up by code.

    The roll-up is what makes a two-hundred-recipe library readable: forty
    ``unresolved-mass`` warnings are one fact about a library that has not been
    enriched, and the per-finding list underneath is there for the two that are
    not like the others.
    """
    return {
        "by_level": dict(Counter(finding.level for finding in findings)),
        "by_code": dict(Counter(finding.code for finding in findings)),
        "detail": [
            {
                "level": finding.level,
                "code": finding.code,
                "recipe": finding.recipe,
                "node": finding.node,
            }
            for finding in findings
        ],
    }


def _error(exception: BaseException | None) -> str | None:
    """The last update failure as one line, or ``None``.

    ``str`` rather than the exception: ``repr`` on a ``LibraryProblem`` carries
    its arguments, and a traceback would carry the parser's view of a half-written
    document.
    """
    return None if exception is None else str(exception)
