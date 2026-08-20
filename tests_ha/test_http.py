"""The two read-only views, the static bundle, and the panel over them.

The claims worth holding here are the ones a browser would only discover by
breaking. A recipe's ``@id`` is a URN with a slash in it, so the dish route has to
be written to accept one; a dish is resolved off the event loop, because the
harness will not catch that for us when the work is arithmetic rather than
file I/O; an id nobody has is a 404 with a message, not a traceback; nothing is
served to a browser without a login; and a checkout with no frontend bundle in it
still gets its sensors, its shopping list and its actions.
"""

from __future__ import annotations

import threading
from http import HTTPStatus
from pathlib import Path
from urllib.parse import quote

import pytest
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.recipe_wizard import http as rw_http
from custom_components.recipe_wizard.const import DOMAIN

CAKE = "urn:recipe:rte/vanilla-cake"
QEEMA = "urn:recipe:rte/qeema"
BUTTERCREAM = "urn:recipe:rte/vanilla-buttercream"

LIBRARY_URL = "/api/recipe_wizard/library"


def dish_url(recipe_id: str, **query: str) -> str:
    """The dish route, with the id written straight into the path.

    Straight in, not percent-encoded, because that is the form a caller reaches
    for first and the route has to accept it;
    ``test_a_recipe_id_is_reachable_however_the_caller_spells_it`` covers the
    encoded form beside it.
    """
    suffix = "?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else ""
    return f"/api/recipe_wizard/dish/{recipe_id}{suffix}"


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the built frontend, in a directory the test owns.

    The real bundle is produced by a separate toolchain and is not in a checkout
    of this repository, so every other test in this suite runs the no-bundle
    path. Patching ``WWW_DIR`` is what makes the other half reachable without
    writing into ``custom_components/`` from a test.
    """
    www = tmp_path / "www"
    www.mkdir()
    (www / rw_http.BUNDLE_NAME).write_text(
        "export class RecipeWizardPanel extends HTMLElement {}\n", encoding="utf-8"
    )
    monkeypatch.setattr(rw_http, "WWW_DIR", www)
    return www


@pytest.fixture
def no_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The other half of ``bundle``: a directory with no bundle in it.

    Pointed somewhere empty rather than left to whatever is on disk, because
    ``custom_components/recipe_wizard/www/`` is built by another toolchain and may
    or may not be present in a working tree. A test whose premise is "there is no
    bundle" has to arrange that rather than hope for it.
    """
    empty = tmp_path / "no-www"
    empty.mkdir()
    monkeypatch.setattr(rw_http, "WWW_DIR", empty)
    return empty


def _served_static_routes(hass: HomeAssistant) -> int:
    """How many router entries answer for the bundle directory."""
    return sum(
        resource.canonical == rw_http.STATIC_URL
        for resource in hass.http.app.router.resources()
    )


# ---------------------------------------------------------------------------
# The library view
# ---------------------------------------------------------------------------


