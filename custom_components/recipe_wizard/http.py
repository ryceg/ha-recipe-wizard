"""The library and one dish over HTTP, and the panel that reads them.

Named ``http.py`` because that is where Home Assistant integrations put their
views, and it holds the panel too: a custom panel is one JavaScript file served
over this same surface, so splitting "the two views" from "the static file the
browser fetches next" would put one decision -- the bundle is either being
served or it is not -- in two modules.

**Two views, read-only, and no third.** ``/api/recipe_wizard/library`` is the
index and ``/api/recipe_wizard/dish/{recipe_id}`` is one dish at one scale.
There is deliberately no write endpoint and no cursor endpoint:

* Writing goes through the four cook-along actions. They already refuse a name
  that matches three recipes, a move with nothing on the go and a step back from
  the first step, each with a translated message naming what the cook got wrong.
  A second write path would be a second place that validation lives, and the two
  would drift.
* The cursor is already on ``sensor.recipe_wizard_current_step``'s attributes --
  small, push-updated when the entry's options change, and tested. A panel reads
  it the way every other Home Assistant card reads a state, over the websocket
  the frontend is already holding open. An endpoint that polled for it would be
  slower *and* a second answer to the same question.

**The payload is private.** ``core/serialise.py`` says it in full: what comes
back is a *dish* -- resolved, scaled, expanded, planned -- not the format on
disk, its field names are not an interface, it carries no version, and it may
change in any release. The only consumer is the panel this repository ships.
That is a promise about the shape, and this module keeps it by not advertising
the endpoints anywhere a stranger would find them.

**Authentication is Home Assistant's, unchanged.** ``HomeAssistantView`` requires
a signed-in user by default and nothing here relaxes it. That is the whole
reason the design has no token in it: the panel runs inside the authenticated
frontend, so the browser already carries the credentials, and a view that opted
out would put a household's recipe library on the network for anyone who found
the port.

**Views register once per run; the panel belongs to the entry.** Home Assistant
can add a view or a static path and has no way to take either back, so both are
registered from ``async_setup`` -- doing it per entry would stack a duplicate
route on every reload. A panel *can* be removed, so it is registered in
``async_setup_entry`` and removed in ``async_unload_entry``, which is what makes
the sidebar item disappear when the integration is deleted.

**A missing bundle is not a failed setup.** The frontend is built separately and
a source checkout has no ``www/recipe-wizard.js`` in it. If the file is not
there, this logs a warning naming it and registers neither the static path nor
the panel. Raising instead would take the cook-along sensors and the shopping
list down over an absent asset, which is a much worse day than a missing sidebar
entry.
"""

from __future__ import annotations

import logging
from functools import partial
from http import HTTPStatus  # the stdlib module; this file is not on sys.path
from pathlib import Path
from typing import Any, Final

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .core.dish import resolve_dish
from .core.library import Library, LibraryProblem
from .core.serialise import dish_json, library_json
from .coordinator import RecipeWizardConfigEntry

_LOGGER = logging.getLogger(__name__)

#: Where the built frontend lands. A module-level name and not a call, so a test
#: can point it at a directory it controls -- the bundle is built by another
#: toolchain and a checkout of this repository does not contain one.
WWW_DIR: Final = Path(__file__).parent / "www"

#: Fixed by agreement with the frontend. Changing any of these five is a change
#: to two codebases: the panel element's name is what the bundle defines, and the
#: URL path is what a bookmark and the sidebar both hold.
BUNDLE_NAME: Final = "recipe-wizard.js"
STATIC_URL: Final = "/recipe_wizard_static"
PANEL_URL_PATH: Final = "recipe-wizard"
PANEL_ELEMENT: Final = "recipe-wizard-panel"
PANEL_TITLE: Final = "Recipes"

#: Matches the integration's own entity icons rather than inventing a mark.
PANEL_ICON: Final = "mdi:chef-hat"

API_BASE: Final = f"/api/{DOMAIN}"

