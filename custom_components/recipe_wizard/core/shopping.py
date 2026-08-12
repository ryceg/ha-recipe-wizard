"""The shopping-list roll-up: one line per **food**, across the whole dish.

The second surface after the cook-along, and the rule it implements has been
settled in ``docs/format.md`` for a while: **merge after scaling, recursively,
on ``rw:food`` and *not* on preparation.** Cited components are excluded.

Every clause of that is forced by ``recipes/vanilla-cake.json``. Double the cake
and the butter appears twice at two different scales -- 230 g *cut into cubes*
in the cake (it is ``sublinear``, so doubling does not double it) and 450 g in
the buttercream, whose use carries the parent's local "make it 225 g" override.
Merging *before* scaling would shop for one batch of a doubled cake; merging on
the words instead of the food would ask for "unsalted butter" twice, once cubed
and once not. So: **melted butter and softened butter are one line to buy and
two things to have ready**, which is why ``ShoppingLine`` keeps every
contribution rather than a running total, and why ``breakdown()`` exists.

Almost none of the work is here. ``resolve_dish()`` already hands back every
``Resolution`` in the tree *at its own effective scale*, so merge-after-scaling
falls out of walking it -- nothing in this module multiplies anything. And a
cited component is in ``Dish.unresolvable`` and never in ``Dish.components``, so
"excluded" is structural rather than a filter somebody has to remember. What is
left is one real judgement, below.

**A row with no mass must never merge into a numeric total.** ``mass_g`` is
``None`` for a level-0 line lifted from a ``recipeIngredient`` string, and for a
volume whose food the bank has no density for. "500 g flour" plus "some flour"
is not "500 g flour", and it is not 500 g of anything. Principle 3 of the format
doc applies -- *refuse rather than guess; a silently assumed number is worse
than an error* -- so ``total_g`` is ``None`` the moment any contributor could not
be weighed, and the partial sum is only reachable through ``measured_g``, whose
name says what it is and which sits next to ``unweighed``. The rendered line
says *"at least 500 g, plus 1 line with no weight"*. There is deliberately no
attribute on this class that returns a bare number for a line that does not
have one.

**"To taste" is an answer, not a failure to answer.** The qeema's coriander
leaves are ``rw:toTaste``, which the mass table reduces to no grams with
confidence ``n/a``. That is not the same event as the ginger's missing density:
the source declined to specify because for shopping it does not matter -- you
buy some, or you have some. So a to-taste contribution does **not** land in
``unweighed`` and does not suppress the total; it sets ``to_taste`` on the line
and reads *"1.5 g, plus more to taste"*. Treating it as an unweighed line would
make a genuinely complete total refuse to state itself, and would render the
qeema's coriander identical to its ginger, which is two different problems.

**An unlinked row merges with nothing, including another spelling of itself.**
Two recipes both saying "1 onion, finely chopped" with no ``rw:food`` stay two
lines. That is the visible cost of imperfect enrichment against a ~95% target,
and it is better than the alternatives: matching on the name would merge "1
onion" with "1 red onion", and matching on ``(recipe, ingredient)`` would merge
two uses of *the same* sub-recipe while still refusing two recipes that agree,
which is a rule nobody could predict. So an unlinked row is keyed on its
position in the walk and is therefore always exactly one line.

**Optional is a flag, never a filter.** ``include_optional=False`` drops optional
*components* -- the qeema without the mint yogurt -- because ``Dish.walk()``
already knows how. An optional *ingredient* row is different: the buttercream's
milk is optional and its food is the same milk the cake needs 495 g of, so
dropping the row would silently reduce a total the cook does need. Instead
``ShoppingLine.optional`` is true only when **every** contribution is optional --
an ``all()``, not an ``any()`` -- which is exactly the question a shopping list
asks: *is there any way I get through this without buying it?* The surface
filters on the flag; the library does not decide for it.

Plain data on the way out, with no Home Assistant in it: a ``TodoListEntity``
backs each line with ``describe()`` for the summary and ``breakdown()`` for the
description, and nothing here knows that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dish import Dish, resolve_dish
from .library import Library
from .model import Adjustment, ComponentUse
from .render import format_mass
from .units import Quantity

#: Worst-first, so a line can report the shakiest conversion under it.
#: ``n/a`` is absent on purpose: a to-taste line has no conversion to doubt.
_CONFIDENCE_ORDER = ("none", "low", "medium", "high")


def _joined(names: list[str]) -> str:
    """"a", "a and b", "a, b and c" -- the list is read by a cook, not parsed."""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _unique(values: list[str]) -> list[str]:
    """De-duplicated, first occurrence winning, order preserved."""
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


@dataclass(frozen=True, slots=True)
class Contribution:
    """One recipe's ingredient row, as its share of one shopping line.

    Frozen and complete: the whole point of keeping these rather than a running
    total is that a merged line can still say *which* 200 g is the melted one.
    ``label`` is the dish's label, so the cake's use of the buttercream reads
    "Vanilla buttercream" and not the sub-recipe's own name.
    """

    label: str
    recipe_id: str
    ingredient_id: str
    name: str
    """The words *this* recipe used for the food. Lines merge on the food, so
    the two spellings of one thing are both kept and only one is displayed."""
    mass_g: float | None
    preparation: str | None = None
    optional: bool = False
    to_taste: bool = False
    display: str | None = None
    """The source's own measure where it had one: "2-4 tbsp, if needed"."""
    confidence: str = "high"
    """From the mass table. ``low`` on the qeema's ginger, whose density the
    food bank does not trust; ``n/a`` where the line is to-taste."""

    @property
    def unweighed(self) -> bool:
        """No mass, and not because the source declined to give one.

        The distinction this property draws is the module's central one. A
        to-taste row has no grams and needs none; a volume with no density in
        the bank has no grams and *needed* some.
        """
        return self.mass_g is None and not self.to_taste

    def describe(self) -> str:
        """One line of the mise-en-place: how much, prepared how, for what."""
        amount = (
            "to taste" if self.to_taste
            else format_mass(self.mass_g) if self.mass_g is not None
            else self.display or "no weight given"
        )
        parts = [amount]
        if self.preparation:
            parts.append(self.preparation)
        if self.optional:
            parts.append("optional")
        return f"{', '.join(parts)} - {self.label}"


