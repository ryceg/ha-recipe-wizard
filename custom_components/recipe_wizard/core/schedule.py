"""Scheduling over the dataflow graph, and the constraints that limit it.

The obvious feature of a recipe DAG is that independent branches can run in
parallel, so a planner can tell you to start the frosting while the cake bakes.
The non-obvious part is that some edges must *not* be stretched. RecipeTin
Eats' vanilla cake says "do not leave batter sitting once mixing begins; air
bubbles subside quickly, resulting in a dense cake" — a naive critical-path
planner will happily schedule the batter early and ruin it.

So edges carry constraints as well as direction:

* ``maxDelayAfter`` — a hard ceiling on the gap between two steps. Zero means
  back-to-back, which defines a rigid chain the planner may not break.
* ``leadBefore`` — something must *start* this far ahead (the oven preheat).

A plan that violates either is rejected, not warned about.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .model import Recipe, Step
from .resolve import Resolution


#: Assumed duration for a step that states none. Shared by ``schedule`` and
#: ``check_plan`` so a plan is never rejected over an assumption mismatch.
DEFAULT_STEP_S = 60.0


class ScheduleError(ValueError):
    """The step graph is not schedulable — usually a cycle."""


def effective_recipe(source: Recipe | Resolution) -> Recipe:
    """The document a plan or a table is actually true of.

    A ``Recipe`` passes straight through, because a level-0 scrape has no
    resolution and still has to be planned and rendered. Given a
    ``Resolution``, this hands back its *effective* recipe — base plus the
    variant chain plus the parent's local adjustments — carrying the
    resolution's **scaled** step portions.

    This exists because the coffee buttercream is, on disk, nothing but a patch
    list: zero ingredients and zero steps. Every caller that reached for
    ``library.recipe(id)`` and planned or rendered *that* got an empty table
    and a 0-minute plan. The other half of the same bug was available to any
    caller holding a recipe *and* a resolution: it read masses off the
    resolution and portions off the document, so a doubled brownie tray printed
    500 g of peanut butter beside an unscaled "dollop 2 tbsp". Taking one
    argument instead of two makes both impossible to write.
    """
    if isinstance(source, Recipe):
        return source
    if source.steps is source.recipe.steps:
        return source.recipe
    return replace(source.recipe, steps=source.steps)


@dataclass(slots=True)
class ScheduledStep:
    step_id: str
    position: int
    text: str
    start_s: float
    end_s: float
    attention: str
    doneness: str | None = None
    """The state that decides when this step is really finished.

    Carried onto the plan rather than left behind on the ``Step``, because the
    plan is what a timer is built from and the timer is where it matters: the
    brownies' bake is "32 min" *and* "edges firmish, centre still jiggling",
    and a timer that shows only the number tells the cook the wrong one of the
    two is authoritative.
    """

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(slots=True)
class Violation:
    kind: str
    step_id: str
    message: str


@dataclass(slots=True)
class Plan:
    steps: list[ScheduledStep] = field(default_factory=list)
    total_s: float = 0.0
    active_s: float = 0.0
    unattended_s: float = 0.0
    rigid_chains: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def step(self, step_id: str) -> ScheduledStep | None:
        for entry in self.steps:
            if entry.step_id == step_id:
                return entry
        return None


def producers(recipe: Recipe) -> dict[str, str]:
    """Map each intermediate product id to the step that emits it."""
    out: dict[str, str] = {}
    for step in recipe.steps:
        for product in step.produces:
            out[product.id] = step.id
    return out


def dependencies(recipe: Recipe) -> dict[str, set[str]]:
    """Which steps each step waits on.

    Three sources: consuming another step's product, an explicit
    ``maxDelayAfter``, and an explicit ``leadBefore``.
    """
    emits = producers(recipe)
    deps: dict[str, set[str]] = {step.id: set() for step in recipe.steps}
    for step in recipe.steps:
        for consumed in step.consumed_ids:
            producer = emits.get(consumed)
            if producer and producer != step.id:
                deps[step.id].add(producer)
        for constraint in (*step.max_delay_after, *step.min_delay_after):
            if constraint.from_step in deps:
                deps[step.id].add(constraint.from_step)
        for lead_step in step.lead_before:
            if lead_step in deps:
                deps[step.id].add(lead_step)
    return deps


def topological_order(recipe: Recipe) -> list[Step]:
    """Steps in dependency order, falling back on declared position for ties."""
    deps = dependencies(recipe)
    by_id = {step.id: step for step in recipe.steps}
    remaining = dict(deps)
    ordered: list[Step] = []

    while remaining:
        ready = sorted(
            (sid for sid, need in remaining.items() if not need),
            key=lambda sid: by_id[sid].position,
        )
        if not ready:
            raise ScheduleError(
                "cycle in the step graph among: " + ", ".join(sorted(remaining))
            )
        for sid in ready:
            ordered.append(by_id[sid])
            del remaining[sid]
        for need in remaining.values():
            need.difference_update(ready)
    return ordered


def rigid_chains(recipe: Recipe) -> list[list[str]]:
    """Runs of steps that must happen back-to-back, in order.

    These are the stretches a planner is forbidden to interrupt — the answer to
    "can I do this bit tomorrow?" is no, and the graph says so explicitly.
    """
    linked: dict[str, str] = {}
    for step in recipe.steps:
        for constraint in step.max_delay_after:
            if constraint.limit.seconds == 0:
                linked[constraint.from_step] = step.id

    starts = [src for src in linked if src not in linked.values()]
    chains = []
    for start in starts:
        chain = [start]
        current = start
        while current in linked:
            current = linked[current]
            chain.append(current)
        chains.append(chain)
    return chains


MAX_ITERATIONS = 100


def successors(deps: dict[str, set[str]]) -> dict[str, set[str]]:
    """Invert the dependency map."""
    out: dict[str, set[str]] = {step_id: set() for step_id in deps}
    for step_id, needs in deps.items():
        for need in needs:
            out.setdefault(need, set()).add(step_id)
    return out


def _latest_pass(
    recipe: Recipe,
    ordered: list[Step],
    earliest_start: dict[str, float],
    end: dict[str, float],
    duration_of,
) -> dict[str, float]:
    """Schedule every step as late as it can go without delaying the finish.

    Earliest-start is the intuitive algorithm and it is the wrong default for
    cooking. Nothing in the brownie graph forces the batter to be mixed after
    the peanut butter has frozen, so an earliest-start plan melts the chocolate
    at t=0 and leaves the batter to stiffen for two hours before it is poured.
    The same shape appeared in the cake with the hot milk. Both are the same
    mistake: prep that *can* happen early usually *should not*.

    Scheduling backwards from the finish makes just-in-time the default and
    leaves ``maxDelayAfter`` to handle the genuinely hard cases rather than
    every ordinary one.
    """
    deps = dependencies(recipe)
    succ = successors(deps)
    finish = max(end.values(), default=0.0)
    latest_start: dict[str, float] = {}

    for step in reversed(ordered):
        following = succ.get(step.id, set())
        if not following:
            latest_end = finish
        else:
            latest_end = min(
                latest_start[other] - _edge_gap(recipe, step.id, other)
                for other in following
                if other in latest_start
            )
        start = latest_end - duration_of(step)
        # Never earlier than the forward pass allows: that bound carries the
        # minimum delays and lead requirements.
        latest_start[step.id] = max(start, earliest_start[step.id])

    return latest_start


def _edge_gap(recipe: Recipe, before: str, after: str) -> float:
    """Any mandatory wait between two steps, from a minimum-delay constraint."""
    step = recipe.step(after)
    if step is None:
        return 0.0
    return max(
        (c.limit.seconds for c in step.min_delay_after if c.from_step == before),
        default=0.0,
    )


def schedule(
    source: Recipe | Resolution,
    *,
    default_step_s: float = DEFAULT_STEP_S,
    strategy: str = "just-in-time",
) -> Plan:
    """Plan the recipe, in seconds from t=0.

    Takes a ``Recipe`` or a ``Resolution``. A resolution is planned from its
    *effective* document: the coffee buttercream's own file has no steps at all,
    so planning the document on disk produced a 0-minute plan for a recipe that
    takes seven minutes.

    Earliest-start is the obvious algorithm and it is wrong on its own. The
    cake's butter and milk have no predecessor, so ASAP starts them at t=0 —
    half an hour before they are folded into the batter, by which time the
    source's "ensure milk and butter are hot when incorporated" has been
    quietly violated. A ``maxDelayAfter`` therefore has to be able to push a
    *predecessor later*, not merely reject a successor that runs late.

    That makes this a system of difference constraints rather than a simple
    topological walk, solved here by alternating a forward earliest-start pass
    with a backward just-in-time pass until nothing moves.
    """
    recipe = effective_recipe(source)
    deps = dependencies(recipe)
    ordered = topological_order(recipe)
    by_id = {step.id: step for step in recipe.steps}
    warnings: list[str] = []

    def duration_of(step: Step) -> float:
        return step.duration.seconds if step.duration else default_step_s

    # Lower bounds on each step's start, raised by the backward pass.
    release: dict[str, float] = {step.id: 0.0 for step in recipe.steps}

    def forward() -> tuple[dict[str, float], dict[str, float]]:
        start: dict[str, float] = {}
        end: dict[str, float] = {}
        for step in ordered:
            earliest = max(
                [end[d] for d in deps[step.id] if d in end] + [release[step.id]]
            )
            # A minimum delay is a floor, not something to iterate towards: the
            # brownies must chill three hours before cutting, so the cut simply
            # cannot start earlier.
            for constraint in step.min_delay_after:
                if constraint.from_step in end:
                    earliest = max(
                        earliest, end[constraint.from_step] + constraint.limit.seconds
                    )
            start[step.id] = earliest
            end[step.id] = earliest + duration_of(step)
        return start, end

    start, end = forward()

    for _ in range(MAX_ITERATIONS):
        changed = False
        for step in ordered:
            # Just-in-time: a bounded gap means the predecessor waits.
            for constraint in step.max_delay_after:
                source = constraint.from_step
                if source not in end:
                    continue
                gap = start[step.id] - end[source]
                if gap > constraint.limit.seconds + 1e-9:
                    release[source] += gap - constraint.limit.seconds
                    changed = True
            # A lead requirement is a floor on the dependent step, not a shove
            # applied to the whole timeline.
            for lead_id, lead in step.lead_before.items():
                if lead_id not in start:
                    warnings.append(
                        f"{step.id} requires lead from unknown step {lead_id!r}"
                    )
                    continue
                required = start[lead_id] + lead.seconds
                if start[step.id] < required - 1e-9:
                    release[step.id] = max(release[step.id], required)
                    changed = True
        if not changed:
            break
        start, end = forward()
    else:
        warnings.append(
            "scheduling constraints did not settle; the plan may violate a "
            "maxDelayAfter. This usually means two constraints contradict."
        )

    if strategy == "just-in-time":
        latest = _latest_pass(recipe, ordered, start, end, duration_of)
        start = latest
        end = {sid: latest[sid] + duration_of(by_id[sid]) for sid in latest}
    elif strategy != "asap":
        raise ScheduleError(f"unknown scheduling strategy {strategy!r}")

    base = min(start.values(), default=0.0)
    scheduled = [
        ScheduledStep(
            step_id=step.id,
            position=step.position,
            text=step.text,
            start_s=start[step.id] - base,
            end_s=end[step.id] - base,
            attention=step.attention,
            doneness=step.doneness,
        )
        for step in ordered
    ]
    scheduled.sort(key=lambda s: (s.start_s, s.position))
    active, unattended = _attention_wall_clock(scheduled)

    return Plan(
        steps=scheduled,
        total_s=max((s.end_s for s in scheduled), default=0.0),
        active_s=active,
        unattended_s=unattended,
        rigid_chains=rigid_chains(recipe),
        warnings=warnings,
    )


def _attention_wall_clock(scheduled: list[ScheduledStep]) -> tuple[float, float]:
    """Split the timeline into hands-on and hands-off wall-clock time.

    Summing per-step durations double-counts overlapping branches, which is how
    you get "20 minutes unattended" out of a 40-minute recipe that also claims
    20 minutes of prep. Sweeping the timeline instead means the two figures add
    up to something a cook can actually plan around: any instant with an active
    step running counts as active, even if something is baking alongside it.
    """
    boundaries = sorted({t for s in scheduled for t in (s.start_s, s.end_s)})
    active = unattended = 0.0
    for start, end in zip(boundaries, boundaries[1:]):
        running = [s for s in scheduled if s.start_s < end and s.end_s > start]
        if not running:
            continue
        span = end - start
        if any(s.attention == "active" for s in running):
            active += span
        else:
            unattended += span
    return active, unattended


def check_plan(
    source: Recipe | Resolution,
    starts: dict[str, float],
    *,
    default_step_s: float = DEFAULT_STEP_S,
) -> list[Violation]:
    """Reject a proposed set of start times.

    This is the guard against a planner deciding the batter can be made ahead.
    Given start times in seconds, it returns every constraint they break.

    Takes the same ``Recipe | Resolution`` as ``schedule``, so a plan and the
    check on it cannot be run against two different documents.
    """
    recipe = effective_recipe(source)
    by_id = {step.id: step for step in recipe.steps}
    violations: list[Violation] = []

    def finish(step_id: str) -> float | None:
        step = by_id.get(step_id)
        if step is None or step_id not in starts:
            return None
        duration = step.duration.seconds if step.duration else default_step_s
        return starts[step_id] + duration

    for step in recipe.steps:
        if step.id not in starts:
            continue
        for constraint in step.max_delay_after:
            predecessor_end = finish(constraint.from_step)
            if predecessor_end is None:
                continue
            gap = starts[step.id] - predecessor_end
            if gap < 0:
                violations.append(
                    Violation(
                        "out-of-order",
                        step.id,
                        f"{step.id} starts before {constraint.from_step} finishes",
                    )
                )
            elif gap > constraint.limit.seconds + 1e-9:
                allowed = constraint.limit.human()
                violations.append(
                    Violation(
                        "max-delay",
                        step.id,
                        f"{step.id} starts {gap / 60:.0f} min after "
                        f"{constraint.from_step}, but the gap must be at most "
                        f"{allowed}"
                        + (f" - {constraint.reason}" if constraint.reason else ""),
                    )
                )
        for constraint in step.min_delay_after:
            predecessor_end = finish(constraint.from_step)
            if predecessor_end is None:
                continue
            gap = starts[step.id] - predecessor_end
            if gap < constraint.limit.seconds - 1e-9:
                violations.append(
                    Violation(
                        "min-delay",
                        step.id,
                        f"{step.id} starts {gap / 60:.0f} min after "
                        f"{constraint.from_step}, but must wait at least "
                        f"{constraint.limit.human()}"
                        + (f" - {constraint.reason}" if constraint.reason else ""),
                    )
                )
        for lead_id, lead in step.lead_before.items():
            if lead_id not in starts:
                continue
            actual_lead = starts[step.id] - starts[lead_id]
            if actual_lead < lead.seconds - 1e-9:
                violations.append(
                    Violation(
                        "insufficient-lead",
                        step.id,
                        f"{lead_id} starts only {actual_lead / 60:.0f} min before "
                        f"{step.id}, but needs {lead.human()}",
                    )
                )
    return violations
