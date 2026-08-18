"""The resolver, tested against the cases the design got wrong on paper."""

import pytest

from conftest import BROWNIES, CAKE, CHOCOLATE_BC, COFFEE_BC, VANILLA_BC
from support import build_library, build_recipe, ingredient, step

from custom_components.recipe_wizard.core import (
    Adjustment,
    BatchConstraintError,
    BatchPolicy,
    Quantity,
    materialise,
    resolve,
    resolve_component,
)
from custom_components.recipe_wizard.core.adjust import AdjustmentError
from custom_components.recipe_wizard.core.mass import UNIT_DIVERGENCE
from custom_components.recipe_wizard.core.resolve import (
    BATCH_CONSTRAINT,
    BATCH_ROUNDED,
    VESSEL_CAPACITY,
    VESSEL_TIMING,
)


def _coded(resolution, code: str) -> list:
    """Findings under one code.

    Keyed on the code and never on the wording. Every one of these assertions
    used to read ``if "holds about" in w``, which meant a test would go green
    for a reworded sentence about something else entirely -- and meant the
    resolver could not reword its own messages without breaking tests that were
    not about wording.
    """
    return [f for f in resolution.findings if f.code == code]

# ---------------------------------------------------------------------------
# Level 0: a bare scrape must still be usable
# ---------------------------------------------------------------------------


def test_a_scraped_recipe_keeps_its_ingredient_strings(level0):
    """The failure that outranked every modelling gap.

    Before this, the loader read only rw:ingredients, so every recipe scraped
    off a website rendered with no ingredient column whatsoever -- not degraded,
    absent.
    """
    assert len(level0.ingredients) == 3
    assert level0.ingredients[0].name == "500 g beef mince"
    assert level0.ingredients[0].original_text == "500 g beef mince"


def test_enrichment_level_is_inferred_when_undeclared(level0, cake):
    assert level0.enrichment_level == 0
    assert cake.enrichment_level == 3


def test_a_scraped_recipe_resolves_without_raising(library, level0):
    result = resolve(library, level0.id, strict=False)
    assert result.batch_yield_g is None
    assert len(result.ingredients) == 3


# ---------------------------------------------------------------------------
# Yield and batches
# ---------------------------------------------------------------------------


def test_frosting_yield_is_derived_not_stated(library):
    """The source states no mass yield at all, only what a batch covers."""
    result = resolve(library, VANILLA_BC)
    # 250 g butter + 500 g icing sugar + 3 tsp vanilla; the milk is optional.
    assert result.batch_yield_g == pytest.approx(763, abs=2)


def test_coverage_claims_survive_as_text(library):
    """Displayed to the cook, computed with by nothing."""
    recipe = library.recipe(VANILLA_BC)
    assert len(recipe.covers) == 4
    assert any("12 cupcakes piped" in c for c in recipe.covers)


def test_the_cake_asks_for_one_batch_of_frosting(library, cake):
    """It never states a quantity, and one batch is what it means."""
    use = cake.components[0]
    assert use.requires_batches == 1.0
    assert use.requires_mass is None
    assert resolve_component(library, use).scale == pytest.approx(1.0)


def test_doubling_a_parent_doubles_its_component(library, cake):
    """Which is the whole of what coverage geometry was needed for."""
    use = cake.components[0]
    use.requires_batches = 2.0  # the library is this test's own; nothing escapes
    result = resolve_component(library, use)
    assert result.scale == pytest.approx(2.0)
    assert result.produced_g == pytest.approx(2 * 738, rel=0.02)


# ---------------------------------------------------------------------------
# Order of operations: adjust at base yield, then scale
# ---------------------------------------------------------------------------


def test_adjustments_apply_at_base_yield_then_scale(library):
    """The ordering that fails silently if you get it backwards.

    An override of "make the sugar 180 g" is written against the base recipe.
    Applied before scaling, a half batch gives 90 g. Applied after, it would
    give 180 g in a half batch -- twice the sugar, with nothing to indicate
    anything went wrong.
    """
    override = Adjustment(
        op="SetQuantity",
        target="#icing-sugar",
        payload={"rw:target": {"@id": "#icing-sugar"},
                 "rw:mass": {"value": 180, "unitCode": "GRM"}},
    )
    full = resolve(library, VANILLA_BC, adjustments=[override])
    assert _ingredient(full, "#icing-sugar").mass_g == pytest.approx(180)

    half = resolve(
        library, VANILLA_BC, adjustments=[override],
        requires_mass=Quantity(full.batch_yield_g / 2, "g"), strict=False,
    )
    assert _ingredient(half, "#icing-sugar").mass_g == pytest.approx(90, abs=1)


