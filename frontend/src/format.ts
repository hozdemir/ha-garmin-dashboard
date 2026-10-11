import type { Metric, MetricKind } from "./types";

export interface FormatContext {
  locale: string;
  lengthUnit: string; // HA unit system: "km" or "mi"
}

const METERS_PER_MILE = 1609.344;

function number(ctx: FormatContext, value: number, maxFraction = 0): string {
  return new Intl.NumberFormat(ctx.locale, { maximumFractionDigits: maxFraction }).format(value);
}

export function formatDistance(ctx: FormatContext, meters: number): string {
  if (ctx.lengthUnit === "mi") {
    return `${number(ctx, meters / METERS_PER_MILE, 2)} mi`;
  }
  return meters < 1000 ? `${number(ctx, meters)} m` : `${number(ctx, meters / 1000, 2)} km`;
}

export function formatDuration(ctx: FormatContext, seconds: number): string {
  const totalMinutes = Math.round(seconds / 60);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  const unit = (value: number, unitName: "hour" | "minute") =>
    new Intl.NumberFormat(ctx.locale, { style: "unit", unit: unitName, unitDisplay: "narrow" }).format(value);
  if (hours === 0) return unit(minutes, "minute");
  return minutes === 0 ? unit(hours, "hour") : `${unit(hours, "hour")} ${unit(minutes, "minute")}`;
}

/** Turn source enum text like "BALANCED" or "Detraining" into readable text. */
export function formatCategory(value: string): string {
  const words = value.replace(/_/g, " ").trim().toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Format an available metric; returns null when there is nothing safe to show. */
export function formatMetric(ctx: FormatContext, metric: Metric): string | null {
  const { value } = metric;
  if (value === null) return null;
  if (metric.kind === "category") return typeof value === "string" ? formatCategory(value) : null;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return formatNumber(ctx, metric.kind, value);
}

/** Format a normalized number of a given kind (meters, seconds, ...). */
export function formatNumber(ctx: FormatContext, kind: MetricKind, value: number): string {
  switch (kind) {
    case "distance":
      return formatDistance(ctx, value);
    case "duration":
      return formatDuration(ctx, value);
    case "percent":
      return `${number(ctx, value)}%`;
    case "energy":
      return `${number(ctx, value)} kcal`;
    case "heart_rate":
      return `${number(ctx, value)} bpm`;
    case "power":
      return `${number(ctx, value)} W`;
    case "hrv":
      return `${number(ctx, value)} ms`;
    case "vo2max":
      return number(ctx, value, 1);
    default:
      return number(ctx, value);
  }
}

/** Progress toward a goal. The bar caps at 100%, the reported percent does not. */
export function goalProgress(value: number | null, goal: number | null): { percent: number; bar: number } | null {
  if (value === null || goal === null || goal <= 0 || value < 0) return null;
  const percent = (value / goal) * 100;
  return { percent, bar: Math.min(percent, 100) };
}
