/**
 * Mount one: the whole page.
 *
 * Home Assistant registers a custom panel by URL path and sets `hass`, `narrow`,
 * `route` and `panel` as properties on this element. All this does is hand the
 * surface its two ports and give it a page to sit on -- a wall tablet in a
 * kitchen may have nothing else on the screen, so the content is centred, capped
 * at a readable measure, and the surface fills it.
 *
 * `hass` is a plain accessor rather than a reactive property on purpose. A fresh
 * `hass` arrives on every state write in the whole system, and re-rendering this
 * element for a light in the hall would be silly; the source filters those and
 * tells the surface only when the cook-along actually moved.
 */

import { LitElement, css, html, type TemplateResult } from "lit";
import "./elements/surface.js";
import { HassCookAlongSource, type Hass } from "./hass-source.js";
import { SystemClock } from "./clock.js";

export class RecipeWizardPanel extends LitElement {
  static override styles = css`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color, #fafafa);
      padding: 16px;
      box-sizing: border-box;
    }

    .page {
      max-width: 720px;
      margin: 0 auto;
      padding: 24px;
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, 0.14));
      box-sizing: border-box;
    }
  `;

  private readonly source = new HassCookAlongSource();
  private readonly clock = new SystemClock();

  set hass(hass: Hass) {
    this.source.update(hass);
  }

  override render(): TemplateResult {
    return html`
      <div class="page">
        <recipe-wizard-surface
          .source=${this.source}
          .clock=${this.clock}
        ></recipe-wizard-surface>
      </div>
    `;
  }
}

customElements.define("recipe-wizard-panel", RecipeWizardPanel);

declare global {
  interface HTMLElementTagNameMap {
    "recipe-wizard-panel": RecipeWizardPanel;
  }
}
