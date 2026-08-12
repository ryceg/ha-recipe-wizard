"""Loading the recipe library off disk, and naming what went wrong.

Two callers need exactly the same thing and neither should own the other. The
config flow loads the library to answer "is this directory usable?" before it
writes a config entry (Bronze ``test-before-configure``); the coordinator loads
it to keep it fresh. So the shared part sits here.

What this adds over ``Library.load()`` is **which file, and which of four
distinct problems**. ``Library.load()`` raises whatever ``json`` or the model
raises, from a loop that has already forgotten the path it was reading — fine for
a CLI that prints a traceback next to the command you just typed, useless in a
config-flow form. A cook who mistyped a directory must be told that, and a cook
with one bad document must be told its name. The re-walk below is the price of
saying so, and it is four lines.

**Everything here is synchronous and blocks on file I/O.** Call it only through
``hass.async_add_executor_job``.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .core.library import DEFAULT_FOODS, FoodBank, Library, LibraryError

#: Fingerprint entry for a path that is not there. Distinct from any real
#: ``stat``, so a deleted recipe changes the fingerprint rather than vanishing
#: from it silently.
_MISSING = (None, None)


class RecipeLibraryError(HomeAssistantError):
    """The library could not be loaded, in words a config-flow form can show.

    ``error_key`` is both the key under ``config.error`` in ``strings.json`` and
    the key under ``exceptions``, so the same failure reads the same whether it
    surfaced in the flow or in a log line. ``detail`` is the part that names the
    file or the path — it goes into the ``{detail}`` placeholder rather than into
    the sentence, so the sentence stays translatable.
    """

    def __init__(self, error_key: str, detail: str = "") -> None:
        super().__init__(
            f"{error_key}: {detail}" if detail else error_key,
            translation_domain=DOMAIN,
            translation_key=error_key,
            translation_placeholders={"detail": detail},
        )
        self.error_key = error_key
        self.detail = detail


def load_library(
    recipes_dir: Path | str,
    foods_path: Path | str = DEFAULT_FOODS,
) -> Library:
    """Every recipe in ``recipes_dir``, or a ``RecipeLibraryError`` saying why not.

    Blocking. ``foods_path`` is a parameter rather than a constant read inline so
    that a test can hand it an unreadable bank without patching a module global;
    in production it is always the one that ships with the integration.
    """
    directory = Path(recipes_dir)
    if not directory.is_dir():
        raise RecipeLibraryError("directory_not_found", str(directory))

    try:
        foods = FoodBank.load(foods_path)
    except (OSError, ValueError) as err:
        # The bank ships inside the integration, so this is a broken install or
        # a broken download rather than anything the user typed. It still has to
        # be a distinct message: "your recipes are fine, this copy of the
        # integration is not" is a different instruction.
        raise RecipeLibraryError("foods_unreadable", str(err)) from err

    documents = sorted(directory.rglob("*.json"))
    if not documents:
        raise RecipeLibraryError("no_recipes", str(directory))

    library = Library()
    library.foods = foods
    for path in documents:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise RecipeLibraryError("invalid_recipe", f"{path.name} ({err})") from err
        try:
            library.add_document(document, path)
        except (LibraryError, ValueError, TypeError, KeyError) as err:
            raise RecipeLibraryError("invalid_recipe", f"{path.name} ({err})") from err

    if not library.recipes:
        # JSON files, but not one recipe among them — a directory of families, or
        # the wrong directory that happens to hold JSON. Same instruction to the
        # user as an empty one, so the same key.
        raise RecipeLibraryError("no_recipes", str(directory))
    return library


def library_fingerprint(
    recipes_dir: Path | str,
    foods_path: Path | str = DEFAULT_FOODS,
) -> tuple[object, ...]:
    """A cheap signature of the library on disk: what is there, and how old.

    Polling exists so a recipe added with ``python -m recipe_wizard --import``
    appears without restarting Home Assistant. Parsing ~200 documents every
    interval to discover that none of them changed would not be worth that, so
    the interval ``stat``s them and this is what it compares.

    The directory's own existence is in the signature. Without it, a directory
    that is deleted after a good load would produce the same empty signature
    every time and the reload would never fire.

    Blocking, like everything else in this module.
    """
    directory = Path(recipes_dir)
    entries: list[object] = [(str(directory), directory.is_dir())]
    for path in [*sorted(directory.rglob("*.json")), Path(foods_path)]:
        try:
            stat = path.stat()
        except OSError:
            entries.append((str(path), *_MISSING))
        else:
            entries.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(entries)
