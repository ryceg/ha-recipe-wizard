"""Writing PDF files with nothing but the standard library.

The integration ships through HACS with an empty ``requirements``, and the
library underneath it has no dependencies at all -- that is the whole reason
``core/`` can be imported by the CLI and by the whole library suite without a
300 MB install.
A PDF surface is not worth reversing that for, so this module writes the format
directly. It is a *small* subset: uncompressed content streams, the base-14
fonts, no images, no transparency, no outlines. That is the entire vocabulary a
recipe needs.

The two facts that make it tractable:

* the base-14 fonts need no ``/Widths`` array and no font file, because every
  viewer already has their metrics -- so the widths below exist only for *this*
  module's own line-breaking, and never reach the file;
* streams are left uncompressed. A recipe is a few kilobytes either way, and an
  inspectable content stream is the difference between a test that asserts on
  the drawing and a test that asserts on a zlib blob.

Coordinates are given **top-left down**, which is not what PDF uses. Every
public method flips into PDF's bottom-left space on the way out. Laying a page
out downwards from a running ``y`` cursor is how the layout code thinks, and
making each caller subtract from the page height is how a footer ends up half an
inch off in one place and not another.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Millimetres to points, and the page sizes worth naming.
MM = 72.0 / 25.4
A4 = (210.0 * MM, 297.0 * MM)
LETTER = (8.5 * 72.0, 11.0 * 72.0)

HELVETICA = "Helvetica"
HELVETICA_BOLD = "Helvetica-Bold"

# Advance widths in 1/1000 em for byte values 32..255 under WinAnsiEncoding,
# extracted from the Arial metrics that Helvetica's AFM shares by design and
# spot-checked against the published AFM values -- see
# ``tests/test_pdf.py::test_the_width_table_matches_the_published_helvetica_metrics``,
# which is the guard against this block being edited by hand. A 0 is a byte
# WinAnsi leaves undefined; it measures as ``_MISSING`` like anything else the
# encoding cannot represent.
_WIDTHS: dict[str, tuple[int, ...]] = {
    HELVETICA: (
        278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
        1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
        667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
        333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
        556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 750,
        556, 0, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0,
        0, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 0, 500, 667,
        278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 552,
        400, 549, 333, 333, 333, 576, 537, 333, 333, 333, 365, 556, 834, 834, 834, 611,
        667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
        722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
        556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 549, 611, 556, 556, 556, 556, 500, 556, 500,
    ),
    HELVETICA_BOLD: (
        278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
        556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611,
        975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
        667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
        333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611,
        611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 750,
        556, 0, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0, 611, 0,
        0, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 0, 500, 667,
        278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 552,
        400, 549, 333, 333, 333, 576, 556, 333, 333, 333, 365, 556, 834, 834, 834, 611,
        722, 722, 722, 722, 722, 722, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278,
        722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611,
        556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278,
        611, 611, 611, 611, 611, 611, 611, 549, 611, 611, 611, 611, 611, 556, 611, 556,
    ),
}

_MISSING = 556
"""Width charged to a byte WinAnsi has no glyph for. It is drawn as '?', which
is 556 wide in both faces, so the measurement is not an approximation."""

# The CP1252 punctuation that Latin-1 leaves empty. Recipes scraped off the web
# are full of curly quotes and en-dashes, and encoding them as '?' would be a
# visible defect on the most ordinary import.
_CP1252 = {
    0x20AC: 0x80, 0x201A: 0x82, 0x0192: 0x83, 0x201E: 0x84, 0x2026: 0x85,
    0x2020: 0x86, 0x2021: 0x87, 0x02C6: 0x88, 0x2030: 0x89, 0x0160: 0x8A,
    0x2039: 0x8B, 0x0152: 0x8C, 0x017D: 0x8E, 0x2018: 0x91, 0x2019: 0x92,
    0x201C: 0x93, 0x201D: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97,
    0x02DC: 0x98, 0x2122: 0x99, 0x0161: 0x9A, 0x203A: 0x9B, 0x0153: 0x9C,
    0x017E: 0x9E, 0x0178: 0x9F,
}

# Characters worth spelling out rather than losing to '?'. Fraction glyphs are
# the ones that matter: a scraped recipe says "1 1/2 cups" with a single glyph
# and WinAnsi only carries three of them.
_TRANSLITERATE = {
    "⅓": "1/3", "⅔": "2/3", "⅕": "1/5", "⅖": "2/5",
    "⅗": "3/5", "⅘": "4/5", "⅙": "1/6", "⅚": "5/6",
    "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
    "−": "-", "‐": "-", "‑": "-", " ": " ",
    " ": " ", " ": " ", "⁄": "/",
    # WinAnsi has no arrow at all, and the text renderer spells this one
    # "->" anyway -- a reader holding the print next to the terminal should
    # see the same token where a block says what it produces, not a '?'.
    "→": "->", "⟶": "->", "←": "<-", "⇒": "=>",
}


def encode(text: str) -> bytes:
    """Text to WinAnsi bytes, losing as little as the encoding allows."""
    out = bytearray()
    for char in text:
        replacement = _TRANSLITERATE.get(char)
        if replacement is not None:
            out.extend(replacement.encode("latin-1"))
            continue
        point = ord(char)
        if point < 0x100 and not 0x80 <= point <= 0x9F:
            out.append(point)
        elif point in _CP1252:
            out.append(_CP1252[point])
        else:
            out.append(ord("?"))
    return bytes(out)


def text_width(text: str, font: str, size: float) -> float:
    """Width of ``text`` in points, measured the way the viewer will set it."""
    table = _WIDTHS[font]
    total = 0
    for byte in encode(text):
        width = table[byte - 32] if 32 <= byte <= 255 else 0
        total += width or _MISSING
    return total * size / 1000.0


def wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Break ``text`` into lines no wider than ``width`` points.

    Greedy, on spaces, and it does not hyphenate. A single word too long for the
    column is left to overflow rather than broken: recipes reach that case with
    URLs and chemical names, and a silent mid-word break reads as a typo in the
    food.
    """
    if not text:
        return [""]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if text_width(candidate, font, size) <= width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _pdf_string(text: str) -> bytes:
    r"""A literal string, with the three bytes PDF reads as syntax escaped."""
    out = bytearray(b"(")
    for byte in encode(text):
        if byte in (0x28, 0x29, 0x5C):  # ( ) \
            out.append(0x5C)
        out.append(byte)
    out.append(0x29)
    return bytes(out)


