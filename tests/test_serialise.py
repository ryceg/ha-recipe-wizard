"""A dish as JSON: what the wire carries, and what it must not invent.

The failures these are named after are the ones a third renderer invites. Two of
them have already happened to the other two renderers: a variant serialised from
its own document rather than the one it inherited, and a surface deriving a
number the library deliberately refused to.
"""

import json
import math

import pytest
from conftest import BROWNIES, CAKE, COFFEE_BC

from custom_components.recipe_wizard.core.dish import resolve_dish
from custom_components.recipe_wizard.core.render import table
from custom_components.recipe_wizard.core.schedule import schedule
from custom_components.recipe_wizard.core.serialise import dish_json, library_json
from custom_components.recipe_wizard.core.shopping import shopping_list_from_dish

QEEMA = "urn:recipe:rte/qeema"


@pytest.fixture
def cake(library):
    return resolve_dish(library, CAKE, strict=False)


@pytest.fixture
def brownies(library):
    return resolve_dish(library, BROWNIES, strict=False)


def roundtrip(payload):
    """What the far end actually receives."""
    return json.loads(json.dumps(payload))


# ---------------------------------------------------------------------------
# It has to survive the wire
# ---------------------------------------------------------------------------


def test_every_dish_in_the_corpus_survives_a_json_round_trip(library):
    """Not "is serialisable" -- *unchanged*. A ``Duration`` that reached the
    payload would raise here, and a float that had gone non-finite would come
    back as something ``json.loads`` cannot produce."""
    for recipe in library:
        for batches in (0.5, 1.0, 3.0):
            dish = resolve_dish(library, recipe.id, batches=batches, strict=False)
            payload = dish_json(dish)
            assert roundtrip(payload) == payload, recipe.id


def test_no_number_on_the_wire_is_infinite_or_not_a_number(library):
    """``json.dumps`` writes ``NaN`` and ``Infinity`` happily and no JSON parser
    on the other side is obliged to read them back."""
    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for value in node:
                yield from walk(value)
        elif isinstance(node, float):
            yield node

    for recipe in library:
        dish = resolve_dish(library, recipe.id, strict=False)
        for number in walk(dish_json(dish)):
            assert math.isfinite(number), recipe.id


def test_an_absent_value_is_omitted_but_a_false_one_is_kept(cake):
    """``may_pause_after: false`` and "no pause information" are different
    claims, and a filter that dropped both would flatten the one this field
    exists to carry."""
    steps = dish_json(cake)["steps"]
    assert all("may_pause_after" in step for step in steps)
    assert any(step["may_pause_after"] is False for step in steps)
    assert any("doneness" not in step for step in steps), "absent, not null"
    assert not any(value is None for step in steps for value in step.values())


# ---------------------------------------------------------------------------
# It must not derive anything of its own
# ---------------------------------------------------------------------------


def test_the_weights_are_the_ones_the_table_derived(cake):
    """Both renderers read ``render.table``. A third deriving its own is how the
    print and the screen come to disagree about how much butter."""
    payload = dish_json(cake)
    assert [
        [(row["label"], row["weight"]) for row in block["rows"]]
        for block in payload["table"]
    ] == [
        [(row.label, row.weight) for row in block.rows]
        for block in table(cake.resolution)
    ]


def test_the_plan_figures_are_the_ones_the_planner_solved(brownies):
    plan = schedule(brownies.resolution)
    payload = dish_json(brownies)["plan"]
    assert payload["total_s"] == plan.total_s
    assert payload["waiting_s"] == plan.waiting_s
    assert [s["step_id"] for s in payload["steps"]] == [
        s.step_id for s in plan.steps
    ]


def test_the_effort_figures_still_partition_the_timeline_on_the_wire(brownies):
    """The header a consumer builds from these claims they add up."""
    plan = dish_json(brownies)["plan"]
    accounted = plan["active_s"] + plan["unattended_s"] + plan["waiting_s"]
    assert accounted == pytest.approx(plan["total_s"], abs=1)


def test_the_shopping_lines_are_the_ones_the_roll_up_merged(cake):
    listing = shopping_list_from_dish(cake)
    payload = dish_json(cake)["shopping"]
    assert [line["text"] for line in payload["lines"]] == [
        line.describe() for line in listing.lines
    ]


def test_a_portion_travels_as_words_and_not_as_a_number_to_multiply(brownies):
    """``docs/format.md`` § Portions: a portion is display-only and is never
    resolved to a mass. Sending the fraction as a number would invite the far end
    to multiply it by the row mass and print a confidently wrong "1,612 g"."""
    portions = [
        need["portion"]
        for step in dish_json(brownies)["steps"]
        for need in step["needs"]
    ]
    assert portions, "premise: the brownies take part of a row"
    assert any(not p["whole"] for p in portions)
    for portion in portions:
        assert isinstance(portion["text"], str)
        assert "fraction" not in portion and "quantity" not in portion


def test_a_needed_thing_carries_the_sentence_the_library_wrote(brownies):
    """"4 tbsp smooth peanut butter (of 500 g)" is a rule about how a partial row
    reads, and it lives in ``StepIngredient.describe``. A payload sending only the
    parts makes every consumer rebuild it, and the second implementation is the
    one that says "1,612 g"."""
    from custom_components.recipe_wizard.core.cookalong import cook_along_from_dish

    written = {
        (entry.recipe_id, entry.step.step_id, need.id): need.describe()
        for entry in cook_along_from_dish(brownies).sequence()
        for need in entry.step.ingredients
    }
    assert written, "premise: the brownies need things"
    on_the_wire = {
        (step["recipe_id"], step["step_id"], need["id"]): need["text"]
        for step in dish_json(brownies)["steps"]
        for need in step["needs"]
    }
    assert on_the_wire == written
    assert any(
        text != written_name
        for (_, _, ident), text in on_the_wire.items()
        for written_name in [ident.lstrip("#")]
    ), "and it is a sentence, not the name again"


