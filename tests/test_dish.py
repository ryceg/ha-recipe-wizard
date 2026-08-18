"""The component tree, tested against the ways a hand-written walk gets it wrong.

The corpus is only two levels deep and holds no cycle and no citation, so the
deeper cases are built here rather than borrowed. Synthetic libraries are built
empty and standalone -- masses are given in grams so no food bank is needed --
because adding documents to the shared library leaks into the validator's
counts.
"""

import pytest

from conftest import CAKE, VANILLA_BC

from custom_components.recipe_wizard.core import (
    BatchConstraintError,
    Dish,
    Library,
    UnresolvableComponent,
    resolve_dish,
)
from custom_components.recipe_wizard.core.dish import ComponentCycleError
from custom_components.recipe_wizard.core.library import LibraryError
from custom_components.recipe_wizard.core.resolve import (
    BATCH_CONSTRAINT,
    VESSEL_CAPACITY,
)

QEEMA = "urn:recipe:rte/qeema"


# ---------------------------------------------------------------------------
# Building synthetic depth the corpus does not have
# ---------------------------------------------------------------------------


def _use(label, ref=None, *, batches=1.0, mass=None, optional=False, citation=None):
    node = {
        "@id": "#" + label.lower().replace(" ", "-"),
        "@type": "rw:ComponentUse",
        "rw:label": label,
    }
    if ref:
        node["rw:recipe"] = {"@id": ref}
    node["rw:requires"] = (
        {"value": mass, "unitCode": "GRM"} if mass is not None
        else {"rw:batches": batches}
    )
    if optional:
        node["rw:optional"] = True
    if citation:
        node["rw:citation"] = citation
    return node


def _recipe(recipe_id, name, *, grams=100.0, components=(), variant_of=None):
    node = {
        "@type": "Recipe",
        "@id": recipe_id,
        "name": name,
        "rw:enrichmentLevel": 3,
        "rw:yieldBasis": "sumOfInputs",
        "rw:ingredients": [{
            "@id": "#stuff",
            "@type": "rw:Ingredient",
            "name": f"{name} stuff",
            "rw:mass": {"value": grams, "unitCode": "GRM"},
        }],
        "rw:components": list(components),
    }
    if variant_of:
        node["rw:isVariantOf"] = {"@id": variant_of}
    return node


def _library(*docs) -> Library:
    library = Library()
    for doc in docs:
        library.add_document(doc)
    return library


# ---------------------------------------------------------------------------
# One walk instead of four
# ---------------------------------------------------------------------------


def test_the_cake_and_its_frosting_resolve_in_one_call(library):
    """``resolve()`` never reads ``recipe.components``, so before this every
    caller re-walked the tree itself and none of them agreed."""
    dish = resolve_dish(library, CAKE)

    assert isinstance(dish, Dish)
    assert dish.resolution.recipe_id == CAKE
    assert [c.label for c in dish.components] == ["Vanilla buttercream"]
    assert dish.components[0].resolution.recipe_id == VANILLA_BC
    assert [d.label for d in dish.walk()] == [
        "My Very Best Vanilla Cake", "Vanilla buttercream"
    ]


def test_the_use_not_the_recipe_names_the_component(library):
    """The cake calls it "Vanilla buttercream"; the document calls itself
    "Vanilla Buttercream". The tree shows the cook the parent's word for it."""
    dish = resolve_dish(library, CAKE)
    frosting = dish.components[0]
    assert frosting.label == "Vanilla buttercream"
    assert frosting.resolution.name == "Vanilla Buttercream"
    assert frosting.use is not None
    assert frosting.use.presentation == "inline"


# ---------------------------------------------------------------------------
# Scale propagation: the point of the exercise
# ---------------------------------------------------------------------------


def test_doubling_the_cake_doubles_its_frosting(library):
    """A component's use knows only its own ``requires``, so nothing in
    ``resolve_component()`` can see that the parent is being doubled. Without
    the tree multiplying it in, two cakes get one batch of frosting."""
    single = resolve_dish(library, CAKE).components[0].resolution
    double = resolve_dish(library, CAKE, batches=2).components[0].resolution

    assert double.scale == pytest.approx(2 * single.scale)
    assert double.requested_g == pytest.approx(2 * single.requested_g)
    # Not exactly double: the vanilla is sublinear and deliberately does not
    # keep up, which is a feature of the resolver rather than a rounding error.
    assert double.produced_g == pytest.approx(2 * single.produced_g, rel=0.02)


def test_scaling_a_component_does_not_mutate_the_library(library):
    """The use is document data shared by every caller. Scale it in place and
    the second person to double the cake gets a quadruple batch of frosting."""
    use = library.recipe(CAKE).components[0]
    resolve_dish(library, CAKE, batches=2)
    assert use.requires_batches == 1.0


