import { LitElement, css, html, nothing, svg, type TemplateResult } from "lit";

import { categoryMessage, hasMessage, type MessageKey, type Translate } from "./i18n";
import { METRIC_ICONS, icon } from "./icons";
import { formatMetric, formatNumber, goalProgress, type FormatContext } from "./format";
import type { Metric, ProfileSnapshot } from "./types";

const HIDDEN_STATUSES = new Set(["missing", "ambiguous"]);
const SIZE = 104;
const STROKE = 9;

/** The headline values, each a ring with a fixed series color (identity, not rank). */
export const SUMMARY_RINGS = ["steps", "body_battery", "sleep_score", "training_readiness"] as const;
type RingKey = (typeof SUMMARY_RINGS)[number];

interface Ring {
  key: RingKey;
  slot: number;
  metric: Metric;
  value: string | null;
  /** Filled share of the ring, 0–1; null draws only the track. */
  fraction: number | null;
  sub: string | null;
  ariaValue: string;
}

/** Summary strip: steps, Body Battery, sleep score and training readiness as rings. */
export class GarminSummary extends LitElement {
  static override properties = {
    snapshot: { attribute: false },
    hiddenMetrics: { attribute: false },
    fmt: { attribute: false },
    t: { attribute: false },
  };

  snapshot?: ProfileSnapshot;
  hiddenMetrics: string[] = [];
  fmt: FormatContext = { locale: "en", lengthUnit: "km" };
  t?: Translate;

  /** Rings this account can show and the user has not hidden. */
  rings(): Ring[] {
    const snapshot = this.snapshot;
    if (!snapshot || !this.t) return [];
    const hidden = new Set(this.hiddenMetrics);
    return SUMMARY_RINGS.flatMap((key, i) => {
      const metric = snapshot.metrics[key];
      if (!metric || hidden.has(key) || HIDDEN_STATUSES.has(metric.status)) return [];
      return [this._ring(snapshot, key, i + 1, metric)];
    });
  }

  private _number(metric: Metric | undefined): number | null {
    return metric?.status === "available" && typeof metric.value === "number" ? metric.value : null;
  }

  private _ring(snapshot: ProfileSnapshot, key: RingKey, slot: number, metric: Metric): Ring {
    const t = this.t!;
    const m = snapshot.metrics;
    const raw = this._number(metric);
    const value = metric.status === "available" ? formatMetric(this.fmt, metric) : null;
    let fraction = raw === null ? null : Math.max(0, Math.min(1, raw / 100));
    let sub: string | null = null;
    switch (key) {
      case "steps": {
        const goal = m.steps_goal;
        const progress = goalProgress(raw, this._number(goal));
        fraction = progress ? progress.bar / 100 : null;
        if (progress && goal) sub = `${Math.round(progress.percent)}% · ${t("of_goal", { goal: formatMetric(this.fmt, goal) ?? "" })}`;
        break;
      }
      case "body_battery": {
        const charged = this._number(m.bb_charged);
        const drained = this._number(m.bb_drained);
        const nf = new Intl.NumberFormat(this.fmt.locale);
        sub = [charged !== null ? `+${nf.format(charged)}` : null, drained !== null ? `−${nf.format(drained)}` : null]
          .filter(Boolean)
          .join(" · ") || null;
        break;
      }
      case "sleep_score": {
        const duration = this._number(m.sleep_duration);
        if (duration !== null) sub = formatNumber(this.fmt, "duration", duration);
        break;
      }
      case "training_readiness": {
        const status = m.training_status;
        const message = status?.status === "available" && typeof status.value === "string" ? categoryMessage(status.value) : null;
        if (message) sub = t(message);
        break;
      }
    }
    return { key, slot, metric, value, fraction, sub, ariaValue: [value ?? "—", sub].filter(Boolean).join(", ") };
  }

  private _label(key: string): string {
    const k = `metric_${key}`;
    return hasMessage(k) ? this.t!(k as MessageKey) : key;
  }

  protected override render(): TemplateResult {
    const rings = this.rings();
    if (!rings.length) return html``;
    return html`<ul>${rings.map((ring) => this._renderRing(ring))}</ul>`;
  }

  private _renderRing(ring: Ring): TemplateResult {
    const t = this.t!;
    const r = (SIZE - STROKE) / 2;
    const c = 2 * Math.PI * r;
    const label = this._label(ring.key);
    const stale = ring.metric.freshness === "stale";
    return html`
      <li class="s${ring.slot}" role="group" aria-label=${`${label}: ${ring.ariaValue}`}>
        <div class="ring">
          <svg width=${SIZE} height=${SIZE} viewBox="0 0 ${SIZE} ${SIZE}" aria-hidden="true">
            <circle class="track" cx=${SIZE / 2} cy=${SIZE / 2} r=${r}></circle>
            ${ring.fraction
              ? svg`<circle class="arc" cx=${SIZE / 2} cy=${SIZE / 2} r=${r}
                  stroke-dasharray="${c * ring.fraction} ${c}" transform="rotate(-90 ${SIZE / 2} ${SIZE / 2})"></circle>`
              : nothing}
          </svg>
          <div class="center">
            ${METRIC_ICONS[ring.key] ? icon(METRIC_ICONS[ring.key]!, 18) : nothing}
            <strong class=${ring.value === null ? "empty" : ""}>${ring.value ?? "—"}</strong>
          </div>
        </div>
        <div class="label">${label}</div>
        ${ring.sub ? html`<div class="sub">${ring.sub}</div>` : nothing}
        ${stale ? html`<div class="sub warn">⚠ ${t("stale")}</div>` : nothing}
      </li>
    `;
  }

  static override styles = css`
    :host { display: block; }
    ul { list-style: none; margin: 0; padding: 0; display: grid; gap: 16px 8px; grid-template-columns: repeat(2, 1fr); }
    @media (min-width: 700px) { ul { grid-template-columns: repeat(4, 1fr); } }
    li { display: flex; flex-direction: column; align-items: center; text-align: center; min-width: 0; }
    .ring { position: relative; width: ${SIZE}px; height: ${SIZE}px; }
    svg { display: block; }
    .track { fill: none; stroke: var(--gd-grid); stroke-width: ${STROKE}; }
    .arc { fill: none; stroke-width: ${STROKE}; stroke-linecap: round; stroke: var(--ring-color); }
    .s1 { --ring-color: var(--gd-series-1); }
    .s2 { --ring-color: var(--gd-series-2); }
    .s3 { --ring-color: var(--gd-series-3); }
    .s4 { --ring-color: var(--gd-series-4); }
    .center {
      position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px;
    }
    .center .mdi { color: var(--ring-color); }
    .center strong { font-size: 20px; font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.1; }
    .center strong.empty { color: var(--secondary-text-color); }
    .label { margin-top: 8px; font-size: 14px; font-weight: 500; }
    .sub { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; font-variant-numeric: tabular-nums; }
    .warn { color: var(--warning-color, #b26a00); }
    @media (prefers-reduced-motion: no-preference) { .arc { transition: stroke-dasharray 0.4s ease; } }
  `;
}

if (!customElements.get("garmin-summary")) {
  customElements.define("garmin-summary", GarminSummary);
}
