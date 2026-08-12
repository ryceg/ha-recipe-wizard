"""The resolver, tested against the cases the design got wrong on paper."""

import pytest

from conftest import BROWNIES, CAKE, CHOCOLATE_BC, COFFEE_BC, VANILLA_BC

from recipe_wizard import (
    Adjustment,
    BatchConstraintError,
    BatchPolicy,
    Quantity,
    materialise,
    resolve,
    resolve_component,
)
from recipe_wizard.adjust import AdjustmentError

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
    use.requires_batches = 2.0
    try:
        result = resolve_component(library, use)
        assert result.scale == pytest.approx(2.0)
        assert result.produced_g == pytest.approx(2 * 738, rel=0.02)
    finally:
        use.requires_batches = 1.0


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
    assert any("minimum batch" in w for w in result.warnings)


def test_discrete_eggs_round_up_and_renormalise_the_batch(library):
    """What a cook actually does: round the eggs, then rescale to them."""
    full = resolve(library, CAKE)
    result = resolve(
        library, CAKE,
        requires_mass=Quantity(full.batch_yield_g * 0.5613, "g"),
        batch_policy=BatchPolicy(mode="roundUpToWholeUnit", basis="#eggs"),
    )
    assert _ingredient(result, "#eggs").mass_g / 52.5 == pytest.approx(3.0, abs=0.01)
    assert result.scale == pytest.approx(0.75, abs=0.01)
    assert result.leftover_g > 0
    assert "leftover" in result.summary()


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
    capacity = [w for w in result.warnings if "holds about" in w]
    assert len(capacity) == 1
    assert "you need roughly 4" in capacity[0]


def test_doubling_refuses_to_scale_the_bake_time(library):
    result = resolve(library, CAKE, requires_batches=2.0)
    assert any("do not scale the time" in w for w in result.warnings)
    assert any("3 x 20cm round: 22 min" in w for w in result.warnings)


def test_an_unscaled_recipe_gets_no_vessel_noise(library):
    assert resolve(library, CAKE).warnings == []


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


def test_source_columns_that_disagree_are_reported_not_resolved(library):
    """200 g in the metric column, 3/4 cup (171 g) in the cups column."""
    result = resolve(library, CHOCOLATE_BC)
    divergence = [w for w in result.warnings if "source columns disagree" in w]
    assert len(divergence) == 1
    assert "200 g" in divergence[0] and "171 g" in divergence[0]
    assert _ingredient(result, "#butter").mass_g == pytest.approx(200)


def _ingredient(resolution, ingredient_id):
    return next(i for i in resolution.ingredients if i.id == ingredient_id)