#: ``{recipe_id:.+}`` and not the default ``{recipe_id}``: a recipe's ``@id`` is
#: a URN -- ``urn:recipe:rte/vanilla-cake`` -- and aiohttp's default placeholder
#: stops at a slash, so every recipe in the corpus would have missed the route.
#: The regex accepts the id written straight into the path and, because aiohttp
#: unquotes after matching, percent-encoded as well.
DISH_URL: Final = f"{API_BASE}/dish/{{recipe_id:.+}}"

#: ``batches`` is a plain factor, as it is everywhere else in this project, so a
#: half batch is as meaningful as three; nought is not, and would resolve a dish
#: of nothing. Extra keys are refused rather than ignored: a request for
#: ``include_optionals=false`` that silently kept the optional parts would be a
#: panel showing a walk nobody asked for, with nothing on the screen to say so.
DISH_QUERY: Final = vol.Schema({
    vol.Optional("batches", default=1.0): vol.All(
        vol.Coerce(float), vol.Range(min=0, min_included=False)
    ),
    vol.Optional("include_optional", default=True): cv.boolean,
})


# ---------------------------------------------------------------------------
# The premise of a request
# ---------------------------------------------------------------------------


def _loaded_library(hass: HomeAssistant) -> Library | None:
    """The library the coordinator has already loaded, or ``None``.

    Read off the entry rather than loaded again: there is one library, the
    coordinator owns it, and a view that parsed the directory itself would serve
    a different answer from the sensors sitting beside it on the same screen.
    """
    entries: list[RecipeWizardConfigEntry] = hass.config_entries.async_loaded_entries(
        DOMAIN
    )
    if not entries:
        return None
    return entries[0].runtime_data.coordinator.data


def _dish_payload(
    library: Library, recipe_id: str, batches: float, include_optional: bool
) -> dict[str, Any]:
    """Runs in the executor: resolving and serialising are one job.

    ``strict=False`` because a dish is built to be shown. Asking for a tenth of
    the vanilla cake puts its buttercream under the minimum batch the paddle can
    reach, and the right answer is a resolution the panel can render with a
    ``resolve-batch-constraint`` finding attached to the *use* -- not an
    exception that costs the cook the whole tree.

    One executor job and not two, so the resolve and the serialise cannot be
    separated by a library reload landing between them.
    """
    dish = resolve_dish(library, recipe_id, batches=batches, strict=False)
    return dish_json(dish, include_optional=include_optional)


# ---------------------------------------------------------------------------
# The views
# ---------------------------------------------------------------------------


