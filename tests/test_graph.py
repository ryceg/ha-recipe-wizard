"""The one index over the dataflow graph, and the drift it was built to stop.

Every test here is named after a failure that the five separate walks either
produced or were one honest document away from producing. Two of them are the
asymmetry bug: a fully-qualified reference resolved for an ingredient and
vanished for a component in the same function, and a scheduling constraint whose
target was written the long way drew no edge while still having a mandatory wait
looked up for it.
"""

import pytest
from conftest import CAKE, COFFEE_BC
from support import build_recipe, component, ingredient, portion, step

from custom_components.recipe_wizard.core.adjust import apply_adjustments
from custom_components.recipe_wizard.core.graph import (
    COMPONENT,
    INGREDIENT,
    PRODUCT,
    recipe_graph,
)
from custom_components.recipe_wizard.core.resolve import resolve
from custom_components.recipe_wizard.core.schedule import schedule, topological_order


def _cake_with_a_long_reference():
    """A cake whose steps name the flour and the frosting the long way round.

    ``@id`` is identity and a fully-qualified reference is legal (docs/format.md
    principle 4), so a document is entitled to write either. The corpus happens
    to write fragments everywhere, which is exactly why nothing caught the split.
    """
    doc_id = "urn:recipe:test/long-form-cake"
    return build_recipe(
        id=doc_id,
        name="Long form cake",
        ingredients=[ingredient("flour", mass=250)],
        components=[component("Vanilla buttercream", id="#frosting",
                              recipe="urn:recipe:test/frosting")],
        steps=[
            step("#bake", consumes=[f"{doc_id}#flour"],
                 produces=("#layers", "Baked layers")),
            step("#assemble", consumes=["#layers", f"{doc_id}#frosting"],
                 produces=("#cake", "Frosted cake")),
        ],
    )


# ---------------------------------------------------------------------------
# One fragment-tolerance rule, across all three id namespaces
# ---------------------------------------------------------------------------


def test_a_fully_qualified_reference_reaches_a_component_as_well_as_an_ingredient():
    """The asymmetry bug, stated as a document.

    ``Recipe.ingredient()`` and ``Recipe.step()`` have always accepted
    ``urn:recipe:x#flour`` as well as ``#flour``. There was no
    ``Recipe.component()``, so ``render.ingredients_for_step`` resolved the
    ingredient through the tolerant lookup and matched the component with
    ``c.id == ref`` on the next line -- one function, two rules, and the same
    reference working for a flour row and silently dropping a sub-recipe.
    """
    recipe = _cake_with_a_long_reference()
    graph = recipe_graph(recipe)
    long_form = f"{recipe.id}#frosting"

    # Both spellings, both namespaces, one rule.
    assert graph.ingredient(f"{recipe.id}#flour").name == "flour"
    assert graph.ingredient("#flour").name == "flour"
    assert graph.component(long_form).label == "Vanilla buttercream"
    assert graph.component("#frosting").label == "Vanilla buttercream"
    assert recipe.component(long_form) is recipe.component("#frosting")

    # And the step that consumes it gets a row rather than nothing at all.
    labels = [entry.label for entry in graph.step_inputs("#assemble")]
    assert labels == ["Baked layers", "Vanilla buttercream"]


def test_a_resolved_reference_is_reported_under_the_nodes_own_id():
    """Otherwise the fix renders a name and loses the weight.

    ``cookalong.step_ingredients`` looks a mass up by the id it is handed,
    against rows filed under the ingredient's own ``@id``. Handing back the
    spelling the *step* used would resolve the label and then miss the mass, so
    a fully-qualified reference would print "flour" with no grams beside it.
    """
    recipe = _cake_with_a_long_reference()
    graph = recipe_graph(recipe)

    inputs = graph.step_inputs("#bake")
    assert [entry.ref for entry in inputs] == ["#flour"]
    assert graph.canonical(f"{recipe.id}#flour") == "#flour"


def test_a_bare_fragment_does_not_reach_another_documents_node():
    """The rule is one-directional, and widening it would be a scope change.

    Try the reference as written, then its fragment -- and never the other way.
    A graph that let ``#flour`` match a node stored as
    ``urn:recipe:other/x#flour`` would let a bare fragment address a node the
    document does not own, which is not tolerance but guessing.
    """
    recipe = build_recipe(
        id="urn:recipe:test/qualified-rows",
        ingredients=[ingredient("flour", mass=250,
                                id="urn:recipe:test/qualified-rows#flour")],
        steps=[step("#mix", consumes=["urn:recipe:test/qualified-rows#flour"],
                    produces=("#dough", "Dough"))],
    )
    graph = recipe_graph(recipe)

    assert graph.ingredient("urn:recipe:test/qualified-rows#flour") is not None
    assert graph.ingredient("#flour") is None


