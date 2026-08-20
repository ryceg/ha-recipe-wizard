/**
 * One step, said the way the format means it.
 *
 * Rendering only: it is handed the step, the cursor and an already-computed
 * countdown, and it emits `rw-next`, `rw-previous` and `rw-stop`. Nothing here
 * reads a clock or a source, which is what makes "awaiting check changes what is
 * on the screen" a test with no timing in it.
 *
 * The four things the domain will not let this element get wrong:
 *
 * * **What ends the step is `finishes_on`, not whether a timer happens to be
 *   set.** A `state` step is ended by the food and its time is an estimate of
 *   that; a `clock` step's time *is* the instruction and is not hedged; a `cook`
 *   step is over when they have done it. Guessing this from the presence of a
 *   number is how "beat the eggs for 30 seconds" comes to read as a guess.
 * * **The doneness outranks the countdown**, and once the estimate has run out
 *   the countdown is gone entirely: the step is not over, and the screen's job
 *   changes from counting to asking.
 * * **Attention** -- whether the cook can walk away -- is on the screen at all
 *   times, because it is the most useful thing on it.
 * * **Every sentence comes from the payload.** `needs[].text` is "4 tbsp smooth
 *   peanut butter (of 500 g)", with the portion scaled and no arithmetic
 *   pretending to know what 4 tbsp of peanut butter weighs; `timer` is
 *   "32 min, then check: edges firmish, centre still jiggling". Reassembling
 *   either from the parts beside them would be a second place that phrasing
 *   lives.
 */

import { LitElement, html, nothing, type TemplateResult } from "lit";
import { surfaceStyles } from "./styles.js";
import { formatRemaining, type Countdown } from "../countdown.js";
import type { Dish, Step } from "../payload.js";

const ATTENTION_TEXT: Record<string, string> = {
  active: "hands on",
  passive: "stay nearby",
  unattended: "you can walk away",
};

export class RecipeWizardStep extends LitElement {
  static override styles = [surfaceStyles];

  static override properties = {
    dish: { attribute: false },
    step: { attribute: false },
    countdown: { attribute: false },
    position: { type: Number },
    of: { type: Number },
    busy: { type: Boolean },
  };

  dish: Dish | null = null;
  step: Step | null = null;
  countdown: Countdown = { remainingMs: null, passed: false, awaitingCheck: false };
  position = 0;
  of = 0;
  busy = false;

  override render(): TemplateResult {
    const step = this.step;
    if (!step) return html`<p class="muted">Nothing on the go.</p>`;

    return html`
      <div class="row spread">
        <span class="position">${this.position}/${this.of}</span>
        <button type="button" @click=${() => this.emit("rw-stop")}>Stop</button>
      </div>
      <h2>${step.label}</h2>
      ${this.dish && this.dish.label !== step.label
        ? html`<p class="muted">for ${this.dish.label}</p>`
        : nothing}
      ${step.attention
        ? html`<span class="attention ${step.attention}"
            >${step.attention} · ${ATTENTION_TEXT[step.attention]}</span
          >`
        : nothing}
      <p class="step-text">${step.text}</p>
      ${this.needs(step)} ${this.timing(step)}
      ${step.safety_note ? html`<p class="note">${step.safety_note}</p>` : nothing}
      <div class="movement">
        <button type="button" ?disabled=${this.busy} @click=${() => this.emit("rw-previous")}>
          Back
        </button>
        <button
          type="button"
          class="primary"
          ?disabled=${this.busy}
          @click=${() => this.emit("rw-next")}
        >
          ${this.countdown.awaitingCheck ? "It's ready — next" : "Next"}
        </button>
      </div>
    `;
  }

  private needs(step: Step): TemplateResult | typeof nothing {
    if (!step.needs.length) return nothing;
    return html`
      <ul class="needs">
        ${step.needs.map(
          (needed) => html`
            <li>
              ${needed.text}${needed.optional ? html` <span class="muted">(optional)</span>` : nothing}
              ${needed.required_state
                ? html`<span class="state">${needed.required_state.description}</span>`
                : nothing}
              ${needed.note ? html`<span class="state">${needed.note}</span>` : nothing}
            </li>
          `,
        )}
      </ul>
    `;
  }

  /**
   * The timer, and the thing that outranks it.
   *
   * `timer_starts_when` gets no countdown at all: the clock starts on something
   * at the bench -- the water coming back to the boil -- that nothing on this
   * screen can see, so the stated time is shown and the cook starts it.
   */
  private timing(step: Step): TemplateResult | typeof nothing {
    const { remainingMs, passed, awaitingCheck } = this.countdown;

    if (step.finishes_on === "state") {
      return html`
        <div class="timing ${awaitingCheck ? "awaiting" : ""}">
          <p class="doneness">
            <span class="lead">${awaitingCheck ? "Check now" : "Ends when"}</span>
            ${step.doneness ?? "the food says so"}
          </p>
          ${awaitingCheck
            ? html`<p class="stated">
                The estimate has run out. The step is over when it looks like that, not before.
              </p>`
            : remainingMs !== null
              ? html`
                  <p class="countdown estimate">${formatRemaining(remainingMs)}</p>
                  <p class="stated">estimated · ${step.timer}</p>
                `
              : step.timer
                ? html`<p class="stated">estimated · ${step.timer}</p>`
                : nothing}
          ${step.timer_starts_when
            ? html`<p class="stated">Timer starts when ${step.timer_starts_when}.</p>`
            : nothing}
        </div>
      `;
    }

    if (step.finishes_on === "clock") {
      return html`
        <div class="timing">
          ${remainingMs !== null && !passed
            ? html`<p class="countdown">${formatRemaining(remainingMs)}</p>`
            : remainingMs !== null
              ? html`<p class="countdown">Time's up</p>`
              : nothing}
          ${step.timer ? html`<p class="stated">${step.timer}</p>` : nothing}
          ${step.timer_starts_when
            ? html`<p class="stated">Timer starts when ${step.timer_starts_when}.</p>`
            : nothing}
        </div>
      `;
    }

    // `cook`: neither a state nor a time, so it is done when they have done it.
    // Nothing is counted and nothing is claimed.
    return html`<p class="stated">Done when you have done it.</p>`;
  }

  private emit(name: string): void {
    this.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true }));
  }
}

customElements.define("recipe-wizard-step", RecipeWizardStep);

declare global {
  interface HTMLElementTagNameMap {
    "recipe-wizard-step": RecipeWizardStep;
  }
}
