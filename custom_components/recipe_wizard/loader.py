"""Loading the recipe library off disk, and naming what went wrong.

Two callers need exactly the same thing and neither should own the other. The
config flow loads the library to answer "is this directory usable?" before it
writes a config entry (Bronze ``test-before-configure``); the coordinator loads
it to keep it fresh. So the shared part sits here.

What this adds over ``Library.load()`` is **which of four distinct problems**,
in a form a config-flow form can show. The library names the file itself — every
``LibraryProblem`` carries its ``source`` — so all that is left here is deciding
which of them means "you mistyped the directory", which means "this document is
broken", and which means "this copy of the integration is broken". Those are
three different instructions to the user.

**Everything here is synchronous and blocks on file I/O.** Call it only through
``hass.async_add_executor_job``.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .core.library import (
    DEFAULT_FOODS,
    FoodBankError,
    Library,
    LibraryProblem,
)

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
        library = Library.load(directory, foods_path)
    except FoodBankError as err:
        # The bank ships inside the integration, so this is a broken install or
        # a broken download rather than anything the user typed. It still has to
        # be a distinct message: "your recipes are fine, this copy of the
        # integration is not" is a different instruction.
        raise RecipeLibraryError("foods_unreadable", str(err)) from err
    except LibraryProblem as err:
        # ``LibraryProblem`` carries the file, which is the whole reason this is
        # four lines rather than a second copy of ``Library.load``'s loop.
        where = err.source.name if err.source else str(directory)
        raise RecipeLibraryError("invalid_recipe", f"{where} ({err})") from err

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