@dataclass(slots=True)
class ShoppingLine:
    """One food to buy, and every recipe in the dish that wants some of it.

    Everything except the food and its contributions is derived, so a total can
    never drift from the parts it was added up from -- and so there is no
    settable field that could hold a number the contributions do not support.
    """

    food_id: str | None
    """``None`` for a row with no ``rw:food``, which is a line of exactly one
    contribution by construction: see the module docstring."""
    contributions: list[Contribution] = field(default_factory=list)

    # -- what to buy ---------------------------------------------------------

    @property
    def name(self) -> str:
        """The first contributor's word for the food.

        First, not "best": the walk starts at the root, so this is what the cook
        is reading on the page they opened. The food bank's own name would be
        the other defensible choice and is a worse one -- a line that says
        "sugar, caster (fine)" where the recipe said "caster sugar" makes the
        shopping list and the cook-along disagree about the same row.
        """
        return self.contributions[0].name if self.contributions else ""

    @property
    def measured_g(self) -> float | None:
        """The sum of the contributions that *could* be weighed.

        ``None``, not ``0.0``, when none of them could. Zero grams of flour is a
        statement about flour, and it is a false one.

        This is a partial sum whenever ``unweighed`` is non-empty, which is why
        it is not called ``total_g`` and why the caller that wants a total has
        to ask for one by that name and be told ``None``.
        """
        weighed = [c.mass_g for c in self.contributions if c.mass_g is not None]
        return sum(weighed) if weighed else None

    @property
    def total_g(self) -> float | None:
        """What to buy, or ``None`` when the list cannot honestly say.

        The refusal is the feature. A caller reaching for the obvious attribute
        gets no number rather than a wrong one, and finds the reason in
        ``unweighed`` next to it.
        """
        return None if self.unweighed else self.measured_g

    @property
    def unweighed(self) -> list[Contribution]:
        """Contributions that wanted a mass and have none."""
        return [c for c in self.contributions if c.unweighed]

    # -- what to have ready --------------------------------------------------

    @property
    def preparations(self) -> list[str]:
        """Every distinct preparation this line swallowed, in tree order.

        The reason the merge is allowed to ignore preparation at all. One line
        of butter to buy; "melted" and "softened" both still reachable, or the
        mise-en-place is lost in the merge.
        """
        return _unique([c.preparation for c in self.contributions if c.preparation])

    @property
    def from_recipes(self) -> list[str]:
        """The labels of the dishes wanting this food, in tree order."""
        return _unique([c.label for c in self.contributions])

    # -- caveats -------------------------------------------------------------

    @property
    def optional(self) -> bool:
        """True only when there is no way through the dish without skipping it.

        An ``all()`` on purpose. The buttercream's optional milk shares its food
        with the cake's required 495 g, and a shopping list that called that
        line optional would be wrong in the direction that ruins the cake.
        """
        return bool(self.contributions) and all(c.optional for c in self.contributions)

    @property
    def to_taste(self) -> bool:
        """Some recipe in the dish seasons with this rather than measuring it."""
        return any(c.to_taste for c in self.contributions)

    @property
    def confidence(self) -> str:
        """The shakiest mass conversion under this line, worst wins.

        Carried because the library reports doubtful masses rather than
        resolving them, and this is the one surface that could quietly present
        one as fact. It is deliberately *not* in ``describe()``: rounding to what
        a shop actually sells swamps a 30% density error on 1.5 g of salt, and
        the validator already reports the conversions that matter, measured
        against a share of the batch. A caller that wants to mark the line may.
        """
        ranked = [
            c.confidence for c in self.contributions
            if c.mass_g is not None and c.confidence in _CONFIDENCE_ORDER
        ]
        if not ranked:
            return "n/a" if self.contributions and self.to_taste else "none"
        return min(ranked, key=_CONFIDENCE_ORDER.index)

    # -- display -------------------------------------------------------------

    def describe(self) -> str:
        """The buy line: the food and how much of it, or why there is no how much.

        Phrased so it cannot be read as a total when it is not one. A complete
        line is *"unsalted butter: 680 g"*; an incomplete one is *"plain flour:
        at least 500 g, plus 1 line with no weight"*, where "at least" is
        load-bearing and true -- an unweighed contribution is some positive
        amount of the food, so the measured sum is a floor.
        """
        parts: list[str] = []
        measured = self.measured_g
        unweighed = self.unweighed
        if measured is not None:
            parts.append(
                f"at least {format_mass(measured)}" if unweighed
                else format_mass(measured)
            )
        if unweighed:
            count = len(unweighed)
            if measured is not None:
                parts.append(f"{count} line{'s' if count > 1 else ''} with no weight")
            elif count == 1:
                parts.append("no weight given")
            else:
                parts.append(f"no weight given on {count} lines")
        if self.to_taste:
            parts.append("more to taste" if parts else "to taste")

        line = f"{self.name}: {', plus '.join(parts)}"
        if self.optional:
            line += " (optional)"
        return line

    def breakdown(self) -> list[str]:
        """One line per contribution: what each recipe wants and how prepared.

        The other half of the merge. ``describe()`` says buy 680 g of butter;
        this says 230 g of it is cut into cubes for the cake and 450 g goes into
        the buttercream as it comes.
        """
        return [c.describe() for c in self.contributions]


