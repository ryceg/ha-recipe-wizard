"""Laying a dish out on paper.

The other renderer. ``render.py`` turns ``render.table()`` into fixed-width
characters for a terminal; this turns the same structure into points on a page,
and the two agree about what a recipe says because neither derives it -- see
``render.table`` for why that seam exists.

What earns its place on paper is not what earns its place on a screen. The
cook-along is left out entirely: it is stateless over a cursor and its whole
point is that something else holds which step you are on, which a sheet of paper
cannot. The plan, by contrast, gets *more* than the terminal gives it -- a bar
per step against a common timeline -- because the thing a cook wants off a
printed plan is the shape of the afternoon, and the shape is where the gaps are.

Everything is measured in points from the top-left; ``pdf.Page`` flips it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import pdf
from .dish import Dish
from .render import TableBlock, table
from .schedule import Plan, schedule
from .shopping import shopping_list_from_dish

MM = pdf.MM

# The page, and the frame the content sits in.
MARGIN_X = 18 * MM
MARGIN_TOP = 16 * MM
MARGIN_BOTTOM = 18 * MM

BODY = 9.0
LEADING = 11.5
SMALL = 7.5

# Column geometry, as offsets from the left margin. The procedure column takes
# whatever is left, which is what keeps the four columns adding up to the frame
# on any page size rather than only on A4.
NAME_W = 108.0
WEIGHT_W = 46.0
SCALE_W = 38.0
GUTTER = 8.0

GREY_RULE = 0.78
GREY_TEXT = 0.42

# Attention as ink. Darker means the cook is more tied to the kitchen, which
# makes the bar chart legible at a glance without a legend to read first.
_ATTENTION_GREY = {"active": 0.25, "passive": 0.55, "unattended": 0.78}


@dataclass(slots=True)
class _Frame:
    """The writable area of a page, and the cursor running down it."""

    page: pdf.Page
    y: float
    left: float
    right: float
    bottom: float
    title: str = ""
    """Stamped into the footer. Held per page because a book retitles itself at
    every recipe, and ``finish()`` runs once, at the end, when only the last one
    would still be assigned."""

    @property
    def width(self) -> float:
        return self.right - self.left

    def fits(self, height: float) -> bool:
        return self.y + height <= self.bottom


class _Layout:
    """A page factory that keeps the running header and footer consistent.

    Pagination lives here rather than in each section because every section
    needs the same three things -- start a page, know when the current one is
    full, and have the footer land in the same place on all of them -- and the
    version where each section did its own put the shopping list's footer four
    points higher than the table's.
    """

    def __init__(self, document: pdf.Document, title: str) -> None:
        self.document = document
        self.title = title
        self.frames: list[_Frame] = []

    @property
    def frame(self) -> _Frame:
        if not self.frames:
            self.new_page()
        return self.frames[-1]

    def new_page(self) -> _Frame:
        page = self.document.page()
        frame = _Frame(
            page=page,
            y=MARGIN_TOP,
            left=MARGIN_X,
            right=page.width - MARGIN_X,
            bottom=page.height - MARGIN_BOTTOM,
            title=self.title,
        )
        self.frames.append(frame)
        return frame

    def need(self, height: float) -> _Frame:
        """The frame with room for ``height``, starting a page if there is not."""
        frame = self.frame
        return frame if frame.fits(height) else self.new_page()

    def finish(self) -> None:
        """Stamp the footers, once the page count is finally known."""
        total = len(self.frames)
        for number, frame in enumerate(self.frames, start=1):
            page = frame.page
            y = page.height - MARGIN_BOTTOM + 12
            page.line(frame.left, y - 9, frame.right, y - 9,
                      width=0.4, grey=GREY_RULE)
            page.text(frame.left, y, frame.title, size=SMALL, grey=GREY_TEXT)
            page.text_right(frame.right, y, f"{number} of {total}",
                            size=SMALL, grey=GREY_TEXT)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def _heading(layout: _Layout, text: str, note: str = "") -> None:
    """A section rule. ``note`` rides on the right and is left alone -- it holds
    things like "x2", which the heading's own upper-casing turns into "X2"."""
    frame = layout.need(34)
    frame.y += 12
    frame.page.text(frame.left, frame.y, text.upper(),
                    font=pdf.HELVETICA_BOLD, size=9.5)
    if note:
        frame.page.text_right(frame.right, frame.y, note, size=SMALL,
                              grey=GREY_TEXT)
    frame.y += 5
    frame.page.line(frame.left, frame.y, frame.right, frame.y,
                    width=0.7, grey=0.35)
    frame.y += 13


