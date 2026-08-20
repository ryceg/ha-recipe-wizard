# Recipe Wizard in Home Assistant

Recipe Wizard turns a folder of recipe files into something you can cook from on
a screen in your kitchen.

It is built around two things:

* **A cook-along.** One step at a time, in the order you should do it, with the
  amounts already worked out for the batch size you are making and a timer that
  says what it is waiting for. A screen you do not have to touch with dough on
  your hands.
* **A shopping list.** One line per food, added up across the whole dish
  including any sub-recipes. Butter that gets melted in one part of the recipe
  and softened in another is *one thing to buy* and *two things to have ready*,
  and the list says both.

Everything happens on your own machine. Recipe Wizard does not talk to the
internet and does not send your recipes anywhere.


## What it needs from you

A folder of recipe files. Each recipe is one file ending in `.json`, in the
structured format this project defines. Folders inside your recipe folder are
searched too, so you can organise however you like.

You create and edit those files outside Home Assistant, using the command-line
tool that comes with this project — see the main [README](../README.md). Recipe
Wizard reads them; it never writes to them.

## Installing it

### With HACS (recommended)

1. In Home Assistant, open **HACS**.
2. Open the three-dot menu in the top right and choose **Custom repositories**.
3. Paste in `https://github.com/ryceg/ha-recipe-wizard`, choose the category
   **Integration**, and select **Add**.
4. Find **Recipe Wizard** in the list and select **Download**.
5. Restart Home Assistant.

### By hand

1. Download or clone this project.
2. Copy the whole folder `custom_components/recipe_wizard` into the
   `custom_components` folder next to your `configuration.yaml`. If there is no
   `custom_components` folder, create one. You should end up with
   `custom_components/recipe_wizard/manifest.json`.
3. Restart Home Assistant.

Either way, put your recipe files in a folder called `recipes` next to your
`configuration.yaml`. That is the folder Recipe Wizard will offer you by default.

## Setting it up

1. Go to **Settings → Devices & services → Add integration**.
2. Search for **Recipe Wizard** and select it.
3. You are asked for one thing: the **recipe folder**. The box is pre-filled with
   `recipes` next to your `configuration.yaml`, which is the usual place. If you
   keep your recipes somewhere else, type the full path instead. A plain name
   with no path is understood as a folder next to your `configuration.yaml`.
4. Select **Submit**.

Recipe Wizard reads every recipe before it saves anything. If something is wrong
it tells you what, and you can correct the folder and try again without starting
over. There is nothing else to configure, and no username, password or key of any
kind.

You can only add Recipe Wizard once. There is one recipe collection, so a second
copy would have nothing different to show.

### If you move your recipes later

You do not have to delete Recipe Wizard and add it back. Open its three-dot menu
in **Settings → Devices & services** and choose **Reconfigure**. You get the same
one box, filled in with the folder it is using now, and the same check before
anything is saved: if the new folder does not read, nothing changes and you can
correct it there and then.

Everything else stays exactly as it is. Your dashboard cards and automations keep
working, because they point at the entities and the entities do not move. A
cook-along in progress stays on the step it was on, and your shopping list keeps
what you had ticked off.

Nothing is copied or moved for you. Move the files yourself first, then tell
Recipe Wizard where they went.

## If setup will not go through

| What it says | What to do |
| --- | --- |
| There is no folder at… | Check the spelling. If you have not made the folder yet, create it and put at least one recipe in it. |
| No recipes were found in… | The folder exists but has no recipe files in it. Recipe Wizard looks for files ending in `.json`. |
| One of the recipe files could not be read… | The message names the file. It is either not valid JSON, or it has no `@id` line giving the recipe its identity. Fix or move that file and try again. |
| Recipe Wizard could not read its own list of foods… | This one is not your fault: a file that ships inside the integration is missing or damaged. Re-download the integration and restart Home Assistant. |
| Something unexpected went wrong | Look in **Settings → System → Logs** for the details, and please open an issue with what you find. |

If setup succeeded before and the integration later shows as *retrying*, the
usual cause is the same list above — most often a recipe file that has been
edited and is no longer valid. The log names the file.

## When one recipe has something wrong with it

A file that will not parse at all stops the whole folder loading, because loading
six recipes out of seven and saying nothing would leave you hunting for a recipe
that is on disk. A recipe that parses but does not *hang together* is different:
the rest of your collection is fine, and Recipe Wizard tells you about that one
in **Settings → System → Repairs**.

The notice names the recipe and lists each part of it to look at — a step that
asks for something no ingredient row and no earlier step provides, a sub-recipe
that is not in your folder. Each line quotes the id to search the file for.