@dataclass(frozen=True, slots=True)
class CitedComponent:
    """A component the list can only tell you to go and find.

    ``docs/format.md`` § ComponentUse is explicit that a cited component is
    *"excluded from shopping lists rather than silently contributing nothing"* --
    Modernist's *"see page 121"* and a RecipeTin cookbook-only flavour are both
    things the cook has to have on the bench, and neither has a quantity this
    library is allowed to invent. So they come out of the fold separately from
    ``lines``: a thing to buy or find, with no grams attached, and the page
    number to find it on.
    """

    label: str
    needed_by: str
    """The label of the dish whose recipe cites it."""
    where: str
    """The citation as text: "Dinner, p.308"."""
    use: ComponentUse
    """The use itself, for a caller that wants the rest of it."""

    def describe(self) -> str:
        return f"{self.label}: not in the library - see {self.where}"


@dataclass(slots=True)
class ShoppingList:
    """The whole roll-up for one dish: what to buy, and what to go and find.

    ``lines`` are in **first-use order** -- the root recipe's own ingredient
    order, then each component's foods that had not appeared yet. Not sorted:
    the order a recipe lists its ingredients in is information (the cake's dry
    goods, then its wet), and alphabetising it by a name that came out of
    whichever recipe happened to be walked first would be a worse order chosen
    less deliberately. A surface that wants aisles can sort on ``food_id``.
    """

    label: str
    scale: float
    lines: list[ShoppingLine] = field(default_factory=list)
    to_find: list[CitedComponent] = field(default_factory=list)
    """Cited components. Excluded from ``lines`` and reported here instead."""

    def for_food(self, food_id: str) -> ShoppingLine | None:
        """The line for one food, or ``None`` if the dish does not want any."""
        for line in self.lines:
            if line.food_id == food_id:
                return line
        return None

    @property
    def incomplete(self) -> list[ShoppingLine]:
        """Lines that cannot state a total. What enrichment still owes the cook."""
        return [line for line in self.lines if line.total_g is None]

    def report(self) -> str:
        """Plain text, for ``--shopping``.

        Indented under a line only what the buy line cannot say. Several
        recipes want the food: the full breakdown, because which 230 g is the
        cubed one is the thing the merge would otherwise have lost. One recipe
        wants it prepared: just the preparation, since repeating "500 g - Vanilla
        cake" under "plain flour: 500 g" is length without information.
        """
        made = f"x{self.scale:g}" if abs(self.scale - 1.0) > 1e-9 else "one batch"
        out = [f"SHOPPING LIST  {self.label}  ({made})"]
        for line in self.lines:
            out.append(f"  - {line.describe()}")
            if len(line.contributions) > 1:
                out.extend(f"      {entry}" for entry in line.breakdown())
            elif line.preparations:
                out.append(f"      {line.preparations[0]}")
        for cited in self.to_find:
            out.append(f"  ? {cited.describe()}  (for {cited.needed_by})")
        return "\n".join(out)

    def __str__(self) -> str:
        return self.report()


