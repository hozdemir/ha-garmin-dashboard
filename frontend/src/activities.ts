import { LitElement, css, html, nothing, type TemplateResult } from "lit";

import { formatDistance, formatNumber, formatSpeedOrPace, type FormatContext } from "./format";
import { sportLabel, type Translate } from "./i18n";
import type { Activity } from "./types";

/** Recent activities with a sport filter and expandable details. */
export class GarminActivities extends LitElement {
  static override properties = {
    activities: { attribute: false },
    truncated: { type: Boolean },
    disabled: { type: Boolean },
    fmt: { attribute: false },
    t: { attribute: false },
    _sport: { state: true },
    _open: { state: true },
  };

  activities: Activity[] = [];
  truncated = false;
  /** The source's activity sensors are turned off. */
  disabled = false;
  fmt: FormatContext = { locale: "en", lengthUnit: "km" };
  t?: Translate;
  private _sport = "";
  private _open?: string;

  private _date(iso: string | null): string {
    if (!iso) return "—";
    return new Date(iso).toLocaleString(this.fmt.locale, {
      weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
    });
  }

  protected override render(): TemplateResult {
    const t = this.t;
    if (!t) return html``;
    if (this.disabled) return html`<p class="note">${t("activities_disabled")}</p>`;
    if (!this.activities.length) return html`<p class="note">${t("activities_empty")}</p>`;
    const sports = [...new Set(this.activities.map((a) => a.sport))];
    const sport = sports.includes(this._sport) ? this._sport : "";
    const shown = sport ? this.activities.filter((a) => a.sport === sport) : this.activities;
    return html`
      <p class="note">
        ${t("activities_source_note", { count: String(this.activities.length) })}
        ${this.truncated ? html` · ${t("activities_truncated", { count: String(this.activities.length) })}` : nothing}
      </p>
      ${sports.length > 1
        ? html`<div class="chips" role="radiogroup" aria-label=${t("activities_filter")}>
            ${["", ...sports].map((s) => html`<button role="radio" aria-checked=${s === sport}
              @click=${() => (this._sport = s)}>${s ? sportLabel(t, s) : t("activities_all")}</button>`)}
          </div>`
        : nothing}
      <ul class="list">${shown.map((a) => this._row(a))}</ul>
    `;
  }

  private _row(a: Activity): TemplateResult {
    const t = this.t!;
    const open = this._open === a.id;
    const facts = [
      a.distance_meters !== null ? formatDistance(this.fmt, a.distance_meters) : null,
      a.duration_seconds !== null ? formatNumber(this.fmt, "duration", a.duration_seconds) : null,
      a.average_speed_mps !== null ? formatSpeedOrPace(this.fmt, a.sport, a.average_speed_mps) : null,
      a.average_heart_rate_bpm !== null ? formatNumber(this.fmt, "heart_rate", a.average_heart_rate_bpm) : null,
    ].filter((f): f is string => f !== null);
    return html`
      <li>
        <button class="row" aria-expanded=${open} aria-controls="d-${a.id}"
          @click=${() => (this._open = open ? undefined : a.id)}>
          <span class="main">
            <span class="title">${a.title ?? t("activity_untitled")}</span>
            <span class="meta">${sportLabel(t, a.sport)} · ${this._date(a.started_at)}</span>
          </span>
          <span class="facts">${facts.join(" · ")}</span>
          <span class="chevron" aria-hidden="true">${open ? "▴" : "▾"}</span>
        </button>
        ${open ? this._details(a) : nothing}
      </li>
    `;
  }

  private _details(a: Activity): TemplateResult {
    const t = this.t!;
    const f = this.fmt;
    const rows: [string, string | null][] = [
      [t("activity_distance"), a.distance_meters !== null ? formatDistance(f, a.distance_meters) : null],
      [t("activity_duration"), a.duration_seconds !== null ? formatNumber(f, "duration", a.duration_seconds) : null],
      [t("activity_moving"), a.moving_seconds !== null ? formatNumber(f, "duration", a.moving_seconds) : null],
      [t("activity_speed"), a.average_speed_mps !== null ? formatSpeedOrPace(f, a.sport, a.average_speed_mps) : null],
      [t("activity_max_speed"), a.max_speed_mps !== null ? formatSpeedOrPace(f, "cycling", a.max_speed_mps) : null],
      [t("activity_hr"), a.average_heart_rate_bpm !== null ? formatNumber(f, "heart_rate", a.average_heart_rate_bpm) : null],
      [t("activity_max_hr"), a.max_heart_rate_bpm !== null ? formatNumber(f, "heart_rate", a.max_heart_rate_bpm) : null],
      [t("activity_power"), a.average_power_w ? formatNumber(f, "power", a.average_power_w) : null],
      [t("activity_np"), a.normalized_power_w ? formatNumber(f, "power", a.normalized_power_w) : null],
      [t("activity_elevation"), a.elevation_gain_m !== null ? `${formatNumber(f, "count", a.elevation_gain_m)} m` : null],
      [t("activity_calories"), a.calories_kcal !== null ? formatNumber(f, "energy", a.calories_kcal) : null],
      [t("activity_aerobic"), a.aerobic_effect !== null ? formatNumber(f, "vo2max", a.aerobic_effect) : null],
      [t("activity_anaerobic"), a.anaerobic_effect !== null ? formatNumber(f, "vo2max", a.anaerobic_effect) : null],
      [t("activity_load"), a.training_load !== null ? formatNumber(f, "count", a.training_load) : null],
    ];
    return html`
      <div class="details" id="d-${a.id}">
        <dl>
          ${rows.filter(([, v]) => v !== null).map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}
        </dl>
        ${this._zones(a)}
      </div>
    `;
  }

