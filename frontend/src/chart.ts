import { LitElement, css, html, nothing, svg, type PropertyValues, type SVGTemplateResult, type TemplateResult } from "lit";

import {
  areaPath,
  barWidth,
  extent,
  hasData,
  linePath,
  linearScale,
  nearestIndex,
  segments,
  ticksForKind,
  type ChartPayload,
  type ChartSeries,
  type Point,
  type Scale,
} from "./chart-data";
import { formatNumber, type FormatContext } from "./format";
import type { Translate } from "./i18n";

const PLOT_HEIGHT = 140;
const AXIS_BAND = 22;
const MARGIN = { left: 44, right: 16, top: 10 };
const DAY = 86_400_000;

interface Active {
  index: number;
  x: number;
  y: number;
}

/** One chart card body: SVG plot, hover/focus tooltip and a table view twin. */
export class GarminChart extends LitElement {
  static override properties = {
    payload: { attribute: false },
    fmt: { attribute: false },
    t: { attribute: false },
    heading: { type: String },
    seriesLabels: { attribute: false },
    refreshing: { type: Boolean, reflect: true },
    _width: { state: true },
    _active: { state: true },
    _table: { state: true },
  };

  payload?: ChartPayload;
  fmt: FormatContext = { locale: "en", lengthUnit: "km" };
  t?: Translate;
  heading = "";
  seriesLabels: Record<string, string> = {};
  refreshing = false;
  private _width = 0;
  private _active?: Active;
  private _table = false;
  private _observer?: ResizeObserver;

  override connectedCallback(): void {
    super.connectedCallback();
    this._observer = new ResizeObserver((entries) => {
      const width = Math.floor(entries[0]?.contentRect.width ?? 0);
      if (width && width !== this._width) this._width = width;
    });
    this._observer.observe(this);
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._observer?.disconnect();
  }

  protected override willUpdate(changed: PropertyValues): void {
    if (changed.has("payload")) this._active = undefined;
  }

  private get _primary(): ChartSeries | undefined {
    return this.payload?.series[0];
  }

  private _label(metric: string): string {
    return this.seriesLabels[metric] ?? metric;
  }

  private _fmtValue(series: ChartSeries, value: number): string {
    return formatNumber(this.fmt, series.kind, value);
  }

  private _fmtTime(ms: number): string {
    const payload = this.payload;
    const intraday = payload?.method === "intraday" || payload?.method === "cumulative_today";
    return new Date(ms).toLocaleString(this.fmt.locale, intraday
      ? { hour: "2-digit", minute: "2-digit" }
      : { day: "numeric", month: "short" });
  }

  private _timeNote(): string {
    const t = this.t;
    if (!t || !this.payload) return "";
    switch (this.payload.method) {
      case "change_points":
        return this.payload.per_day ? t("chart_note_day_last") : t("chart_note_arrived");
      case "daily_range":
        return t("chart_note_daily_range");
      default:
        return "";
    }
  }

  protected override render(): TemplateResult {
    const t = this.t;
    const payload = this.payload;
    if (!t) return html``;
    return html`
      <div class="head">
        <h3>${this.heading}</h3>
        ${payload && hasData(payload)
          ? html`<button class="link" @click=${() => (this._table = !this._table)} aria-pressed=${this._table}>
              ${this._table ? t("chart_show_chart") : t("chart_show_table")}
            </button>`
          : nothing}
      </div>
      ${!payload
        ? html`<div class="placeholder" style="height:${PLOT_HEIGHT + AXIS_BAND}px"></div>`
        : !hasData(payload)
          ? html`<p class="empty">${t("chart_no_data")}</p>`
          : this._table
            ? this._renderTable(payload)
            : this._renderChart(payload)}
    `;
  }

