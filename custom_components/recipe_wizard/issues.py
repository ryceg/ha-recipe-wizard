"""Telling a cook that one of their recipes is broken, once, where they will see it.

Gold ``repair-issues``. The library already knows: ``core/validate.py`` is the
contract the enrichment loop iterates against, and it produces a ``Finding`` for
every defect it can name. Until this module existed none of that reached a user
who was not running ``python -m recipe_wizard --validate`` on a terminal -- a
recipe with a dangling ``rw:consumes`` would simply not appear in a cook-along,
and the explanation was in a report nobody had asked for.

**Only errors, never warnings.** This is the whole of the design and it is worth
being blunt about, because the tempting version of this module raises a repair for
every finding and would be worse than nothing. A warning in this project is
frequently the *correct* outcome: ``docs/format.md`` says a document must refuse
to guess, so a source that genuinely says "a splash of milk" leaves an
``unresolved-mass`` warning behind for ever, and a scraped level-0 document is
supposed to read as a scrape. A repair the user cannot make go away is a repair
they learn to dismiss, and the next one -- the real one -- gets dismissed with it.
``Finding.level`` is the producer's decision (``validate.py``, ``schedule.py``,
``resolve.py``, ``mass.py`` each set their own), so this module reads it and does
not second-guess it.

**One issue per document, not per finding.** A half-enriched recipe reports five
findings that are one afternoon's work on one file; five cards in the repairs
panel would say five problems. The issue names the recipe, and its description
lists every node a fix goes on -- which is what ``Finding.node`` is for, and why
it is canonical under ``graph.py``'s id rule: the ids in the card can be pasted
straight back into the document.

**Not fixable, deliberately.** ``is_fixable=False`` means the card explains and
does not offer a button. There is nothing Home Assistant could do: the fix is an
edit to a JSON document that the integration only ever reads (``docs/format.md``,
and the removal instructions promise it in so many words). A fix flow would have
to either write to the user's recipes or apologise, and a module named
``repairs.py`` is Home Assistant's platform contract for the flow we are not
offering -- hence this file's name, which keeps the repairs platform from being
loaded and logging that we did not implement it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .core.library import Library
from .core.validate import ERROR, Finding, validate_library

_LOGGER = logging.getLogger(__name__)

#: What every issue this module raises is filed under. A prefix rather than a
#: bare recipe id so that the sweep below can tell its own issues from any other
#: kind this integration might raise later, and delete only the ones it owns.
ISSUE_PREFIX = "invalid_recipe_"

#: The translation key in ``strings.json``. One key for every document, because
#: the sentence is the same one -- what differs is the list of findings, which
#: goes into a placeholder.
TRANSLATION_KEY = "invalid_recipe"


@dataclass(frozen=True, slots=True)
class BrokenDocument:
    """One document the validator reports errors on, and what to call it.

    ``label`` is separate from ``document`` because a repair card is read in a
    kitchen. ``Finding.recipe`` is an ``@id`` -- ``urn:recipe:rte/vanilla-cake``
    -- which is the right thing to *grep* for and the wrong thing to lead a
    notification with, so the card's title says "Vanilla cake" and its body says
    the id. Where the library has no document under that id (a family naming a
    member that is not there), the two are the same string, and saying it twice
    is better than inventing a name.
    """

    document: str
    label: str
    findings: tuple[Finding, ...]


def error_findings(library: Library) -> dict[str, BrokenDocument]:
    """Every document with at least one *error*, and the errors it has.

    Blocking: ``validate_library`` materialises the variant chain and builds a
    mass table for every recipe. Call it through ``hass.async_add_executor_job``.

    Grouped on ``Finding.recipe`` rather than on the library's own iteration
    order, because two of the rules in ``validate_library`` file a finding under
    a *family's* id -- the family is the document that is wrong when it names a
    member that does not exist -- and those deserve a card as much as any recipe
    does. Which is also why the label is looked up in both indexes.
    """
    grouped: dict[str, list[Finding]] = {}
    for finding in validate_library(library):
        if finding.level == ERROR:
            grouped.setdefault(finding.recipe, []).append(finding)
    return {
        document: BrokenDocument(document, _label(library, document), tuple(findings))
        for document, findings in grouped.items()
    }


def _label(library: Library, document: str) -> str:
    """The document's own name, falling back to its id."""
    known = library.recipes.get(document) or library.families.get(document)
    return known.name if known is not None and known.name else document


def describe(findings: tuple[Finding, ...]) -> str:
    """The findings as Markdown for the card, one line each, node first.

    The node leads because it is the thing the reader has to go and find in the
    file, and the stable code trails because it is what an issue report should
    quote. This is deliberately not ``str(Finding)``: that line is padded for a
    terminal column and carries a severity that is ``error`` on every line here.
    """
    lines: list[str] = []
    for finding in findings:
        where = f"`{finding.node}` — " if finding.node else ""
        lines.append(f"- {where}{finding.message} (`{finding.code}`)")
    return "\n".join(lines)


def async_reconcile_issues(
    hass: HomeAssistant, broken: dict[str, BrokenDocument]
) -> None:
    """Raise a card for every broken document, and withdraw the rest.

    Called after every *successful* reload, which is the only moment the answer
    can have changed: the coordinator only reparses when a file's mtime has
    moved, so an unchanged library costs nothing here either.

    The withdrawal half matters as much as the raising half. A cook fixes a
    recipe, the poll picks the file up within fifteen minutes, and the card has to
    go on its own -- a repair that outlives its cause is how the panel becomes
    something people stop reading. The set of live issues is read back out of the
    registry rather than remembered in this process, so a reloaded entry does not
    strand the previous coordinator's cards.
    """
    wanted = {f"{ISSUE_PREFIX}{document}" for document in broken}
    for issue_id in _live_issue_ids(hass) - wanted:
        ir.async_delete_issue(hass, DOMAIN, issue_id)

    for document in broken.values():
        ir.async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_PREFIX}{document.document}",
            is_fixable=False,
            # Not persistent: it is recomputed from the documents on the first
            # refresh after every restart, so storing it would only risk showing
            # a card for a recipe the user fixed while Home Assistant was down.
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=TRANSLATION_KEY,
            translation_placeholders={
                "name": document.label,
                "recipe": document.document,
                "findings": describe(document.findings),
            },
        )
    if broken:
        _LOGGER.debug(
            "%d recipe(s) have validation errors: %s",
            len(broken),
            ", ".join(sorted(broken)),
        )


def async_clear_issues(hass: HomeAssistant) -> None:
    """Withdraw every card this module raised.

    For entry *removal* only. Nothing in Home Assistant sweeps an integration's
    issues when it is deleted, and a card about a recipe belonging to an
    integration the user has just removed is a puzzle with no way to act on it.
    Unloading is deliberately not a caller: a reload unloads and sets up again,
    and clearing there would blink every card off and back on.
    """
    for issue_id in _live_issue_ids(hass):
        ir.async_delete_issue(hass, DOMAIN, issue_id)


def _live_issue_ids(hass: HomeAssistant) -> set[str]:
    """The issue ids this module currently owns, read off the registry.

    Read back rather than remembered in this process, so that a reloaded entry --
    which builds a new coordinator with no memory of what the last one raised --
    still withdraws cards that are no longer true.
    """
    return {
        issue_id
        for domain, issue_id in ir.async_get(hass).issues
        if domain == DOMAIN and issue_id.startswith(ISSUE_PREFIX)
    }
