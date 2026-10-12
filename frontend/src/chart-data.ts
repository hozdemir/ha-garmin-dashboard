// Chart payload types and pure geometry helpers (no DOM), unit-tested.

import type { MetricKind } from "./types";

export type ChartForm = "line" | "area" | "step" | "columns" | "dots" | "range_columns" | "stacked_bar";
export type ChartMethod = "intraday" | "cumulative_today" | "change_points" | "daily_range" | "current";

/** [epoch ms, value]; a null value marks a gap in the records. */
export type Point = [number, number | null];
export type Range = [number, number, number]; // [day start ms, low, high]

export interface ChartSeries {
  metric: string;
  kind: MetricKind;
  unit: string | null;
  points?: Point[];
  ranges?: Range[];
}

export interface ChartPayload {
  chart_id: string;
  group: "today" | "trends";
  form: ChartForm;
  method: ChartMethod;
  range_days: number;
  /** One value per HA day (the day's last), drawn at local midnight. */
  per_day?: boolean;
  start: string;
  end: string;
  series: ChartSeries[];
  goal?: number | null;
  /** A reference range drawn behind the series; `current_only` means it is today's range for the whole chart. */
  band?: { low: number; high: number; current_only: boolean } | null;
}

export interface Scale {
  (value: number): number;
  domain: [number, number];
  range: [number, number];
}

export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const scale = ((value: number) => r0 + ((value - d0) / span) * (r1 - r0)) as Scale;
  scale.domain = domain;
  scale.range = range;
  return scale;
}

/** Round tick values ("nice numbers") covering [min, max], about `count` of them. */
export function niceTicks(min: number, max: number, count = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const rough = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const residual = rough / magnitude;
  const step = (residual >= 5 ? 10 : residual >= 2 ? 5 : residual >= 1 ? 2 : 1) * magnitude;
  const start = Math.floor(min / step) * step;
  const ticks: number[] = [];
  for (let v = start; v <= max + step * 0.5; v += step) {
    ticks.push(Number(v.toFixed(10)));
  }
  return ticks;
}

/** Y ticks for a metric kind; durations tick on whole hours. */
export function ticksForKind(kind: MetricKind, min: number, max: number): number[] {
  if (kind === "duration") {
    return niceTicks(min / 3600, max / 3600, 4).map((h) => h * 3600);
  }
  // Scores and percentages read best anchored at zero.
  const low = kind === "percent" ? 0 : min;
  const high = kind === "percent" ? Math.max(100, max) : max;
  return niceTicks(low, high, 4);
}

/** Split a series into drawable runs at gaps. */
export function segments(points: Point[]): [number, number][][] {
  const runs: [number, number][][] = [];
  let current: [number, number][] = [];
  for (const [t, v] of points) {
    if (v === null) {
      if (current.length) runs.push(current);
      current = [];
    } else {
      current.push([t, v]);
    }
  }
  if (current.length) runs.push(current);
  return runs;
}

export function linePath(run: [number, number][], x: Scale, y: Scale, step = false): string {
  return run
    .map(([t, v], i) => {
      const px = x(t).toFixed(1);
      const py = y(v).toFixed(1);
      if (i === 0) return `M${px},${py}`;
      if (!step) return `L${px},${py}`;
      const prev = run[i - 1];
      return prev ? `H${px}V${py}` : `L${px},${py}`;
    })
    .join("");
}

export function areaPath(run: [number, number][], x: Scale, y: Scale, baseline: number): string {
  const first = run[0];
  const last = run[run.length - 1];
  if (!first || !last) return "";
  return `${linePath(run, x, y)}L${x(last[0]).toFixed(1)},${baseline}L${x(first[0]).toFixed(1)},${baseline}Z`;
}

/** Index of the defined point nearest to time `t`, or -1. */
export function nearestIndex(points: Point[], t: number): number {
  let best = -1;
  let bestDistance = Infinity;
  points.forEach(([pt, v], i) => {
    if (v === null) return;
    const distance = Math.abs(pt - t);
    if (distance < bestDistance) {
      best = i;
      bestDistance = distance;
    }
  });
  return best;
}

/** Value extent of all defined points and ranges, optionally including extra values. */
export function extent(series: ChartSeries[], extra: (number | null | undefined)[] = []): [number, number] | null {
  const values: number[] = [];
  for (const s of series) {
    for (const [, v] of s.points ?? []) if (v !== null) values.push(v);
    for (const [, lo, hi] of s.ranges ?? []) values.push(lo, hi);
  }
  for (const v of extra) if (typeof v === "number" && Number.isFinite(v)) values.push(v);
  if (!values.length) return null;
  return [Math.min(...values), Math.max(...values)];
}

/** Bar width for `slots` evenly spaced marks: at most 24px, leaving air between bars. */
export function barWidth(plotWidth: number, slots: number): number {
  if (slots <= 0) return 0;
  return Math.max(2, Math.min(24, (plotWidth / slots) * 0.6));
}

export function hasData(payload: ChartPayload): boolean {
  return payload.series.some(
    (s) => (s.points ?? []).some(([, v]) => v !== null) || (s.ranges ?? []).length > 0,
  );
}