def test_cake_records_its_butter_disagreement_as_a_local_override(library, cake):
    """225 g here, 250 g on the standalone page, both called "2 sticks"."""
    standalone = resolve(library, VANILLA_BC)
    in_cake = resolve_component(library, cake.components[0])

    assert _ingredient(standalone, "#butter").mass_g == pytest.approx(250)
    assert _ingredient(in_cake, "#butter").mass_g == pytest.approx(225)

    ratio = (_ingredient(in_cake, "#butter").mass_g
             / _ingredient(in_cake, "#icing-sugar").mass_g)
    assert ratio == pytest.approx(0.45, abs=0.01), "1:2.22, not the standalone 1:2.0"


# ---------------------------------------------------------------------------
# Variants, siblings, families
# ---------------------------------------------------------------------------


def test_coffee_is_a_variant_and_inherits_everything_unstated(library):
    coffee = resolve(library, COFFEE_BC)
    vanilla = resolve(library, VANILLA_BC)
    assert [s.id for s in coffee.steps] == [s.id for s in vanilla.steps]

    espresso = _ingredient(coffee, "#vanilla")
    assert espresso.food_id == "food:espresso-concentrate"
    assert espresso.mass_g == pytest.approx(45)
    assert _ingredient(coffee, "#icing-sugar").mass_g == pytest.approx(450)


def test_a_variant_inherits_its_bases_coverage_text(library):
    recipe, _ = materialise(library, COFFEE_BC)
    assert len(recipe.covers) == 4


def test_chocolate_is_a_sibling_not_a_variant(library):
    """Every quantity and the method differ, so a patch would exceed the recipe."""
    chocolate = library.recipe(CHOCOLATE_BC)
    assert chocolate.is_variant_of is None
    assert chocolate.family == library.recipe(VANILLA_BC).family
    assert len(chocolate.steps) != len(library.recipe(VANILLA_BC).steps)

    resolved = resolve(library, CHOCOLATE_BC)
    ratio = (_ingredient(resolved, "#butter").mass_g
             / _ingredient(resolved, "#icing-sugar").mass_g)
    assert ratio == pytest.approx(0.63, abs=0.02), "1:1.6"


def test_a_family_does_not_resolve_anything(library):
    """It is a browsing tag. Swapping siblings is done by reading both recipes."""
    family = library.family("family:buttercream")
    assert len(family.members) == 3
    assert not hasattr(family, "interchangeable")


def test_a_patch_against_a_missing_target_fails_loudly(library):
    bad = Adjustment(
        op="SetQuantity", target="#does-not-exist",
        payload={"rw:target": {"@id": "#does-not-exist"},
                 "rw:mass": {"value": 1, "unitCode": "GRM"}},
    )
    with pytest.raises(AdjustmentError, match="no ingredient"):
        materialise(library, VANILLA_BC, adjustments=[bad])


# ---------------------------------------------------------------------------
# Batch reality
# ---------------------------------------------------------------------------


def test_a_batch_below_the_minimum_is_refused_with_its_reason(library):
    """You cannot make 200 g of buttercream; the paddle does not reach it."""
    with pytest.raises(BatchConstraintError, match="minimum batch"):
        resolve(library, VANILLA_BC, requires_mass=Quantity(200, "g"))


def test_strict_false_downgrades_the_refusal_to_a_warning(library):
    result = resolve(library, VANILLA_BC, requires_mass=Quantity(200, "g"),
                     strict=False)
    refusal = _coded(result, BATCH_CONSTRAINT)
    assert len(refusal) == 1
    assert refusal[0].level == "warning", (
        "not an error: the resolution that carries it is one a cook can work "
        "from, which is the whole of what strict=False asked for"
    )
    assert refusal[0].node is None, "the batch is the subject, not any one line"
    assert "minimum batch" in refusal[0].message


