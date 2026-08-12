"""The cook-along: what to do now, what it needs, and what timer to start.

This is the surface the whole format was designed against — a screen you do not
have to touch with dough on your hands — and until this module existed nothing
joined the pieces it needs. The join is four-way and every caller was doing it
by hand:

* ``resolve_dish()`` knows the effective recipe and the scale, for the dish and
  every component under it.
* ``resolution.steps`` holds the step portions *scaled* — "dollop 2 tbsp"
  becomes 4 tbsp in a doubled tray.
* ``resolution.ingredients`` holds the masses at that same scale.
* ``schedule()`` knows the order, the start and end of each step, and which
  stretches may not be interrupted.

Doing that join in the Home Assistant entity would put it in the least testable
place in the system, which is why it is here instead. Two of the four had
already gone wrong in the CLI: the renderer read the procedure column off the
unscaled document while reading masses off the resolution, and the planner
planned the document on disk — which for the coffee buttercream, a pure patch
list with no steps of its own, is a 0-minute plan.

**Stateless over a cursor.** Nothing here advances, mutates or remembers. The
integration holds "which step am I on" as its own state and asks
``CookAlong.at(cursor)`` what that step is; asking twice gives the same answer.
A ``next()`` that advanced something internally would put the same state in two
places, and Home Assistant restores its own on restart.

**Components are grouped, never interleaved.** A dish is a tree of recipes, each
with its own plan, and this presents it as exactly that: the root's steps in its
own plan order, then each component's, labelled. It does *not* merge them into
one timeline. Scheduling in ``docs/format.md`` is per-recipe — every constraint
(``maxDelayAfter``, ``leadBefore``, the rigid chains) names step ids inside one
document — so slotting the frosting into the gap while the cake cools would mean
inventing edges no recipe states: which of the cake's 18 steps the frosting must
precede, whether one cook can be in two active steps at once, and what the
buttercream's own "use immediately on cooled cakes" does to the answer. That is
a design decision, not a refactor, so ``sequence()`` walks the tree in document
order and each component keeps its own ``Plan`` for the cook to read.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from .dish import Dish, resolve_dish
from .duration import Duration
from .library import Library
from .model import (
    Adjustment,
    ComponentUse,
    MakeAhead,
    Portion,
    Product,
    RequiredState,
)
from .render import format_mass, ingredients_for_step
from .resolve import Resolution
from .schedule import DEFAULT_STEP_S, Plan, effective_recipe, schedule
from .units import Quantity


@dataclass(slots=True)
class StepIngredient:
    """One thing the cook needs in front of them at one step, at this scale.

    ``portion`` says how much of the row this step takes and ``row_mass_g`` is
    the mass of the **whole row** at this batch size. They are deliberately not
    multiplied together: portions are display-only and never resolved to a mass
    (``docs/format.md`` § Portions), because nobody weighs half a Bolognese and
    a confidently wrong "1,612 g" is worse than "just over half".

    So a doubled brownie tray reads "4 tbsp smooth peanut butter (of 500 g)" —
    the portion scaled, the row's mass scaled, and no arithmetic pretending to
    know what 4 tbsp of peanut butter weighs.
    """

    id: str
    name: str
    portion: Portion
    row_mass_g: float | None = None
    """The whole row's mass at this scale, or ``None`` for an intermediate or a
    sub-recipe that states no mass — "half the brownie batter" has no weight."""
    optional: bool = False
    to_taste: bool = False
    display: str | None = None
    """The source's own measure, where it had one: "2-4 tbsp, if needed"."""
    required_state: RequiredState | None = None
    """"softened to room temperature", with the hour it takes to get there."""
    note: str | None = None

    @property
    def takes_whole_row(self) -> bool:
        return self.portion.is_whole

    def describe(self) -> str:
        """One line for the cook: how much of what.

        A whole row reads as a weight and a name; a partial one names the thing
        first and then the source's own words for the share, because "the rest
        plain yogurt" is not English and "plain yogurt: the rest (of 193 g)" is
        what the cook needs to see.
        """
        if self.to_taste:
            return f"{self.name}, to taste"
        mass = format_mass(self.row_mass_g) if self.row_mass_g is not None else None
        if self.takes_whole_row:
            line = f"{mass} {self.name}" if mass else self.name
        else:
            line = f"{self.name}: {self.portion.describe()}"
            if mass:
                line += f" (of {mass})"
        if self.optional:
            line += " (optional)"
        return line


