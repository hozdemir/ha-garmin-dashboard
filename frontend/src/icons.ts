// Material Design Icons (the set Home Assistant uses), bundled as SVG paths.

import {
  mdiAlert,
  mdiAlertCircle,
  mdiArmFlex,
  mdiBatteryArrowDown,
  mdiBatteryArrowUp,
  mdiBatteryHeartVariant,
  mdiBike,
  mdiCheckCircle,
  mdiChartLine,
  mdiFire,
  mdiHeart,
  mdiHeartFlash,
  mdiHeartPulse,
  mdiInformationOutline,
  mdiLightningBolt,
  mdiLungs,
  mdiMapMarkerDistance,
  mdiMapMarkerPath,
  mdiMinusCircle,
  mdiPowerSleep,
  mdiScaleBathroom,
  mdiShoePrint,
  mdiSleep,
  mdiSpeedometer,
  mdiTimerSand,
  mdiWalk,
  mdiWater,
} from "@mdi/js";
import { html, nothing, type TemplateResult } from "lit";

import type { SectionId } from "./catalog";
import type { Tone } from "./format";

export const SECTION_ICONS: Record<SectionId | "status", string> = {
  movement: mdiWalk,
  recovery: mdiBatteryHeartVariant,
  training: mdiArmFlex,
  body: mdiScaleBathroom,
  gear: mdiBike,
  activities: mdiMapMarkerPath,
  status: mdiInformationOutline,
};

export const METRIC_ICONS: Record<string, string> = {
  steps: mdiShoePrint,
  distance_day: mdiMapMarkerDistance,
  calories_active: mdiFire,
  calories_total: mdiFire,
  body_battery: mdiBatteryHeartVariant,
  bb_charged: mdiBatteryArrowUp,
  bb_drained: mdiBatteryArrowDown,
  sleep_score: mdiSleep,
  sleep_duration: mdiPowerSleep,
  hrv_status: mdiHeartPulse,
  hrv_last_night: mdiHeartPulse,
  resting_hr: mdiHeart,
  spo2_avg: mdiWater,
  training_readiness: mdiSpeedometer,
  training_status: mdiChartLine,
  recovery_time: mdiTimerSand,
  vo2max: mdiLungs,
  ftp_cycling: mdiLightningBolt,
  ptw_cycling: mdiLightningBolt,
  ftp_running: mdiLightningBolt,
  lthr_cycling: mdiHeartFlash,
  lthr_running: mdiHeartFlash,
  weight: mdiScaleBathroom,
};

export const TONE_ICONS: Record<Tone, string> = {
  good: mdiCheckCircle,
  warning: mdiAlert,
  serious: mdiAlertCircle,
  neutral: mdiMinusCircle,
};

/** A 24×24 MDI path as inline SVG; decorative unless a label is given. */
export function icon(path: string, size = 18, label?: string): TemplateResult {
  return html`<svg class="mdi" width=${size} height=${size} viewBox="0 0 24 24"
    role=${label ? "img" : nothing} aria-hidden=${label ? nothing : "true"} aria-label=${label ?? nothing}
    ><path fill="currentColor" d=${path}></path></svg>`;
}