Two things it deliberately does not do:

* **It only reports mistakes, never doubts.** Recipe Wizard also notices things
  it is merely unsure about — a source that says "a splash of milk" leaves a
  weight it cannot work out, and that is the honest answer rather than a problem
  to fix. Those never raise a notice. If they did, you would have notices you
  could never clear, and you would stop reading the ones that matter.
* **It does not offer to fix anything.** Your recipe files are your own
  documents and Recipe Wizard never writes to them. Open the file in a text
  editor, or run `python -m recipe_wizard --list --validate` to see the same list
  on a terminal.

The notice disappears on its own once the recipe reads cleanly — within 15
minutes of you saving it, or straight away if you reload Recipe Wizard.

## If you need to report a problem

Recipe Wizard's page in **Settings → Devices & services** has **Download
diagnostics** in its three-dot menu, and the file is safe to attach to a public
issue. **It contains none of your recipes** — no ingredients, no step text, no
quantities. What it holds is how many recipes you have and how complete they are,
where the folder is, which recipe a cook-along is on and how far through, and a
list of what the checker found, given as its short code and the part of the
recipe it is about.

## The Recipes page

Once Recipe Wizard is set up, **Recipes** appears in the sidebar on the left,
below your dashboards. It is a full page of its own rather than a card you have
to find room for on a dashboard, because a recipe is a lot to read on a phone
propped against a mixing bowl.

The page shows the recipes in your folder. Choose one, say how many batches you
are making, and you get the whole thing worked out at that size: what to buy,
what to have ready, the running order, and the steps themselves.

You do not have to use it. Everything on that page is also available as the
sensors, the shopping list and the actions described below, so a dashboard you
have built yourself keeps working exactly as it did.

**Nothing on that page leaves your machine.** It is served by your own Home
Assistant, to your own browser, and only to someone already signed in to Home
Assistant. If you are not logged in, there is nothing to see.

### If Recipes is not in the sidebar

The page is a small file that ships inside the integration. If it is missing —
which happens if you installed by copying files by hand and missed a folder, or
if you are running from a checkout of the source — Recipe Wizard writes a line to
your log saying which file it could not find, and then carries on without the
page. **Nothing else is affected:** the sensors, the shopping list and the actions
all set up as usual. Reinstall through HACS, or copy the whole
`custom_components/recipe_wizard` folder across rather than part of it, and
restart Home Assistant.

## Cooking along

This is the part you use in the kitchen. You tell Recipe Wizard what you are
making and how much of it, and it shows you one step at a time.

Everything appears under a single item called **Recipe Wizard** in
**Settings → Devices & services**. It is listed as a *service* rather than a
device, because there is no gadget — it is a folder of files on your own machine.

### The two sensors

**Current step** — `sensor.recipe_wizard_current_step`

Its value is where you are, written as a position: `12/16` means the twelfth step
of sixteen. Two other values are possible: `idle` when you are not cooking
anything, and `finished` when you have gone past the last step.

The value is a position rather than the words of the step because Home Assistant
only allows 255 characters in a value, and a step can be longer than that. The
words are in the attributes instead, where there is no limit:

| Attribute | What it holds |
| --- | --- |
| `step` | The step itself, in the recipe's own words. This is the one to put on screen. |
| `needs` | What to have in front of you for this step, already worked out for your batch size — *"smooth peanut butter: 4 tbsp (of 500 g)"*. |
| `timer` | What a timer for this step should say — *"32 min, then check: edges firmish, centre still jiggling"* — or nothing if the step has no waiting in it. |
| `doneness` | How you know the step is done. Where a recipe gives both a time and a state, **the state is the one to trust.** |
| `attention` | `active` if you have to stand there, `passive` if you can potter, `unattended` if you can leave the room. |
| `may_pause_after` | `true` if this is a sensible place to stop and carry on later. |
| `recipe` and `recipe_id` | Which recipe this step belongs to. A cake and its frosting each have their own run of steps, so this changes partway through. |
| `dish` | What you are making overall. |
| `step_number` and `of` | The same numbers as the value, separately, for a card that wants to do arithmetic. |
| `batches` | How many batches you asked for. |
| `produces` | What this step makes, so you know what to label the bowl. |
| `warnings` | Anything the recipe itself says will not work at this size — *"cannot be made at 100 g: its minimum batch is 500 g"*. Worth reading before you start. |
| `cited_components` | Parts of the recipe that live in a cookbook rather than in your folder. You have to go and get the book. |
| `safety_note`, `timer_starts_when` | Only present when the recipe says something about them. |