async def test_the_library_view_lists_what_there_is_to_cook(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """The index the panel opens on, off the library the coordinator already
    holds -- not a second parse of the same directory."""
    client = await hass_client()
    response = await client.get(LIBRARY_URL)

    assert response.status == HTTPStatus.OK
    payload = await response.json()
    assert {recipe["id"] for recipe in payload["recipes"]} >= {CAKE, QEEMA}
    assert all("name" in recipe for recipe in payload["recipes"])
    assert "families" in payload


# ---------------------------------------------------------------------------
# The dish view
# ---------------------------------------------------------------------------


async def test_a_recipe_id_is_reachable_however_the_caller_spells_it(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """``urn:recipe:rte/vanilla-cake`` has a slash in it, and aiohttp's default
    placeholder stops at one. Written straight into the path and percent-encoded
    are both things a caller will do, and both have to land on the same dish."""
    client = await hass_client()

    plain = await client.get(dish_url(CAKE))
    encoded = await client.get(dish_url(quote(CAKE, safe="")))

    assert plain.status == HTTPStatus.OK
    assert encoded.status == HTTPStatus.OK
    assert (await plain.json())["id"] == (await encoded.json())["id"] == CAKE


async def test_a_dish_comes_back_at_the_batch_size_asked_for(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """Doubling is a plain factor and propagates into every component, so the
    cake's buttercream is doubled too -- which is the whole reason a surface asks
    for a dish rather than a recipe."""
    client = await hass_client()
    response = await client.get(dish_url(CAKE, batches="2"))

    assert response.status == HTTPStatus.OK
    payload = await response.json()
    assert payload["batches"] == 2.0
    assert payload["steps"], "the walk is the primary surface and is never empty"
    assert payload["plan"]["steps"]
    assert payload["shopping"]["lines"]
    assert any(
        component["recipe_id"] == BUTTERCREAM for component in payload["components"]
    )


async def test_leaving_the_optional_parts_out_changes_the_walk(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """``include_optional`` changes what the dish *is* -- the qeema without its
    mint yogurt is a different walk and a different shopping list -- so it
    belongs to the request rather than to the rendering, and a surface that sends
    it must get a shorter answer back."""
    client = await hass_client()
    with_it = await (await client.get(dish_url(QEEMA))).json()
    without = await (
        await client.get(dish_url(QEEMA, include_optional="false"))
    ).json()

    assert len(without["steps"]) < len(with_it["steps"])
    assert len(without["shopping"]["lines"]) < len(with_it["shopping"]["lines"])


async def test_an_impossible_batch_is_a_finding_rather_than_a_refusal(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """A dish is built to be shown. A tenth of the cake puts its buttercream
    under the minimum batch the paddle can reach, and the cook should get a
    resolution they can read with the warning attached to the *use* -- not a 500
    and an empty screen. ``strict=False`` is what buys that, so this test fails
    the moment someone tidies it away."""
    client = await hass_client()
    response = await client.get(dish_url(CAKE, batches="0.1"))

    assert response.status == HTTPStatus.OK
    payload = await response.json()
    constraints = [
        finding
        for finding in payload["findings"]
        if finding["code"] == "resolve-batch-constraint"
    ]
    assert constraints, "the batch constraint should be reported, not raised"
    assert constraints[0]["level"] == "warning"
    assert constraints[0]["where"], "which use it belongs to is the whole point"


async def test_a_recipe_that_is_not_there_is_a_404_and_not_a_500(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """A mistyped id is the caller's to fix, so it comes back named. Without the
    check the same request raises ``LibraryError`` inside the executor and lands
    as a 500 with a traceback in the log -- which tells the browser nothing."""
    client = await hass_client()
    response = await client.get(dish_url("urn:recipe:test/no-such-thing"))

    assert response.status == HTTPStatus.NOT_FOUND
    assert "no-such-thing" in (await response.json())["message"]


async def test_a_batch_of_nothing_is_refused_rather_than_resolved(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """Half a batch is meaningful and nought is not: it would resolve a dish of
    nothing and read as a bug in the panel rather than as what was asked for."""
    client = await hass_client()
    assert (await client.get(dish_url(CAKE, batches="0"))).status == (
        HTTPStatus.BAD_REQUEST
    )
    assert (await client.get(dish_url(CAKE, batches="lots"))).status == (
        HTTPStatus.BAD_REQUEST
    )


async def test_a_misspelled_query_parameter_is_refused_rather_than_ignored(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client
):
    """``include_optionals=false`` accepted and ignored would be a panel quietly
    showing the optional parts with nothing on the screen to say so. A 400 naming
    the key is the cheaper failure by a distance."""
    client = await hass_client()
    response = await client.get(dish_url(CAKE, include_optionals="false"))

    assert response.status == HTTPStatus.BAD_REQUEST
    assert "include_optionals" in (await response.json())["message"]


# ---------------------------------------------------------------------------
# What the views promise about themselves
# ---------------------------------------------------------------------------


async def test_neither_view_answers_without_a_login(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, hass_client_no_auth
):
    """``requires_auth`` is left at its default, which is the reason there is no
    token anywhere in this design: the panel runs inside the authenticated
    frontend. A view that opted out would put a household's recipe library on the
    network for anyone who found the port."""
    client = await hass_client_no_auth()

    assert (await client.get(LIBRARY_URL)).status == HTTPStatus.UNAUTHORIZED
    assert (await client.get(dish_url(CAKE))).status == HTTPStatus.UNAUTHORIZED


async def test_the_views_say_why_when_there_is_no_library_yet(
    hass: HomeAssistant, custom_integration: None, hass_client
):
    """The views register in ``async_setup``, so they exist before any entry does
    -- the same reason the actions do. "Recipe Wizard is not set up" is
    actionable; "no such endpoint" is not."""
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    client = await hass_client()

    for url in (LIBRARY_URL, dish_url(CAKE)):
        response = await client.get(url)
        assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
        assert "not set up" in (await response.json())["message"]


async def test_nothing_is_resolved_or_serialised_on_the_event_loop(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    hass_client,
    monkeypatch: pytest.MonkeyPatch,
):
    """Invariant 2, and the harness cannot catch this one for us: resolving a
    dish is arithmetic rather than file I/O, so the blocking-call detector never
    fires and a regression would only show up as a stuttering dashboard."""
    loop_thread = threading.current_thread()
    seen: list[threading.Thread] = []

    def spy(original):
        def wrapper(*args, **kwargs):
            seen.append(threading.current_thread())
            return original(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(rw_http, "_dish_payload", spy(rw_http._dish_payload))
    monkeypatch.setattr(rw_http, "library_json", spy(rw_http.library_json))

    client = await hass_client()
    assert (await client.get(LIBRARY_URL)).status == HTTPStatus.OK
    assert (await client.get(dish_url(CAKE))).status == HTTPStatus.OK

    assert len(seen) == 2
    assert all(thread is not loop_thread for thread in seen)


# ---------------------------------------------------------------------------
# The bundle and the panel
# ---------------------------------------------------------------------------


async def test_a_missing_bundle_does_not_take_the_sensors_down_with_it(
    hass: HomeAssistant,
    no_bundle: Path,
    loaded_entry: MockConfigEntry,
    hass_client,
):
    """A checkout without a built ``www/recipe-wizard.js`` in it is an ordinary
    state, and a setup that failed over an absent frontend asset would cost the
    cook their cook-along and their shopping list to save them a sidebar entry."""
    assert loaded_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.recipe_wizard_current_step") is not None
    assert rw_http.PANEL_URL_PATH not in hass.data.get(frontend.DATA_PANELS, {})
    assert _served_static_routes(hass) == 0

    # The API is the half that does not depend on the bundle, and it still works.
    client = await hass_client()
    assert (await client.get(LIBRARY_URL)).status == HTTPStatus.OK


async def test_the_panel_and_the_bundle_behind_it_arrive_together(
    hass: HomeAssistant,
    bundle: Path,
    loaded_entry: MockConfigEntry,
    hass_client,
):
    """The sidebar entry is offered exactly when the script it loads is being
    served. A panel registered without its bundle opens on a blank page and a 404
    in the browser console, which is a worse answer than no panel at all."""
    panel = hass.data[frontend.DATA_PANELS][rw_http.PANEL_URL_PATH]
    assert panel.sidebar_title == "Recipes"
    assert panel.config["_panel_custom"] == {
        "name": "recipe-wizard-panel",
        "embed_iframe": False,
        "trust_external": False,
        # An ES module, so module_url and never js_url.
        "module_url": "/recipe_wizard_static/recipe-wizard.js",
    }

    client = await hass_client()
    response = await client.get("/recipe_wizard_static/recipe-wizard.js")
    assert response.status == HTTPStatus.OK
    assert "RecipeWizardPanel" in await response.text()


async def test_the_panel_goes_when_the_entry_does(
    hass: HomeAssistant, bundle: Path, loaded_entry: MockConfigEntry
):
    """Deleting the integration has to take its sidebar entry with it, or the
    cook is left with a *Recipes* link that opens on nothing."""
    assert rw_http.PANEL_URL_PATH in hass.data[frontend.DATA_PANELS]

    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert rw_http.PANEL_URL_PATH not in hass.data[frontend.DATA_PANELS]


async def test_a_reload_does_not_stack_a_second_copy_of_the_bundle_route(
    hass: HomeAssistant, bundle: Path, loaded_entry: MockConfigEntry
):
    """Home Assistant can register a static path and has no way to take one back,
    so the reconfigure flow -- which reloads the entry -- must not add another
    every time the cook moves their recipe folder. The panel still comes back,
    which is the half that *is* removed on unload."""
    before = _served_static_routes(hass)
    assert before

    assert await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert _served_static_routes(hass) == before
    assert rw_http.PANEL_URL_PATH in hass.data[frontend.DATA_PANELS]
