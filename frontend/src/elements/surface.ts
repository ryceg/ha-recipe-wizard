/**
 * The surface itself: pick a recipe, set the batches, and cook along.
 *
 * A *surface* is a place a cook reads a dish or drives a cook-along, and there
 * are several -- the command line, the sensors, paper, this. Exactly one owns
 * the cursor, and it is not this: the cursor lives in the config entry's options
 * on the Home Assistant side, which is what brings a cook back to the brownies'
 * three-hour chill after a restart. This element **asks** where the cook is and
 * **asks** to move; it never keeps its own idea of the position, because the
 * moment two surfaces keep one they disagree, and the cook is the one who finds
 * out.
 *
 * It knows nothing about where it is mounted. Both mounts hand it the same two
 * ports and it renders the same screen inside a panel and inside a card.
 *
 * **The dish comes over HTTP, not out of the cursor.** The entity's attributes
 * carry most of a step and it is tempting to render the whole screen from them,
 * but they are sized for dashboards and templates rather than as a wire format.
 * A change to the cursor is therefore an *invalidation signal*: re-read where
 * the cook is, and fetch the dish again when the answer no longer fits the dish
 * in hand -- a different recipe, a different scale, or a step that is not in it,
 * which is exactly what a recipe edited on disk under a running cook looks like.
 *
 * Left room for, and deliberately not built: the Modernist table, the plan and
 * the shopping list. All three are already in the dish payload, so each is a
 * section added to this render and nothing else.
 */

import { LitElement, html, nothing, type TemplateResult } from "lit";
import { surfaceStyles } from "./styles.js";
import "./picker.js";
import "./step.js";
import type { CookRequest } from "./picker.js";
import { countdown, nextTick, type Countdown } from "../countdown.js";
import type { Dish, LibraryIndex, Step } from "../payload.js";
import { IDLE, type Clock, type CookAlongSource, type CursorState, type Unsubscribe } from "../ports.js";
import { SystemClock } from "../clock.js";

export class RecipeWizardSurface extends LitElement {
  static override styles = [surfaceStyles];

  static override properties = {
    source: { attribute: false },
    clock: { attribute: false },
    index: { state: true },
    dish: { state: true },
    cursor: { state: true },
    busy: { state: true },
    error: { state: true },
    tick: { state: true },
  };

  source: CookAlongSource | null = null;
  clock: Clock = new SystemClock();
  index: LibraryIndex | null = null;
  dish: Dish | null = null;
  cursor: CursorState = IDLE;
  busy = false;
  error: string | null = null;
  /** Bumped by the clock so the countdown redraws. Its value means nothing. */
  tick = 0;

  private unsubscribe: Unsubscribe | null = null;
  private cancelTick: Unsubscribe | null = null;
  /** What the dish in hand was fetched for, so a re-render does not re-fetch. */
  private fetchedFor: string | null = null;

  override connectedCallback(): void {
    super.connectedCallback();
    this.attach();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this.unsubscribe?.();
    this.unsubscribe = null;
    this.cancelTick?.();
    this.cancelTick = null;
  }

  override willUpdate(changed: Map<string, unknown>): void {
    if (changed.has("source")) this.attach();
  }

  private attach(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    const source = this.source;
    if (!source || !this.isConnected) return;
    this.unsubscribe = source.subscribe(() => this.sync());
    void source
      .library()
      .then((index) => {
        this.index = index;
      })
      .catch((reason) => this.blame(reason));
    this.sync();
  }

  /** Read the cursor, and fetch the dish if the one in hand no longer answers. */
  private sync(): void {
    const source = this.source;
    if (!source) return;
    this.cursor = source.cursor();
    const { status, recipeId, batches } = this.cursor;
    if (status === "idle" || recipeId === undefined) {
      this.dish = null;
      this.fetchedFor = null;
      return;
    }
    const wanted = `${recipeId}|${batches ?? 1}`;
    const stale = this.fetchedFor !== wanted || (status === "cooking" && this.step() === null);
    if (!stale) return;
    this.fetchedFor = wanted;
    void source
      .dish(recipeId, batches ?? 1)
      .then((dish) => {
        this.dish = dish;
        this.error = null;
      })
      .catch((reason) => {
        this.fetchedFor = null;
        this.blame(reason);
      });
  }