def test_discrete_eggs_round_up_and_renormalise_the_batch():
    """What a cook actually does: round the eggs, then rescale to them.

    The premise is stated rather than reverse-engineered out of the cake: a
    400 g batch built on 4 eggs, asked for 225 g, wants 2.25 eggs. There is no
    such thing as 2.25 eggs, so the batch goes up to 3 of them -- x0.75, not
    x0.5625 -- and the 75 g surplus is told to the cook rather than hidden.
    """
    recipe = build_recipe(ingredients=[
        ingredient("eggs", count=4, unit_mass=50, discrete=True),
        ingredient("flour", mass=200),
    ])
    library = build_library(recipe)

    result = resolve(
        library, recipe.id,
        requires_mass=Quantity(225, "g"),
        batch_policy=BatchPolicy(mode="roundUpToWholeUnit", basis="#eggs"),
    )
    assert result.batch_yield_g == pytest.approx(400)
    assert _ingredient(result, "#eggs").mass_g / 50 == pytest.approx(3.0)
    assert result.scale == pytest.approx(0.75)
    assert result.leftover_g == pytest.approx(75)
    assert "leftover" in result.summary()
    rounding = _coded(result, BATCH_ROUNDED)
    assert len(rounding) == 1, "the rounding is reported, not silently applied"
    assert "2.25 eggs rounded to 3" in rounding[0].message
    assert rounding[0].node == "#eggs", ("the basis it counted, so a reader "
                                         "goes straight to that line")


def test_sublinear_ingredients_do_not_scale_linearly(library):
    half = resolve(
        library, VANILLA_BC,
        requires_mass=Quantity(resolve(library, VANILLA_BC).batch_yield_g / 2, "g"),
        strict=False,
    )
    assert _ingredient(half, "#vanilla").mass_g == pytest.approx(13.2 * 0.707, rel=0.02)


def test_optional_ingredients_are_excluded_from_yield(library):
    result = resolve(library, VANILLA_BC)
    milk = _ingredient(result, "#milk")
    assert milk.optional and milk.mass_g > 0
    assert result.batch_yield_g == pytest.approx(763, abs=2)


# ---------------------------------------------------------------------------
# Scaling the vessel, not just the quantities
# ---------------------------------------------------------------------------


def test_doubling_the_cake_warns_that_the_tins_will_not_hold_it(library):
    """The failure that only surfaced once doubling was known to be routine."""
    result = resolve(library, CAKE, requires_batches=2.0)
    capacity = _coded(result, VESSEL_CAPACITY)
    assert len(capacity) == 1
    assert "you need roughly 4" in capacity[0].message
    assert capacity[0].node is None, (
        "rw:vessel is declared on the document and is not an ingredient, a step "
        "or a component -- there is no node to hand back to RecipeGraph.node, "
        "and inventing one would send a fixer at a step that is not wrong"
    )


def test_doubling_refuses_to_scale_the_bake_time(library):
    result = resolve(library, CAKE, requires_batches=2.0)
    timing = _coded(result, VESSEL_TIMING)
    assert len(timing) == 1
    assert "3 x 20cm round: 22 min" in timing[0].message
    assert timing[0].node is not None, (
        "unlike the capacity finding beside it, this one is about a step and "
        "names which -- the step whose rw:vesselOptions say so"
    )


def test_an_unscaled_recipe_gets_no_vessel_noise():
    """A recipe that would warn if it were scaled has to stay silent at x1.

    Built rather than borrowed: this used to assert the cake resolves with no
    warnings *at all*, so one volume measure added anywhere in it, with no
    density in the bank, failed a test about vessels.
    """
    recipe = build_recipe(
        ingredients=[ingredient("flour", mass=600)],
        steps=[step("#bake", consumes=["#flour"], produces=("#loaf", "Loaf"),
                    vessel_options=[("2 x 20cm round", "PT30M")])],
        vessel=("20 cm round tin", 1, 500),
    )
    library = build_library(recipe)

    assert resolve(library, recipe.id).findings == []
    assert resolve(library, recipe.id, requires_batches=2.0).findings, \
        "the premise: this recipe does have something to say once it is scaled"