def test_the_three_id_namespaces_answer_through_one_lookup(library, brownies):
    """A ``rw:consumes`` may point at any of the three, and the caller asking
    "what is this" should not have to know which before it asks."""
    graph = recipe_graph(brownies)

    assert graph.node("#peanut-butter").kind == INGREDIENT
    assert graph.node("#brownie-batter").kind == PRODUCT
    assert graph.node("#nothing-like-this") is None

    cake = recipe_graph(library.recipe(CAKE))
    assert cake.node("#frosting").kind == COMPONENT
    assert cake.label("#frosting") == "Vanilla buttercream"


def test_a_dangling_reference_keeps_the_spelling_the_author_used():
    """The validator has to quote a bad reference back in the author's own words,
    so an unresolvable ref is filed as written rather than normalised."""
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250)],
        steps=[step("#mix", consumes=["#flour", "urn:recipe:test/x#ghost"],
                    produces=("#dough", "Dough"))],
    )
    graph = recipe_graph(recipe)

    assert graph.node("urn:recipe:test/x#ghost") is None
    assert graph.canonical("urn:recipe:test/x#ghost") == "urn:recipe:test/x#ghost"
    assert [use.ref for use in graph.edges] == [
        "#flour", "urn:recipe:test/x#ghost",
    ]
    # And it is dropped from the cook's list rather than guessed at.
    assert [entry.ref for entry in graph.step_inputs("#mix")] == ["#flour"]


# ---------------------------------------------------------------------------
# Producers and consumers: one answer where there were three shapes
# ---------------------------------------------------------------------------


def test_the_producer_of_a_ref_is_one_answer_rather_than_three(brownies):
    """The planner wanted a step id, the renderer a label, the validator only
    whether the id existed. All three are the emitting step plus an attribute,
    and the renderer's version was rebuilt on every single call."""
    graph = recipe_graph(brownies)

    assert graph.producer("#brownie-batter").id == "#add-dry"
    assert graph.label("#brownie-batter") == "Brownie batter"
    assert graph.producer("#peanut-butter") is None, "an ingredient is not produced"
    assert "#brownie-batter" in graph.product_ids


def test_consumers_carry_the_portion_each_step_takes(brownies):
    """The reason portions exist, asked of the graph rather than of every step.

    Without them the whole 250 g of peanut butter renders against step 2 and
    step 12's "dollop 2 tbsp across the surface" shows no ingredient at all.
    """
    uses = recipe_graph(brownies).consumers("#peanut-butter")
    assert [(use.step.id, use.portion.describe()) for use in uses] == [
        ("#spread-pb", "all but the reserved 2 tbsp"),
        ("#dollop", "2 tbsp"),
    ]


def test_two_spellings_of_one_target_are_one_target():
    """Otherwise a document can take 60% of a thing twice and nothing notices.

    The portion rules add fractions up *per target*. Grouping them by the
    reference each step happened to write would file the same batter under two
    keys and report neither the overdraw nor the double claim.
    """
    doc_id = "urn:recipe:test/split-two-ways"
    recipe = build_recipe(
        id=doc_id,
        ingredients=[ingredient("flour", mass=250)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#batter", "Batter")),
            step("#pour", consumes=[("#batter", portion(fraction=0.6))],
                 produces=("#tray-one", "First tray")),
            step("#pour-again",
                 consumes=[(f"{doc_id}#batter", portion(fraction=0.6))],
                 produces=("#tray-two", "Second tray")),
        ],
    )
    graph = recipe_graph(recipe)

    uses = graph.consumers("#batter")
    assert [use.step.id for use in uses] == ["#pour", "#pour-again"]
    assert sum(use.portion.fraction for use in uses) == pytest.approx(1.2)


