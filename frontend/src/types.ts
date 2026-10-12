// Mirrors the backend snapshot contract.

export const SCHEMA_VERSION = 1;

export type MetricStatus =
  | "available"
  | "unknown"
  | "unavailable"
  | "disabled"
  | "missing"
  | "ambiguous"
  | "invalid";

export type Freshness = "fresh" | "stale" | "unknown";

export type MetricKind =
  | "count"
  | "distance"
  | "duration"
  | "energy"
  | "percent"
  | "score"
  | "heart_rate"
  | "power"
  | "vo2max"
  | "category"
  | "hrv"
  | "level";

export type Section = "movement" | "recovery" | "training";

export interface Metric {
  key: string;
  section: Section;
  kind: MetricKind;
  value: number | string | null;
  unit: string | null;
  status: MetricStatus;
  freshness: Freshness;
  observed_at: string;
  ha_updated_at: string | null;
  measured_at: string | null;
  source_date: string | null;
}

export interface Gear {
  id: string;
  name: string | null;
  status: MetricStatus;
  distance_meters: number | null;
  retired: boolean;
}

export interface Activity {
  id: string;
  id_source: "source" | "start_time";
  sport: string;
  title: string | null;
  started_at: string | null;
  duration_seconds: number | null;
  moving_seconds: number | null;
  distance_meters: number | null;
  average_speed_mps: number | null;
  max_speed_mps: number | null;
  average_heart_rate_bpm: number | null;
  max_heart_rate_bpm: number | null;
  average_power_w: number | null;
  normalized_power_w: number | null;
  elevation_gain_m: number | null;
  calories_kcal: number | null;
  aerobic_effect: number | null;
  anaerobic_effect: number | null;
  training_load: number | null;
  hr_zone_seconds: (number | null)[] | null;
}

export interface Route {
  title: string | null;
  points: [number, number][];
  bounds: [number, number, number, number];
  source_points: number;
  invalid_points: number;
  simplified: boolean;
}

export type SourceStatus = "ready" | "starting" | "offline" | "removed" | "unsupported";

export interface ProfileSnapshot {
  schema_version: number;
  profile_id: string;
  display_name: string;
  revision: number;
  source_status: SourceStatus;
  source_synced_at: string | null;
  /** Model of the device that last synced (any Garmin device type), if known. */
  source_sync_device?: string | null;
  metrics: Record<string, Metric>;
  gear: Gear[];
  activities: Activity[];
  activities_truncated?: boolean;
  capabilities: string[];
}

export interface ProfileStatus {
  source_version: string | null;
  compatible: boolean;
  metric_status: Record<string, MetricStatus>;
  metric_counts: Partial<Record<MetricStatus | "resolved", number>>;
  activity_sensors: Record<string, string>;
  gear_count: number;
}

export interface ProfileInfo {
  profile_id: string;
  display_name: string;
  source_status: SourceStatus;
  status: ProfileStatus;
}

export interface ProfilesResult {
  schema_version: number;
  profiles: ProfileInfo[];
}

// The subset of HA's frontend `hass` object the panel uses.
export interface HassLike {
  language: string;
  locale?: { language: string; number_format?: string; time_zone?: string };
  config: { unit_system: { length: string }; time_zone: string };
  connection: {
    subscribeMessage<T>(
      callback: (message: T) => void,
      message: Record<string, unknown>,
    ): Promise<() => Promise<void>>;
    addEventListener(event: string, callback: () => void): void;
    removeEventListener(event: string, callback: () => void): void;
  };
  callWS<T>(message: Record<string, unknown>): Promise<T>;
  themes?: { darkMode?: boolean };
}