  private _zones(a: Activity): TemplateResult | typeof nothing {
    const t = this.t!;
    const zones = (a.hr_zone_seconds ?? []).map((s, i) => ({ n: i + 1, s: s ?? 0 }));
    const total = zones.reduce((sum, z) => sum + z.s, 0);
    if (!total) return nothing;
    const visible = zones.filter((z) => z.s > 0);
    return html`
      <h4>${t("activity_hr_zones")}</h4>
      <div class="stack" role="img"
        aria-label=${zones.map((z) => `${t("hr_zone", { n: String(z.n) })} ${formatNumber(this.fmt, "duration", z.s)}`).join(", ")}>
        ${visible.map((z) => html`<span class="seg z${z.n}" style="flex-grow:${z.s}"></span>`)}
      </div>
      <ul class="legend">
        ${zones.map((z) => html`<li><span class="swatch z${z.n}"></span>${t("hr_zone", { n: String(z.n) })}
          <strong>${formatNumber(this.fmt, "duration", z.s)}</strong>
          <small>${Math.round((z.s / total) * 100)}%</small></li>`)}
      </ul>
    `;
  }

  static override styles = css`
    :host { display: block; min-width: 0; }
    .note { font-size: 13px; color: var(--secondary-text-color); margin: 0 0 8px; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .chips button {
      min-height: 36px; padding: 0 12px; border-radius: 18px; font: inherit; font-size: 13px; cursor: pointer;
      border: 1px solid var(--divider-color, #ccc); background: none; color: var(--primary-text-color);
    }
    .chips button[aria-checked="true"] { background: var(--primary-color); border-color: var(--primary-color); color: var(--text-primary-color, #fff); }
    .list { list-style: none; margin: 0; padding: 0; }
    .list > li { border-bottom: 1px solid var(--divider-color, #eee); }
    .list > li:last-child { border-bottom: 0; }
    .row {
      width: 100%; display: grid; grid-template-columns: 1fr auto; grid-template-areas: "main chevron" "facts chevron";
      gap: 2px 8px; align-items: center; text-align: left; padding: 10px 0; min-height: 44px;
      border: 0; background: none; color: inherit; font: inherit; cursor: pointer;
    }
    @media (min-width: 700px) {
      .row { grid-template-columns: 1fr auto auto; grid-template-areas: "main facts chevron"; }
    }
    .row:focus-visible, .chips button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .main { grid-area: main; display: flex; flex-direction: column; min-width: 0; }
    .title { font-weight: 500; overflow-wrap: anywhere; }
    .meta, .facts { font-size: 13px; color: var(--secondary-text-color); }
    .facts { grid-area: facts; font-variant-numeric: tabular-nums; }
    .chevron { grid-area: chevron; color: var(--secondary-text-color); }
    .details { padding: 0 0 12px; }
    dl { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px 16px; margin: 0; }
    dt { font-size: 12px; color: var(--secondary-text-color); }
    dd { margin: 0; font-weight: 500; }
    h4 { font-size: 13px; font-weight: 500; margin: 12px 0 6px; }
    .stack { display: flex; gap: 2px; height: 16px; }
    .seg { min-width: 2px; height: 100%; }
    .seg:first-child { border-radius: 4px 0 0 4px; }
    .seg:last-child { border-radius: 0 4px 4px 0; }
    .legend { list-style: none; margin: 6px 0 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 4px 12px; font-size: 13px; }
    .legend strong { white-space: nowrap; }
    .legend li { display: flex; align-items: center; gap: 6px; }
    .legend strong { margin-left: auto; }
    .legend small { color: var(--secondary-text-color); }
    .swatch { width: 10px; height: 10px; border-radius: 2px; flex: none; }
    /* Ordinal ramp (zone 1 → 5), validated on both HA card surfaces. */
    .z1 { background: var(--gd-zone-1); }
    .z2 { background: var(--gd-zone-2); }
    .z3 { background: var(--gd-zone-3); }
    .z4 { background: var(--gd-zone-4); }
    .z5 { background: var(--gd-zone-5); }
  `;
}

if (!customElements.get("garmin-activities")) {
  customElements.define("garmin-activities", GarminActivities);
}
