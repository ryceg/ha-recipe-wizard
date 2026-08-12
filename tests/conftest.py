import pytest

from recipe_wizard import Library

VANILLA_BC = "urn:recipe:rte/vanilla-buttercream"
CHOCOLATE_BC = "urn:recipe:rte/chocolate-buttercream"
COFFEE_BC = "urn:recipe:local/coffee-buttercream"
CAKE = "urn:recipe:rte/vanilla-cake"
BROWNIES = "urn:recipe:rte/peanut-butter-stuffed-brownies"


@pytest.fixture(scope="session")
def library() -> Library:
    return Library.load()


@pytest.fixture
def cake(library):
    return library.recipe(CAKE)


@pytest.fixture
def brownies(library):
    return library.recipe(BROWNIES)


@pytest.fixture
def level0(library):
    """A bare schema.org scrape: ingredient strings, step text, nothing linked."""
    library.add_document({
        "@type": "Recipe",
        "@id": "urn:recipe:test/level0",
        "name": "Level 0 Scrape",
        "recipeIngredient": [
            "500 g beef mince",
            "1 onion, finely chopped",
            "2 tbsp olive oil",
        ],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Heat the oil and cook the onion."},
            {"@type": "HowToStep", "text": "Add the beef and cook until browned."},
            {"@type": "HowToStep", "text": "Simmer 45 minutes."},
        ],
    })
    return library.recipe("urn:recipe:test/level0")
