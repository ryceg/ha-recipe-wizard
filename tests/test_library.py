"""Loading a directory of documents, and saying which one is broken."""

import json

import pytest

from custom_components.recipe_wizard.core.library import (
    DocumentError,
    FoodBank,
    FoodBankError,
    Library,
    LibraryError,
    LibraryProblem,
)
from support import build_document


def _corpus(tmp_path, **documents):
    """Write a directory of documents, returning the directory."""
    directory = tmp_path / "recipes"
    directory.mkdir()
    for name, document in documents.items():
        path = directory / f"{name}.json"
        if isinstance(document, str):
            path.write_text(document, encoding="utf-8")
        else:
            path.write_text(json.dumps(document), encoding="utf-8")
    return directory


def test_a_broken_document_names_the_file_it_is_in(tmp_path):
    """`json` reports a line and a column and never a filename.

    Fine when you are looking at the file you just edited. The enrichment loop
    runs against a bank heading for ~200 documents, and "Expecting ',' delimiter:
    line 1 column 37" on its own does not say which one to open.
    """
    directory = _corpus(
        tmp_path,
        good=build_document(id="urn:recipe:test/good"),
        broken='{"@type": "Recipe", "name": "truncated"',
    )

    with pytest.raises(DocumentError) as caught:
        Library.load(directory)

    assert "broken.json" in str(caught.value)
    assert caught.value.source is not None
    assert caught.value.source.name == "broken.json"
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)


def test_a_document_the_model_refuses_names_the_file_too(tmp_path):
    """Not every failure is malformed JSON. A duration that is not ISO 8601
    parses as JSON and dies in the model, which has never seen a filename."""
    document = build_document(id="urn:recipe:test/bad-duration")
    document["recipeInstructions"][0]["totalTime"] = "half an hour"
    directory = _corpus(tmp_path, sloppy=document)

    with pytest.raises(DocumentError) as caught:
        Library.load(directory)

    assert caught.value.source.name == "sloppy.json"


def test_a_recipe_with_no_identity_still_reads_as_a_lookup_failure(tmp_path):
    """Identity lives in the ``@id``, so a document without one cannot be
    indexed. It stays a ``LibraryError`` -- callers catch that as a
    ``LookupError`` -- and now says which file to go and fix."""
    directory = _corpus(tmp_path, anonymous={"@type": "Recipe", "name": "No id"})

    with pytest.raises(LibraryError) as caught:
        Library.load(directory)

    assert isinstance(caught.value, LookupError), "callers catch it as one"
    assert isinstance(caught.value, LibraryProblem), "and it carries a source"
    assert caught.value.source.name == "anonymous.json"


def test_an_unreadable_food_bank_is_a_different_problem_from_a_bad_recipe(tmp_path):
    """The bank ships with the library, so a broken one is a broken install.

    The distinction is load-bearing for anything with a user in front of it:
    "your recipe is malformed" and "this copy of the library is malformed" send
    that person to two different places.
    """
    bank = tmp_path / "foods.json"
    bank.write_text("{not json", encoding="utf-8")
    directory = _corpus(tmp_path, good=build_document(id="urn:recipe:test/good"))

    with pytest.raises(FoodBankError) as caught:
        Library.load(directory, bank)

    assert caught.value.source.name == "foods.json"
    assert isinstance(caught.value, DocumentError), "a bank is a document"

    with pytest.raises(FoodBankError):
        FoodBank.load(bank)


def test_a_missing_food_bank_says_so_rather_than_raising_oserror(tmp_path):
    with pytest.raises(FoodBankError):
        FoodBank.load(tmp_path / "not-there.json")


def test_every_load_failure_shares_one_base(tmp_path):
    """So a caller can catch the category without listing OSError, ValueError,
    TypeError, KeyError and LibraryError and hoping that is all of them."""
    directory = _corpus(tmp_path, broken="not json at all")

    with pytest.raises(LibraryProblem):
        Library.load(directory)
