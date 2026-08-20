"""The PDF surface: the writer underneath it, and what reaches the page.

The assertions read the text back out of the content stream, which is only
possible because ``pdf.py`` leaves it uncompressed -- see its module docstring
for why that trade was made deliberately.
"""

import re

import pytest
from conftest import BROWNIES, CAKE, COFFEE_BC

from custom_components.recipe_wizard.core import pdf
from custom_components.recipe_wizard.core.dish import resolve_dish
from custom_components.recipe_wizard.core.printing import dish_pdf, library_pdf
from custom_components.recipe_wizard.core.render import table

_ESCAPED = re.compile(rb"\\(.)")


def pages(data: bytes) -> list[str]:
    """The text drawn on each page, in the order it was drawn."""
    out = []
    for stream in re.findall(rb"stream\n(.*?)\nendstream", data, re.S):
        drawn = []
        for raw in re.findall(rb"\((.*?)\) Tj", stream, re.S):
            drawn.append(_ESCAPED.sub(rb"\1", raw).decode("cp1252"))
        out.append("\n".join(drawn))
    return out


def whole(data: bytes) -> str:
    return "\n".join(pages(data))


@pytest.fixture
def cake_dish(library):
    return resolve_dish(library, CAKE, strict=False)


@pytest.fixture
def brownie_dish(library):
    return resolve_dish(library, BROWNIES, strict=False)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "font, char, expected",
    [
        # Published Helvetica AFM values. The table in pdf.py was extracted from
        # Arial, which shares them by design; this is the guard against it being
        # edited by hand or regenerated from a font that only looks similar.
        (pdf.HELVETICA, " ", 278), (pdf.HELVETICA, "A", 667),
        (pdf.HELVETICA, "a", 556), (pdf.HELVETICA, "i", 222),
        (pdf.HELVETICA, "M", 833), (pdf.HELVETICA, "W", 944),
        (pdf.HELVETICA, "%", 889), (pdf.HELVETICA, ".", 278),
        (pdf.HELVETICA_BOLD, " ", 278), (pdf.HELVETICA_BOLD, "A", 722),
        (pdf.HELVETICA_BOLD, "i", 278), (pdf.HELVETICA_BOLD, "W", 944),
    ],
)
def test_the_width_table_matches_the_published_helvetica_metrics(font, char, expected):
    assert pdf.text_width(char, font, 1000) == pytest.approx(expected)


def test_wrapping_measures_the_font_and_not_the_character_count():
    """The reason the table exists at all: sixteen 'M's are nearly four times
    the width of sixteen 'i's, and a column that wraps on character count fits
    one of them and overflows the other."""
    narrow = pdf.text_width("i" * 16, pdf.HELVETICA, 10)
    wide = pdf.text_width("M" * 16, pdf.HELVETICA, 10)
    assert wide > narrow * 3


def test_a_word_too_wide_for_its_column_is_left_whole():
    """Not hyphenated and not broken. A mid-word break in a quantity or a
    chemical name reads as a mistake in the food."""
    lines = pdf.wrap("supercalifragilistic", pdf.HELVETICA, 10, 20)
    assert lines == ["supercalifragilistic"]


def test_wrapping_never_returns_a_line_wider_than_the_column():
    text = "beat the eggs for seven minutes until tripled in volume and pale"
    for line in pdf.wrap(text, pdf.HELVETICA, 9, 120):
        assert pdf.text_width(line, pdf.HELVETICA, 9) <= 120


def test_the_punctuation_a_scrape_arrives_with_survives_the_encoding():
    """Curly quotes and en-dashes are what a web import is full of, and WinAnsi
    carries all of them -- in the 0x80 block Latin-1 leaves empty."""
    assert pdf.encode("’") == b"\x92"
    assert pdf.encode("“”") == b"\x93\x94"
    assert pdf.encode("–") == b"\x96"
    assert pdf.encode("café") == b"caf\xe9"


def test_a_glyph_winansi_cannot_carry_is_spelled_out_rather_than_lost():
    """The arrow closing a table block is the live case: it was drawn as '?'
    against every result the recipe produces."""
    assert pdf.encode("→ Dry mix") == b"-> Dry mix"
    assert pdf.encode("⅓ cup") == b"1/3 cup"


def test_an_unrepresentable_character_still_measures_as_what_is_drawn():
    """It comes out as '?', so charging it '?' is the honest width."""
    assert pdf.text_width("中", pdf.HELVETICA, 10) == pytest.approx(
        pdf.text_width("?", pdf.HELVETICA, 10)
    )


def test_a_string_carrying_pdf_syntax_does_not_break_the_file():
    document = pdf.Document()
    document.page().text(10, 10, "Grease 2 x 20cm (8\") pans \\ then line them")
    data = document.render()
    assert whole(data) == 'Grease 2 x 20cm (8") pans \\ then line them'


def test_the_cross_reference_table_points_at_every_object(cake_dish):
    """A viewer follows these byte offsets to find anything at all, so an off-by-
    one here is a file that opens as blank rather than as slightly wrong."""
    data = dish_pdf(cake_dish, plan=True, shopping=True)
    start = int(data[data.rindex(b"startxref") + 9:].split()[0])
    rows = data[start:].split(b"\n")
    count = int(rows[1].split()[1])
    for number, row in enumerate(rows[2:2 + count]):
        if number == 0:  # the free head of the chain
            continue
        offset = int(row.split()[0])
        assert data[offset:].startswith(b"%d 0 obj" % number)


