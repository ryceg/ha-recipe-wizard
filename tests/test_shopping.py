"""The shopping-list roll-up, tested against the ways a merge goes quietly wrong.

Two premises come from the corpus because the corpus *is* the subject: the cake
doubled has butter at two different scales in one list, and the qeema has an
optional whole component and a to-taste line. Everything deeper or stranger --
three levels, a food the bank has no density for, two recipes that agree in
English and not in ``rw:food`` -- is built here, because the corpus is only two
levels deep and holds no citation at all.
"""

import pytest

from conftest import CAKE, VANILLA_BC
from support import build_library, build_recipe, component, ingredient

from custom_components.recipe_wizard.core import (
    Library,
    resolve_dish,
    shopping_list,
    shopping_list_from_dish,
)

QEEMA = "urn:recipe:rte/qeema"
BUTTER = "food:butter-unsalted"
MILK = "food:milk-full-fat"
SALT = "food:salt-kosher"
SUGAR = "food:sugar-caster"
#: A food nobody has put a density in the bank for yet. Linking to it is what a
#: half-finished enrichment produces, and the reason a volume can be linked and
#: still have no mass.
UNKNOWN = "food:pistachio-flour"


def _list(*recipes, batches=1.0, include_optional=True):
    """Fold a built dish, root first, with the real food bank behind it."""
    library = build_library(*recipes)
    dish = resolve_dish(library, recipes[0].id, batches=batches, strict=False)
    return shopping_list_from_dish(dish, include_optional=include_optional)


# ---------------------------------------------------------------------------
# Merge after scaling, on the food
# ---------------------------------------------------------------------------


def test_butter_merges_across_two_scales_into_one_line(library):
    """The whole rule, in one corpus line.

    Doubling the cake gives 230 g of butter in the cake -- ``sublinear`` never
    reaches it, so it is a plain double of 115 g -- and 450 g in the
    buttercream, whose use overrides the standalone 250 g down to 225 g. Merge
    before scaling and a doubled cake shops for a single batch; merge on the
    words and there are two butter lines.
    """
    single = shopping_list(library, CAKE)
    double = shopping_list(library, CAKE, batches=2)

    assert single.for_food(BUTTER).total_g == pytest.approx(340)
    assert double.for_food(BUTTER).total_g == pytest.approx(680)
    assert len(double.for_food(BUTTER).contributions) == 2


def test_a_merged_line_keeps_every_preparation_it_swallowed(library):
    """Melted butter and softened butter are one line to buy and two things to
    have ready. A merge that dropped the preparation would lose the
    mise-en-place, which is why the line keeps the contributions."""
    lines = shopping_list(library, CAKE, batches=2)
    butter = lines.for_food(BUTTER)

    assert butter.preparations == ["cut into cubes"]
    assert butter.breakdown() == [
        "230 g, cut into cubes - My Very Best Vanilla Cake",
        "450 g - Vanilla buttercream",
    ]


def test_two_preparations_of_one_food_are_both_named():
    """The corpus only prepares butter on one side of the merge. Both sides is
    the case the rule was written for, so state it here."""
    cake = build_recipe(
        name="Brown butter cake",
        ingredients=[ingredient("butter", food=BUTTER, mass=100, preparation="melted")],
        components=[component("Frosting", recipe="urn:recipe:test/frosting")],
    )
    frosting = build_recipe(
        id="urn:recipe:test/frosting",
        name="Frosting",
        ingredients=[ingredient("butter", food=BUTTER, mass=200,
                                preparation="softened")],
    )

    butter = _list(cake, frosting).for_food(BUTTER)

    assert butter.total_g == pytest.approx(300)
    assert butter.preparations == ["melted", "softened"]
    assert butter.from_recipes == ["Brown butter cake", "Frosting"]


