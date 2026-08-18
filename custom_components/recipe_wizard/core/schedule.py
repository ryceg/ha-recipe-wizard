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

The graph itself lives in ``graph.py`` and is indexed once per call: this module
used to rebuild the dependency map three times and the step-id index twice inside
a single ``schedule()``, and to look a constraint's target up by exact dict key
in the passes while ``_edge_gap`` looked the same target up tolerantly -- so a
fully-qualified ``rw:from`` drew no edge and quietly lost the wait it carried.
Every step reference here is resolved through ``graph.step_id`` before it is used
as a key.

**Defects here are ``validate.Finding``s and nothing else.** This module used to
carry its own record -- ``Violation(kind, step_id, message)`` -- plus a list of
bare strings on ``Plan``, which made three shapes for one idea across two
modules, and it was *this* one that named the node. Nothing converted between
them and ``validate_recipe`` never called ``check_plan``, so a document whose
constraints contradicted each other passed validation and misbehaved only when
somebody asked for a plan.

``Finding`` lives in ``validate.py`` because that module is the contract
(``docs/format.md`` § Scope) and scheduling is one producer of it, not its owner.
That direction means the import has to be made inside the two functions that
build findings: ``validate`` imports this module at the top, so a module-level
import back would be a cycle. It is one lookup in ``sys.modules`` per call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .graph import GraphSource, RecipeGraph, recipe_graph
from .model import Step, fragment

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .validate import Finding


#: Assumed duration for a step that states none. Shared by ``schedule`` and
#: ``check_plan`` so a plan is never rejected over an assumption mismatch.
DEFAULT_STEP_S = 60.0