def _title_block(layout: _Layout, dish: Dish) -> None:
    resolution = dish.resolution
    effective = resolution.recipe
    frame = layout.frame

    frame.y += 16
    for line in pdf.wrap(effective.name, pdf.HELVETICA_BOLD, 19, frame.width):
        frame.page.text(frame.left, frame.y, line,
                        font=pdf.HELVETICA_BOLD, size=19)
        frame.y += 22

    meta: list[str] = []
    if resolution.batch_yield_g:
        meta.append(f"Yield {resolution.batch_yield_g:.0f} g "
                    f"({effective.yield_basis})")
    if abs(resolution.scale - 1.0) > 1e-9:
        made = f", makes {resolution.produced_g:.0f} g" if resolution.produced_g else ""
        meta.append(f"Batch x{resolution.scale:g}{made}")
    for entry in effective.storage:
        keeps = entry.keeps.human() if entry.keeps else "unspecified"
        line = f"Keeps {keeps} {entry.method}"
        if entry.quality_window:
            line += f" (best {entry.quality_window.human()})"
        meta.append(line)
    for method in effective.unsuitable_for:
        meta.append(f"Not suitable for {method}")

    if meta:
        frame.y += 1
        for line in pdf.wrap(" • ".join(meta), pdf.HELVETICA, SMALL, frame.width):
            frame.page.text(frame.left, frame.y, line, size=SMALL, grey=GREY_TEXT)
            frame.y += 10
    if effective.url:
        frame.page.text(frame.left, frame.y, effective.url,
                        size=SMALL, grey=GREY_TEXT)
        frame.y += 10
    frame.y += 6


def _column_header(frame: _Frame) -> None:
    """The band, repeated at the top of every page the table runs onto."""
    frame.page.rect(frame.left, frame.y - 8, frame.width, 13, grey=0.91)
    name_x = frame.left
    weight_x = name_x + NAME_W + WEIGHT_W
    scale_x = weight_x + GUTTER + SCALE_W
    proc_x = scale_x + GUTTER + GUTTER
    frame.page.text(name_x + 2, frame.y, "INGREDIENT",
                    font=pdf.HELVETICA_BOLD, size=6.8)
    frame.page.text_right(weight_x, frame.y, "WEIGHT",
                          font=pdf.HELVETICA_BOLD, size=6.8)
    frame.page.text_right(scale_x, frame.y, "SCALING",
                          font=pdf.HELVETICA_BOLD, size=6.8)
    frame.page.text(proc_x, frame.y, "PROCEDURE",
                    font=pdf.HELVETICA_BOLD, size=6.8)
    frame.y += 13


def _table_section(layout: _Layout, dish: Dish) -> None:
    frame = layout.need(60)
    _column_header(frame)

    for block in table(dish.resolution):
        left, right = _block_lines(block, frame.width)
        rows = max(len(left), len(right))
        # A block is kept whole where a whole page could hold it. Splitting the
        # cake's aerated-egg-foam block puts its weights on one page and the
        # beating times on the next, which is the one pairing the layout exists
        # to make.
        block_height = rows * LEADING + (14 if block.result else 0) + 8
        if not frame.fits(block_height) and block_height < _usable(layout):
            frame = layout.new_page()
            _column_header(frame)

        for row in range(rows):
            if not frame.fits(LEADING):
                frame = layout.new_page()
                _column_header(frame)
            _draw_row(frame, left[row] if row < len(left) else None,
                      right[row] if row < len(right) else None)
            frame.y += LEADING

        if block.result:
            frame.y += 1
            frame.page.text_right(
                frame.left + NAME_W + WEIGHT_W + GUTTER + SCALE_W, frame.y,
                f"-> {block.result}", font=pdf.HELVETICA_BOLD, size=SMALL,
                grey=0.2,
            )
            frame.y += 10
        frame.y += 4
        frame.page.line(frame.left, frame.y, frame.right, frame.y,
                        width=0.4, grey=GREY_RULE)
        frame.y += 8


def _usable(layout: _Layout) -> float:
    page = layout.frame.page
    return page.height - MARGIN_TOP - MARGIN_BOTTOM - 26


def _block_lines(block: TableBlock, width: float):
    """Wrap both columns of one block, ready to be interleaved row by row."""
    proc_x = NAME_W + WEIGHT_W + GUTTER + SCALE_W + GUTTER + GUTTER
    proc_w = width - proc_x

    left: list[tuple[str, str, str]] = []
    for row in block.rows:
        chunks = pdf.wrap(row.label, pdf.HELVETICA, BODY, NAME_W - 4) or [""]
        for index, chunk in enumerate(chunks):
            if index == 0:
                left.append((chunk, row.weight, row.scaling))
            else:
                left.append((chunk, "", ""))

    right: list[str] = []
    for step in block.steps:
        marker = f"{step.position}."
        indent = pdf.text_width("00. ", pdf.HELVETICA, BODY)
        chunks = pdf.wrap(step.text, pdf.HELVETICA, BODY, proc_w - indent) or [""]
        for index, chunk in enumerate(chunks):
            right.append(f"{marker}\t{chunk}" if index == 0 else f"\t{chunk}")
    return left, right


