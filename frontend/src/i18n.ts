const en = {
  title: "Garmin",
  loading: "Loading…",
  refresh: "Refresh",
  menu: "Menu",
  last_sync: "Last sync",
  last_sync_unknown: "Sync time not provided by source",
  section_movement: "Daily activity",
  section_recovery: "Recovery",
  section_training: "Training",
  section_gear: "Gear",
  section_status: "Status",
  of_goal: "of {goal}",
  stale: "Out of date",
  last_value: "Last value",
  retired: "Retired",
  status_unknown: "No data yet",
  status_unavailable: "Waiting for connection",
  status_disabled: "Sensor turned off in Home Assistant",
  status_missing: "Not provided by your device or account",
  status_ambiguous: "Could not be matched safely",
  status_invalid: "Unexpected value",
  source_ready: "Connected",
  source_starting: "Data source is starting",
  source_offline: "Data source has a problem. Check the Garmin Connect integration.",
  source_removed: "Garmin Connect connection was removed",
  source_unsupported: "This Garmin Connect version is not verified yet",
  no_profiles: "Garmin Dashboard has no account configured.",
  connection_lost: "Connection to Home Assistant lost. Reconnecting…",
  reload_needed: "Garmin Dashboard was updated. Reload the page.",
  source_version: "Garmin Connect version",
  compatible: "Compatibility",
  compatible_yes: "Verified",
  compatible_no: "Not verified",
  metrics_found: "Metrics found",
  metrics_off: "Turned off",
  metrics_missing: "Not provided",
  metric_steps: "Steps",
  metric_steps_goal: "Step goal",
  metric_distance_day: "Distance",
  metric_calories_active: "Active calories",
  metric_calories_total: "Total calories",
  metric_body_battery: "Body Battery",
  metric_sleep_score: "Sleep score",
  metric_sleep_duration: "Sleep",
  metric_hrv_status: "HRV status",
  metric_hrv_last_night: "HRV last night",
  metric_resting_hr: "Resting heart rate",
  metric_training_readiness: "Training readiness",
  metric_training_status: "Training status",
  metric_recovery_time: "Recovery time",
  metric_vo2max: "VO2 max",
  metric_ftp_cycling: "FTP (cycling)",
  metric_ftp_running: "FTP (running)",
};

export type MessageKey = keyof typeof en;

const tr: Record<MessageKey, string> = {
  title: "Garmin",
  loading: "Yükleniyor…",
  refresh: "Yenile",
  menu: "Menü",
  last_sync: "Son senkronizasyon",
  last_sync_unknown: "Kaynak senkronizasyon zamanı sağlamıyor",
  section_movement: "Günlük hareket",
  section_recovery: "Toparlanma",
  section_training: "Antrenman",
  section_gear: "Ekipman",
  section_status: "Durum",
  of_goal: "hedef {goal}",
  stale: "Güncel değil",
  last_value: "Son değer",
  retired: "Emekli",
  status_unknown: "Henüz veri yok",
  status_unavailable: "Bağlantı bekleniyor",
  status_disabled: "Sensör Home Assistant'ta kapalı",
  status_missing: "Cihazın veya hesabın bu veriyi sağlamıyor",
  status_ambiguous: "Güvenle eşleştirilemedi",
  status_invalid: "Beklenmeyen değer",
  source_ready: "Bağlı",
  source_starting: "Veri kaynağı hazırlanıyor",
  source_offline: "Veri kaynağında sorun var. Garmin Connect entegrasyonunu kontrol edin.",
  source_removed: "Garmin Connect bağlantısı kaldırıldı",
  source_unsupported: "Bu Garmin Connect sürümü henüz doğrulanmadı",
  no_profiles: "Garmin Dashboard'da yapılandırılmış hesap yok.",
  connection_lost: "Home Assistant bağlantısı koptu. Yeniden bağlanılıyor…",
  reload_needed: "Garmin Dashboard güncellendi. Sayfayı yenileyin.",
  source_version: "Garmin Connect sürümü",
  compatible: "Uyumluluk",
  compatible_yes: "Doğrulandı",
  compatible_no: "Doğrulanmadı",
  metrics_found: "Bulunan metrik",
  metrics_off: "Kapalı",
  metrics_missing: "Sağlanmayan",
  metric_steps: "Adım",
  metric_steps_goal: "Adım hedefi",
  metric_distance_day: "Mesafe",
  metric_calories_active: "Aktif kalori",
  metric_calories_total: "Toplam kalori",
  metric_body_battery: "Body Battery",
  metric_sleep_score: "Uyku skoru",
  metric_sleep_duration: "Uyku",
  metric_hrv_status: "HRV durumu",
  metric_hrv_last_night: "HRV (dün gece)",
  metric_resting_hr: "Dinlenme nabzı",
  metric_training_readiness: "Antrenman hazırlığı",
  metric_training_status: "Antrenman durumu",
  metric_recovery_time: "Toparlanma süresi",
  metric_vo2max: "VO2 max",
  metric_ftp_cycling: "FTP (bisiklet)",
  metric_ftp_running: "FTP (koşu)",
};

const catalogs: Record<string, Record<MessageKey, string>> = { en, tr };

export type Translate = (key: MessageKey, vars?: Record<string, string>) => string;

export function translator(language: string): Translate {
  const catalog = catalogs[language.split("-")[0] ?? "en"] ?? en;
  return (key, vars) => {
    let text = catalog[key] ?? en[key];
    for (const [name, value] of Object.entries(vars ?? {})) {
      text = text.replace(`{${name}}`, value);
    }
    return text;
  };
}

export function hasMessage(key: string): key is MessageKey {
  return key in en;
}