**Step timer** — `sensor.recipe_wizard_step_timer`

Roughly when the current step's stated time runs out, as a time of day, which
Home Assistant shows as a countdown. It is an **estimate**, and it is deliberately
blank rather than approximate:

* A step that gives no time at all gets no countdown. Recipe Wizard will not
  invent one.
* A step whose timing starts on something happening — *"once the water is back to
  the boil"* — gets no countdown either, because nothing here can see your pan.
  The phrase is in the `timer_starts_when` attribute instead.
* Where a recipe gives a range, such as *freeze for two to three hours*, the
  countdown is the early end and the attribute `latest_estimate` is the late one.
  Neither is averaged into a number the recipe never gave.

Its `doneness` attribute sits beside it on purpose. **A countdown reaching zero is
not the same as the food being ready.**

### The four actions

You can call these from a dashboard button, a script, an automation, or by voice.
None of them asks which Recipe Wizard you mean, because there is only one.

| Action | What it does |
| --- | --- |
| `recipe_wizard.start_cook_along` | Starts a recipe. Takes **Recipe** and, optionally, **Batches**. |
| `recipe_wizard.next_step` | On to the next step. After the last one it reads as `finished`. |
| `recipe_wizard.previous_step` | Back one step, to read it again. |
| `recipe_wizard.stop_cook_along` | Done. Clears the current step. |

**Recipe** does not have to be the recipe's full internal name. Part of its title
is enough — `brownies` — as long as it matches only one recipe. If it matches
several you are told which ones, rather than being given the wrong one. If it
matches nothing, the message quotes what you typed so you can see the typo.

**Batches** is a plain multiplier: `1` is the recipe as written, `2` doubles
everything including any sub-recipes, and `0.5` halves it. Every amount you see
afterwards is already scaled, so there is no arithmetic left for you.

Where you are is remembered properly, not just for as long as Home Assistant
happens to be running. If you restart it while a tray is chilling, the cook-along
comes back on the same step.

### A cook-along card

This is a plain Markdown card, which is enough for a screen on a kitchen wall:

```yaml
type: markdown
content: |
  {% set s = states.sensor.recipe_wizard_current_step %}
  {% if s.state in ['idle', 'finished', 'unknown'] %}
  Nothing on the go.
  {% else %}
  ### {{ s.attributes.recipe }} — step {{ s.attributes.step_number }} of {{ s.attributes.of }}

  {{ s.attributes.step }}

  {% for line in s.attributes.needs %}- {{ line }}
  {% endfor %}
  {% if s.attributes.timer %}**{{ s.attributes.timer }}**{% endif %}
  {% if s.attributes.may_pause_after %}You can stop here and carry on later.{% endif %}
  {% endif %}
```

With two buttons under it, big enough for a knuckle:

```yaml
type: horizontal-stack
cards:
  - type: button
    name: Back
    icon: mdi:arrow-left
    tap_action:
      action: perform-action
      perform_action: recipe_wizard.previous_step
  - type: button
    name: Next
    icon: mdi:arrow-right
    tap_action:
      action: perform-action
      perform_action: recipe_wizard.next_step
```

### Announcing a step's timer

Because the step timer is a time of day, an automation can wait for it:

```yaml
automation:
  - alias: Say when the current step's time is up
    triggers:
      - trigger: template
        value_template: >-
          {{ has_value('sensor.recipe_wizard_step_timer')
             and as_datetime(states('sensor.recipe_wizard_step_timer')) <= now() }}
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            {{ state_attr('sensor.recipe_wizard_current_step', 'recipe') }}:
            time is up. Check {{ state_attr('sensor.recipe_wizard_step_timer', 'doneness')
            or 'the step' }}.
```

Note that it reads the doneness out and says it. That is the point: the time is a
guess and the state of the food is not.

## Using the shopping list

Recipe Wizard adds one to-do list, called **Recipe Wizard Shopping list**. You
will find it in the **To-do lists** panel in the sidebar, and you can put it on a
dashboard with a to-do list card.

It starts empty, because it does not yet know what you are cooking.

### Telling it what you are shopping for

There is one list, not one per recipe, so something has to say which recipe it is
for. That is the **Set shopping list** action.

In **Developer tools → Actions**, choose **Recipe Wizard: Set shopping list**, and
fill in:

* **Recipe** — the name of the recipe, or enough of the name to pick out just one.
  "Qeema" is enough; "buttercream" is not, if you have three of them. It will tell
  you which ones it matched so you can be more specific.
* **Batches** — how many batches you are making. 1 is the recipe as written, 2
  doubles it. Half batches are allowed.