def test_a_third_level_merges_like_the_first(library):
    """Two levels is all the corpus has, and a fold that recursed once looks
    exactly like one that recurses all the way until there is a third."""
    top = build_recipe(
        name="Top", ingredients=[ingredient("sugar", food=SUGAR, mass=10)],
        components=[component("Middle", recipe="urn:recipe:test/middle")],
    )
    middle = build_recipe(
        id="urn:recipe:test/middle", name="Middle",
        ingredients=[ingredient("sugar", food=SUGAR, mass=20)],
        components=[component("Bottom", recipe="urn:recipe:test/bottom")],
    )
    bottom = build_recipe(
        id="urn:recipe:test/bottom", name="Bottom",
        ingredients=[ingredient("sugar", food=SUGAR, mass=40)],
    )

    lines = _list(top, middle, bottom)

    assert len(lines.lines) == 1
    assert lines.for_food(SUGAR).total_g == pytest.approx(70)
    assert lines.for_food(SUGAR).from_recipes == ["Top", "Middle", "Bottom"]


def test_scaling_reaches_every_level_before_the_merge():
    """``resolve_dish`` multiplies each parent's effective scale into its
    children, and the fold must not undo or re-apply that. Half a batch of the
    top means a quarter of the bottom's two batches."""
    top = build_recipe(
        name="Top", ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
        components=[component("Bottom", recipe="urn:recipe:test/bottom",
                              requires_batches=2)],
    )
    bottom = build_recipe(
        id="urn:recipe:test/bottom", name="Bottom",
        ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
    )

    line = _list(top, bottom, batches=0.5).for_food(SUGAR)

    # 50 g from the top, 100 g from one whole effective batch of the bottom.
    assert [c.mass_g for c in line.contributions] == [
        pytest.approx(50), pytest.approx(100)
    ]
    assert line.total_g == pytest.approx(150)


def test_one_sub_recipe_used_twice_sums_rather_than_overwriting():
    """A trifle with a bottom layer and a top layer of the same custard is
    ordinary. A fold keyed so the second use replaced the first would shop for
    one layer."""
    trifle = build_recipe(
        name="Trifle", ingredients=[ingredient("sugar", food=SUGAR, mass=10)],
        components=[
            component("Bottom layer", id="#bottom", recipe="urn:recipe:test/custard"),
            component("Top layer", id="#top", recipe="urn:recipe:test/custard",
                      requires_batches=2),
        ],
    )
    custard = build_recipe(
        id="urn:recipe:test/custard", name="Custard",
        ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
    )

    line = _list(trifle, custard).for_food(SUGAR)

    assert line.total_g == pytest.approx(310)
    assert len(line.contributions) == 3


# ---------------------------------------------------------------------------
# A row with no mass must not merge into a numeric total
# ---------------------------------------------------------------------------


def test_an_unweighed_row_does_not_disappear_into_a_total():
    """"500 g flour" plus "some flour" is not "500 g flour".

    The second row is linked to a food the bank has no density for, so it has a
    food and no mass -- which is exactly what a half-finished enrichment
    produces. ``total_g`` refuses; the partial sum is only reachable by a name
    that says it is partial.
    """
    cake = build_recipe(
        name="Cake", ingredients=[ingredient("nut flour", food=UNKNOWN, mass=500)],
        components=[component("Crumble", recipe="urn:recipe:test/crumble")],
    )
    crumble = build_recipe(
        id="urn:recipe:test/crumble", name="Crumble",
        ingredients=[ingredient("pistachio flour", food=UNKNOWN, volume=(1, "cup"))],
    )

    line = _list(cake, crumble).for_food(UNKNOWN)

    assert line.total_g is None, "a partial sum must not be handed out as a total"
    assert line.measured_g == pytest.approx(500)
    assert [c.ingredient_id for c in line.unweighed] == ["#pistachio-flour"]
    assert "at least 500 g" in line.describe()
    assert "1 line with no weight" in line.describe()
    assert line in _list(cake, crumble).incomplete


def test_a_line_with_nothing_weighed_does_not_total_zero():
    """Summing an empty list gives 0.0, and "0 g flour" is a statement about
    flour that happens to be false. ``None`` is the only honest answer."""
    cake = build_recipe(
        name="Cake",
        ingredients=[ingredient("pistachio flour", food=UNKNOWN, volume=(1, "cup"))],
        components=[component("Crumble", recipe="urn:recipe:test/crumble")],
    )
    crumble = build_recipe(
        id="urn:recipe:test/crumble", name="Crumble",
        ingredients=[ingredient("nut flour", food=UNKNOWN, volume=(2, "cup"))],
    )

    line = _list(cake, crumble).for_food(UNKNOWN)

    assert line.measured_g is None
    assert line.total_g is None
    assert "0 g" not in line.describe()
    assert "no weight given on 2 lines" in line.describe()