def test_a_line_no_one_could_weigh_carries_no_total(library):
    """``total_g`` is ``None`` the moment a contributor has no derivable mass,
    and this must not reach for ``measured_g`` to have a number to show."""
    dish = resolve_dish(library, QEEMA, strict=False)
    lines = dish_json(dish)["shopping"]["lines"]
    unweighed = [line for line in lines if "total_g" not in line]
    assert unweighed, "premise: the qeema has a line with no derivable mass"
    for line in unweighed:
        assert "at least" in line["text"] or "no weight" in line["text"] \
            or "to taste" in line["text"]


# ---------------------------------------------------------------------------
# What the dish actually is
# ---------------------------------------------------------------------------


def test_a_variant_serialises_the_steps_it_inherited(library):
    """The defect both other renderers had: a variant's own document is a patch
    list, so serialising it off disk is a name and an empty walk."""
    payload = dish_json(resolve_dish(library, COFFEE_BC, strict=False))
    assert payload["steps"], "a variant has steps"
    assert any("Cream butter" in s["text"] for s in payload["steps"])
    assert any(
        need["name"] == "espresso concentrate"
        for step in payload["steps"]
        for need in step["needs"]
    )


def test_a_step_is_identified_by_the_pair_a_cursor_is_addressed_by(cake):
    """``(recipe_id, step_id)``, because a step id is unique in a recipe and not
    in a dish -- see ADR 0003. A consumer holding one of these can say where the
    cook is without inventing an identity of its own."""
    steps = dish_json(cake)["steps"]
    pairs = [(s["recipe_id"], s["step_id"]) for s in steps]
    assert len(set(pairs)) == len(pairs), "the pair is unique across the dish"
    bare = [s["step_id"] for s in steps]
    assert len(set(bare)) < len(bare), "premise: the step id alone is not"


def test_a_component_is_named_in_the_table_and_carries_no_weight(cake):
    rows = [
        row for block in dish_json(cake)["table"] for row in block["rows"]
        if row.get("component")
    ]
    assert rows, "the cake has a component"
    assert all(row["weight"] == "-" for row in rows)


def test_a_component_is_reported_with_its_own_numbers(cake):
    components = dish_json(cake)["components"]
    assert [c["label"] for c in components] == ["Vanilla buttercream"]
    assert components[0]["produced_g"] > 0
    assert components[0]["change_log"], "the cake overrides its butter"


def test_dropping_the_optional_component_changes_the_dish_not_the_rendering(
    library,
):
    """The qeema's mint yogurt is optional as a whole component. Leaving it out
    is a different walk and a different shopping list, which is why it is a
    property of the request and not a display flag."""
    dish = resolve_dish(library, QEEMA, strict=False)
    with_it = dish_json(dish, include_optional=True)
    without = dish_json(dish, include_optional=False)
    assert len(without["steps"]) < len(with_it["steps"])
    assert len(without["shopping"]["lines"]) < len(with_it["shopping"]["lines"])


def test_a_finding_carries_the_use_it_belongs_to(library):
    """``all_findings`` pairs each with the *use's* label, which is the only
    thing that says which use a finding is about when one sub-recipe is used
    twice. Flattening that away is the information this payload would lose."""
    dish = resolve_dish(library, CAKE, batches=8.0, strict=False)
    findings = dish_json(dish)["findings"]
    assert findings, "premise: eight batches will not fit the tins"
    assert all("where" in f and "level" in f and "code" in f for f in findings)


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


def test_the_index_lists_families_apart_from_recipes(library):
    """Nothing resolves through a family -- it is a browsing tag. A picker
    offering ``family:buttercream`` as a thing to cook would be offering
    something no resolver accepts, which is what the CLI does today."""
    index = library_json(library)
    ids = {r["id"] for r in index["recipes"]}
    assert index["families"], "premise: the corpus has a family"
    for family in index["families"]:
        assert family["id"] not in ids
        assert set(family["members"]) <= ids, "but its members are choosable"


def test_the_index_says_which_recipes_are_variants(library):
    index = library_json(library)
    entries = {r["id"]: r for r in index["recipes"]}
    assert entries[COFFEE_BC]["variant_of"] == "urn:recipe:rte/vanilla-buttercream"
    assert "variant_of" not in entries[CAKE], "absent, not null, for a base recipe"


def test_the_index_survives_the_wire(library):
    payload = library_json(library)
    assert roundtrip(payload) == payload


# ---------------------------------------------------------------------------
# The same payload, off the command line
# ---------------------------------------------------------------------------


def test_the_cli_emits_a_dish_as_the_api_would(capsys, library, monkeypatch):
    """``--json`` exists so the shape can be read without Home Assistant
    running. It has to be the *same* shape, not a second one written for a
    terminal."""
    from custom_components.recipe_wizard.core import __main__ as cli

    monkeypatch.setattr(cli.Library, "load", staticmethod(lambda *a, **k: library))
    assert cli.main(["qeema", "--batches", "2", "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)

    assert printed == roundtrip(
        dish_json(resolve_dish(library, QEEMA, batches=2.0, strict=False))
    )


def test_the_cli_json_stream_carries_nothing_but_json(capsys, library, monkeypatch):
    """``--list --json`` used to print the human listing first, which left a
    stream no parser could read and no reader could see was broken."""
    from custom_components.recipe_wizard.core import __main__ as cli

    monkeypatch.setattr(cli.Library, "load", staticmethod(lambda *a, **k: library))
    assert cli.main(["--list", "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == roundtrip(library_json(library))