  /**
   * Which step the cook is on, found by **(step recipe, step)** and not by the
   * number beside it (ADR 0003). The walk is the dish's own steps followed by
   * each component's, so a step added to a *sub-recipe* renumbers the parent
   * from that point on and an index silently moves the cook. The position is
   * only the fallback, for a cursor that has not yet been told its step id.
   */
  private step(): Step | null {
    const dish = this.dish;
    const { stepId, stepRecipeId, position } = this.cursor;
    if (!dish) return null;
    if (stepId !== undefined) {
      const found = dish.steps.find(
        (step) =>
          step.step_id === stepId &&
          (stepRecipeId === undefined || step.recipe_id === stepRecipeId),
      );
      if (found) return found;
      if (stepRecipeId !== undefined) return null;
    }
    if (position !== undefined && position >= 1 && position <= dish.steps.length) {
      return dish.steps[position - 1]!;
    }
    return null;
  }

  private countdown(step: Step): Countdown {
    return countdown(step, this.cursor, this.clock.now());
  }

  override updated(): void {
    // One wake-up, for the next whole second this screen needs -- rather than a
    // ticker running through a three-hour chill.
    this.cancelTick?.();
    this.cancelTick = null;
    const step = this.step();
    if (!step || this.cursor.status !== "cooking") return;
    const { remainingMs, passed } = this.countdown(step);
    if (remainingMs === null || passed) return;
    const at = nextTick(remainingMs, this.clock.now());
    if (at === null) return;
    this.cancelTick = this.clock.schedule(at, () => {
      this.tick += 1;
    });
  }

  override render(): TemplateResult {
    if (!this.source) return html`<p class="muted">No cook-along source.</p>`;
    return html`
      ${this.error ? html`<p class="error">${this.error}</p>` : nothing} ${this.body()}
    `;
  }

  private body(): TemplateResult {
    switch (this.cursor.status) {
      case "idle":
        return html`
          <recipe-wizard-picker .index=${this.index} @rw-cook=${this.onCook}></recipe-wizard-picker>
        `;
      case "unknown":
        return html`
          <h2>Something is wrong with this recipe</h2>
          <p class="note">${this.cursor.problem ?? "The recipe will not resolve."}</p>
          <button type="button" @click=${this.onStop}>Stop</button>
        `;
      case "finished":
        return html`
          <h2>${this.dish?.label ?? "Done"}</h2>
          <p class="step-text">That's the last step. Enjoy it.</p>
          <div class="movement">
            <button type="button" @click=${this.onPrevious}>Back</button>
            <button type="button" class="primary" @click=${this.onStop}>Finish</button>
          </div>
        `;
      case "cooking":
        return this.cooking();
    }
  }

  private cooking(): TemplateResult {
    const step = this.step();
    if (!step) return html`<p class="muted">Finding where you are…</p>`;
    return html`
      <recipe-wizard-step
        .dish=${this.dish}
        .step=${step}
        .countdown=${this.countdown(step)}
        .position=${this.cursor.position ?? step.cursor + 1}
        .of=${this.cursor.of ?? step.of}
        ?busy=${this.busy}
        @rw-next=${this.onNext}
        @rw-previous=${this.onPrevious}
        @rw-stop=${this.onStop}
      ></recipe-wizard-step>
      ${this.findings()}
    `;
  }

  /**
   * The resolver's warnings: the tins will not hold a doubled cake, the batch
   * was rounded to whole eggs. Nothing is wrong with the document and the dish
   * is one a cook can work from -- which is why they are shown here, quietly and
   * always, rather than refused up front or dropped.
   */
  private findings(): TemplateResult | typeof nothing {
    const findings = this.dish?.findings ?? [];
    if (!findings.length) return nothing;
    return html`
      <ul class="findings">
        ${findings.map((finding) => html`<li>${finding.message}</li>`)}
      </ul>
    `;
  }

  private onCook(event: CustomEvent<CookRequest>): void {
    const { recipeId, batches } = event.detail;
    void this.run(() => this.source!.start(recipeId, batches));
  }

  private onNext(): void {
    void this.run(() => this.source!.next());
  }

  private onPrevious(): void {
    void this.run(() => this.source!.previous());
  }

  private onStop(): void {
    void this.run(() => this.source!.stop());
  }

  /** Movements are disabled while one is in flight: a cook drumming Next on a
   * slow connection should not skip three steps when they all land. */
  private async run(movement: () => Promise<void>): Promise<void> {
    if (this.busy || !this.source) return;
    this.busy = true;
    this.error = null;
    try {
      await movement();
      this.sync();
    } catch (reason) {
      this.blame(reason);
    } finally {
      this.busy = false;
    }
  }

  private blame(reason: unknown): void {
    this.error = reason instanceof Error ? reason.message : String(reason);
  }
}

customElements.define("recipe-wizard-surface", RecipeWizardSurface);

declare global {
  interface HTMLElementTagNameMap {
    "recipe-wizard-surface": RecipeWizardSurface;
  }
}
