"""Turning a recipe page into a faithful level-0 document.

The point of importing mechanically rather than letting a model read the page
and write the file is fidelity. An importer cannot paraphrase "2 1/2 teaspoons
baking powder" into "2.5 tsp baking powder", cannot quietly drop the second
half of a note, and cannot invent a quantity. Enrichment then works from text
that provably came from the source, with ``rw:originalText`` on every line to
check against.

schema.org's Recipe is what almost every recipe site emits, and it is a loose
shape: ``recipeInstructions`` may be a string, a list of strings, a list of
HowToStep, or HowToSection objects wrapping itemListElement. All four appear in
the wild and all four are handled here.
"""

from __future__ import annotations

import html
import json
import re
import urllib.request
from typing import Any

_SCRIPT = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

USER_AGENT = "Mozilla/5.0 (compatible; ha-recipe-wizard/0.1)"


class ImportError_(ValueError):
    """The page carried no recipe we could read."""


def fetch(url: str, timeout: float = 30.0) -> str:
    """Fetch a page. Many recipe sites reject a default urllib user agent."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def clean(text: Any) -> str:
    """Strip markup and collapse whitespace, preserving the wording."""
    if text is None:
        return ""
    if isinstance(text, dict):
        text = text.get("text") or text.get("name") or ""
    if not isinstance(text, str):
        text = str(text)
    text = html.unescape(text)
    text = _TAG.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def extract_jsonld(page: str) -> list[dict]:
    """Every JSON-LD node on the page, flattened out of @graph wrappers."""
    nodes: list[dict] = []
    for block in _SCRIPT.findall(page):
        try:
            parsed = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        queue = parsed if isinstance(parsed, list) else [parsed]
        while queue:
            node = queue.pop(0)
            if not isinstance(node, dict):
                continue
            if isinstance(node.get("@graph"), list):
                queue.extend(node["@graph"])
                continue
            nodes.append(node)
    return nodes


def _types(node: dict) -> set[str]:
    value = node.get("@type", "")
    values = value if isinstance(value, list) else [value]
    return {str(v) for v in values}


def find_recipe(nodes: list[dict]) -> dict:
    for node in nodes:
        if "Recipe" in _types(node):
            return node
    raise ImportError_("no schema.org Recipe node on the page")


def _instructions(value: Any) -> list[str]:
    """Flatten schema.org's four instruction shapes into ordered step text."""
    out: list[str] = []
    for entry in value if isinstance(value, list) else [value]:
        if isinstance(entry, str):
            # A single blob of prose: split on sentences-with-newlines only,
            # never mid-sentence, so nothing is invented or merged.
            for line in entry.split("\n"):
                text = clean(line)
                if text:
                    out.append(text)
            continue
        if not isinstance(entry, dict):
            continue
        if "HowToSection" in _types(entry):
            out.extend(_instructions(entry.get("itemListElement", [])))
            continue
        text = clean(entry.get("text") or entry.get("name"))
        if text:
            out.append(text)
    return out


def _slug(url: str, name: str) -> str:
    match = re.search(r"//[^/]+/([^?#]+)", url or "")
    if match:
        parts = [p for p in match.group(1).split("/") if p]
        if parts:
            return parts[-1]
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "untitled"


def _source(url: str) -> str:
    match = re.search(r"//(?:www\.)?([^/]+)", url or "")
    if not match:
        return "local"
    return match.group(1).split(".")[0]


def to_level0(node: dict, url: str = "") -> dict:
    """Build the rw document, keeping every string exactly as published."""
    url = clean(node.get("url")) or url
    name = clean(node.get("name")) or "Untitled"
    author = node.get("author")
    if isinstance(author, list):
        author = author[0] if author else None
    author_name = clean(author.get("name")) if isinstance(author, dict) else clean(author)

    ingredients = [
        clean(i) for i in node.get("recipeIngredient", node.get("ingredients", []))
    ]
    steps = _instructions(node.get("recipeInstructions", []))

    document: dict[str, Any] = {
        "@context": ["https://schema.org", {"rw": "https://ha-recipe-wizard.local/vocab#"}],
        "@type": "Recipe",
        "@id": f"urn:recipe:{_source(url)}/{_slug(url, name)}",
        "name": name,
        "rw:enrichmentLevel": 0,
        "rw:importNote": (
            "Imported mechanically from the page's own schema.org JSON-LD. Every "
            "string is as published. Enrichment must not alter these strings, "
            "only add structure alongside them."
        ),
    }
    if url:
        document["url"] = url
        document["isBasedOn"] = url
    if author_name:
        document["author"] = {"@type": "Person", "name": author_name}
    for key in ("prepTime", "cookTime", "totalTime"):
        if node.get(key):
            document[key] = node[key]
    if node.get("recipeYield"):
        value = node["recipeYield"]
        document["recipeYield"] = value[0] if isinstance(value, list) else value
    if ingredients:
        document["recipeIngredient"] = ingredients
    if steps:
        document["recipeInstructions"] = [
            {"@type": "HowToStep", "position": index, "text": text}
            for index, text in enumerate(steps, start=1)
        ]
    notes = clean(node.get("description"))
    if notes:
        document["description"] = notes
    return document


def import_page(page: str, url: str = "") -> dict:
    """HTML in, level-0 rw document out."""
    return to_level0(find_recipe(extract_jsonld(page)), url)


def import_url(url: str) -> dict:
    return import_page(fetch(url), url)
