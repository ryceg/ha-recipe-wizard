"""Importing a page, and scoring an enrichment against ground truth."""

import json

import pytest

from conftest import CAKE

from custom_components.recipe_wizard.core import Library
from custom_components.recipe_wizard.core.compare import compare, similarity
from custom_components.recipe_wizard.core.importer import ImportError_, clean, extract_jsonld, import_page

PAGE = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"WebSite","name":"Some Site"},
  {"@type":"Recipe","name":"Test Sauté","url":"https://example.com/recipes/test-saute/",
   "author":{"@type":"Person","name":"A Cook"},
   "prepTime":"PT5M","cookTime":"PT15M","recipeYield":"4",
   "recipeIngredient":["3 tbsp olive oil","1 large onion, diced","500g/1 lb beef mince"],
   "recipeInstructions":[
     {"@type":"HowToSection","name":"Cook","itemListElement":[
       {"@type":"HowToStep","text":"Heat the <b>oil</b> and cook the onion."},
       {"@type":"HowToStep","text":"Add the beef &amp; brown it."}]},
     {"@type":"HowToStep","text":"Simmer 45 minutes."}]}
]}
</script></head><body></body></html>
"""


def test_jsonld_is_found_through_the_graph_wrapper():
    nodes = extract_jsonld(PAGE)
    assert {n["@type"] for n in nodes} == {"WebSite", "Recipe"}


def test_the_document_keeps_every_string_as_published():
    """Importing mechanically is the whole point: a model reading the page can
    paraphrase a quantity, and an importer cannot."""
    doc = import_page(PAGE)
    assert doc["recipeIngredient"] == [
        "3 tbsp olive oil", "1 large onion, diced", "500g/1 lb beef mince",
    ]


def test_sections_and_bare_steps_both_flatten_in_order():
    doc = import_page(PAGE)
    texts = [s["text"] for s in doc["recipeInstructions"]]
    assert texts == [
        "Heat the oil and cook the onion.",
        "Add the beef & brown it.",
        "Simmer 45 minutes.",
    ]
    assert [s["position"] for s in doc["recipeInstructions"]] == [1, 2, 3]


def test_markup_and_entities_are_cleaned_without_rewording():
    assert clean("Heat the <b>oil</b> &amp; wait") == "Heat the oil & wait"


def test_accents_survive_the_round_trip():
    doc = import_page(PAGE)
    assert doc["name"] == "Test Sauté"
    assert json.loads(json.dumps(doc, ensure_ascii=False))["name"] == "Test Sauté"


def test_the_id_comes_from_the_url_slug():
    doc = import_page(PAGE)
    assert doc["@id"] == "urn:recipe:example/test-saute"


def test_an_imported_document_is_level_0_and_loads(library):
    doc = import_page(PAGE)
    assert doc["rw:enrichmentLevel"] == 0
    scratch = Library()
    scratch.foods = library.foods
    scratch.add_document(doc)
    recipe = scratch.recipe(doc["@id"])
    assert len(recipe.ingredients) == 3, "the strings become visible rows"
    assert len(recipe.steps) == 3


def test_a_page_without_a_recipe_raises():
    with pytest.raises(ImportError_, match="no schema.org Recipe"):
        import_page("<html><head></head><body>nothing here</body></html>")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_a_recipe_scores_perfectly_against_itself(library, cake):
    result = compare(cake, cake)
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.ingredients_missing == []


def test_a_bare_scrape_scores_zero_on_edges(library, cake):
    """It has no edges at all, which is the correct score, not a tool failure."""
    scratch = Library()
    scratch.foods = library.foods
    scratch.add_document({
        "@type": "Recipe", "@id": "urn:recipe:test/scrape", "name": cake.name,
        "recipeIngredient": [i.original_text for i in cake.ingredients],
        "recipeInstructions": [{"@type": "HowToStep", "text": s.text}
                               for s in cake.steps],
    })
    result = compare(cake, scratch.recipe("urn:recipe:test/scrape"))
    assert result.steps_matched == len(cake.steps), "steps still align on text"
    assert result.recall == 0.0
    assert len(result.edges_absent) == 9


def test_a_wrong_link_is_named_not_just_counted(library, cake):
    """The output has to be actionable, or it cannot drive a fix."""
    candidate = cake.copy()
    salt = next(c for c in candidate.step("#whisk-dry").consumes if c.ref == "#salt")
    candidate.step("#whisk-dry").consumes.remove(salt)
    candidate.step("#beat-eggs").consumes.append(salt)

    result = compare(cake, candidate)
    assert any("kosher salt -> step 3" in e for e in result.edges_absent)
    assert any("kosher salt -> step 4" in e for e in result.edges_wrong)
    assert result.precision < 1.0


def test_alignment_tolerates_reworded_steps(library, cake):
    """A low score should mean the graph is wrong, not that the wording moved."""
    candidate = cake.copy()
    for step in candidate.steps:
        step.text = step.text.replace("the ", "").replace("Add ", "Now add ")
    result = compare(cake, candidate)
    assert result.steps_matched == len(cake.steps)
    assert result.recall == 1.0


def test_similarity_is_on_content_words():
    assert similarity("Whisk the flour and salt", "whisk flour, salt") > 0.7
    assert similarity("Beat the eggs", "Preheat the oven") < 0.2
