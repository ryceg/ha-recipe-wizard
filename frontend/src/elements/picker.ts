/**
 * What there is to cook, and how many batches of it.
 *
 * The one rule this element exists to keep: **a family is not a recipe**. A
 * family is a browsing tag that groups siblings -- chocolate and vanilla
 * buttercream fill the same role without either being a patch on the other --
 * and nothing resolves through one. So a family is drawn as a heading and never
 * as a row a thumb can land on: handing `family:buttercream` to `start` where a
 * recipe is expected fails, and the place to make that impossible is here,
 * rather than in an error message after the tap.
 *
 * Recipes carrying no family are listed on their own beneath, in the order the
 * library sent them, which is by name.
 */

import { LitElement, html, nothing, type TemplateResult } from "lit";
import { surfaceStyles } from "./styles.js";
import type { LibraryIndex, RecipeSummary } from "../payload.js";

export interface CookRequest {
  recipeId: string;
  batches: number;
}

export class RecipeWizardPicker extends LitElement {
  static override styles = [surfaceStyles];

  static override properties = {
    index: { attribute: false },
    chosen: { state: true },
    batches: { state: true },
  };

  index: LibraryIndex | null = null;
  chosen: string | null = null;
  batches = 1;

  override render(): TemplateResult {
    if (!this.index) return html`<p class="muted">Reading the library…</p>`;

    const byId = new Map(this.index.recipes.map((recipe) => [recipe.id, recipe]));
    const grouped = new Set<string>();
    const families = this.index.families.map((family) => {
      const members = family.members
        .map((id) => byId.get(id))
        .filter((recipe): recipe is RecipeSummary => recipe !== undefined);
      for (const recipe of members) grouped.add(recipe.id);
      return { family, members };
    });
    const loose = this.index.recipes.filter((recipe) => !grouped.has(recipe.id));

    return html`
      <h2>What are we cooking?</h2>
      ${families.map(
        ({ family, members }) => html`
          <!-- A heading. Nothing resolves through a family, so nothing here is
               a button. -->
          <h3 class="family">${family.name}</h3>
          ${this.recipeList(members)}
        `,
      )}
      ${loose.length ? this.recipeList(loose) : nothing}
      ${this.chosen ? this.batchesControl() : nothing}
    `;
  }

  private recipeList(recipes: RecipeSummary[]): TemplateResult {
    return html`
      <ul class="recipes">
        ${recipes.map(
          (recipe) => html`
            <li>
              <button
                type="button"
                aria-pressed=${this.chosen === recipe.id ? "true" : "false"}
                @click=${() => this.choose(recipe.id)}
              >
                ${recipe.name}
              </button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  private batchesControl(): TemplateResult {
    const name = this.index?.recipes.find((recipe) => recipe.id === this.chosen)?.name ?? "";
    return html`
      <div class="batches">
        <h3>How many batches of ${name}?</h3>
        <div class="row">
          <button
            type="button"
            aria-label="Fewer batches"
            ?disabled=${this.batches <= 0.5}
            @click=${() => this.step(-0.5)}
          >
            −
          </button>
          <output>×${this.batches}</output>
          <button
            type="button"
            aria-label="More batches"
            ?disabled=${this.batches >= 20}
            @click=${() => this.step(0.5)}
          >
            +
          </button>
        </div>
        <div class="movement">
          <span></span>
          <button type="button" class="primary" @click=${this.cook}>Start cooking</button>
        </div>
      </div>
    `;
  }

  private choose(recipeId: string): void {
    this.chosen = this.chosen === recipeId ? null : recipeId;
  }

  private step(by: number): void {
    // Halves, because halving a recipe is a thing cooks do and the resolver
    // takes a plain factor. Rounded to avoid 1.5000000000000002 on the screen.
    this.batches = Math.round(Math.min(20, Math.max(0.5, this.batches + by)) * 2) / 2;
  }

  private cook(): void {
    if (!this.chosen) return;
    this.dispatchEvent(
      new CustomEvent<CookRequest>("rw-cook", {
        detail: { recipeId: this.chosen, batches: this.batches },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

customElements.define("recipe-wizard-picker", RecipeWizardPicker);

declare global {
  interface HTMLElementTagNameMap {
    "recipe-wizard-picker": RecipeWizardPicker;
  }
}
