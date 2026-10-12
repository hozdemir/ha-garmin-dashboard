// What the panel can show; mirrors the backend catalog and chart IDs.

import type { Section } from "./types";

export type SectionId = Section | "gear" | "activities";

export const TILE_SECTIONS: { id: Section; keys: string[] }[] = [
  { id: "movement", keys: ["steps", "distance_day", "calories_active", "calories_total"] },
  { id: "recovery", keys: ["body_battery", "sleep_score", "sleep_duration", "hrv_status", "hrv_last_night", "resting_hr"] },
  {
    id: "training",
    keys: [
      "training_readiness", "training_status", "recovery_time", "vo2max",
      "ftp_cycling", "ptw_cycling", "lthr_cycling", "ftp_running", "lthr_running",
    ],
  },
];

export interface ChartDef {
  id: string;
  group: "today" | "trends";
  metrics: string[];
}

export const CHARTS: ChartDef[] = [
  { id: "body_battery_today", group: "today", metrics: ["body_battery"] },
  { id: "steps_today", group: "today", metrics: ["steps"] },
  { id: "sleep_stages", group: "today", metrics: ["sleep_deep", "sleep_light", "sleep_rem", "sleep_awake"] },
  { id: "stress_today", group: "today", metrics: ["stress_avg"] },
  { id: "body_battery_range", group: "trends", metrics: ["body_battery"] },
  { id: "sleep_score", group: "trends", metrics: ["sleep_score"] },
  { id: "sleep_duration", group: "trends", metrics: ["sleep_duration"] },
  { id: "resting_hr", group: "trends", metrics: ["resting_hr"] },
  { id: "hrv", group: "trends", metrics: ["hrv_last_night"] },
  { id: "weekly_steps", group: "trends", metrics: ["weekly_step_avg"] },
  { id: "vo2max", group: "trends", metrics: ["vo2max"] },
  { id: "ftp_cycling", group: "trends", metrics: ["ftp_cycling"] },
  { id: "ptw_cycling", group: "trends", metrics: ["ptw_cycling"] },
];

export const TREND_RANGES = [7, 30, 90] as const;

export interface Preferences {
  section_order: SectionId[];
  hidden_sections: SectionId[];
  hidden_metrics: string[];
  hidden_charts: string[];
  trend_range_days: number;
  show_route: boolean;
}