# ---------------------------------------------------------------------------
# What reaches the page
# ---------------------------------------------------------------------------


def test_every_step_of_the_recipe_reaches_the_page(cake_dish):
    """Wrapping breaks step text across lines, so this checks the words are all
    there rather than the sentences -- a step dropped by pagination loses its
    words too."""
    drawn = whole(dish_pdf(cake_dish)).replace("\n", " ")
    for step in cake_dish.resolution.recipe.steps:
        for word in step.text.split():
            assert word in drawn, f"{step.id}: {word!r}"


def test_the_weight_column_says_what_the_text_table_says(cake_dish):
    """Both renderers read ``render.table``. If they ever disagree about a mass,
    it is because one of them started deriving its own."""
    drawn = whole(dish_pdf(cake_dish))
    for block in table(cake_dish.resolution):
        for row in block.rows:
            if row.weight != "-":
                assert row.weight in drawn


def test_a_component_is_named_on_the_page_but_carries_no_weight(cake_dish):
    """The buttercream is a use of a sub-recipe, not an ingredient with a mass,
    and a table that gave it one would be inventing it."""
    rows = [row for block in table(cake_dish.resolution)
            for row in block.rows if row.is_component]
    assert rows, "the cake has a component"
    assert all(row.weight == "-" for row in rows)
    # The label wraps inside the narrow name column, so it reaches the page as
    # words rather than as one string.
    drawn = whole(dish_pdf(cake_dish)).replace("\n", " ")
    assert "Vanilla" in drawn and "buttercream" in drawn and "(sub-recipe)" in drawn


def test_a_variant_prints_the_steps_it_inherited(library):
    """The same defect ``schedule`` had: a variant's own document is a patch
    list, so printing it off disk would be a title and an empty table."""
    drawn = whole(dish_pdf(resolve_dish(library, COFFEE_BC, strict=False)))
    assert "Cream butter" in drawn.replace("\n", " ")
    assert "espresso concentrate" in drawn


def test_the_plan_section_reports_the_wait_the_cook_has_to_plan_around(
    brownie_dish,
):
    """The brownies' chill is 195 of their 420 minutes and belongs to neither
    attention class -- see ``schedule._wall_clock_split``."""
    drawn = whole(dish_pdf(brownie_dish, plan=True))
    assert "waiting 195 min" in drawn
    assert "total 420 min" in drawn


def test_the_shopping_list_merges_on_the_page_as_it_does_in_the_report(cake_dish):
    """One line per food, with the two recipes wanting butter shown under it."""
    drawn = whole(dish_pdf(cake_dish, shopping=True))
    assert "unsalted butter: 340 g" in drawn
    assert "225 g - Vanilla buttercream" in drawn


def test_asking_for_nothing_but_the_table_prints_nothing_but_the_table(cake_dish):
    drawn = whole(dish_pdf(cake_dish))
    assert "PLAN" not in drawn
    assert "SHOPPING LIST" not in drawn


def test_the_scale_in_a_heading_is_not_upper_cased_with_it(library):
    """``x2`` became ``X2``, which is not how the rest of the project writes a
    batch and reads as a different thing entirely."""
    doubled = resolve_dish(library, CAKE, batches=2.0, strict=False)
    drawn = whole(dish_pdf(doubled, shopping=True))
    assert "x2" in drawn
    assert "X2" not in drawn


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_every_page_is_numbered_out_of_the_true_total(cake_dish):
    data = dish_pdf(cake_dish, components=True, plan=True, shopping=True)
    drawn = pages(data)
    assert len(drawn) > 1
    for number, page in enumerate(drawn, start=1):
        assert f"{number} of {len(drawn)}" in page


def test_the_column_header_repeats_on_every_page_the_table_runs_onto(brownie_dish):
    """A page of weights with no column telling you they are weights."""
    data = dish_pdf(brownie_dish)
    for page in pages(data):
        if "PROCEDURE" not in page:
            continue
        assert "INGREDIENT" in page and "WEIGHT" in page


def test_the_book_numbers_pages_across_the_library_not_within_each_recipe(library):
    """Concatenating single-recipe documents would give every recipe its own
    "1 of 2", which is the reason ``library_pdf`` shares one layout."""
    dishes = [resolve_dish(library, r.id, strict=False)
              for r in sorted(library, key=lambda r: r.name)]
    drawn = pages(library_pdf(dishes))
    assert len(drawn) >= len(dishes)
    assert f"{len(drawn)} of {len(drawn)}" in drawn[-1]
    assert "1 of 1" not in drawn[0]


def test_each_recipe_in_the_book_starts_its_own_page(library):
    dishes = [resolve_dish(library, r.id, strict=False)
              for r in sorted(library, key=lambda r: r.name)]
    drawn = pages(library_pdf(dishes))
    starts = [page for page in drawn if "INGREDIENT" in page]
    assert len(starts) >= len(dishes)
    for dish in dishes:
        name = dish.resolution.recipe.name
        assert any(name in page for page in drawn), name


def test_the_footer_names_the_recipe_the_page_is_actually_about(library):
    """It used to name whichever recipe was last, because the footers are
    stamped after the fact and the title had moved on."""
    dishes = [resolve_dish(library, r.id, strict=False)
              for r in sorted(library, key=lambda r: r.name)][:2]
    drawn = pages(library_pdf(dishes))
    first, last = dishes[0].resolution.recipe.name, dishes[-1].resolution.recipe.name
    assert first != last
    assert first in drawn[0]