  private _renderChart(payload: ChartPayload): TemplateResult {
    if (payload.form === "stacked_bar") return this._renderStacked(payload);
    const width = this._width;
    if (!width) return html`<div class="placeholder" style="height:${PLOT_HEIGHT + AXIS_BAND}px"></div>`;
    const series = this._primary;
    if (!series) return html``;

    let start = Date.parse(payload.start);
    let end = Date.parse(payload.end);
    // Day-aligned marks are drawn mid-day; widen the axis to whole days so the
    // first and last columns stay inside the plot instead of over the axis labels.
    if (payload.form === "range_columns" || (payload.form === "columns" && payload.per_day)) {
      const days = [...(series.ranges ?? []).map(([t]) => t), ...(series.points ?? []).map(([t]) => t)];
      if (days.length) {
        start = Math.min(start, Math.min(...days));
        end = Math.max(end, Math.max(...days) + DAY);
      }
    }
    const band = payload.band ?? null;
    const range = extent(payload.series, [payload.goal, band?.low, band?.high]);
    if (!range) return html``;
    const ticks = ticksForKind(series.kind, payload.form === "columns" ? 0 : range[0], range[1]);
    // Bar length encodes the value, so columns always start at zero.
    const yMin = payload.form === "columns" ? 0 : Math.min(ticks[0] ?? range[0], range[0]);
    const yMax = Math.max(ticks[ticks.length - 1] ?? range[1], range[1]);
    const plotRight = width - MARGIN.right;
    const x = linearScale([start, end], [MARGIN.left, plotRight]);
    const y = linearScale([yMin, yMax], [MARGIN.top + PLOT_HEIGHT, MARGIN.top]);
    const height = MARGIN.top + PLOT_HEIGHT + AXIS_BAND;
    const points = series.points ?? [];
    // Through columns the line only adds clutter; their average stays in the summary below.
    const mean = payload.per_day && payload.form !== "columns" ? average(points) : null;

    return html`
      <div class="plot" style="height:${height}px">
        <svg
          width=${width}
          height=${height}
          role="img"
          aria-label=${this._summary(series)}
          tabindex="0"
          @pointermove=${(e: PointerEvent) => this._onPointer(e, x, y)}
          @pointerleave=${() => (this._active = undefined)}
          @keydown=${(e: KeyboardEvent) => this._onKey(e, x, y)}
          @blur=${() => (this._active = undefined)}
        >
          <defs>
            <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
              <stop class="fade-top" offset="0"></stop>
              <stop class="fade-bottom" offset="1"></stop>
            </linearGradient>
          </defs>
          ${this._grid(ticks, y, series, plotRight)}
          ${this._xAxis(start, end, x, height)}
          ${band
            ? svg`<rect class="band" x=${MARGIN.left} width=${plotRight - MARGIN.left}
                y=${y(band.high)} height=${Math.max(1, y(band.low) - y(band.high))}></rect>`
            : nothing}
          ${payload.goal != null ? this._goalLine(series, payload.goal, y, plotRight) : nothing}
          ${mean !== null ? this._meanLine(series, mean, y, plotRight) : nothing}
          ${this._marks(payload, series, points, x, y, plotRight)}
          ${this._crosshair(payload, series, points, x, y)}
        </svg>
        ${this._tooltip(payload, series, points, width)}
      </div>
      <p class="summary">${this._summary(series)}${this._timeNote() ? html` · ${this._timeNote()}` : nothing}</p>
      ${band
        ? html`<p class="summary"><span class="band-key" aria-hidden="true"></span>${this._bandNote(series, band)}</p>`
        : nothing}
    `;
  }

  private _bandNote(series: ChartSeries, band: { low: number; high: number }): string {
    const t = this.t;
    if (!t) return "";
    return `${t("chart_band_hrv")}: ${this._fmtValue(series, band.low)} – ${this._fmtValue(series, band.high)}`;
  }

  private _grid(ticks: number[], y: Scale, series: ChartSeries, plotRight: number): SVGTemplateResult {
    // Enough decimals that neighbouring ticks never print the same label (3.35 vs 3.40).
    const step = ticks.length > 1 ? Math.abs(ticks[1]! - ticks[0]!) : 1;
    const decimals = Math.min(3, Math.max(0, -Math.floor(Math.log10(step) + 1e-9)));
    return svg`${ticks.map(
      (tick) => svg`
        <line class="grid" x1=${MARGIN.left} x2=${plotRight} y1=${y(tick)} y2=${y(tick)}></line>
        <text class="tick" x=${MARGIN.left - 6} y=${y(tick) + 4} text-anchor="end">${this._tickLabel(series, tick, decimals)}</text>`,
    )}`;
  }