@dataclass(slots=True)
class CookStep:
    """One step, ready to put on a screen: when, what, what with, what timer.

    ``start_s``/``end_s`` come from the plan and are where this step sits in the
    whole recipe's timeline. ``timer`` is the step's *own* stated duration, and
    is ``None`` when the step states none — the planner assumes a minute for
    those so the graph has a length, and starting a 60-second timer on that
    assumption would be a lie a cook could act on.
    """

    step_id: str
    position: int
    text: str
    attention: str
    """active / passive / unattended — whether the cook can walk away."""
    start_s: float
    end_s: float
    timer: Duration | None = None
    timer_max: Duration | None = None
    """Upper end of a range: the brownies' peanut butter freezes for 2-3 hours."""
    doneness: str | None = None
    timer_starts_when: str | None = None
    safety_note: str | None = None
    may_pause_after: bool = False
    """A sanctioned stopping point — "freeze until firm" is one, and the cook
    asking "can I do the rest tomorrow?" deserves a straight answer."""
    produces: list[Product] = field(default_factory=list)
    ingredients: list[StepIngredient] = field(default_factory=list)

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    @property
    def timer_s(self) -> float | None:
        return None if self.timer is None else self.timer.seconds

    @property
    def timer_max_s(self) -> float | None:
        return None if self.timer_max is None else self.timer_max.seconds

    @property
    def has_timer(self) -> bool:
        return self.timer is not None

    def timer_label(self) -> str | None:
        """What a timer for this step should say, or ``None`` if it has nothing.

        The state is authoritative and the time is an estimate, and the phrasing
        has to carry that round the right way: the brownies bake for "32 min"
        until "edges firmish, centre still jiggling", and a timer showing only
        the number tells the cook the oven decides. So a step with both reads
        *"32 min, then check: edges firmish, centre still jiggling"*, and a step
        with a state and no time says to go by the state rather than implying
        there is nothing to wait for.
        """
        span = None
        if self.timer is not None:
            span = self.timer.human()
            upper = self.timer_max
            if upper is not None and upper.seconds > self.timer.seconds:
                span = f"{span}-{upper.human()}"
        if span and self.doneness:
            return f"{span}, then check: {self.doneness}"
        if span:
            return span
        if self.doneness:
            return f"go by: {self.doneness}"
        return None


@dataclass(frozen=True, slots=True)
class CursorStep:
    """One position in the walk, and which dish's page the cook is on.

    ``label`` is the *use's* label, so a cook halfway through the cake's
    frosting sees "Vanilla buttercream" and not the parent's name.
    """

    cursor: int
    of: int
    recipe_id: str
    label: str
    step: CookStep

    @property
    def is_last(self) -> bool:
        return self.cursor >= self.of - 1


@dataclass(slots=True)
class CookAlong:
    """One dish's cook-along: its own ordered steps, its own plan, its children.

    A tree, mirroring ``Dish``. Nothing is merged across recipes — see the
    module docstring for why the frosting is not slotted into the gap while the
    cake cools.
    """

    recipe_id: str
    label: str
    scale: float
    resolution: Resolution
    """Carried so a caller has the yield, the storage, the warnings and the
    whole ingredient list without resolving anything a second time."""
    plan: Plan
    steps: list[CookStep] = field(default_factory=list)
    components: list["CookAlong"] = field(default_factory=list)
    unresolvable: list[ComponentUse] = field(default_factory=list)
    """Components that are a book citation rather than a document. The cook
    still has to be told to go and get *Dinner* p.308."""
    optional: bool = False
    make_ahead: MakeAhead | None = None
    """How far ahead this component may be made, where its use says."""

    # -- this dish -----------------------------------------------------------

    def step(self, step_id: str) -> CookStep | None:
        fragment = "#" + step_id.split("#")[-1]
        for entry in self.steps:
            if entry.step_id in (step_id, fragment):
                return entry
        return None

    @property
    def total_s(self) -> float:
        return self.plan.total_s

    # -- the tree ------------------------------------------------------------

    def walk(self, *, include_optional: bool = True) -> Iterator["CookAlong"]:
        """This dish, then its descendants, depth-first in document order.

        ``include_optional=False`` drops an optional component and everything
        under it — the qeema without the mint yogurt — which is how a caller
        folds the tree without knowing its shape. The root is always yielded.
        """
        yield self
        for child in self.components:
            if child.optional and not include_optional:
                continue
            yield from child.walk(include_optional=include_optional)

    def sequence(self, *, include_optional: bool = True) -> list[CursorStep]:
        """Every step in the tree, grouped by dish and numbered from zero.

        The order is: this dish's steps in *its plan's* order, then each
        component's, in the order the document names them. Grouped, not
        interleaved: the cursor addresses "the nth page of this recipe book",
        and each dish's own ``plan`` is what says when to start it.
        """
        entries = [
            (dish.recipe_id, dish.label, step)
            for dish in self.walk(include_optional=include_optional)
            for step in dish.steps
        ]
        total = len(entries)
        return [
            CursorStep(cursor=index, of=total, recipe_id=rid, label=label, step=step)
            for index, (rid, label, step) in enumerate(entries)
        ]

    def at(self, cursor: int, *, include_optional: bool = True) -> CursorStep | None:
        """The step at ``cursor``, or ``None`` when the cursor is off the end.

        ``None`` rather than an exception because "not started" and "finished"
        are ordinary states for the entity holding the cursor to be in, and
        because a recipe edited under a saved cursor must not crash the
        integration on restart.
        """
        if cursor < 0:
            return None
        steps = self.sequence(include_optional=include_optional)
        if cursor >= len(steps):
            return None
        return steps[cursor]

    def total_steps(self, *, include_optional: bool = True) -> int:
        return sum(
            len(dish.steps)
            for dish in self.walk(include_optional=include_optional)
        )