@dataclass(slots=True)
class Page:
    """One page, accumulating drawing operators in top-left coordinates."""

    width: float
    height: float
    _ops: list[bytes] = field(default_factory=list)

    def text(
        self,
        x: float,
        y: float,
        content: str,
        *,
        font: str = HELVETICA,
        size: float = 10.0,
        grey: float = 0.0,
    ) -> None:
        """Draw one line, with ``y`` the **baseline** measured from the top."""
        if not content:
            return
        self._ops.append(
            b"BT " + _name(font) + b" %.2f Tf %.3f g 1 0 0 1 %.2f %.2f Tm "
            % (size, grey, x, self.height - y) + _pdf_string(content) + b" Tj ET"
        )

    def text_right(self, x: float, y: float, content: str, **kwargs) -> None:
        """Draw one line ending at ``x``. The weight column is right-aligned and
        computing that in the layout would put ``text_width`` in two places."""
        size = kwargs.get("size", 10.0)
        font = kwargs.get("font", HELVETICA)
        self.text(x - text_width(content, font, size), y, content, **kwargs)

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        width: float = 0.5,
        grey: float = 0.0,
    ) -> None:
        self._ops.append(
            b"%.2f w %.3f G %.2f %.2f m %.2f %.2f l S"
            % (width, grey, x1, self.height - y1, x2, self.height - y2)
        )

    def rect(
        self, x: float, y: float, width: float, height: float, *, grey: float = 0.9
    ) -> None:
        """A filled block, for the header band behind a column heading."""
        self._ops.append(
            b"%.3f g %.2f %.2f %.2f %.2f re f"
            % (grey, x, self.height - y - height, width, height)
        )

    def content(self) -> bytes:
        return b"\n".join(self._ops)


def _name(font: str) -> bytes:
    return b"/F2" if font == HELVETICA_BOLD else b"/F1"


class Document:
    """A page list that knows how to serialise itself.

    Object numbering is decided at write time rather than as pages are added,
    because the cross-reference table needs byte offsets and those are not known
    until the objects exist. Nothing here is incremental: ``render`` builds the
    whole file in memory, which for a cookbook of every recipe in the corpus is
    well under a megabyte.
    """

    def __init__(self, size: tuple[float, float] = A4, *, title: str = "") -> None:
        self.size = size
        self.title = title
        self.pages: list[Page] = []

    def page(self) -> Page:
        page = Page(*self.size)
        self.pages.append(page)
        return page

    def render(self) -> bytes:
        objects: list[bytes] = []

        def add(body: bytes) -> int:
            objects.append(body)
            return len(objects)

        # Reserved first so /Pages can name its kids and each page its parent:
        # the two reference each other, which no single-pass numbering survives.
        catalog_num, pages_num = 1, 2
        objects.extend([b"", b""])
        font_regular = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        )
        font_bold = add(
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
            b"/Encoding /WinAnsiEncoding >>"
        )
        resources = (
            b"<< /Font << /F1 %d 0 R /F2 %d 0 R >> >>" % (font_regular, font_bold)
        )

        kids: list[int] = []
        for page in self.pages:
            stream = page.content()
            contents = add(
                b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
            )
            kids.append(add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] "
                b"/Resources %s /Contents %d 0 R >>"
                % (pages_num, page.width, page.height, resources, contents)
            ))

        objects[pages_num - 1] = (
            b"<< /Type /Pages /Count %d /Kids [%s] >>"
            % (len(kids), b" ".join(b"%d 0 R" % k for k in kids))
        )
        objects[catalog_num - 1] = (
            b"<< /Type /Catalog /Pages %d 0 R >>" % pages_num
        )
        info = add(b"<< /Title " + _pdf_string(self.title) + b" /Producer "
                   b"(recipe_wizard) >>") if self.title else None

        out = bytearray(b"%PDF-1.4\n")
        # A binary comment marks the file as such for anything sniffing it.
        out.extend(b"%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (len(objects) + 1)
        for number, body in enumerate(objects, start=1):
            offsets[number] = len(out)
            out.extend(b"%d 0 obj\n" % number + body + b"\nendobj\n")

        start_xref = len(out)
        out.extend(b"xref\n0 %d\n" % (len(objects) + 1))
        out.extend(b"0000000000 65535 f \n")
        for number in range(1, len(objects) + 1):
            out.extend(b"%010d 00000 n \n" % offsets[number])
        trailer = b"<< /Size %d /Root %d 0 R" % (len(objects) + 1, catalog_num)
        if info is not None:
            trailer += b" /Info %d 0 R" % info
        out.extend(b"trailer\n" + trailer + b" >>\n")
        out.extend(b"startxref\n%d\n%%%%EOF\n" % start_xref)
        return bytes(out)
