# One cursor, served by Home Assistant

The website is not standalone. It is a second **surface** on the same cook-along:
it reads and writes through Home Assistant, and it does not work when Home
Assistant is down. That is a deliberate limit and the alternative was seriously
considered.

`CONTEXT.md` defines a cook-along as *stateless over a cursor* — the caller holds
which step it is on. For as long as there was one caller that was a detail. A
second surface makes it the design question, and it has only two honest answers.

**Two cursors.** The website keeps its own position in browser storage and works
offline. Then a cook who advances on the kitchen tablet has not advanced
anywhere else: `sensor.recipe_wizard_current_step` still reports the old step, an
automation waiting on the bake timer never fires, and the phone in the lounge
shows a different page of the same recipe. The sensors do not merely lag — they
are *wrong*, and nothing in the system can tell which of the two positions is the
real one. Reconciling them later means inventing a merge rule for a fact that has
no natural one.

**One cursor.** Home Assistant owns it, in the config entry's options, where it
already survives a restart during the brownies' three-hour chill (see
`cursor.py`). Every surface drives that one position, so the sensors stay
truthful, automations keep working, and two devices in one kitchen agree. The
cost is that the website needs Home Assistant reachable.

We took the second. A cook-along is a thing happening in one kitchen to one tray
of food; it has one position by nature, and the offline story was buying a
capability nobody asked for at the price of the sensors being trustworthy.

## Consequences

**"Standalone" is on `CONTEXT.md`'s avoid list**, because it implies an
independent cursor and there is only ever one. The word for a place a cook reads
a dish or drives a cook-along is **surface**, and exactly one of them owns the
cursor.

**The website is a custom panel, not a separately hosted page.** Once Home
Assistant is required anyway, serving the page from Home Assistant's own origin
costs nothing and removes the entire authentication problem:
`panel_custom.async_register_panel` puts it inside the authenticated frontend, so
there is no CORS to open and no long-lived access token sitting in a browser on a
kitchen wall. A token would have been a full Home Assistant credential — the
platform has no read-only ones — on a device other people touch. Kiosk a tablet
at `/recipe-wizard` and it is, to the cook, the ordinary website that was asked
for.

**Writes go through the four existing actions, and there is no write endpoint.**
They already validate, already distinguish what the cook got wrong from what the
document got wrong, and are already tested. A second write path would be a second
place that validation lives.

**Reads go over HTTP even inside Home Assistant, where `hass` is right there.**
The alternative was to serve the whole application from the sensor's attributes,
and attributes are written to the recorder on every state change — a full dish on
a twenty-one step walk would bloat the database for a card that could have asked
for it. `_unrecorded_attributes` would fix the bloat and cost the history. So the
sensor stays sized for dashboards and templates, the API carries the dish, and
the entity is used as an **invalidation signal**: when the cursor moves, re-fetch.
One code path, exercised identically by the card and the panel, so a bug in one
is a bug in both.

**The API is private and carries no version.** It exists for the surface this
repo ships and is documented as changing without notice. `docs/format.md` is what
a designed, stable interface looks like here; if anything outside the repo ever
needs to read a dish, that is a deliberate act with a `/v1/` path and a design
pass, not something that happened because an endpoint was reachable.
