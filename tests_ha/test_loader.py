"""The four ways loading a recipe directory fails, and how the poll stays cheap.

These are the failures a config-flow form has to be able to phrase, so each one
is tested for its *key* rather than its message: the key is what picks the
sentence out of ``strings.json``, and a test asserting the sentence would go red
every time the wording improves.

Nothing here needs a ``hass``. It lives in this suite only because
``loader.py`` imports ``HomeAssistantError``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.recipe_wizard.loader import (
    RecipeLibraryError,
    library_fingerprint,
    load_library,
)
from tests_ha.support import write_recipe


def test_a_missing_directory_is_named_rather_than_raising_oserror(tmp_path: Path):
    """The commonest setup mistake is a typo, and it must read like one."""
    missing = tmp_path / "not-here"
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(missing)
    assert caught.value.error_key == "directory_not_found"
    assert str(missing) in caught.value.detail


def test_a_file_where_a_directory_should_be_is_also_directory_not_found(tmp_path: Path):
    """``is_dir()`` rather than ``exists()``: pointing at a recipe *file* is a typo
    of the same kind and must not fall through to "no recipes"."""
    target = tmp_path / "recipes.json"
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(target)
    assert caught.value.error_key == "directory_not_found"


def test_an_empty_directory_is_not_an_empty_library(tmp_path: Path):
    """Accepting it would produce an integration with nothing in it and no
    explanation, which is the shape of bug that gets reported as "it doesn't
    work"."""
    empty = tmp_path / "recipes"
    empty.mkdir()
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(empty)
    assert caught.value.error_key == "no_recipes"


def test_json_files_holding_no_recipe_report_no_recipes(tmp_path: Path):
    """A directory of families, or simply the wrong directory that happens to hold
    JSON. Same instruction to the user as an empty one, so the same key."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "buttercream.json").write_text(
        json.dumps({"@type": "rw:RecipeFamily", "@id": "urn:family:test/x",
                    "name": "Buttercreams"}),
        encoding="utf-8",
    )
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(recipes)
    assert caught.value.error_key == "no_recipes"


def test_a_document_that_will_not_parse_names_the_file(tmp_path: Path):
    """The reason this module exists rather than calling ``Library.load()``.

    "Expecting ',' delimiter: line 4" with no filename in front of it is not
    something a cook with 200 recipes can act on.
    """
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    write_recipe(recipes / "good.json", name="Good cake")
    (recipes / "broken.json").write_text('{"@type": "Recipe",', encoding="utf-8")
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(recipes)
    assert caught.value.error_key == "invalid_recipe"
    assert "broken.json" in caught.value.detail


def test_a_recipe_with_no_id_is_an_invalid_recipe_not_a_crash(tmp_path: Path):
    """Identity lives in the ``@id``, so a document without one cannot be indexed.
    The library says so by raising ``LibraryError``; the flow has to survive it."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    (recipes / "nameless.json").write_text(
        json.dumps({"@type": "Recipe", "name": "No identity"}), encoding="utf-8"
    )
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(recipes)
    assert caught.value.error_key == "invalid_recipe"
    assert "nameless.json" in caught.value.detail


def test_an_unreadable_food_bank_is_a_different_failure_from_a_bad_recipe(
    tmp_path: Path,
):
    """"Your recipes are fine, this copy of the integration is not" is a different
    instruction, so it cannot share a key with ``invalid_recipe``."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    write_recipe(recipes / "cake.json", name="Cake")
    bad_bank = tmp_path / "foods.json"
    bad_bank.write_text("not json at all", encoding="utf-8")
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(recipes, foods_path=bad_bank)
    assert caught.value.error_key == "foods_unreadable"


def test_a_missing_food_bank_is_also_foods_unreadable(tmp_path: Path):
    """``OSError`` and ``JSONDecodeError`` are the same problem to the user."""
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    write_recipe(recipes / "cake.json", name="Cake")
    with pytest.raises(RecipeLibraryError) as caught:
        load_library(recipes, foods_path=tmp_path / "gone.json")
    assert caught.value.error_key == "foods_unreadable"


def test_the_shipped_corpus_loads_with_its_shipped_food_bank(recipes_dir: Path):
    """The integration's default configuration has to work. Recipes are found in
    sub-directories too -- ``recipes/families/`` is one."""
    library = load_library(recipes_dir)
    assert len(library) >= 7
    assert library.families
    assert len(library.foods) > 0


# --- the poll -------------------------------------------------------------


def test_the_fingerprint_is_stable_when_nothing_changes(recipes_dir: Path):
    """If it were not, every interval would reparse and the guard would be a lie."""
    assert library_fingerprint(recipes_dir) == library_fingerprint(recipes_dir)


def test_an_added_recipe_changes_the_fingerprint(recipes_dir: Path):
    """The whole reason for polling: a recipe imported with the CLI must be seen
    without restarting Home Assistant."""
    before = library_fingerprint(recipes_dir)
    write_recipe(recipes_dir / "new.json", name="Brand new cake")
    assert library_fingerprint(recipes_dir) != before


def test_an_edited_recipe_changes_the_fingerprint(recipes_dir: Path):
    """Enrichment edits a document in place, so the file set alone is not enough."""
    target = next(recipes_dir.glob("*.json"))
    before = library_fingerprint(recipes_dir)
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert library_fingerprint(recipes_dir) != before


def test_a_deleted_directory_changes_the_fingerprint(recipes_dir: Path):
    """Without the directory's own existence in the signature, a deleted directory
    would produce the same empty fingerprint for ever and the reload would never
    fire -- the integration would serve a library that is no longer there."""
    before = library_fingerprint(recipes_dir)
    for path in recipes_dir.rglob("*.json"):
        path.unlink()
    for path in sorted(recipes_dir.rglob("*"), reverse=True):
        path.rmdir()
    recipes_dir.rmdir()
    assert library_fingerprint(recipes_dir) != before