* **Include optional parts** — leave this on unless you want to skip the parts of
  the recipe marked optional, such as a sauce that goes alongside.

In YAML, for a dashboard button or an automation:

```yaml
action: recipe_wizard.set_shopping_list
target:
  entity_id: todo.recipe_wizard_shopping_list
data:
  recipe: Vanilla cake
  batches: 2
```

The list fills in straight away. Choosing a different recipe starts a new list.

### What a line means

Each line is **one food to buy**, added up across the whole recipe — including
any sub-recipes it uses. A doubled vanilla cake needs butter in the cake and in
the buttercream, so the list says:

> **unsalted butter: 680 g**
> 230 g, cut into cubes — My Very Best Vanilla Cake
> 450 g — Vanilla buttercream

One thing to buy, on the first line. Two things to have ready, underneath. Tap or
click a line to see that second part.

Some lines cannot give you a weight, and they say so rather than guessing:

* **at least 500 g, plus 1 line with no weight** — part of the recipe gives an
  amount that cannot be turned into a weight, such as "a splash of milk". So the
  weight shown is a floor, not a total, and buying only that much may not be
  enough.
* **no weight given** — none of it could be weighed. This usually means the recipe
  has not been fully written up yet.
* **plus more to taste** — a recipe seasons with it rather than measuring it. Buy
  some; there is nothing to add up.
* **(optional)** — no part of what you are making needs it.
* **not in the library — see Dinner, p.308** — the recipe points at a cookbook
  rather than another recipe file. Recipe Wizard cannot know what is in it, so it
  puts the book reference on the list instead of a quantity, and leaves it out of
  the weights on purpose.

### Ticking things off, and adding your own

The list works like any other to-do list in Home Assistant:

* **Tick a line** as you put it in the trolley. Ticks are remembered — they
  survive Home Assistant restarting, and they survive you editing a recipe while
  you are out.
* **Add your own items.** Bin bags, milk for tea, anything. These are yours:
  Recipe Wizard never removes them, not when the recipes change, not when you
  restart, and not when you choose a different recipe.
* **Remove completed items** to clear the lines you have already got. Lines that
  came from the recipe come back the next time you choose a recipe, because the
  recipe still calls for them.

Two things it will not let you do, and why:

* **You cannot reword a line that came from a recipe.** Those words are worked out
  from the recipe file, so the next time Recipe Wizard reads the folder it would
  overwrite whatever you typed. Rather than lose your text quietly, it refuses and
  says so. Items you added yourself can be reworded freely.
* **You cannot reorder the list.** The order is the order the recipe lists its
  ingredients in, which is information worth keeping.

Choosing a new recipe clears the ticks, because they belonged to the last shop.
Choosing the *same* recipe and batch size again changes nothing, so a dashboard
button is safe to press twice.

If the list ever shows as **unavailable**, the recipe it was pointing at can no
longer be read — most often because the file was moved, renamed or deleted. The
reason is in **Settings → System → Logs**. Choose a recipe again to fix it.

## Keeping up with changes

Recipe Wizard checks the recipe folder **every 15 minutes**, so a recipe you add
or edit turns up on its own and you do not have to restart Home Assistant.

The check itself is deliberately cheap: it looks at *when* each file was last
changed and only re-reads the recipes when something has actually moved. Adding
a recipe is a thing you do a few times a week, not a few times a second, so 15
minutes is generous on purpose.

## Removing it

1. Go to **Settings → Devices & services**.
2. Find **Recipe Wizard**, open its three-dot menu and choose **Delete**.

That removes the integration's own settings, the shopping list, anything you had
ticked off or added to it, the **Recipes** entry in the sidebar, and any repair
notices it had raised about your recipes. **Your recipe files are not touched.** They are your own documents, they live outside
the integration folder, and nothing in Recipe Wizard ever deletes or edits them —
so you can delete the integration and add it back later against the same folder.

To remove the software as well, delete it in HACS, or delete the
`custom_components/recipe_wizard` folder if you installed it by hand, and then
restart Home Assistant.

## Things it does not do

Worth knowing before you rely on it:

* **The shopping list is for one recipe at a time.** There is one list, and the
  Set shopping list action says which recipe it is showing. A separate list for
  every recipe you own would mean hundreds of them, all but one of them useless.
  If you are cooking two things, shop for them one after the other, or add the
  second one's items yourself.
* **You edit recipes outside Home Assistant.** There is no screen for writing or
  changing a recipe. That is done with the command-line tool.