def test_a_grandchild_multiplies_every_scale_above_it():
    """Two levels is all the corpus has, and a factor that is applied once
    looks identical to one that is applied at every level until there is a
    third. Half a batch of A pulls in half of B, and a quarter of C."""
    library = _library(
        _recipe("urn:a", "A", grams=100, components=[_use("B", "urn:b", batches=1)]),
        _recipe("urn:b", "B", grams=200, components=[_use("C", "urn:c", batches=2)]),
        _recipe("urn:c", "C", grams=50),
    )

    dish = resolve_dish(library, "urn:a", batches=0.5)
    b = dish.components[0]
    c = b.components[0]

    assert dish.resolution.scale == pytest.approx(0.5)
    assert b.resolution.scale == pytest.approx(0.5)
    assert c.resolution.scale == pytest.approx(1.0)  # 2 batches x 0.5
    assert c.resolution.produced_g == pytest.approx(50)


def test_a_component_asked_for_by_mass_scales_too():
    """Most parents ask in batches, but a mass request is the other branch and
    it would otherwise sail through a doubling unchanged."""
    library = _library(
        _recipe("urn:a", "A", components=[_use("B", "urn:b", mass=100)]),
        _recipe("urn:b", "B", grams=200),
    )

    dish = resolve_dish(library, "urn:a", batches=3)
    b = dish.components[0]
    assert b.resolution.requested_g == pytest.approx(300)
    assert b.resolution.scale == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# Citations are recorded, not raised
# ---------------------------------------------------------------------------


def test_a_cited_component_is_recorded_rather_than_raised():
    """Modernist's "see page 121" is referenced, renderable and not
    expandable. Letting ``UnresolvableComponent`` out of the tree would cost
    the cook the whole dish over a component they own a book about."""
    library = _library(
        _recipe("urn:a", "A", components=[
            _use("Stove-top carotene butter",
                 citation={"name": "Modernist Cuisine", "rw:page": 121}),
        ]),
    )

    dish = resolve_dish(library, "urn:a")

    assert dish.components == []
    assert [u.label for u in dish.unresolvable] == ["Stove-top carotene butter"]
    # The use is kept whole, so the message the cook needs is reproducible.
    assert "p.121" in str(UnresolvableComponent(dish.unresolvable[0]))
    assert dish.resolution.produced_g == pytest.approx(100)


def test_a_component_missing_from_the_library_still_raises():
    """Only the citation is caught. A component that points at an ``@id``
    nobody wrote is a data error, and swallowing it would hide the recipe the
    cook is about to be told to make without a recipe."""
    library = _library(
        _recipe("urn:a", "A", components=[_use("Ghost", "urn:nowhere")]),
    )
    with pytest.raises(LibraryError):
        resolve_dish(library, "urn:a")


# ---------------------------------------------------------------------------
# Optional whole components
# ---------------------------------------------------------------------------


def test_the_qeemas_mint_yogurt_stays_optional(library):
    """Optional as a whole component, not as an ingredient: the source offers
    plain yogurt instead. It is resolved either way, and flagged."""
    dish = resolve_dish(library, QEEMA)

    assert [(c.label, c.optional) for c in dish.components] == [("Mint yogurt", True)]
    assert len(list(dish.walk())) == 2
    assert len(list(dish.walk(include_optional=False))) == 1


def test_skipping_an_optional_component_skips_its_children_too():
    """Leaving the glaze out leaves out the candied peel that only the glaze
    uses. A filter that looks at one level puts it on the shopping list."""
    library = _library(
        _recipe("urn:cake", "Cake", components=[
            _use("Glaze", "urn:glaze", optional=True),
            _use("Streusel", "urn:streusel"),
        ]),
        _recipe("urn:glaze", "Glaze", components=[_use("Peel", "urn:peel")]),
        _recipe("urn:peel", "Peel"),
        _recipe("urn:streusel", "Streusel"),
    )

    dish = resolve_dish(library, "urn:cake")

    assert [d.label for d in dish.walk()] == ["Cake", "Glaze", "Peel", "Streusel"]
    assert [d.label for d in dish.walk(include_optional=False)] == ["Cake", "Streusel"]


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def test_a_component_cycle_raises_naming_the_path():
    """Nobody has written one, which is exactly when the guard gets left out.
    The variant chain refuses a cycle rather than hanging; so does this."""
    library = _library(
        _recipe("urn:a", "A", components=[_use("B", "urn:b")]),
        _recipe("urn:b", "B", components=[_use("A again", "urn:a")]),
    )

    with pytest.raises(ComponentCycleError) as exc:
        resolve_dish(library, "urn:a")
    assert "urn:a -> urn:b -> urn:a" in str(exc.value)


def test_a_recipe_that_uses_itself_raises():
    library = _library(
        _recipe("urn:a", "A", components=[_use("Itself", "urn:a")]),
    )
    with pytest.raises(ComponentCycleError):
        resolve_dish(library, "urn:a")


