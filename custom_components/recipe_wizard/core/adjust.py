"""Typed patch operations against a base recipe.

A variant is base + an ordered list of operations, never a copy. Copying is how
a fix to the base silently fails to reach the twelve forks of it.

Every operation targets a stable ``@id`` in the base, which is why base recipes
must use semantic ids (``#sugar``, ``#whip-to-emulsion``) and never positional
ones (``#step-3``). An unresolvable target raises rather than being skipped, so
deleting ``#vanilla`` from a base fails loudly at validation time instead of
quietly at dinner time.
"""

from __future__ import annotations

from .model import Adjustment, Ingredient, Recipe, Step, _as_list, _get
from .units import Quantity


class AdjustmentError(ValueError):
    """A patch could not be applied — usually a target that no longer exists."""


def _require_target(recipe: Recipe, adj: Adjustment) -> str:
    if not adj.target:
        raise AdjustmentError(f"{adj.op} needs a target")
    return adj.target


def _apply_quantities(ing: Ingredient, node: dict) -> None:
    """Overwrite whichever measures the patch supplies, leave the rest alone."""
    for attr, key in (("mass", "mass"), ("volume", "volume"), ("count", "count")):
        value = _get(node, key)
        if value is not None:
            setattr(ing, attr, Quantity.from_jsonld(value))


def apply_adjustments(
    recipe: Recipe, adjustments: list[Adjustment]
) -> tuple[Recipe, list[str]]:
    """Apply operations in order, returning a new recipe and a change log."""
    result = recipe.copy()
    log: list[str] = []

    for adj in adjustments:
        op = adj.op
        node = adj.payload

        if op == "Add":
            ing_node = _get(node, "ingredient")
            if ing_node is None:
                raise AdjustmentError("Add needs an 'ingredient'")
            ing = Ingredient.parse(ing_node)
            if result.ingredient(ing.id):
                raise AdjustmentError(f"Add: {ing.id!r} already exists")
            result.ingredients.append(ing)
            log.append(f"added {ing.name}")

        elif op == "Remove":
            target = _require_target(result, adj)
            ing = result.ingredient(target)
            if ing is None:
                raise AdjustmentError(f"Remove: no ingredient {target!r}")
            result.ingredients.remove(ing)
            log.append(f"removed {ing.name}")

        elif op == "Replace":
            target = _require_target(result, adj)
            ing = result.ingredient(target)
            if ing is None:
                raise AdjustmentError(f"Replace: no ingredient {target!r}")
            with_node = _get(node, "with")
            if with_node is None:
                raise AdjustmentError("Replace needs a 'with'")
            replacement = Ingredient.parse(with_node)
            # Keep the original id so anything already pointing at it still works.
            replacement.id = ing.id
            if not replacement.name:
                replacement.name = ing.name
            index = result.ingredients.index(ing)
            result.ingredients[index] = replacement
            log.append(f"replaced {ing.name} with {replacement.name}")

        elif op == "SetQuantity":
            target = _require_target(result, adj)
            ing = result.ingredient(target)
            if ing is None:
                raise AdjustmentError(f"SetQuantity: no ingredient {target!r}")
            scale_by = _get(node, "scaleBy")
            if scale_by is not None:
                factor = float(scale_by)
                for attr in ("mass", "volume", "count"):
                    q = getattr(ing, attr)
                    if q is not None:
                        setattr(ing, attr, q.scaled(factor))
                log.append(f"scaled {ing.name} by {factor:g}x")
            else:
                _apply_quantities(ing, node)
                log.append(f"set {ing.name} to {ing.mass or ing.volume or ing.count}")
            note = _get(node, "note")
            if note:
                ing.note = note

        elif op == "AmendStep":
            target = _require_target(result, adj)
            step = result.step(target)
            if step is None:
                raise AdjustmentError(f"AmendStep: no step {target!r}")
            append = _get(node, "append")
            prepend = _get(node, "prepend")
            if append:
                step.text = f"{step.text.rstrip()} {append}".strip()
            if prepend:
                step.text = f"{prepend} {step.text.lstrip()}".strip()
            if not append and not prepend:
                raise AdjustmentError("AmendStep needs an 'append' or a 'prepend'")
            log.append(f"amended {step.id}")

        elif op == "ReplaceStep":
            target = _require_target(result, adj)
            step = result.step(target)
            if step is None:
                raise AdjustmentError(f"ReplaceStep: no step {target!r}")
            text = _get(node, "text")
            if text is None:
                raise AdjustmentError("ReplaceStep needs a 'text'")
            step.text = text
            log.append(f"replaced text of {step.id}")

        elif op == "InsertStep":
            step_node = _get(node, "step")
            if step_node is None:
                raise AdjustmentError("InsertStep needs a 'step'")
            after = _get(node, "after")
            new_step = Step.parse(step_node, len(result.steps) + 1)
            if after:
                anchor = result.step(after if isinstance(after, str) else after.get("@id"))
                if anchor is None:
                    raise AdjustmentError(f"InsertStep: no step {after!r} to insert after")
                index = result.steps.index(anchor) + 1
            else:
                index = len(result.steps)
            result.steps.insert(index, new_step)
            _renumber(result)
            log.append(f"inserted {new_step.id}")

        elif op == "Set":
            prop = _get(node, "property")
            value = _get(node, "value")
            if not prop:
                raise AdjustmentError("Set needs a 'property'")
            if not hasattr(result, prop):
                raise AdjustmentError(f"Set: {prop!r} is not a recipe property")
            setattr(result, prop, value)
            log.append(f"set {prop} to {value!r}")

        else:
            raise AdjustmentError(f"unknown adjustment operation {op!r}")

    return result, log


def _renumber(recipe: Recipe) -> None:
    """Recompute display positions. Ids are stable; positions never are."""
    for index, step in enumerate(recipe.steps, start=1):
        step.position = index


def apply_parameters(
    recipe: Recipe, selections: dict[str, str]
) -> tuple[Recipe, list[str]]:
    """Apply parameter selections, which are themselves expressed as patches.

    Parameters cover variation the base author anticipated; patches cover the
    rest. Both end up here because an option is just a bundle of operations.
    """
    result = recipe
    log: list[str] = []
    for param in recipe.parameters:
        chosen = selections.get(param.id) or selections.get(param.name) or param.default
        if chosen is None:
            continue
        option = None
        for candidate in param.options:
            if candidate.get("@id") == chosen or candidate.get("name") == chosen:
                option = candidate
                break
        if option is None:
            available = [c.get("@id") or c.get("name") for c in param.options]
            raise AdjustmentError(
                f"parameter {param.name!r} has no option {chosen!r} "
                f"(available: {', '.join(str(a) for a in available)})"
            )
        ops = [Adjustment.parse(a) for a in _as_list(_get(option, "apply"))]
        result, sub_log = apply_adjustments(result, ops)
        log.append(f"{param.name} = {option.get('name', chosen)}")
        log.extend(f"  {entry}" for entry in sub_log)
    return result, log