  private _tickLabel(series: ChartSeries, value: number, decimals: number): string {
    if (series.kind === "duration") return `${Math.round(value / 3600)}${this.t?.("hour_short") ?? "h"}`;
    if (Math.abs(value) >= 1000) {
      return new Intl.NumberFormat(this.fmt.locale, { notation: "compact", maximumFractionDigits: 1 }).format(value);
    }
    return new Intl.NumberFormat(this.fmt.locale, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }).format(value);
  }

  private _xAxis(start: number, end: number, x: Scale, height: number): SVGTemplateResult {
    const span = end - start;
    const count = Math.max(2, Math.min(6, Math.floor((x.range[1] - x.range[0]) / 80)));
    const ticks = Array.from({ length: count }, (_, i) => start + (span * i) / (count - 1));
    const short = span <= 2 * DAY;
    return svg`${ticks.map((t, i) => svg`
      <text class="tick" x=${x(t)} y=${height - 6}
        text-anchor=${i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle"}>
        ${new Date(t).toLocaleString(this.fmt.locale, short ? { hour: "2-digit", minute: "2-digit" } : { day: "numeric", month: "short" })}
      </text>`)}`;
  }

  private _goalLine(series: ChartSeries, goal: number, y: Scale, plotRight: number): SVGTemplateResult {
    return svg`
      <line class="goal" x1=${MARGIN.left} x2=${plotRight} y1=${y(goal)} y2=${y(goal)}></line>
      <text class="ref" x=${MARGIN.left + 4} y=${y(goal) - 5}>${this.t?.("chart_goal_value", { value: this._fmtValue(series, goal) }) ?? ""}</text>`;
  }

  /** Dashed average of the days shown, labelled at the left so it never meets the latest value. */
  private _meanLine(series: ChartSeries, mean: number, y: Scale, plotRight: number): SVGTemplateResult {
    return svg`
      <line class="mean" x1=${MARGIN.left} x2=${plotRight} y1=${y(mean)} y2=${y(mean)}></line>
      <text class="ref halo" x=${MARGIN.left + 4} y=${y(mean) - 5}>${this.t?.("chart_avg", { value: this._fmtValue(series, mean) }) ?? ""}</text>`;
  }

  /** The latest value, written next to its mark. */
  private _lastLabel(series: ChartSeries, point: [number, number], x: Scale, y: Scale): SVGTemplateResult {
    const px = x(point[0]);
    const py = y(point[1]);
    return svg`<text class="last halo" x=${px - 8} y=${py - 10} text-anchor="end">${this._fmtValue(series, point[1])}</text>`;
  }

  private _marks(
    payload: ChartPayload, series: ChartSeries, points: Point[], x: Scale, y: Scale, plotRight: number,
  ): SVGTemplateResult {
    const baseline = y.range[0];
    const plotWidth = plotRight - MARGIN.left;
    switch (payload.form) {
      case "range_columns": {
        const ranges = series.ranges ?? [];
        const w = barWidth(plotWidth, payload.range_days);
        return svg`${ranges.map(([t, lo, hi], i) => {
          const cx = x(t + DAY / 2);
          const top = y(hi);
          const h = Math.max(2, y(lo) - top);
          const dim = this._active !== undefined && this._active.index !== i;
          return svg`<rect class=${dim ? "bar dim" : "bar"} x=${cx - w / 2} y=${top} width=${w} height=${h} rx=${Math.min(4, w / 2)}></rect>`;
        })}`;
      }
      case "columns": {
        const w = barWidth(plotWidth, payload.range_days);
        return svg`${points.map(([t, v], i) => {
          if (v === null) return nothing;
          const top = y(v);
          // Per-day values sit at local midnight; centre the column on its day.
          const cx = payload.per_day ? x(t + DAY / 2) : x(t);
          const dim = this._active !== undefined && this._active.index !== i;
          return svg`<path class=${dim ? "bar dim" : "bar"} d=${columnPath(cx, top, baseline, w)}></path>`;
        })}`;
      }
      case "dots": {
        const runs = segments(points);
        const last = runs[runs.length - 1]?.[runs[runs.length - 1]!.length - 1];
        return svg`
          ${runs.map((run) => svg`<path class="line thin" d=${linePath(run, x, y)}></path>`)}
          ${points.map(([t, v]) => (v === null ? nothing : svg`<circle class="dot" cx=${x(t)} cy=${y(v)} r="4"></circle>`))}
          ${last ? this._lastLabel(series, last, x, y) : nothing}`;
      }
      default: {
        const step = payload.form === "step";
        const runs = segments(points);
        const last = runs[runs.length - 1]?.[runs[runs.length - 1]!.length - 1];
        // Cumulative counts and levels read as a filled area; trends stay plain lines.
        const filled = payload.form === "area" || payload.method === "cumulative_today";
        return svg`
          ${filled ? runs.map((run) => svg`<path class="area" d=${areaPath(run, x, y, baseline)}></path>`) : nothing}
          ${runs.map((run, i) => svg`<path class="line" d=${linePath(step && i === runs.length - 1 ? extendToNow(run, x) : run, x, y, step)}></path>`)}
          ${last ? svg`<circle class="dot" cx=${x(last[0])} cy=${y(last[1])} r="4"></circle>` : nothing}
          ${last && !step ? this._lastLabel(series, last, x, y) : nothing}`;
      }
    }
  }

  private _crosshair(payload: ChartPayload, series: ChartSeries, points: Point[], x: Scale, y: Scale): SVGTemplateResult | typeof nothing {
    const active = this._active;
    if (!active) return nothing;
    const lineForm = payload.form !== "columns" && payload.form !== "range_columns";
    return svg`
      ${lineForm ? svg`<line class="crosshair" x1=${active.x} x2=${active.x} y1=${MARGIN.top} y2=${MARGIN.top + PLOT_HEIGHT}></line>` : nothing}
      ${payload.form === "range_columns" ? nothing : svg`<circle class="dot active" cx=${active.x} cy=${active.y} r="5"></circle>`}`;
  }

  private _tooltip(payload: ChartPayload, series: ChartSeries, points: Point[], width: number): TemplateResult | typeof nothing {
    const active = this._active;
    if (!active) return nothing;
    let value: string;
    let time: number;
    if (payload.form === "range_columns") {
      const range = series.ranges?.[active.index];
      if (!range) return nothing;
      value = `${this._fmtValue(series, range[1])} – ${this._fmtValue(series, range[2])}`;
      time = range[0];
    } else {
      const point = points[active.index];
      if (!point || point[1] === null) return nothing;
      value = this._fmtValue(series, point[1]);
      time = point[0];
    }
    const left = Math.min(Math.max(active.x - 80, 0), width - 160);
    return html`
      <div class="tooltip" style="left:${left}px" role="status">
        <span class="series"><i class="swatch s1"></i>${this._label(series.metric)}</span>
        <strong>${value}</strong>
        <span>${this._fmtTime(time)}</span>
        ${this._timeNote() ? html`<small>${this._timeNote()}</small>` : nothing}
      </div>
    `;
  }

  private _onPointer(e: PointerEvent, x: Scale, y: Scale): void {
    const svgEl = e.currentTarget as SVGSVGElement;
    const px = e.clientX - svgEl.getBoundingClientRect().left;
    const t = x.domain[0] + ((px - x.range[0]) / (x.range[1] - x.range[0])) * (x.domain[1] - x.domain[0]);
    this._activate(this._indexNear(t), x, y);
  }

  private _onKey(e: KeyboardEvent, x: Scale, y: Scale): void {
    const count = this._count();
    if (!count) return;
    let index = this._active?.index ?? count - 1;
    if (e.key === "ArrowLeft") index = Math.max(0, index - 1);
    else if (e.key === "ArrowRight") index = Math.min(count - 1, index + 1);
    else if (e.key === "Home") index = 0;
    else if (e.key === "End") index = count - 1;
    else return;
    e.preventDefault();
    this._activate(index, x, y);
  }

  private _count(): number {
    const s = this._primary;
    return this.payload?.form === "range_columns" ? (s?.ranges?.length ?? 0) : (s?.points?.length ?? 0);
  }

  /** Per-day columns are drawn mid-day; hover and focus must use the same position. */
  private get _offset(): number {
    return this.payload?.per_day && this.payload.form === "columns" ? DAY / 2 : 0;
  }

  private _indexNear(t: number): number {
    const s = this._primary;
    if (!s) return -1;
    t -= this._offset;
    if (this.payload?.form === "range_columns") {
      const ranges = s.ranges ?? [];
      return nearestIndex(ranges.map(([day]) => [day + DAY / 2, 0] as Point), t);
    }
    return nearestIndex(s.points ?? [], t);
  }

  private _activate(index: number, x: Scale, y: Scale): void {
    const s = this._primary;
    if (!s || index < 0) return;
    if (this.payload?.form === "range_columns") {
      const range = s.ranges?.[index];
      if (range) this._active = { index, x: x(range[0] + DAY / 2), y: y(range[2]) };
      return;
    }
    const point = s.points?.[index];
    if (!point || point[1] === null) {
      // Keyboard landed on a gap; skip to the nearest real value.
      const near = nearestIndex(s.points ?? [], point?.[0] ?? 0);
      if (near >= 0 && near !== index) this._activate(near, x, y);
      return;
    }
    this._active = { index, x: x(point[0] + this._offset), y: y(point[1]) };
  }

  private _summary(series: ChartSeries): string {
    const t = this.t;
    if (!t) return "";
    const values = [
      ...(series.points ?? []).map(([, v]) => v).filter((v): v is number => v !== null),
      ...(series.ranges ?? []).flatMap(([, lo, hi]) => [lo, hi]),
    ];
    if (!values.length) return "";
    const last = series.ranges?.length
      ? series.ranges[series.ranges.length - 1]![2]
      : values[values.length - 1]!;
    const text = t("chart_summary", {
      last: this._fmtValue(series, last),
      min: this._fmtValue(series, Math.min(...values)),
      max: this._fmtValue(series, Math.max(...values)),
    });
    const mean = this.payload?.per_day ? average(series.points ?? []) : null;
    return mean === null ? text : `${text} · ${t("chart_avg", { value: this._fmtValue(series, mean) })}`;
  }

  private _renderStacked(payload: ChartPayload): TemplateResult {
    const parts = payload.series
      .map((s, slot) => ({ s, slot, v: s.points?.[0]?.[1] ?? null }))
      .filter((p): p is { s: ChartSeries; slot: number; v: number } => p.v !== null && p.v > 0);
    const total = parts.reduce((sum, p) => sum + p.v, 0);
    if (!total) return html`<p class="empty">${this.t?.("chart_no_data")}</p>`;
    return html`
      <div class="stack" role="img" aria-label=${parts.map((p) => `${this._label(p.s.metric)} ${this._fmtValue(p.s, p.v)}`).join(", ")}>
        ${parts.map(
          (p) => html`<span class="seg s${p.slot + 1}" style="flex-grow:${p.v}" title=${`${this._label(p.s.metric)}: ${this._fmtValue(p.s, p.v)}`}></span>`,
        )}
      </div>
      <ul class="legend">
        ${parts.map(
          (p) => html`<li><span class="swatch s${p.slot + 1}"></span>${this._label(p.s.metric)}
            <strong>${this._fmtValue(p.s, p.v)}</strong> <small>${Math.round((p.v / total) * 100)}%</small></li>`,
        )}
      </ul>
    `;
  }

  private _renderTable(payload: ChartPayload): TemplateResult {
    const t = this.t!;
    const rows: { time: number; cells: string[] }[] = [];
    if (payload.form === "range_columns") {
      const s = payload.series[0]!;
      for (const [time, lo, hi] of s.ranges ?? []) rows.push({ time, cells: [this._fmtValue(s, lo), this._fmtValue(s, hi)] });
    } else if (payload.form === "stacked_bar") {
      for (const s of payload.series) {
        const point = s.points?.[0];
        if (point && point[1] !== null) rows.push({ time: point[0], cells: [this._label(s.metric), this._fmtValue(s, point[1])] });
      }
    } else {
      const s = payload.series[0]!;
      for (const [time, v] of s.points ?? []) if (v !== null) rows.push({ time, cells: [this._fmtValue(s, v)] });
    }
    const headers =
      payload.form === "range_columns" ? [t("chart_low"), t("chart_high")]
      : payload.form === "stacked_bar" ? [t("chart_stage"), t("chart_value")]
      : [t("chart_value")];
    return html`
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">${t("chart_time")}</th>${headers.map((h) => html`<th scope="col">${h}</th>`)}</tr></thead>
          <tbody>
            ${rows.slice().reverse().map(
              (r) => html`<tr><td>${this._fmtTime(r.time)}</td>${r.cells.map((c) => html`<td>${c}</td>`)}</tr>`,
            )}
          </tbody>
        </table>
      </div>
    `;
  }

  static override styles = css`
    :host { display: block; min-width: 0; position: relative; }
    :host([refreshing]) .plot, :host([refreshing]) .stack { opacity: 0.5; }
    .head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
    h3 { font-size: 14px; font-weight: 500; margin: 0 0 6px; }
    .link {
      border: 0; background: none; color: var(--primary-color); font: inherit; font-size: 13px;
      min-height: 44px; padding: 0 4px; cursor: pointer;
    }
    .link:focus-visible, svg:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .plot { position: relative; }
    svg { display: block; overflow: visible; touch-action: pan-y; }
    .grid { stroke: var(--gd-grid); stroke-width: 1; }
    .tick { fill: var(--secondary-text-color); font-size: 11px; font-variant-numeric: tabular-nums; }
    .goal { stroke: var(--secondary-text-color); stroke-width: 1; }
    .mean { stroke: var(--secondary-text-color); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.8; }
    .ref { fill: var(--secondary-text-color); font-size: 11px; }
    .last { fill: var(--primary-text-color); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .halo { paint-order: stroke; stroke: var(--gd-surface); stroke-width: 3px; stroke-linejoin: round; }
    .fade-top { stop-color: var(--gd-series-1); stop-opacity: 0.32; }
    .fade-bottom { stop-color: var(--gd-series-1); stop-opacity: 0.02; }
    .line { fill: none; stroke: var(--gd-series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    .line.thin { stroke-width: 1; opacity: 0.6; }
    .area { fill: url(#fade); stroke: none; }
    .band { fill: var(--gd-series-3); opacity: 0.12; stroke: none; }
    .band-key { display: inline-block; width: 10px; height: 10px; margin-right: 6px; border-radius: 2px; background: var(--gd-series-3); opacity: 0.35; vertical-align: -1px; }
    .bar { fill: var(--gd-series-1); }
    .bar.dim { opacity: 0.45; }
    .dot { fill: var(--gd-series-1); stroke: var(--gd-surface); stroke-width: 2; }
    .dot.active { r: 5; }
    .crosshair { stroke: var(--secondary-text-color); stroke-width: 1; }
    .tooltip {
      position: absolute; top: 0; width: 160px; box-sizing: border-box; pointer-events: none;
      background: var(--gd-surface); color: var(--primary-text-color);
      border: 1px solid var(--gd-grid); border-radius: 8px; padding: 6px 8px;
      display: flex; flex-direction: column; gap: 2px; font-size: 12px;
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
    }
    .tooltip strong { font-size: 15px; font-variant-numeric: tabular-nums; }
    .tooltip .series { display: flex; align-items: center; gap: 6px; color: var(--primary-text-color); }
    .tooltip span, .tooltip small { color: var(--secondary-text-color); }
    .summary, .empty { font-size: 12px; color: var(--secondary-text-color); margin: 4px 0 0; }
    .empty { padding: 24px 0; text-align: center; }
    .placeholder { width: 100%; }
    .stack { display: flex; gap: 2px; height: 28px; margin: 8px 0 12px; }
    .seg { min-width: 2px; height: 100%; }
    .seg:first-child { border-radius: 4px 0 0 4px; }
    .seg:last-child { border-radius: 0 4px 4px 0; }
    .s1 { background: var(--gd-series-1); }
    .s2 { background: var(--gd-series-2); }
    .s3 { background: var(--gd-series-3); }
    .s4 { background: var(--gd-series-4); }
    .legend { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 4px 12px; font-size: 13px; }
    .legend li { display: flex; align-items: center; gap: 6px; }
    .legend strong { margin-left: auto; }
    .legend small { color: var(--secondary-text-color); }
    .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 2px; flex: none; }
    .table-wrap { max-height: 220px; overflow: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
    th, td { text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--gd-grid); }
    th { color: var(--secondary-text-color); font-weight: 500; position: sticky; top: 0; background: var(--gd-surface); }
    @media (prefers-reduced-motion: no-preference) { .plot, .stack { transition: opacity 0.2s; } }
  `;
}

/** Mean of the defined values, or null when there are fewer than two. */
function average(points: Point[]): number | null {
  const values = points.map(([, v]) => v).filter((v): v is number => v !== null);
  return values.length < 2 ? null : values.reduce((a, b) => a + b, 0) / values.length;
}

/** Column with a 4px rounded data end and a square baseline. */
function columnPath(cx: number, top: number, baseline: number, width: number): string {
  const r = Math.min(4, width / 2, Math.max(0, baseline - top));
  const left = cx - width / 2;
  const right = cx + width / 2;
  return `M${left},${baseline}V${top + r}Q${left},${top} ${left + r},${top}H${right - r}Q${right},${top} ${right},${top + r}V${baseline}Z`;
}

/** A step series holds its last value until now, so the line reaches the right edge. */
function extendToNow(run: [number, number][], x: Scale): [number, number][] {
  const last = run[run.length - 1];
  if (!last) return run;
  return [...run, [x.domain[1], last[1]]];
}

if (!customElements.get("garmin-chart")) {
  customElements.define("garmin-chart", GarminChart);
}