def test_first_use_is_the_step_rather_than_its_number():
    """What made the renderer's row-blocking collapse two blocks into one.

    An ingredient's block is decided by the first step that consumes it. Keyed on
    the step's ``position`` *number*, two ingredients first used by two different
    steps that a document numbers the same are filed as one block; keyed on the
    step, they are not.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=250), ingredient("butter", mass=100)],
        steps=[
            step("#sift", consumes=["#flour"], produces=("#dry", "Dry mix"),
                 position=1),
            step("#cream", consumes=["#butter"], produces=("#creamed", "Creamed butter"),
                 position=1),
            step("#combine", consumes=["#dry", "#creamed"],
                 produces=("#dough", "Dough"), position=2),
        ],
    )
    graph = recipe_graph(recipe)

    assert graph.first_use("#flour").id == "#sift"
    assert graph.first_use("#butter").id == "#cream"
    assert graph.first_use("#flour").position == graph.first_use("#butter").position
    assert graph.first_use("#dough") is None, "nothing consumes the finished dough"


# ---------------------------------------------------------------------------
# The three notions of "the end", which are three questions
# ---------------------------------------------------------------------------


def test_the_three_notions_of_the_end_are_three_different_questions():
    """Merging them would be a behaviour change dressed as a refactor.

    They coincide across today's corpus and stop coinciding the moment a recipe
    finishes two things at once, or ends on an instruction that produces nothing.
    The validator excuses the last step *on the page* from needing a dependant,
    and separately asks which *products* nothing takes; the answers are not even
    the same shape.
    """
    side_by_side = build_recipe(
        name="Curry and rice",
        ingredients=[ingredient("beef mince", mass=500), ingredient("rice", mass=300)],
        steps=[
            step("#curry", consumes=["#beef-mince"], produces=("#qeema", "Qeema")),
            step("#boil", consumes=["#rice"], produces=("#steamed", "Steamed rice")),
        ],
    )
    graph = recipe_graph(side_by_side)
    assert graph.last_position == 2, "one last page"
    assert graph.unconsumed_products() == {"#qeema", "#steamed"}, "two loose ends"
    assert graph.sink_steps() == [], "and no step that emits nothing"

    plated = build_recipe(
        name="Curry, plated",
        ingredients=[ingredient("beef mince", mass=500)],
        steps=[
            step("#curry", consumes=["#beef-mince"], produces=("#qeema", "Qeema")),
            step("#serve", consumes=["#qeema"]),
        ],
    )
    graph = recipe_graph(plated)
    assert graph.last_position == 2
    assert graph.unconsumed_products() == set(), "the qeema is taken by the plating"
    assert [s.id for s in graph.sink_steps()] == ["#serve"]


# ---------------------------------------------------------------------------
# Dependency edges
# ---------------------------------------------------------------------------


def test_a_constraint_naming_its_step_the_long_way_still_draws_the_edge():
    """The planner's half of the asymmetry, and it lost an hour of chilling.

    ``dependencies`` matched a ``rw:minDelayAfter``'s target by exact dict key
    while ``_edge_gap`` matched the same target through the tolerant
    ``recipe.step()``. A fully-qualified ``rw:from`` therefore produced no edge
    at all, and the floor it carried was dropped in silence -- the same class of
    mistake as cutting the brownies straight out of the oven.
    """
    doc_id = "urn:recipe:test/long-form-chill"
    recipe = build_recipe(
        id=doc_id,
        ingredients=[ingredient("butter", mass=250)],
        steps=[
            step("#chill-tin", produces=("#cold-tin", "Chilled tin"), duration=5),
            step("#mix", consumes=["#butter"], produces=("#dough", "Dough"),
                 duration=5,
                 min_delay_after=[(f"{doc_id}#chill-tin", "PT1H",
                                   "the tin has to be properly cold")]),
        ],
    )
    graph = recipe_graph(recipe)

    assert graph.dependencies["#mix"] == {"#chill-tin"}
    plan = schedule(graph)
    gap = plan.step("#mix").start_s - plan.step("#chill-tin").end_s
    assert gap == pytest.approx(3600, abs=1)


def test_reading_the_dependency_map_does_not_consume_it(cake):
    """The hazard a shared index introduces, and the one it actually hit.

    ``topological_order`` used to shallow-copy the map it was given and then
    ``difference_update`` the sets inside it, which was harmless only because
    every caller rebuilt the map first. Sharing one map per graph turns that into
    a plan that is right once and wrong every time after.
    """
    graph = recipe_graph(cake)

    first = [s.id for s in topological_order(graph)]
    assert graph.dependencies["#cool-in-pan"] == {"#bake"}
    second = [s.id for s in topological_order(graph)]

    assert first == second
    assert graph.dependencies["#cool-in-pan"] == {"#bake"}


def test_successors_invert_the_dependencies(cake):
    graph = recipe_graph(cake)
    assert "#cool-in-pan" in graph.successors["#bake"]
    assert graph.successors["#assemble"] == set(), "nothing follows the last step"


# ---------------------------------------------------------------------------
# Which document gets indexed, and for how long
# ---------------------------------------------------------------------------


def test_a_resolution_is_indexed_from_the_document_it_is_true_of(library):
    """The coffee buttercream's own file is a patch list: zero steps, zero rows.

    Indexing *that* answers every question with "nothing", which is the shape of
    the bug ``effective_recipe`` was written for. A graph over the resolution has
    the base's steps and the variant's substitution.
    """
    on_disk = recipe_graph(library.recipe(COFFEE_BC))
    assert on_disk.edges == ()

    resolved = recipe_graph(resolve(library, COFFEE_BC, strict=False))
    assert [s.id for s in resolved.ordered_steps] == [
        "#cream-butter", "#add-sugar", "#finish",
    ]
    assert resolved.ingredient("#vanilla").name == "espresso concentrate"


def test_a_graph_is_a_snapshot_of_the_document_it_was_handed():
    """Why no graph is memoised on a ``Recipe`` or on a ``Resolution``.

    ``apply_adjustments`` inserts steps and renumbers every position after them,
    so an index that outlived a patch would report a step count, a set of
    positions and a first-use map the document no longer has. It would read as
    bad data rather than as a stale cache, which is why the index is built by the
    caller that needs it, from the effective document, and passed down.
    """
    base = build_recipe(
        id="urn:recipe:test/patched",
        ingredients=[ingredient("flour", mass=250), ingredient("salt", mass=5)],
        steps=[
            step("#mix", consumes=["#flour"], produces=("#dough", "Dough")),
            step("#bake", consumes=["#dough"], produces=("#loaf", "Loaf")),
        ],
        adjustments=[{
            "@type": "rw:InsertStep",
            "rw:after": {"@id": "#mix"},
            "rw:step": step("#season", consumes=["#salt"],
                            produces=("#seasoned", "Seasoned dough")),
        }],
    )
    before = recipe_graph(base)
    patched, _ = apply_adjustments(base, base.adjustments)
    after = recipe_graph(patched)

    assert before.step("#season") is None
    assert before.first_use("#salt") is None
    assert before.last_position == 2

    assert after.step("#season") is not None
    assert after.first_use("#salt").id == "#season"
    assert after.last_position == 3, "every position after the insert moved"


def test_a_graph_handed_back_is_the_graph_that_was_passed_in(brownies):
    """So a function deep in a walk can take either and never rebuild.

    ``schedule()``, ``render_table()`` and ``blocks()`` all accept a document, a
    resolution or a graph. The last case is the one that stops the four rebuilt
    id indexes coming back.
    """
    graph = recipe_graph(brownies)
    assert recipe_graph(graph) is graph
    assert recipe_graph(brownies).recipe is brownies


def test_the_step_index_is_shared_rather_than_rebuilt(brownies):
    graph = recipe_graph(brownies)
    assert graph.steps_by_id is graph.steps_by_id
    assert graph.steps_by_id["#bake"] is graph.step("#bake")
    with pytest.raises(TypeError):
        graph.steps_by_id["#invented"] = None  # type: ignore[index]


def test_the_real_corpus_indexes_without_a_dangling_reference(library):
    """The contract the enrichment skill iterates against, from the graph's side:
    every ``rw:consumes`` in the library names something that exists."""
    for recipe in library:
        graph = recipe_graph(recipe)
        unknown = [use.ref for use in graph.edges if graph.node(use.ref) is None]
        assert unknown == [], f"{recipe.id} consumes {unknown}"


def test_a_component_use_is_indexed_even_when_it_is_only_a_citation(library):
    """Modernist's "see page 121" is referenced, renderable, and not expandable.
    It still has to appear in the ingredient column."""
    recipe = build_recipe(
        name="Cites a book",
        ingredients=[ingredient("flour", mass=250)],
        components=[{
            "@id": "#sauce",
            "@type": "rw:ComponentUse",
            "rw:label": "Bolognese",
            "rw:citation": {"name": "Dinner", "rw:page": 308},
        }],
        steps=[step("#combine", consumes=["#flour", "#sauce"],
                    produces=("#baked", "Baked pasta"))],
    )
    graph = recipe_graph(recipe)
    assert graph.component("#sauce").label == "Bolognese"
    assert [entry.label for entry in graph.step_inputs("#combine")] == [
        "flour", "Bolognese",
    ]