def shopping_list_from_dish(
    dish: Dish, *, include_optional: bool = True
) -> ShoppingList:
    """Fold a resolved dish into one line per food.

    The whole implementation of "merge after scaling, recursively": every
    ``Resolution`` in ``dish.walk()`` is already at its own effective scale, so
    walking the tree *is* the merge and nothing here multiplies a mass. Doubling
    the cake reaches the buttercream through ``resolve_dish``, not through here.
    """
    lines: dict[object, ShoppingLine] = {}
    to_find: list[CitedComponent] = []

    for index, node in enumerate(dish.walk(include_optional=include_optional)):
        for use in node.unresolvable:
            to_find.append(_cited(use, needed_by=node.label))
        for ing in node.resolution.ingredients:
            # A food merges; a row with no food is keyed on where it sits in the
            # walk, so it is always exactly one line and can collide with
            # nothing -- not another recipe's identical wording, and not the
            # same line of the same sub-recipe used twice.
            key: object = (
                ("food", ing.food_id) if ing.food_id else ("row", index, ing.id)
            )
            line = lines.get(key)
            if line is None:
                line = lines[key] = ShoppingLine(food_id=ing.food_id)
            line.contributions.append(
                Contribution(
                    label=node.label,
                    recipe_id=node.resolution.recipe_id,
                    ingredient_id=ing.id,
                    name=ing.name,
                    mass_g=ing.mass_g,
                    preparation=ing.preparation,
                    optional=ing.optional,
                    to_taste=ing.to_taste,
                    display=ing.display,
                    confidence=ing.confidence,
                )
            )

    return ShoppingList(
        label=dish.label,
        scale=dish.resolution.scale,
        lines=list(lines.values()),
        to_find=to_find,
    )


def shopping_list(
    library: Library,
    recipe_id: str,
    *,
    batches: float = 1.0,
    requires_mass: Quantity | None = None,
    adjustments: list[Adjustment] | None = None,
    include_optional: bool = True,
    strict: bool = False,
) -> ShoppingList:
    """What to buy to make this recipe, components and all, at this batch size.

    The same pairing ``cookalong.py`` uses: this resolves the dish, and
    ``shopping_list_from_dish`` serves a caller that has already resolved one
    for another reason -- the CLI shows the table and the list off one tree.
    """
    dish = resolve_dish(
        library,
        recipe_id,
        batches=batches,
        requires_mass=requires_mass,
        adjustments=adjustments,
        strict=strict,
    )
    return shopping_list_from_dish(dish, include_optional=include_optional)


def _cited(use: ComponentUse, *, needed_by: str) -> CitedComponent:
    """Where to find a component that is a book reference, not a document.

    The three lines below are a second copy of the wording in
    ``UnresolvableComponent.__init__``, which builds the same string into a
    sentence this list does not want ("'X' is not in the library: see ..."). The
    single-source fix is a property on that exception; it is in ``resolve.py``,
    which this change does not own.
    """
    cite = use.citation or {}
    where = cite.get("name") or use.recipe_ref or use.label
    page = cite.get("rw:page") or cite.get("page")
    return CitedComponent(
        label=use.label,
        needed_by=needed_by,
        where=f"{where}, p.{page}" if page else str(where),
        use=use,
    )