# ---------------------------------------------------------------------------
# Portions
# ---------------------------------------------------------------------------


def test_fractional_portions_are_scale_invariant(library):
    doubled = resolve(library, BROWNIES, requires_batches=2.0, strict=False)
    step = next(s for s in doubled.steps if s.id == "#pour-half")
    assert step.portion_of("#brownie-batter").fraction == 0.5


def test_absolute_portions_scale(library):
    """"1 cup of the crumb" is two cups in a doubled batch; "half" is still half."""
    single = resolve(library, BROWNIES)
    doubled = resolve(library, BROWNIES, requires_batches=2.0, strict=False)
    before = next(s for s in single.steps if s.id == "#dollop")
    after = next(s for s in doubled.steps if s.id == "#dollop")
    assert before.portion_of("#peanut-butter").quantity.value == 2
    assert after.portion_of("#peanut-butter").quantity.value == 4


# ---------------------------------------------------------------------------
# Each line's mass, computed once
# ---------------------------------------------------------------------------


def test_a_line_is_reduced_to_grams_once_per_resolution(monkeypatch):
    """The resolver used to reduce every line twice over.

    ``batch_yield_grams`` computed the masses and flattened them to a
    ``dict[str, float | None]``, which lost each line's source, confidence and
    warnings -- so the loop building the resolved ingredients called
    ``ingredient_mass`` a second time on the same line just to read
    ``.confidence`` back, and had to discard that call's warnings to avoid
    reporting the chocolate buttercream's butter divergence twice.
    """
    recipe = build_recipe(ingredients=[
        ingredient("flour", mass=250),
        ingredient("butter", mass=200),
        ingredient("milk", volume=(1, "cup"), food="food:milk-full-fat"),
    ])
    library = build_library(recipe)

    from custom_components.recipe_wizard.core import mass as mass_module

    calls: list[str] = []
    real = mass_module.ingredient_mass

    def counting(ing, *args, **kwargs):
        calls.append(ing.id)
        return real(ing, *args, **kwargs)

    monkeypatch.setattr(mass_module, "ingredient_mass", counting)
    resolve(library, recipe.id)

    assert sorted(calls) == ["#butter", "#flour", "#milk"], (
        f"three lines, {len(calls)} conversions: every one of them has to go "
        "through the table, and exactly once"
    )


def test_preparation_survives_into_the_resolved_line():
    """The shopping list merges on rw:food and deliberately not on preparation.

    Melted butter and softened butter are one thing to buy and two things to
    have ready, so a merged row has to be able to name the preparations it
    swallowed. ``Ingredient.preparation`` existed in the model and stopped at
    the resolver, which left the roll-up nothing to show under the merged line.
    """
    recipe = build_recipe(ingredients=[
        ingredient("butter", id="#butter-melted", mass=100,
                   food="food:butter-unsalted", preparation="melted"),
        ingredient("butter", id="#butter-softened", mass=150,
                   food="food:butter-unsalted", preparation="softened"),
    ])
    result = resolve(build_library(recipe), recipe.id)

    melted = _ingredient(result, "#butter-melted")
    softened = _ingredient(result, "#butter-softened")
    assert melted.food_id == softened.food_id, "the premise: one shopping line"
    assert (melted.preparation, softened.preparation) == ("melted", "softened")


def test_a_line_with_no_preparation_says_none_rather_than_inventing_one(library):
    result = resolve(library, VANILLA_BC)
    assert _ingredient(result, "#icing-sugar").preparation == "sifted"
    assert _ingredient(result, "#butter").preparation is None


def test_source_columns_that_disagree_are_reported_not_resolved(library):
    """200 g in the metric column, 3/4 cup (171 g) in the cups column."""
    result = resolve(library, CHOCOLATE_BC)
    divergence = _coded(result, UNIT_DIVERGENCE)
    assert len(divergence) == 1
    assert "200 g" in divergence[0].message and "171 g" in divergence[0].message
    assert divergence[0].node == "#butter", "the line whose own columns disagree"
    assert _ingredient(result, "#butter").mass_g == pytest.approx(200)


def _ingredient(resolution, ingredient_id):
    return next(i for i in resolution.ingredients if i.id == ingredient_id)
