/**
 * Mount two: a card on a dashboard.
 *
 * The same surface as the panel, in a `ha-card`, because a cook-along on the
 * kitchen dashboard beside the lights and the oven is where most people will
 * actually meet it. Nothing about the surface changes -- the buttons stay big,
 * the doneness still outranks the countdown -- since the card is likely the only
 * thing being looked at while the batter is going.
 *
 * The Lovelace contract a card has to honour is small: `setConfig` throws on a
 * configuration it cannot render, `getCardSize` says roughly how tall it is, and
 * `hass` is set on it repeatedly. The two entity ids are configurable and
 * default to the integration's own, which is all that is needed while
 * `single_config_entry` is true; if a second library ever exists, the config is
 * already the place that would say which one.
 */

import { LitElement, css, html, type TemplateResult } from "lit";
import "./elements/surface.js";
import {
  CURRENT_STEP_ENTITY,
  HassCookAlongSource,
  STEP_TIMER_ENTITY,
  type Hass,
} from "./hass-source.js";
import { SystemClock } from "./clock.js";

export interface RecipeWizardCardConfig {
  type: string;
  current_step_entity?: string;
  step_timer_entity?: string;
}

export class RecipeWizardCard extends LitElement {
  static override styles = css`
    ha-card {
      padding: 20px;
    }
  `;

  private source: HassCookAlongSource | null = null;
  private readonly clock = new SystemClock();
  private hassObject: Hass | null = null;

  static getStubConfig(): RecipeWizardCardConfig {
    return { type: "custom:recipe-wizard-card" };
  }

  setConfig(config: RecipeWizardCardConfig): void {
    if (typeof config !== "object" || config === null) {
      throw new Error("A recipe-wizard card needs a configuration.");
    }
    this.source = new HassCookAlongSource({
      currentStepEntity: config.current_step_entity ?? CURRENT_STEP_ENTITY,
      stepTimerEntity: config.step_timer_entity ?? STEP_TIMER_ENTITY,
    });
    if (this.hassObject) this.source.update(this.hassObject);
    this.requestUpdate();
  }

  /** Tall: a step, what it needs, and two buttons a knuckle can find. */
  getCardSize(): number {
    return 10;
  }

  set hass(hass: Hass) {
    this.hassObject = hass;
    this.source?.update(hass);
  }

  override render(): TemplateResult {
    return html`
      <ha-card>
        <recipe-wizard-surface
          .source=${this.source}
          .clock=${this.clock}
        ></recipe-wizard-surface>
      </ha-card>
    `;
  }
}

customElements.define("recipe-wizard-card", RecipeWizardCard);

declare global {
  interface HTMLElementTagNameMap {
    "recipe-wizard-card": RecipeWizardCard;
  }
}
