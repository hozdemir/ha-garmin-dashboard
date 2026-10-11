import { LitElement, css, html, nothing, type TemplateResult } from "lit";

import { CHARTS, TILE_SECTIONS, TREND_RANGES, type Preferences, type SectionId } from "./catalog";
import { hasMessage, type MessageKey, type Translate } from "./i18n";

/** Sections that exist in this release (activities arrives with the Activities screen). */
const SETTABLE_SECTIONS: SectionId[] = ["movement", "recovery", "training", "gear"];

/** Settings view: edits a draft copy, emits `save` or `cancel`. */
export class GarminSettings extends LitElement {
  static override properties = {
    preferences: { attribute: false },
    available: { attribute: false },
    t: { attribute: false },
    busy: { type: Boolean },
    _draft: { state: true },
  };

  preferences?: Preferences;
  /** Metric keys this account provides; others are not offered. */
  available: Set<string> = new Set();
  t?: Translate;
  busy = false;
  private _draft?: Preferences;

  protected override willUpdate(): void {
    if (!this._draft && this.preferences) this._draft = structuredClone(this.preferences);
  }

  private _label(key: string): string {
    return hasMessage(key) ? this.t!(key as MessageKey) : key;
  }

  private _toggle(list: "hidden_sections" | "hidden_metrics" | "hidden_charts", key: string, visible: boolean): void {
    const draft = this._draft!;
    const set = new Set<string>(draft[list]);
    if (visible) set.delete(key);
    else set.add(key);
    this._draft = { ...draft, [list]: [...set] };
  }

  private _move(section: SectionId, delta: number): void {
    // Reorder only the sections shown here; keep the rest after them.
    const all = this._draft!.section_order;
    const order = all.filter((s) => SETTABLE_SECTIONS.includes(s));
    const index = order.indexOf(section);
    const target = index + delta;
    if (index < 0 || target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target]!, order[index]!];
    const rest = all.filter((s) => !SETTABLE_SECTIONS.includes(s));
    this._draft = { ...this._draft!, section_order: [...order, ...rest] };
  }

  private _emit(name: "save" | "cancel" | "reset", detail?: Preferences): void {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
  }

  protected override render(): TemplateResult {
    const t = this.t;
    const draft = this._draft;
    if (!t || !draft) return html``;
    const order = draft.section_order.filter((s) => SETTABLE_SECTIONS.includes(s));
    return html`
      <form @submit=${(e: Event) => { e.preventDefault(); this._emit("save", this._draft); }}>
        <fieldset>
          <legend>${t("settings_sections")}</legend>
          <p class="hint">${t("settings_sections_hint")}</p>
          <ol class="order">
            ${order.map((section, i) => html`
              <li>
                <label>
                  <input type="checkbox" .checked=${!draft.hidden_sections.includes(section)}
                    @change=${(e: Event) => this._toggle("hidden_sections", section, (e.target as HTMLInputElement).checked)} />
                  ${this._label(`section_${section}`)}
                </label>
                <span class="moves">
                  <button type="button" ?disabled=${i === 0} @click=${() => this._move(section, -1)} aria-label="${t("move_up")}: ${this._label(`section_${section}`)}">↑</button>
                  <button type="button" ?disabled=${i === order.length - 1} @click=${() => this._move(section, 1)} aria-label="${t("move_down")}: ${this._label(`section_${section}`)}">↓</button>
                </span>
              </li>`)}
          </ol>
        </fieldset>

        <fieldset>
          <legend>${t("settings_metrics")}</legend>
          ${TILE_SECTIONS.map((section) => {
            const keys = section.keys.filter((k) => this.available.has(k));
            if (!keys.length) return nothing;
            return html`
              <h4>${this._label(`section_${section.id}`)}</h4>
              <div class="checks">
                ${keys.map((key) => html`
                  <label><input type="checkbox" .checked=${!draft.hidden_metrics.includes(key)}
                    @change=${(e: Event) => this._toggle("hidden_metrics", key, (e.target as HTMLInputElement).checked)} />
                    ${this._label(`metric_${key}`)}</label>`)}
              </div>`;
          })}
        </fieldset>

        <fieldset>
          <legend>${t("settings_charts")}</legend>
          ${(["today", "trends"] as const).map((group) => {
            const charts = CHARTS.filter((c) => c.group === group && c.metrics.some((m) => this.available.has(m)));
            if (!charts.length) return nothing;
            return html`
              <h4>${t(`group_${group}`)}</h4>
              <div class="checks">
                ${charts.map((chart) => html`
                  <label><input type="checkbox" .checked=${!draft.hidden_charts.includes(chart.id)}
                    @change=${(e: Event) => this._toggle("hidden_charts", chart.id, (e.target as HTMLInputElement).checked)} />
                    ${this._label(`chart_${chart.id}`)}</label>`)}
              </div>`;
          })}
          <label class="inline">
            ${t("settings_trend_range")}
            <select @change=${(e: Event) => (this._draft = { ...draft, trend_range_days: Number((e.target as HTMLSelectElement).value) })}>
              ${TREND_RANGES.map((d) => html`<option value=${d} ?selected=${draft.trend_range_days === d}>${t("range_days", { days: String(d) })}</option>`)}
            </select>
          </label>
        </fieldset>

        <div class="actions">
          <button type="submit" class="primary" ?disabled=${this.busy}>${t("save")}</button>
          <button type="button" @click=${() => this._emit("cancel")}>${t("cancel")}</button>
          <button type="button" class="right" @click=${() => { if (confirm(t("reset_confirm"))) this._emit("reset"); }}>${t("reset_defaults")}</button>
        </div>
      </form>
    `;
  }

  static override styles = css`
    :host { display: block; max-width: 720px; }
    fieldset {
      border: 1px solid var(--divider-color, #ddd); border-radius: var(--ha-card-border-radius, 12px);
      background: var(--card-background-color); margin: 0 0 16px; padding: 12px 16px 16px; min-width: 0;
    }
    legend { font-weight: 500; padding: 0 4px; }
    h4 { margin: 12px 0 4px; font-size: 13px; font-weight: 500; color: var(--secondary-text-color); }
    .hint { margin: 0 0 8px; font-size: 13px; color: var(--secondary-text-color); }
    .order { list-style: none; margin: 0; padding: 0; }
    .order li { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--divider-color, #eee); }
    .order li:last-child { border-bottom: 0; }
    .checks { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); column-gap: 12px; }
    label { display: flex; align-items: center; gap: 8px; min-height: 44px; }
    label.inline { margin-top: 8px; flex-wrap: wrap; }
    input[type="checkbox"] { width: 20px; height: 20px; margin: 0; }
    select { min-height: 44px; font: inherit; }
    button {
      min-height: 44px; min-width: 44px; padding: 0 16px; font: inherit; border-radius: 8px; cursor: pointer;
      border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color); color: var(--primary-text-color);
    }
    button:disabled { opacity: 0.4; cursor: default; }
    button.primary { background: var(--primary-color); color: var(--text-primary-color, #fff); border-color: transparent; padding: 0 20px; }
    button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .moves { display: flex; gap: 4px; }
    .moves button { padding: 0; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .actions .right { margin-left: auto; }
  `;
}

if (!customElements.get("garmin-settings")) {
  customElements.define("garmin-settings", GarminSettings);
}