def test_a_level_0_string_row_is_a_line_with_no_weight(library, level0):
    """A scraped document's rows carry ``originalText`` and nothing else. They
    still have to reach the list -- the cook needs the onion -- and they must
    not pretend to a mass."""
    lines = shopping_list(library, level0.id)

    assert [line.name for line in lines.lines] == [
        "500 g beef mince", "1 onion, finely chopped", "2 tbsp olive oil",
    ]
    assert all(line.food_id is None for line in lines.lines)
    assert all(line.total_g is None for line in lines.lines)
    assert lines.incomplete == lines.lines


# ---------------------------------------------------------------------------
# An unlinked row merges with nothing, including itself
# ---------------------------------------------------------------------------


def test_unlinked_rows_never_merge_even_when_identically_worded():
    """Two recipes both saying "1 onion, finely chopped" with no ``rw:food``
    stay two lines. That is the visible cost of imperfect enrichment against a
    ~95% target, and the alternative -- matching on the name -- would merge
    "1 onion" with "1 red onion" and be wrong in the shop."""
    stew = build_recipe(
        name="Stew", ingredients=[ingredient("onion, finely chopped", mass=150)],
        components=[component("Salsa", recipe="urn:recipe:test/salsa")],
    )
    salsa = build_recipe(
        id="urn:recipe:test/salsa", name="Salsa",
        ingredients=[ingredient("onion, finely chopped", mass=150)],
    )

    lines = _list(stew, salsa).lines

    assert len(lines) == 2, "an unlinked row cannot merge, not even with itself"
    assert [line.total_g for line in lines] == [pytest.approx(150)] * 2
    assert [line.food_id for line in lines] == [None, None]


def test_the_same_unlinked_line_of_one_sub_recipe_used_twice_stays_two_lines():
    """The one case where keying on ``(recipe, ingredient)`` would have merged
    an unlinked row. Predictability wins: no ``rw:food``, no merge, ever."""
    trifle = build_recipe(
        name="Trifle", ingredients=[ingredient("sugar", food=SUGAR, mass=10)],
        components=[
            component("Bottom layer", id="#bottom", recipe="urn:recipe:test/custard"),
            component("Top layer", id="#top", recipe="urn:recipe:test/custard"),
        ],
    )
    custard = build_recipe(
        id="urn:recipe:test/custard", name="Custard",
        ingredients=[ingredient("nonna's vanilla paste", mass=5)],
    )

    unlinked = [line for line in _list(trifle, custard).lines if line.food_id is None]

    assert len(unlinked) == 2
    assert [line.from_recipes for line in unlinked] == [
        ["Bottom layer"], ["Top layer"],
    ]


# ---------------------------------------------------------------------------
# To taste is an answer, not a failure to answer
# ---------------------------------------------------------------------------


def test_to_taste_does_not_stop_a_complete_line_stating_its_total():
    """A to-taste row has no grams and needs none: you buy some, or you have
    some. Filing it with the ginger whose density is missing would make a total
    that is genuinely complete refuse to state itself."""
    curry = build_recipe(
        name="Curry", ingredients=[ingredient("cooking salt", food=SALT, mass=2)],
        components=[component("Raita", recipe="urn:recipe:test/raita")],
    )
    raita = build_recipe(
        id="urn:recipe:test/raita", name="Raita",
        ingredients=[
            ingredient("yogurt", food="food:yogurt-plain", mass=200),
            ingredient("salt", food=SALT, to_taste=True),
        ],
    )

    line = _list(curry, raita).for_food(SALT)

    assert line.total_g == pytest.approx(2)
    assert line.unweighed == [], "to taste is not an unweighed line"
    assert line.to_taste is True
    assert "plus more to taste" in line.describe()


