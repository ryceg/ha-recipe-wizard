/**
 * How the surface looks, in one place, because both mounts are the same screen.
 *
 * Two things here are not taste. **Everything is big**: this runs on a kitchen
 * wall tablet, read from across the room, tapped with a knuckle because the
 * cook's hands are covered in batter, and it may be the only thing on screen.
 * Next and Back are the primary controls and are sized like it -- the minimum
 * hit target is 64 px and the two of them fill the width.
 *
 * And **the doneness is never quieter than the countdown**. A step reading
 * "32 min, then check: edges firmish, centre still jiggling" is not a promise
 * about 32 minutes; the state is what decides and the time is an estimate of it.
 * A screen that renders the number in the big type and the state in the small
 * type would teach the opposite of what the format spent its design on, so the
 * doneness gets the accent colour and its own block, and the countdown sits
 * under it labelled as the estimate it is.
 *
 * Colours come from Home Assistant's theme variables with plain fallbacks, so
 * the same file renders in a dashboard, on a full page, and in a dev server with
 * no Home Assistant behind it at all.
 */

import { css } from "lit";

export const surfaceStyles = css`
  :host {
    --rw-text: var(--primary-text-color, #212121);
    --rw-dim: var(--secondary-text-color, #727272);
    --rw-accent: var(--primary-color, #03a9f4);
    --rw-surface: var(--card-background-color, var(--ha-card-background, #fff));
    --rw-line: var(--divider-color, #e0e0e0);
    --rw-alert: var(--error-color, #db4437);
    --rw-warn: var(--warning-color, #ffa600);
    --rw-radius: var(--ha-card-border-radius, 12px);

    display: block;
    color: var(--rw-text);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    font-size: 18px;
    line-height: 1.45;
    box-sizing: border-box;
  }

  *,
  *::before,
  *::after {
    box-sizing: inherit;
  }

  h2,
  h3 {
    margin: 0;
    font-weight: 500;
  }

  .muted {
    color: var(--rw-dim);
  }

  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .spread {
    justify-content: space-between;
  }

  /* -- controls ---------------------------------------------------------- */

  button {
    font: inherit;
    color: inherit;
    background: none;
    border: 2px solid var(--rw-line);
    border-radius: var(--rw-radius);
    padding: 12px 18px;
    min-height: 56px;
    cursor: pointer;
    touch-action: manipulation;
  }

  button:disabled {
    opacity: 0.4;
    cursor: default;
  }

  button.primary {
    background: var(--rw-accent);
    border-color: var(--rw-accent);
    color: var(--text-primary-color, #fff);
  }

  /* The two the cook actually hits, mid-recipe, without looking properly. */
  .movement {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 12px;
    margin-top: 24px;
  }

  .movement button {
    min-height: 76px;
    font-size: 22px;
    font-weight: 500;
  }

  /* -- the step ---------------------------------------------------------- */

  .position {
    font-variant-numeric: tabular-nums;
    font-size: 15px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--rw-dim);
  }

  .step-text {
    font-size: 28px;
    line-height: 1.3;
    margin: 16px 0;
  }

  .attention {
    display: inline-block;
    border: 2px solid currentColor;
    border-radius: 999px;
    padding: 2px 12px;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .attention.active {
    color: var(--rw-alert);
  }

  .attention.passive {
    color: var(--rw-warn);
  }

  .attention.unattended {
    color: var(--rw-accent);
  }

  .needs {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--rw-line);
  }

  .needs li {
    padding: 10px 0;
    border-bottom: 1px solid var(--rw-line);
    font-size: 20px;
  }

  .needs .state {
    display: block;
    font-size: 16px;
    color: var(--rw-dim);
  }

  /* -- the timer, and the thing that outranks it ------------------------- */

  .timing {
    margin-top: 20px;
    padding: 16px;
    border: 2px solid var(--rw-line);
    border-radius: var(--rw-radius);
  }

  .timing.awaiting {
    border-color: var(--rw-warn);
  }

  .doneness {
    font-size: 24px;
    line-height: 1.3;
  }

  .doneness .lead {
    display: block;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--rw-warn);
  }

  .countdown {
    font-variant-numeric: tabular-nums;
    font-size: 40px;
    line-height: 1.1;
    margin-top: 8px;
  }

  .countdown.estimate {
    font-size: 30px;
    color: var(--rw-dim);
  }

  .stated {
    font-size: 17px;
    color: var(--rw-dim);
  }

  .note {
    margin-top: 12px;
    padding-left: 12px;
    border-left: 4px solid var(--rw-alert);
    font-size: 17px;
  }

  .findings {
    margin-top: 16px;
    padding-left: 12px;
    border-left: 4px solid var(--rw-warn);
    font-size: 16px;
    color: var(--rw-dim);
  }

  /* -- the picker -------------------------------------------------------- */

  .family {
    margin: 20px 0 6px;
    font-size: 15px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--rw-dim);
  }

  .recipes {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .recipes li {
    margin: 8px 0;
  }

  .recipes button {
    width: 100%;
    text-align: left;
    font-size: 20px;
    min-height: 64px;
  }

  .recipes button[aria-pressed="true"] {
    border-color: var(--rw-accent);
  }

  .batches {
    margin-top: 20px;
  }

  .batches output {
    font-variant-numeric: tabular-nums;
    font-size: 28px;
    min-width: 3ch;
    text-align: center;
  }

  .batches button {
    min-width: 64px;
    font-size: 26px;
  }

  .error {
    color: var(--rw-alert);
    margin-top: 12px;
  }
`;