def _draw_row(frame: _Frame, left, right) -> None:
    name_x = frame.left
    weight_x = name_x + NAME_W + WEIGHT_W
    scale_x = weight_x + GUTTER + SCALE_W
    proc_x = scale_x + GUTTER + GUTTER
    indent = pdf.text_width("00. ", pdf.HELVETICA, BODY)

    if left is not None:
        label, weight, scaling = left
        frame.page.text(name_x, frame.y, label, size=BODY)
        if weight:
            frame.page.text_right(weight_x, frame.y, weight, size=BODY)
        if scaling and scaling != "-":
            frame.page.text_right(scale_x, frame.y, scaling, size=BODY,
                                  grey=GREY_TEXT)
    if right is not None:
        marker, _, text = right.partition("\t")
        if marker:
            frame.page.text(proc_x, frame.y, marker, font=pdf.HELVETICA_BOLD,
                            size=BODY)
        frame.page.text(proc_x + indent, frame.y, text, size=BODY)


def _components_section(layout: _Layout, dish: Dish) -> None:
    nodes = list(dish.walk())[1:]
    unresolvable = [(node.label, use) for node in dish.walk()
                    for use in node.unresolvable]
    if not nodes and not unresolvable:
        return
    _heading(layout, "Components")

    for node in nodes:
        frame = layout.need(LEADING * 3)
        frame.page.text(frame.left, frame.y, node.resolution.summary(),
                        font=pdf.HELVETICA_BOLD, size=BODY)
        frame.y += LEADING
        for ingredient in node.resolution.ingredients:
            frame = layout.need(LEADING)
            frame.page.text(frame.left + 12, frame.y, str(ingredient), size=BODY)
            frame.y += LEADING
        for entry in node.resolution.change_log:
            frame = layout.need(LEADING)
            frame.page.text(frame.left + 12, frame.y, f"· {entry}",
                            size=SMALL, grey=GREY_TEXT)
            frame.y += LEADING - 2
        frame.y += 5

    for label, use in unresolvable:
        frame = layout.need(LEADING)
        frame.page.text(frame.left, frame.y, f"{label}: unresolvable", size=BODY)
        frame.y += LEADING


def _plan_section(layout: _Layout, plan: Plan) -> None:
    _heading(layout, "Plan")

    frame = layout.need(LEADING * 3)
    figures = [f"total {plan.total_s / 60:.0f} min",
               f"hands-on {plan.active_s / 60:.0f} min",
               f"hands-off {plan.unattended_s / 60:.0f} min"]
    if plan.waiting_s:
        figures.append(f"waiting {plan.waiting_s / 60:.0f} min")
    frame.page.text(frame.left, frame.y, "   ".join(figures),
                    font=pdf.HELVETICA_BOLD, size=BODY)
    frame.y += LEADING
    if plan.state_decided_s:
        frame.page.text(
            frame.left, frame.y,
            f"{plan.state_decided_s / 60:.0f} min of that is decided by a state, "
            f"not the clock", size=SMALL, grey=GREY_TEXT)
        frame.y += LEADING
    frame.y += 4

    # The chart. A bar per step against one timeline, which is the only view
    # that shows an enforced wait for what it is: an empty stretch nothing sits
    # on. The terminal's two columns of numbers make the cook do that in
    # their head.
    label_w = 104.0
    total = plan.total_s or 1.0
    chart_x = layout.frame.left + label_w
    chart_w = layout.frame.right - chart_x - 34

    for step in plan.steps:
        frame = layout.need(LEADING)
        page = frame.page
        page.text(frame.left, frame.y, step.step_id[:26], size=SMALL)
        x1 = chart_x + chart_w * (step.start_s / total)
        x2 = chart_x + chart_w * (step.end_s / total)
        grey = _ATTENTION_GREY.get(step.attention, 0.5)
        # A zero-length step still has to be visible, or the plan appears to
        # skip it: floor the bar at half a point rather than let it vanish.
        page.rect(x1, frame.y - 6, max(x2 - x1, 0.6), 7, grey=grey)
        page.text_right(frame.right, frame.y,
                        f"{step.start_s / 60:.0f}–{step.end_s / 60:.0f}",
                        size=6.8, grey=GREY_TEXT)
        frame.y += LEADING

    notes = [f"no pause allowed: {' -> '.join(chain)}"
             for chain in plan.rigid_chains]
    notes += [str(finding) for finding in plan.findings]
    if notes:
        frame = layout.need(LEADING * len(notes))
        frame.y += 4
        for note in notes:
            frame = layout.need(LEADING)
            frame.page.text(frame.left, frame.y, note, size=SMALL, grey=GREY_TEXT)
            frame.y += LEADING - 2

    # Doneness last, and only where there is some: a state is what actually ends
    # the step, and hanging it off the bar would have made every row two lines.
    checks = [(s.step_id, s.doneness) for s in plan.steps if s.doneness]
    if checks:
        frame = layout.need(LEADING * 2)
        frame.y += 8
        frame.page.text(frame.left, frame.y, "Then check",
                        font=pdf.HELVETICA_BOLD, size=SMALL)
        frame.y += LEADING
        for step_id, doneness in checks:
            wrapped = pdf.wrap(doneness, pdf.HELVETICA, SMALL,
                               layout.frame.width - label_w)
            frame = layout.need(LEADING * len(wrapped))
            frame.page.text(frame.left, frame.y, step_id[:26], size=SMALL,
                            grey=GREY_TEXT)
            for line in wrapped:
                frame.page.text(frame.left + label_w, frame.y, line, size=SMALL)
                frame.y += LEADING - 2