def test_a_to_taste_only_line_states_no_number_at_all(library):
    """The qeema's coriander leaves. "to taste" is the whole answer, and a
    number invented for it would be the guess Principle 3 forbids."""
    line = shopping_list(library, QEEMA).for_food("food:coriander-leaves")

    assert line.total_g is None
    assert line.describe() == "cilantro/coriander leaves: to taste (optional)"


# ---------------------------------------------------------------------------
# Optional is a flag, never a filter
# ---------------------------------------------------------------------------


def test_an_optional_component_leaves_the_list_when_asked(library):
    """The qeema's mint yogurt is optional as a whole component. Dropping it
    has to drop the foods only it wants -- and keep its share of the salt out
    of the salt total, which is the merge and the filter interacting."""
    with_it = shopping_list(library, QEEMA)
    without = shopping_list(library, QEEMA, include_optional=False)

    assert with_it.for_food("food:mint-leaves") is not None
    assert without.for_food("food:mint-leaves") is None
    assert with_it.for_food(SALT).total_g == pytest.approx(3.0, abs=0.05)
    assert without.for_food(SALT).total_g == pytest.approx(2.2, abs=0.05)


def test_an_optional_ingredient_is_flagged_rather_than_dropped(library):
    """The buttercream's milk is optional and its food is the same milk the
    cake needs 495 g of. Dropping the row would silently shrink a total the
    cook does need, so the line is flagged only when *every* contribution is
    optional -- an ``all()``, not an ``any()``."""
    cake = shopping_list(library, CAKE, batches=2)
    frosting = shopping_list(library, VANILLA_BC)

    shared = cake.for_food(MILK)
    assert shared.optional is False, "required in the cake, so it must be bought"
    assert shared.total_g == pytest.approx(619, abs=1)
    assert [c.optional for c in shared.contributions] == [False, True]

    # The same food, in the recipe where nothing requires it.
    assert frosting.for_food(MILK).optional is True
    assert "(optional)" in frosting.for_food(MILK).describe()


# ---------------------------------------------------------------------------
# Cited components: excluded from the quantities, not from the list
# ---------------------------------------------------------------------------


def test_a_cited_component_reaches_the_list_as_something_to_find():
    """``docs/format.md`` is explicit that a cited component is "excluded from
    shopping lists rather than silently contributing nothing". It has no
    quantity this library may invent, and the cook still has to have it."""
    pie = build_recipe(
        name="Pie", ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
        components=[component(
            "Bolognese", recipe=None,
            citation={"name": "Dinner", "rw:page": 308},
        )],
    )

    lines = _list(pie)

    assert [line.food_id for line in lines.lines] == [SUGAR]
    assert len(lines.to_find) == 1
    cited = lines.to_find[0]
    assert cited.label == "Bolognese"
    assert cited.where == "Dinner, p.308"
    assert cited.needed_by == "Pie"
    assert cited.describe() == "Bolognese: not in the library - see Dinner, p.308"


def test_a_citation_under_an_optional_component_goes_with_it():
    """Skipping the glaze skips the book the glaze needs. A ``to_find`` built
    from anything but the same walk would leave it on the list."""
    cake = build_recipe(
        name="Cake", ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
        components=[component("Glaze", recipe="urn:recipe:test/glaze",
                              optional=True)],
    )
    glaze = build_recipe(
        id="urn:recipe:test/glaze", name="Glaze",
        ingredients=[ingredient("sugar", food=SUGAR, mass=50)],
        components=[component("Carotene butter", recipe=None,
                              citation={"name": "Modernist Cuisine",
                                        "rw:page": 121})],
    )

    assert len(_list(cake, glaze).to_find) == 1
    assert _list(cake, glaze, include_optional=False).to_find == []


def test_a_citation_with_no_page_still_says_where(library):
    """Not every citation has a page. The line must degrade to the name rather
    than to "p.None"."""
    pie = build_recipe(
        name="Pie", ingredients=[ingredient("sugar", food=SUGAR, mass=100)],
        components=[component("Stock", recipe=None,
                              citation={"name": "The Flavour Bible"})],
    )

    assert _list(pie).to_find[0].where == "The Flavour Bible"


# ---------------------------------------------------------------------------
# What the cook reads
# ---------------------------------------------------------------------------


