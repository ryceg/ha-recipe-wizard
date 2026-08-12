"""Scoring an enriched recipe against a hand-authored one.

The plan accepts that LLM enrichment will be roughly right and occasionally
wrong in ways no validator catches -- an ingredient linked to the wrong one of
several steps that all mention it is structurally valid and factually false.
That trade is only defensible if "roughly right" is a measured number rather
than a hope.

The hand-authored recipes in ``recipes/`` are the ground truth. This module
aligns a candidate document against one of them and reports precision and
recall on the thing that actually matters: the ingredient-to-step edges.

Alignment is deliberately generous -- fuzzy on names and step text -- so that a
low score means the *graph* is wrong rather than the wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import Recipe

_STOP = {
    "the", "a", "an", "of", "and", "or", "to", "in", "into", "on", "for", "with",
    "then", "until", "about", "over", "at", "it", "is", "be", "so", "you", "your",
}
_MATCH_THRESHOLD = 0.34


def tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if t not in _STOP and len(t) > 2
    }


def similarity(a: str, b: str) -> float:
    """Jaccard overlap on content words."""
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _align(
    reference: list, candidate: list, key, threshold: float = _MATCH_THRESHOLD
) -> tuple[dict[str, str], list, list]:
    """Greedy best-match alignment. Returns candidate id -> reference id."""
    pairs = []
    for ref in reference:
        for cand in candidate:
            score = similarity(key(ref), key(cand))
            if score >= threshold:
                pairs.append((score, ref, cand))
    pairs.sort(key=lambda p: -p[0])

    mapping: dict[str, str] = {}
    used_ref: set[str] = set()
    used_cand: set[str] = set()
    for _, ref, cand in pairs:
        if ref.id in used_ref or cand.id in used_cand:
            continue
        mapping[cand.id] = ref.id
        used_ref.add(ref.id)
        used_cand.add(cand.id)

    missing = [r for r in reference if r.id not in used_ref]
    extra = [c for c in candidate if c.id not in used_cand]
    return mapping, missing, extra


@dataclass
class Comparison:
    """How close a candidate came, and where it went wrong."""

    ingredients_matched: int = 0
    ingredients_missing: list[str] = field(default_factory=list)
    ingredients_extra: list[str] = field(default_factory=list)
    steps_matched: int = 0
    steps_missing: list[str] = field(default_factory=list)
    steps_extra: list[str] = field(default_factory=list)
    edges_correct: list[str] = field(default_factory=list)
    edges_wrong: list[str] = field(default_factory=list)
    edges_absent: list[str] = field(default_factory=list)
    products_reference: int = 0
    products_candidate: int = 0
    constraints_found: int = 0
    constraints_reference: int = 0
    portions_found: int = 0
    portions_reference: int = 0

    @property
    def precision(self) -> float:
        claimed = len(self.edges_correct) + len(self.edges_wrong)
        return len(self.edges_correct) / claimed if claimed else 0.0

    @property
    def recall(self) -> float:
        total = len(self.edges_correct) + len(self.edges_absent)
        return len(self.edges_correct) / total if total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def report(self) -> str:
        lines = [
            f"ingredients   matched {self.ingredients_matched}"
            f"  missing {len(self.ingredients_missing)}"
            f"  spurious {len(self.ingredients_extra)}",
            f"steps         matched {self.steps_matched}"
            f"  missing {len(self.steps_missing)}"
            f"  spurious {len(self.steps_extra)}",
            f"edges         correct {len(self.edges_correct)}"
            f"  wrong {len(self.edges_wrong)}"
            f"  missed {len(self.edges_absent)}",
            f"              precision {self.precision:.0%}"
            f"  recall {self.recall:.0%}  F1 {self.f1:.0%}",
            f"products      {self.products_candidate} vs {self.products_reference} "
            "in the reference",
            f"constraints   {self.constraints_found} of {self.constraints_reference} found",
            f"portions      {self.portions_found} of {self.portions_reference} found",
        ]
        for name in self.ingredients_missing:
            lines.append(f"  MISSING INGREDIENT  {name}")
        for name in self.ingredients_extra:
            lines.append(f"  INVENTED INGREDIENT {name}")
        for edge in self.edges_wrong:
            lines.append(f"  WRONG LINK          {edge}")
        for edge in self.edges_absent:
            lines.append(f"  MISSED LINK         {edge}")
        return "\n".join(lines)


def compare(reference: Recipe, candidate: Recipe) -> Comparison:
    """Score ``candidate`` against a hand-authored ``reference``."""
    result = Comparison()

    ing_map, ing_missing, ing_extra = _align(
        reference.ingredients, candidate.ingredients,
        key=lambda i: f"{i.name} {i.original_text or ''}",
    )
    result.ingredients_matched = len(ing_map)
    result.ingredients_missing = [i.name for i in ing_missing]
    result.ingredients_extra = [i.name for i in ing_extra]

    step_map, step_missing, step_extra = _align(
        reference.steps, candidate.steps, key=lambda s: s.text,
    )
    result.steps_matched = len(step_map)
    result.steps_missing = [s.text[:60] for s in step_missing]
    result.steps_extra = [s.text[:60] for s in step_extra]

    # Edges, in reference terms. Only ingredient edges are scored: intermediate
    # products are named freely and comparing them would measure vocabulary
    # rather than structure.
    ref_ingredients = {i.id for i in reference.ingredients}
    reference_edges = {
        (ref, step.id)
        for step in reference.steps
        for ref in step.consumed_ids
        if ref in ref_ingredients
    }
    candidate_edges = set()
    for step in candidate.steps:
        mapped_step = step_map.get(step.id)
        if mapped_step is None:
            continue
        for ref in step.consumed_ids:
            mapped_ingredient = ing_map.get(ref)
            if mapped_ingredient is not None:
                candidate_edges.add((mapped_ingredient, mapped_step))

    names = {i.id: i.name for i in reference.ingredients}
    positions = {s.id: s.position for s in reference.steps}

    def describe(edge: tuple[str, str]) -> str:
        ingredient, step = edge
        return f"{names.get(ingredient, ingredient)} -> step {positions.get(step, '?')}"

    result.edges_correct = sorted(describe(e) for e in reference_edges & candidate_edges)
    result.edges_wrong = sorted(describe(e) for e in candidate_edges - reference_edges)
    result.edges_absent = sorted(describe(e) for e in reference_edges - candidate_edges)

    result.products_reference = sum(len(s.produces) for s in reference.steps)
    result.products_candidate = sum(len(s.produces) for s in candidate.steps)

    result.constraints_reference = sum(
        len(s.max_delay_after) + len(s.min_delay_after) + len(s.lead_before)
        for s in reference.steps
    )
    result.constraints_found = sum(
        len(s.max_delay_after) + len(s.min_delay_after) + len(s.lead_before)
        for s in candidate.steps
    )

    result.portions_reference = sum(
        1 for s in reference.steps for c in s.consumes if not c.portion.is_whole
    )
    result.portions_found = sum(
        1 for s in candidate.steps for c in s.consumes if not c.portion.is_whole
    )
    return result