def test_two_components_sharing_a_sub_recipe_is_not_a_cycle():
    """A guard kept as a global "seen" set would refuse this, and a dish that
    uses one custard twice is ordinary rather than broken."""
    library = _library(
        _recipe("urn:trifle", "Trifle", components=[
            _use("Bottom layer", "urn:custard"),
            _use("Top layer", "urn:custard", batches=2),
        ]),
        _recipe("urn:custard", "Custard", grams=300),
    )

    dish = resolve_dish(library, "urn:trifle")

    assert [c.label for c in dish.components] == ["Bottom layer", "Top layer"]
    assert dish.components[1].resolution.produced_g == pytest.approx(
        2 * dish.components[0].resolution.produced_g
    )


def test_a_variant_inherits_its_bases_components():
    """A variant only adds or substitutes flavouring, and never restates the
    components. Read the document off disk instead of materialising it and a
    variant of the cake quietly has no frosting."""
    library = _library(
        _recipe("urn:base", "Base", components=[_use("Sauce", "urn:sauce")]),
        _recipe("urn:variant", "Variant", variant_of="urn:base"),
        _recipe("urn:sauce", "Sauce", grams=90),
    )

    dish = resolve_dish(library, "urn:variant")

    assert [c.label for c in dish.components] == ["Sauce"]
    assert dish.components[0].resolution.produced_g == pytest.approx(90)


# ---------------------------------------------------------------------------
# Warnings and change log keep their labels
# ---------------------------------------------------------------------------


def test_findings_keep_the_component_they_came_from(library):
    """"The tins will not hold it" is about the cake and not about the
    frosting. Flattened into one list the cook cannot tell, and a finding
    attached to the wrong thing is worse than no finding."""
    dish = resolve_dish(library, CAKE, batches=2)
    findings = dish.all_findings()

    assert findings, "doubling the cake must report the tins"
    assert all(label == dish.label for label, _ in findings)
    assert any(f.code == VESSEL_CAPACITY for _, f in findings)


def test_a_component_finding_is_not_lost_in_the_parents_list():
    """The child carries its own findings, and the only thing that reads them
    is a walk of the tree."""
    library = _library(
        _recipe("urn:a", "A", components=[_use("Sauce", "urn:sauce")]),
        {
            "@type": "Recipe",
            "@id": "urn:sauce",
            "name": "Sauce",
            "rw:enrichmentLevel": 3,
            "rw:batchConstraints": {
                "rw:minYield": {"value": 500, "unitCode": "GRM"},
                "rw:reason": "the paddle does not reach any less",
            },
            "rw:yieldBasis": "sumOfInputs",
            "rw:ingredients": [{
                "@id": "#stuff", "@type": "rw:Ingredient", "name": "stuff",
                "rw:mass": {"value": 100, "unitCode": "GRM"},
            }],
        },
    )

    dish = resolve_dish(library, "urn:a")
    labelled = dish.all_findings()

    assert dish.resolution.findings == []
    assert [label for label, _ in labelled] == ["Sauce"], (
        "the label is the use's, and it is the only thing that says which use a "
        "finding belongs to when one sub-recipe is used twice"
    )
    assert labelled[0][1].code == BATCH_CONSTRAINT
    assert labelled[0][1].recipe == "urn:sauce", (
        "the finding names the document it is true of, which is the sauce -- the "
        "label says which use, the recipe id says which document"
    )


def test_a_parents_local_override_is_visible_in_the_change_log(library):
    """The cake states 225 g of butter where the frosting states 250 g, both
    called "2 sticks". It is recorded against the frosting's resolution, so
    only a walk of the tree finds it."""
    dish = resolve_dish(library, CAKE)
    changes = dish.all_change_log()

    assert any(
        label == "Vanilla buttercream" and "225" in text for label, text in changes
    )


def test_strict_keeps_the_refusal_when_the_caller_wants_it():
    """A dish defaults to lenient because it is built to be shown, but the
    validator wants the batch constraint to raise."""
    library = _library(
        _recipe("urn:a", "A", components=[_use("Sauce", "urn:sauce")]),
        {
            "@type": "Recipe",
            "@id": "urn:sauce",
            "name": "Sauce",
            "rw:enrichmentLevel": 3,
            "rw:batchConstraints": {"rw:minYield": {"value": 500, "unitCode": "GRM"}},
            "rw:yieldBasis": "sumOfInputs",
            "rw:ingredients": [{
                "@id": "#stuff", "@type": "rw:Ingredient", "name": "stuff",
                "rw:mass": {"value": 100, "unitCode": "GRM"},
            }],
        },
    )

    with pytest.raises(BatchConstraintError):
        resolve_dish(library, "urn:a", strict=True)