def test_lines_keep_the_order_the_recipes_list_them_in(library):
    """Not sorted. The order a recipe lists its ingredients in is information --
    the cake's dry goods, then its wet -- and alphabetising by a name that came
    out of whichever recipe was walked first is a worse order chosen less
    deliberately. The frosting's own foods land after the cake's."""
    names = [line.name for line in shopping_list(library, CAKE).lines]

    assert names[:3] == ["plain flour", "baking powder", "kosher salt"]
    assert names[-1] == "soft icing sugar"


def test_a_line_names_the_food_the_recipe_the_cook_opened_called_it():
    """The food bank calls it something else, and a list that used the bank's
    name would disagree with the cook-along about the same row."""
    cake = build_recipe(
        name="Cake", ingredients=[ingredient("caster sugar", food=SUGAR, mass=100)],
        components=[component("Frosting", recipe="urn:recipe:test/frosting")],
    )
    frosting = build_recipe(
        id="urn:recipe:test/frosting", name="Frosting",
        ingredients=[ingredient("superfine sugar", food=SUGAR, mass=50)],
    )

    line = _list(cake, frosting).for_food(SUGAR)

    assert line.name == "caster sugar"
    assert [c.name for c in line.contributions] == ["caster sugar", "superfine sugar"]


def test_a_complete_line_does_not_hedge(library):
    """"at least" is load-bearing and must not appear where the total is real,
    or it stops meaning anything."""
    flour = shopping_list(library, CAKE).for_food("food:flour-plain")

    assert flour.describe() == "plain flour: 250 g"
    assert flour.total_g == pytest.approx(250)


def test_the_report_indents_a_breakdown_only_where_it_says_something(library):
    """One recipe wanting 250 g of flour does not need "250 g - Cake" printed
    underneath. A merged butter line does, because which 230 g is the cubed one
    is precisely what the merge would otherwise have lost."""
    report = shopping_list(library, CAKE, batches=2).report()

    assert "SHOPPING LIST  My Very Best Vanilla Cake  (x2)" in report
    assert "  - plain flour: 500 g\n  - baking powder" in report
    assert "  - unsalted butter: 680 g\n      230 g, cut into cubes" in report
    # A single contribution that needs preparing says so and nothing more.
    assert "  - soft icing sugar: 1000 g\n      sifted" in report


def test_the_shakiest_conversion_under_a_line_is_reachable(library):
    """The qeema's ginger is a volume against a density the food bank does not
    trust. The list reports rather than resolves, like everything else here --
    though ``describe()`` stays clean, because rounding to what a shop sells
    swamps the error."""
    ginger = shopping_list(library, QEEMA).for_food("food:ginger")

    assert ginger.confidence == "low"
    assert "~" not in ginger.describe()


# ---------------------------------------------------------------------------
# The two entry points agree
# ---------------------------------------------------------------------------


def test_folding_a_dish_and_resolving_one_give_the_same_list(library):
    """The CLI shows the table, the plan and the list off one tree; the
    integration will ask for a list on its own. Resolving twice for one screen
    is waste the entity is in no position to notice."""
    from_id = shopping_list(library, CAKE, batches=2)
    from_dish = shopping_list_from_dish(
        resolve_dish(library, CAKE, batches=2, strict=False)
    )

    assert [line.describe() for line in from_id.lines] == [
        line.describe() for line in from_dish.lines
    ]
    assert from_id.scale == from_dish.scale == 2


def test_a_food_the_dish_does_not_want_has_no_line(library):
    """``for_food`` answering ``None`` rather than an empty line: "buy 0 g of
    cocoa" is the same false statement as a zero total."""
    assert shopping_list(library, CAKE).for_food("food:cocoa-powder") is None


def test_an_empty_library_is_not_a_special_case():
    """A recipe with one ingredient and no components still folds, and the
    header still reads."""
    lines = _list(build_recipe(name="Toast",
                              ingredients=[ingredient("bread", mass=60)]))

    assert len(lines.lines) == 1
    assert lines.to_find == []
    assert lines.report().startswith("SHOPPING LIST  Toast  (one batch)")
    assert isinstance(build_library(), Library)