* **Nutrition is not calculated.** Recipe Wizard works in grams and millilitres,
  not calories or carbohydrates. If you are counting carbohydrates — for diabetes
  or any other reason — do not treat anything here as a nutrition figure, and talk
  to your care team about how you count. This is general information, not medical
  advice.
* **Some weights are honestly unknown.** Where a recipe gives a measure that
  cannot be turned into a weight — "a splash of milk", or a cup of something
  whose density is not known — the list says so rather than guessing. A shopping
  line can read *"at least 500 g, plus 1 line with no weight"*, and that is the
  truth rather than a gap.
* **Steps from different recipes are not woven together.** A cake and its
  frosting each get their own running order. Recipe Wizard will not decide to slot
  the frosting into the gap while the cake cools, because no recipe says it is
  safe to.
* **A timer is an estimate and does not go off.** Recipe Wizard tells you roughly
  when a step's stated time runs out and what to check when it does. It does not
  set an alarm for you, and it never claims the food is ready — that is what the
  doneness is for. If you want a sound, write an automation like the one above.
* **Recipes that point at a cookbook stay pointing at a cookbook.** If a recipe
  says "use the sauce on page 308", Recipe Wizard tells you to go and get the
  book. It leaves that off the shopping list on purpose rather than pretending it
  needs nothing.

## For contributors

The integration is a thin layer over `custom_components/recipe_wizard/core/`, a
stdlib-only library with no Home Assistant dependency. Two things follow from
that and are worth knowing before changing anything:

* `custom_components/recipe_wizard/__init__.py` must not import `homeassistant`
  at module scope. See
  [`adr/0002`](adr/0002-no-home-assistant-imports-at-module-scope.md);
  `tests/test_packaging.py` enforces it.
* Every call into the library goes through `hass.async_add_executor_job`. It does
  synchronous file I/O, and the event loop must not wait on a disk.

### The HTTP API is private

`http.py` serves two read-only views behind Home Assistant's own authentication:

```
GET /api/recipe_wizard/library
GET /api/recipe_wizard/dish/{recipe_id}?batches=1&include_optional=true
```

**They are private, they carry no version, and they may change in any release.**
They exist for the *Recipes* page this repository ships and for nothing else. The
payload is whatever `core/serialise.py` currently emits — a dish, which is
derived and disposable, not the format on disk — and its field names are not an
interface. Do not build anything outside this repository on them. If something
ever needs to read a dish over HTTP, that is a deliberate act with a versioned
path and a design pass behind it, not a thing that happened because an endpoint
was already there.

There is deliberately **no write endpoint and no cursor endpoint**. Moving a
cook-along goes through the four actions, which already validate and already say
what the cook got wrong; a second write path would be a second place that
validation lives. The cursor's position is already on
`sensor.recipe_wizard_current_step`, which the page reads over the websocket like
any other card.

There are two test suites, and they cannot share an interpreter — the Home
Assistant test harness installs autouse fixtures that attach to every test in the
session, which breaks all 220 library tests:

```bash
python -m pytest -q                 # the library, on bare Python, no Home Assistant
```

The integration suite needs Home Assistant and cannot run on Windows
(`homeassistant.runner` imports `fcntl`), so run it in a container:

```bash
docker build -t rw-hass-test tests_ha    # once
docker run --rm -v "$(pwd):/app" -w /app rw-hass-test \
    python -m pytest -q -o asyncio_mode=auto tests_ha
```

From Git Bash on Windows, keep the paths away from MSYS or the run never starts:
`MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/app" -w /app ...`. Without it
`-w /app` is rewritten to `C:/Program Files/Git/app`, and Docker rejecting that
looks like a Docker problem rather than a shell one.

`-o asyncio_mode=auto` is required; without it every test errors on the harness's
autouse async fixtures. Both suites also run in CI on `ubuntu-latest`, along with
`hassfest`, HACS validation and the type check — see `.github/workflows/ci.yml`.

The type check needs Home Assistant installed for the same reason the integration
suite does: nearly every annotation in the integration is one of its types, so
mypy without it reports fifty missing stubs and proves nothing. It takes no
arguments — `pyproject.toml` holds the file list, the strictness, and the reason
behind each place the strictness is narrowed:

```bash
pip install "mypy==2.3.1"       # into the same environment as homeassistant
python -m mypy
```

The integration modules are strict. `core/` is checked but not strictly, and the
short list of pre-existing findings it is silenced on is in `pyproject.toml` with
a note against each. That list should only ever get shorter.

`custom_components/recipe_wizard/quality_scale.yaml` records where the integration
stands against the Home Assistant quality scale, with a reason against every
exemption.
