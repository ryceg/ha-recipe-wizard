import json
from copy import deepcopy
from pathlib import Path

import pytest

from support import build_recipe, food_bank

from custom_components.recipe_wizard.core import Library
from custom_components.recipe_wizard.core.library import DEFAULT_RECIPES

VANILLA_BC = "urn:recipe:rte/vanilla-buttercream"
CHOCOLATE_BC = "urn:recipe:rte/chocolate-buttercream"
COFFEE_BC = "urn:recipe:local/coffee-buttercream"
CAKE = "urn:recipe:rte/vanilla-cake"
BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"


@pytest.fixture(scope="session")
def corpus() -> list[dict]:
    """Every recipe document, read off disk exactly once.

    The parsing is not cached with it. A session-scoped ``Library`` is a mutable
    object shared by every test, and tests do mutate it -- a component's
    ``requires_batches``, a step's ``consumes``, an added test document -- so
    whatever one test did leaked into the whole-library assertions that ran after
    it. Re-reading the disk per test would be the obvious fix and the wrong one
    at 200 recipes; re-parsing cached bytes is a millisecond.
    """
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(Path(DEFAULT_RECIPES).rglob("*.json"))]


@pytest.fixture
def library(corpus) -> Library:
    """The real corpus, freshly parsed for this test and nobody else's.

    The documents are copied on the way in as well, so a test reaching into
    ``Recipe.raw`` cannot reach the next test either.
    """
    library = Library()
    library.foods = food_bank()
    for document in corpus:
        library.add_document(deepcopy(document))
    return library


@pytest.fixture
def cake(library):
    return library.recipe(CAKE)


@pytest.fixture
def brownies(library):
    return library.recipe(BROWNIES)


@pytest.fixture
def level0(library):
    """A bare schema.org scrape: ingredient strings, step text, nothing linked.

    Registered in this test's library only. It used to be added to the shared
    session-scoped one with no teardown, so ``urn:recipe:test/level0`` was part
    of the corpus for every test that ran afterwards -- including the assertions
    about what the whole library validates to.
    """
    recipe = build_recipe(
        id="urn:recipe:test/level0",
        name="Level 0 Scrape",
        ingredients=[
            "500 g beef mince",
            "1 onion, finely chopped",
            "2 tbsp olive oil",
        ],
        steps=[
            "Heat the oil and cook the onion.",
            "Add the beef and cook until browned.",
            "Simmer 45 minutes.",
        ],
    )
    library.recipes[recipe.id] = recipe
    return recipe