class ScheduleError(ValueError):
    """The step graph is not schedulable — usually a cycle."""


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
class Plan:
    steps: list[ScheduledStep] = field(default_factory=list)
    total_s: float = 0.0
    active_s: float = 0.0
    unattended_s: float = 0.0
    rigid_chains: list[list[str]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    """What the planner could not do, in the report's one shape.

    Was ``warnings: list[str]``, which was a third shape for the idea
    ``Finding`` and ``Violation`` were already two of, and it was the wrong word
    besides: a ``rw:leadBefore`` pointing at no step and a pair of constraints
    that cannot both hold are errors -- the plan that comes back is wrong, not
    merely uncertain -- and the CLI printed them next to a validation report that
    counted its errors and did not count these.
    """
    _by_id: dict[str, ScheduledStep] | None = field(
        default=None, repr=False, compare=False
    )
    """Lazy id index. ``step()`` was a linear scan over a list every caller reads
    step-by-step -- the CLI, the cook-along and every scheduling test."""

    @property
    def state_decided_s(self) -> float:
        """How much of this plan is a step whose end a *state* decides.

        A sum of those steps' own durations, and deliberately **not** a share of
        ``total_s``: the timeline is swept rather than summed, because branches
        overlap -- the brownies mix their chocolate batter while the peanut butter
        freezes -- so a percentage would be arithmetic between two numbers that do
        not divide.

        It exists because "total 7 hr" reads as a promise. Nearly three of those
        hours are a bake and two chills that end when the food says so, and a cook
        planning dinner around the number deserves to know which part of it is
        soft. The planner still builds the timeline from the clock alone -- there
        is nothing else to build it from -- but it no longer presents the result as
        if the clock were the authority.
        """
        return sum(
            entry.duration_s for entry in self.steps if entry.doneness is not None
        )

    def step(self, step_id: str) -> ScheduledStep | None:
        """The scheduled step with this id, under the library's one lookup rule."""
        if self._by_id is None:
            self._by_id = {entry.step_id: entry for entry in self.steps}
        found = self._by_id.get(step_id)
        if found is not None:
            return found
        return self._by_id.get(fragment(step_id))


def dependencies(source: GraphSource) -> dict[str, set[str]]:
    """Which steps each step waits on.

    The name the planner and the validator both already ask by; the index itself
    is built once per graph. This used to be recomputed three times inside a
    single ``schedule()`` call -- in ``topological_order``, in ``_latest_pass``
    and in ``schedule`` itself.
    """
    return recipe_graph(source).dependencies


def topological_order(source: GraphSource) -> list[Step]:
    """Steps in dependency order, falling back on declared position for ties.

    Stays here rather than on the graph because the failure is a *scheduling*
    failure: a cycle means there is no plan, and ``ScheduleError`` is what the
    validator catches to report ``step-cycle``.
    """
    graph = recipe_graph(source)
    by_id = graph.steps_by_id
    # Copied set by set. This used to be a shallow ``dict(deps)`` over a map that
    # was rebuilt on every call, and the ``difference_update`` below emptied the
    # original as it went -- harmless then, and a plan that is right exactly once
    # now that one map is shared for the life of the graph.
    remaining = {step_id: set(need) for step_id, need in graph.dependencies.items()}
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


def rigid_chains(source: GraphSource) -> list[list[str]]:
    """Runs of steps that must happen back-to-back, in order.

    These are the stretches a planner is forbidden to interrupt — the answer to
    "can I do this bit tomorrow?" is no, and the graph says so explicitly.
    """
    graph = recipe_graph(source)
    linked: dict[str, str] = {}
    for step in graph.recipe.steps:
        for constraint in step.max_delay_after:
            predecessor = graph.step_id(constraint.from_step)
            if predecessor is not None and constraint.limit.seconds == 0:
                linked[predecessor] = step.id

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


def _latest_pass(
    graph: RecipeGraph,
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

    "The end" here is a *time*: ``finish`` is the last moment any step occupies,
    and a step with nothing after it is pushed back from that. It is deliberately
    not the validator's two notions of the end -- the last step on the page, and
    the products nothing consumes -- which are questions about the document
    rather than about the clock. Several steps can end at ``finish``.
    """
    succ = graph.successors
    finish = max(end.values(), default=0.0)
    latest_start: dict[str, float] = {}

    for step in reversed(ordered):
        following = succ.get(step.id, set())
        if not following:
            latest_end = finish
        else:
            latest_end = min(
                latest_start[other] - _edge_gap(graph, step.id, other)
                for other in following
                if other in latest_start
            )
        start = latest_end - duration_of(step)
        # Never earlier than the forward pass allows: that bound carries the
        # minimum delays and lead requirements.
        latest_start[step.id] = max(start, earliest_start[step.id])

    return latest_start


def _edge_gap(graph: RecipeGraph, before: str, after: str) -> float:
    """Any mandatory wait between two steps, from a minimum-delay constraint."""
    step = graph.step(after)
    if step is None:
        return 0.0
    return max(
        (
            c.limit.seconds
            for c in step.min_delay_after
            if graph.step_id(c.from_step) == before
        ),
        default=0.0,
    )


def schedule(
    source: GraphSource,
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
    # Deferred, not a cycle: see the module docstring. ``validate`` imports this
    # module at the top, so the record it owns has to be fetched at call time.
    from .validate import ERROR, Finding

    # One graph, indexed once, for every pass below. The dependency map used to
    # be rebuilt three times per call and the id index twice.
    graph = recipe_graph(source)
    recipe = graph.recipe
    deps = graph.dependencies
    ordered = topological_order(graph)
    by_id = graph.steps_by_id
    where = recipe.id or recipe.name
    findings: list[Finding] = []

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
            # cannot start earlier. Resolved to the step's own id first, because
            # this is a key: a ``rw:from`` written the long way used to miss the
            # dict and drop the floor without a word.
            for constraint in step.min_delay_after:
                predecessor = graph.step_id(constraint.from_step)
                if predecessor is not None and predecessor in end:
                    earliest = max(
                        earliest, end[predecessor] + constraint.limit.seconds
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
                # Named, rather than shadowing this function's own ``source``.
                predecessor = graph.step_id(constraint.from_step)
                if predecessor is None or predecessor not in end:
                    continue
                gap = start[step.id] - end[predecessor]
                if gap > constraint.limit.seconds + 1e-9:
                    release[predecessor] += gap - constraint.limit.seconds
                    changed = True
            # A lead requirement is a floor on the dependent step, not a shove
            # applied to the whole timeline.
            for lead_ref, lead in step.lead_before.items():
                # Resolved for the lookup, quoted as written for the warning: an
                # author who mistyped a step id has to see their own spelling.
                lead_id = graph.step_id(lead_ref)
                if lead_id is None or lead_id not in start:
                    findings.append(Finding(
                        ERROR, "schedule-unknown-lead", where,
                        f"{step.id} requires lead from unknown step {lead_ref!r}",
                        step.id,
                    ))
                    continue
                required = start[lead_id] + lead.seconds
                if start[step.id] < required - 1e-9:
                    release[step.id] = max(release[step.id], required)
                    changed = True
        if not changed:
            break
        start, end = forward()
    else:
        # No node: the defect is a *pair* of constraints that cannot both hold,
        # and the loop does not know which two. ``check_plan`` on the plan this
        # returns does, and names the step it broke at -- which is the reason
        # ``validate`` runs both.
        findings.append(Finding(
            ERROR, "schedule-unsettled", where,
            "scheduling constraints did not settle; the plan may violate a "
            "maxDelayAfter. This usually means two constraints contradict.",
        ))

    if strategy == "just-in-time":
        latest = _latest_pass(graph, ordered, start, end, duration_of)
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
        rigid_chains=rigid_chains(graph),
        findings=findings,
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
    source: GraphSource,
    starts: dict[str, float],
    *,
    default_step_s: float = DEFAULT_STEP_S,
) -> list[Finding]:
    """Reject a proposed set of start times.

    This is the guard against a planner deciding the batter can be made ahead.
    Given start times in seconds, it returns every constraint they break, as
    findings under ``schedule-*`` codes.

    Every one is an ERROR, which is what this function has always meant: a plan
    that breaks a ``maxDelayAfter`` is rejected, not warned about, because the
    cake it produces is dense and the brownies ooze. Each finding names the step
    whose start time is wrong in ``node``, which is the field the old
    ``Violation.step_id`` was and the reason the two records had to become one.

    Takes the same ``Recipe | Resolution`` as ``schedule``, so a plan and the
    check on it cannot be run against two different documents.
    """
    # Deferred, not a cycle: see the module docstring.
    from .validate import ERROR, Finding

    graph = recipe_graph(source)
    recipe = graph.recipe
    where = recipe.id or recipe.name
    findings: list[Finding] = []

    def finish(ref: str) -> float | None:
        """When the step ``ref`` names ends, given the proposed starts.

        ``starts`` is keyed by step id, so the reference is resolved to one
        before it is looked up -- the same rule the planner applies, so a plan
        and the check on it cannot disagree about which edges exist.
        """
        step = graph.step(ref)
        if step is None or step.id not in starts:
            return None
        duration = step.duration.seconds if step.duration else default_step_s
        return starts[step.id] + duration

    for step in recipe.steps:
        if step.id not in starts:
            continue
        for constraint in step.max_delay_after:
            predecessor_end = finish(constraint.from_step)
            if predecessor_end is None:
                continue
            gap = starts[step.id] - predecessor_end
            if gap < 0:
                findings.append(
                    Finding(
                        ERROR,
                        "schedule-out-of-order",
                        where,
                        f"{step.id} starts before {constraint.from_step} finishes",
                        step.id,
                    )
                )
            elif gap > constraint.limit.seconds + 1e-9:
                allowed = constraint.limit.human()
                findings.append(
                    Finding(
                        ERROR,
                        "schedule-max-delay",
                        where,
                        f"{step.id} starts {gap / 60:.0f} min after "
                        f"{constraint.from_step}, but the gap must be at most "
                        f"{allowed}"
                        + (f" - {constraint.reason}" if constraint.reason else ""),
                        step.id,
                    )
                )
        for constraint in step.min_delay_after:
            predecessor_end = finish(constraint.from_step)
            if predecessor_end is None:
                continue
            gap = starts[step.id] - predecessor_end
            if gap < constraint.limit.seconds - 1e-9:
                findings.append(
                    Finding(
                        ERROR,
                        "schedule-min-delay",
                        where,
                        f"{step.id} starts {gap / 60:.0f} min after "
                        f"{constraint.from_step}, but must wait at least "
                        f"{constraint.limit.human()}"
                        + (f" - {constraint.reason}" if constraint.reason else ""),
                        step.id,
                    )
                )
        for lead_ref, lead in step.lead_before.items():
            lead_id = graph.step_id(lead_ref)
            if lead_id is None or lead_id not in starts:
                continue
            actual_lead = starts[step.id] - starts[lead_id]
            if actual_lead < lead.seconds - 1e-9:
                # ``node`` is the step that *needs* the lead, not the one that has
                # to start earlier: the ``rw:leadBefore`` is written on this step,
                # so this is the node an author edits.
                findings.append(
                    Finding(
                        ERROR,
                        "schedule-insufficient-lead",
                        where,
                        f"{lead_ref} starts only {actual_lead / 60:.0f} min before "
                        f"{step.id}, but needs {lead.human()}",
                        step.id,
                    )
                )
    return findings