class RecipeWizardLibraryView(HomeAssistantView):
    """What there is to cook: every recipe, and the families that group them."""

    url = f"{API_BASE}/library"
    name = f"api:{DOMAIN}:library"

    async def get(self, request: web.Request) -> web.Response:
        """The index, serialised in the executor."""
        hass = request.app[KEY_HASS]
        library = _loaded_library(hass)
        if library is None:
            return self.json_message(
                "Recipe Wizard is not set up, or it cannot read your recipe "
                "folder at the moment.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        payload = await hass.async_add_executor_job(library_json, library)
        return self.json(payload)


class RecipeWizardDishView(HomeAssistantView):
    """One recipe resolved with its components, at the batch size asked for."""

    url = DISH_URL
    name = f"api:{DOMAIN}:dish"

    async def get(self, request: web.Request, recipe_id: str) -> web.Response:
        """The dish, or the reason there is not one.

        The unknown-recipe check is a dictionary lookup on the loaded library and
        happens before the executor hop, so a typed-in id comes back as a 404
        naming what was asked for rather than as a ``LibraryError`` surfacing as
        a 500 with a traceback in the log.
        """
        hass = request.app[KEY_HASS]
        library = _loaded_library(hass)
        if library is None:
            return self.json_message(
                "Recipe Wizard is not set up, or it cannot read your recipe "
                "folder at the moment.",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )

        try:
            query = DISH_QUERY(dict(request.query))
        except vol.Invalid as err:
            return self.json_message(str(err), HTTPStatus.BAD_REQUEST)

        if recipe_id not in library.recipes:
            return self.json_message(
                f"No recipe with @id {recipe_id!r}.", HTTPStatus.NOT_FOUND
            )

        try:
            payload = await hass.async_add_executor_job(
                partial(
                    _dish_payload,
                    library,
                    recipe_id,
                    query["batches"],
                    query["include_optional"],
                )
            )
        except LibraryProblem as err:
            # Not a 404: the recipe is there and the document is the problem --
            # a variant cycle, say. The same line the repair card would draw.
            _LOGGER.error("Could not resolve %s: %s", recipe_id, err)
            return self.json_message(
                f"Recipe Wizard could not work out {recipe_id!r}: {err}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        return self.json(payload)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@callback
def async_register_views(hass: HomeAssistant) -> None:
    """Both views, once per run. Called from ``async_setup``.

    There is no ``unregister_view``, so registering these per entry would leave a
    second copy of each route behind on every reload. They answer with a 503 and
    a reason while there is no loaded entry, which is the same distinction
    ``actions.py`` draws: "Recipe Wizard is not set up" is actionable and "no
    such endpoint" is not.
    """
    hass.http.register_view(RecipeWizardLibraryView)
    hass.http.register_view(RecipeWizardDishView)


async def async_register_static_path(hass: HomeAssistant) -> None:
    """Serve the bundle directory, if there is a bundle in it.

    ``cache_headers=False`` on purpose. The filename is fixed by the contract
    with the frontend rather than hashed per build, so the far-future caching the
    default asks for would strand a browser on the bundle it fetched before the
    last upgrade, with no way for the user to tell. The file is a few hundred
    kilobytes served off local disk on the same machine.

    The ``is_file`` check goes through the executor like every other read this
    integration does: it is one stat, and the rule that the event loop never
    waits on a disk does not have an exception small enough to be worth writing
    down.
    """
    bundle = WWW_DIR / BUNDLE_NAME
    if not await hass.async_add_executor_job(bundle.is_file):
        _LOGGER.warning(
            "No frontend bundle at %s, so the Recipes panel will not appear. "
            "Everything else -- the cook-along sensors, the shopping list and "
            "the actions -- is set up as usual",
            bundle,
        )
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(WWW_DIR), cache_headers=False)]
    )


@callback
def _static_path_registered(hass: HomeAssistant) -> bool:
    """Whether the bundle directory is being served.

    Asked of the router rather than remembered in ``hass.data``, for two
    reasons. The integration keeps nothing in ``hass.data`` -- ``runtime_data``
    is the rule and ``test_setup_puts_the_library_on_runtime_data`` asserts the
    domain is absent from it -- and the router is the thing the question is
    actually about: the panel should be offered exactly when the script behind it
    is being served, and this is that condition rather than a proxy for it.
    """
    return any(
        resource.canonical == STATIC_URL
        for resource in hass.http.app.router.resources()
    )


async def async_register_recipe_panel(hass: HomeAssistant) -> None:
    """Put *Recipes* in the sidebar. Called from ``async_setup_entry``.

    Silently does nothing when the bundle is not being served, because
    ``async_register_static_path`` has already logged the reason once and a
    second warning per reload would say nothing new. A panel registered anyway
    would be a sidebar entry that opens on a blank page and a 404 in the browser
    console.

    ``module_url`` rather than ``js_url``: the bundle is an ES module, which is
    what the frontend agreement says and what a modern build emits.
    """
    if not _static_path_registered(hass):
        return
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{STATIC_URL}/{BUNDLE_NAME}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        embed_iframe=False,
        require_admin=False,
    )


@callback
def async_remove_recipe_panel(hass: HomeAssistant) -> None:
    """Take the sidebar entry with the entry.

    ``warn_if_unknown=False``: the panel is not registered at all when there is
    no bundle, and unloading in that state is the ordinary case for a source
    checkout rather than something to log about.
    """
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