def step_ingredients(resolution: Resolution, step_id: str) -> list[StepIngredient]:
    """What one step needs, at the scale the resolution was built at.

    **One argument, and it is the resolution.** The unresolved form,
    ``render.ingredients_for_step(recipe, step_id)``, has to keep existing —
    a level-0 scrape has no resolution and must still render — but it can only
    ever answer at base yield. Given a recipe *and* a resolution a caller could
    pass a document from one batch and masses from another and get a plausible
    wrong answer; taking only the resolution removes the choice, because the
    resolution carries the effective document, its scaled portions and its
    scaled masses as one object.
    """
    document = effective_recipe(resolution)
    masses = {row.id: row for row in resolution.ingredients}
    out: list[StepIngredient] = []
    for ref, label, portion in ingredients_for_step(document, step_id):
        row = masses.get(ref)
        out.append(
            StepIngredient(
                id=ref,
                name=row.name if row is not None else label,
                portion=portion,
                row_mass_g=None if row is None else row.mass_g,
                optional=bool(row.optional) if row is not None else False,
                to_taste=bool(row.to_taste) if row is not None else False,
                display=row.display if row is not None else None,
                required_state=row.required_state if row is not None else None,
                note=row.note if row is not None else None,
            )
        )
    return out


def cook_along(
    library: Library,
    recipe_id: str,
    *,
    batches: float = 1.0,
    requires_mass: Quantity | None = None,
    adjustments: list[Adjustment] | None = None,
    strict: bool = False,
    default_step_s: float = DEFAULT_STEP_S,
) -> CookAlong:
    """The whole answer to "what am I cooking, and what is next?".

    ``batches`` propagates: double the cake and the frosting is resolved at two
    batches too, so the portions and masses the cook-along shows for the
    frosting's own steps are the ones on the bench.
    """
    dish = resolve_dish(
        library,
        recipe_id,
        batches=batches,
        requires_mass=requires_mass,
        adjustments=adjustments,
        strict=strict,
    )
    return cook_along_from_dish(dish, default_step_s=default_step_s)


def cook_along_from_dish(
    dish: Dish, *, default_step_s: float = DEFAULT_STEP_S
) -> CookAlong:
    """Same thing, for a caller that already resolved the dish.

    The validator and the CLI both build a ``Dish`` for other reasons, and
    resolving the tree twice to show it once would be waste the entity is in no
    position to notice.
    """
    resolution = dish.resolution
    document = effective_recipe(resolution)
    plan = schedule(resolution, default_step_s=default_step_s)
    by_id = {step.id: step for step in document.steps}

    children = [
        cook_along_from_dish(child, default_step_s=default_step_s)
        for child in dish.components
    ]
    # What each component will actually make, so a step consuming one can show a
    # mass beside it. The mass belongs to the child's resolution, not the
    # parent's ingredient rows, which is why it is filled in here and not in
    # ``step_ingredients``.
    produced_by_use = {
        child.use.id: grown.resolution.produced_g
        for child, grown in zip(dish.components, children)
        if child.use is not None
    }

    steps: list[CookStep] = []
    for scheduled in plan.steps:
        step = by_id.get(scheduled.step_id)
        if step is None:  # pragma: no cover - the plan is built from these
            continue
        ingredients = step_ingredients(resolution, step.id)
        for entry in ingredients:
            if entry.row_mass_g is None and entry.id in produced_by_use:
                entry.row_mass_g = produced_by_use[entry.id]
        steps.append(
            CookStep(
                step_id=step.id,
                position=step.position,
                text=step.text,
                attention=step.attention,
                start_s=scheduled.start_s,
                end_s=scheduled.end_s,
                timer=step.duration,
                timer_max=step.duration_max,
                doneness=step.doneness,
                timer_starts_when=step.timer_starts_when,
                safety_note=step.safety_note,
                may_pause_after=step.may_pause_after,
                produces=list(step.produces),
                ingredients=ingredients,
            )
        )

    return CookAlong(
        recipe_id=resolution.recipe_id,
        label=dish.label,
        scale=resolution.scale,
        resolution=resolution,
        plan=plan,
        steps=steps,
        components=children,
        unresolvable=list(dish.unresolvable),
        optional=dish.optional,
        make_ahead=resolution.make_ahead,
    )