def _shopping_section(layout: _Layout, dish: Dish, *, include_optional: bool) -> None:
    listing = shopping_list_from_dish(dish, include_optional=include_optional)
    _heading(layout, "Shopping list", f"x{listing.scale:g}")

    for line in listing.lines:
        breakdown = line.breakdown() if len(line.contributions) > 1 else []
        frame = layout.need(LEADING * (1 + len(breakdown)))
        # A tick box, because this is a list to walk a shop with.
        page = frame.page
        page.line(frame.left, frame.y - 6.5, frame.left + 7, frame.y - 6.5,
                  width=0.5, grey=0.55)
        page.line(frame.left, frame.y, frame.left + 7, frame.y,
                  width=0.5, grey=0.55)
        page.line(frame.left, frame.y - 6.5, frame.left, frame.y,
                  width=0.5, grey=0.55)
        page.line(frame.left + 7, frame.y - 6.5, frame.left + 7, frame.y,
                  width=0.5, grey=0.55)
        page.text(frame.left + 14, frame.y, line.describe(), size=BODY)
        frame.y += LEADING
        for entry in breakdown:
            frame.page.text(frame.left + 24, frame.y, entry, size=SMALL,
                            grey=GREY_TEXT)
            frame.y += LEADING - 2
        frame.y += 2

    for cited in listing.to_find:
        frame = layout.need(LEADING)
        frame.page.text(frame.left + 14, frame.y, cited.describe(), size=BODY,
                        grey=GREY_TEXT)
        frame.y += LEADING


# ---------------------------------------------------------------------------
# The public surface
# ---------------------------------------------------------------------------


def dish_pdf(
    dish: Dish,
    *,
    components: bool = False,
    plan: bool = False,
    shopping: bool = False,
    include_optional: bool = True,
    size: tuple[float, float] = pdf.A4,
) -> bytes:
    """One dish as a PDF, with the sections the caller asked for.

    The flags mirror the CLI's, and deliberately: ``--components --plan`` and
    ``--components --plan --pdf`` should not be two different ideas of what you
    asked to see. The table is not a flag because a recipe without it is not a
    recipe.
    """
    document = pdf.Document(size, title=dish.resolution.recipe.name)
    layout = _Layout(document, dish.resolution.recipe.name)
    _title_block(layout, dish)
    _table_section(layout, dish)
    if components:
        _components_section(layout, dish)
    if plan:
        _plan_section(layout, schedule(dish.resolution))
    if shopping:
        _shopping_section(layout, dish, include_optional=include_optional)
    layout.finish()
    return document.render()


def library_pdf(
    dishes: list[Dish],
    *,
    components: bool = False,
    plan: bool = False,
    shopping: bool = False,
    include_optional: bool = True,
    size: tuple[float, float] = pdf.A4,
    title: str = "Recipes",
) -> bytes:
    """Every dish as one book, each starting on a fresh page.

    Sharing ``_Layout`` across the whole run rather than concatenating
    single-recipe documents is what makes "3 of 24" true. Concatenation would
    also have meant re-deriving every page's footer after the fact, which is the
    one thing ``_Layout.finish`` exists to avoid.
    """
    document = pdf.Document(size, title=title)
    layout = _Layout(document, title)
    for index, dish in enumerate(dishes):
        if index:
            layout.new_page()
        layout.title = dish.resolution.recipe.name
        _title_block(layout, dish)
        _table_section(layout, dish)
        if components:
            _components_section(layout, dish)
        if plan:
            _plan_section(layout, schedule(dish.resolution))
        if shopping:
            _shopping_section(layout, dish, include_optional=include_optional)
    layout.finish()
    return document.render()
