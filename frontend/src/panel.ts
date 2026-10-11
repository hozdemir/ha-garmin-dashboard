import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";

import { formatDistance, formatMetric, goalProgress, type FormatContext } from "./format";
import { hasMessage, translator, type Translate } from "./i18n";
import {
  SCHEMA_VERSION,
  type HassLike,
  type Metric,
  type ProfileInfo,
  type ProfileSnapshot,
  type ProfilesResult,
  type Section,
} from "./types";

const SECTIONS: { id: Section; keys: string[] }[] = [
  { id: "movement", keys: ["steps", "distance_day", "calories_active", "calories_total"] },
  { id: "recovery", keys: ["body_battery", "sleep_score", "sleep_duration", "hrv_status", "hrv_last_night", "resting_hr"] },
  { id: "training", keys: ["training_readiness", "training_status", "recovery_time", "vo2max", "ftp_cycling", "ftp_running"] },
];

// Statuses that mean "this account never has it": hide instead of showing an empty tile.
const HIDDEN_STATUSES = new Set(["missing", "ambiguous"]);

export class GarminDashboardPanel extends LitElement {
  static override properties = {
    hass: { attribute: false },
    narrow: { type: Boolean },
    _profiles: { state: true },
    _snapshot: { state: true },
    _error: { state: true },
    _disconnected: { state: true },
  };

  hass?: HassLike;
  narrow = false;
  private _profiles?: ProfileInfo[];
  private _snapshot?: ProfileSnapshot;
  private _error?: string;
  private _disconnected = false;
  private _profileId?: string;
  // Revisions restart after an HA restart, so ordering is tracked per subscription.
  private _lastRevision = -1;
  private _unsubscribe?: Promise<() => Promise<void>>;
  private _subscribed = false;

  private readonly _onReady = () => {
    this._disconnected = false;
    void this._load();
  };
  private readonly _onDisconnected = () => {
    this._disconnected = true;
  };

  override connectedCallback(): void {
    super.connectedCallback();
    if (this.hass && !this._subscribed) void this._load();
  }

  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._teardown();
  }

  protected override updated(changed: PropertyValues): void {
    if (changed.has("hass") && this.hass && !this._subscribed) {
      this._subscribed = true;
      this.hass.connection.addEventListener("ready", this._onReady);
      this.hass.connection.addEventListener("disconnected", this._onDisconnected);
      void this._load();
    }
  }

  private _teardown(): void {
    this.hass?.connection.removeEventListener("ready", this._onReady);
    this.hass?.connection.removeEventListener("disconnected", this._onDisconnected);
    this._subscribed = false;
    this._stopSnapshot();
  }

  private _stopSnapshot(): void {
    const unsubscribe = this._unsubscribe;
    this._unsubscribe = undefined;
    void unsubscribe?.then((fn) => fn()).catch(() => undefined);
  }

  private async _load(): Promise<void> {
    if (!this.hass) return;
    try {
      const result = await this.hass.callWS<ProfilesResult>({ type: "garmin_dashboard/profiles" });
      if (result.schema_version !== SCHEMA_VERSION) {
        this._error = "reload_needed";
        return;
      }
      this._error = undefined;
      this._profiles = result.profiles;
      const keep = result.profiles.find((p) => p.profile_id === this._profileId);
      const next = keep ?? result.profiles[0];
      if (next) this._selectProfile(next.profile_id);
    } catch {
      this._error = "source_offline";
    }
  }

  private _selectProfile(profileId: string): void {
    if (!this.hass) return;
    this._stopSnapshot();
    if (profileId !== this._profileId) this._snapshot = undefined;
    this._profileId = profileId;
    this._lastRevision = -1;
    this._unsubscribe = this.hass.connection.subscribeMessage<ProfileSnapshot>(
      (snapshot) => this._applySnapshot(profileId, snapshot),
      { type: "garmin_dashboard/subscribe", profile_id: profileId },
    );
    this._unsubscribe.catch(() => {
      this._error = "source_offline";
    });
  }

  /** Ignore snapshots for a profile we already left, and out-of-order revisions. */
  private _applySnapshot(profileId: string, snapshot: ProfileSnapshot): void {
    if (profileId !== this._profileId || snapshot.profile_id !== profileId) return;
    if (snapshot.schema_version !== SCHEMA_VERSION) {
      this._error = "reload_needed";
      return;
    }
    if (snapshot.revision <= this._lastRevision) return;
    this._lastRevision = snapshot.revision;
    this._snapshot = snapshot;
  }

  private _toggleMenu(): void {
    this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
  }

  private get _t(): Translate {
    return translator(this.hass?.locale?.language ?? this.hass?.language ?? "en");
  }

  private get _fmt(): FormatContext {
    return {
      locale: this.hass?.locale?.language ?? this.hass?.language ?? "en",
      lengthUnit: this.hass?.config.unit_system.length ?? "km",
    };
  }

  protected override render(): TemplateResult {
    const t = this._t;
    return html`
      <header>
        ${this.narrow
          ? html`<button class="icon" @click=${this._toggleMenu} aria-label=${t("menu")}>☰</button>`
          : nothing}
        <h1>${t("title")}</h1>
        ${this._renderProfilePicker()}
      </header>
      ${this._disconnected ? html`<p class="banner" role="status">${t("connection_lost")}</p>` : nothing}
      <main>${this._renderBody()}</main>
    `;
  }

  private _renderProfilePicker(): TemplateResult | typeof nothing {
    const profiles = this._profiles ?? [];
    if (profiles.length < 2) {
      return this._snapshot ? html`<span class="profile">${this._snapshot.display_name}</span>` : nothing;
    }
    return html`
      <select
        aria-label="Profile"
        @change=${(e: Event) => this._selectProfile((e.target as HTMLSelectElement).value)}
      >
        ${profiles.map(
          (p) => html`<option value=${p.profile_id} ?selected=${p.profile_id === this._profileId}>${p.display_name}</option>`,
        )}
      </select>
    `;
  }

  private _renderBody(): TemplateResult {
    const t = this._t;
    if (this._error && hasMessage(this._error)) {
      return html`<p class="banner warn" role="alert">${t(this._error)}</p>`;
    }
    if (this._profiles && this._profiles.length === 0) {
      return html`<p class="banner">${t("no_profiles")}</p>`;
    }
    const snapshot = this._snapshot;
    if (!snapshot) return html`<p class="muted">${t("loading")}</p>`;
    return html`
      ${this._renderSourceState(snapshot)}
      <div class="grid">
        ${SECTIONS.map((section) => this._renderSection(snapshot, section.id, section.keys))}
        ${this._renderGear(snapshot)}
        ${this._renderStatus()}
      </div>
    `;
  }

  private _renderSourceState(snapshot: ProfileSnapshot): TemplateResult {
    const t = this._t;
    const sync = snapshot.source_synced_at
      ? `${t("last_sync")}: ${new Date(snapshot.source_synced_at).toLocaleString(this._fmt.locale)}`
      : t("last_sync_unknown");
    const warn = snapshot.source_status !== "ready";
    return html`
      <p class="source ${warn ? "warn" : ""}" role=${warn ? "alert" : "status"}>
        ${warn ? html`<strong>${t(`source_${snapshot.source_status}`)}</strong> · ` : nothing}${sync}
      </p>
    `;
  }

  private _renderSection(snapshot: ProfileSnapshot, section: Section, keys: string[]): TemplateResult | typeof nothing {
    const metrics = keys
      .map((key) => snapshot.metrics[key])
      .filter((m): m is Metric => m !== undefined && !HIDDEN_STATUSES.has(m.status));
    // A section the account never provides is hidden (e.g. no sleep data on a bike-only setup).
    if (metrics.length === 0) return nothing;
    return html`
      <section class="card" aria-labelledby="h-${section}">
        <h2 id="h-${section}">${this._t(`section_${section}`)}</h2>
        <div class="tiles">${metrics.map((m) => this._renderMetric(snapshot, m))}</div>
      </section>
    `;
  }

  private _renderMetric(snapshot: ProfileSnapshot, metric: Metric): TemplateResult {
    const t = this._t;
    const labelKey = `metric_${metric.key}`;
    const label = hasMessage(labelKey) ? t(labelKey) : metric.key;
    const shown = metric.status === "available" || metric.status === "unavailable" ? formatMetric(this._fmt, metric) : null;
    const statusKey = `status_${metric.status}`;
    const stale = metric.freshness === "stale";
    return html`
      <div class="tile">
        <div class="label">${label}</div>
        ${shown !== null
          ? html`<div class="value">${shown}</div>`
          : html`<div class="value empty">—</div>`}
        ${metric.key === "steps" ? this._renderGoal(snapshot, metric) : nothing}
        ${metric.status !== "available" && hasMessage(statusKey)
          ? html`<div class="note">${t(statusKey)}</div>`
          : nothing}
        ${stale ? html`<div class="note warn">⚠ ${t("stale")}</div>` : nothing}
      </div>
    `;
  }

  private _renderGoal(snapshot: ProfileSnapshot, steps: Metric): TemplateResult | typeof nothing {
    const goal = snapshot.metrics["steps_goal"];
    const progress = goalProgress(
      typeof steps.value === "number" ? steps.value : null,
      goal?.status === "available" && typeof goal.value === "number" ? goal.value : null,
    );
    if (!progress || !goal) return nothing;
    const goalText = formatMetric(this._fmt, goal) ?? "";
    return html`
      <div class="progress" role="progressbar" aria-valuenow=${Math.round(progress.percent)} aria-valuemin="0">
        <div class="bar" style="width: ${progress.bar}%"></div>
      </div>
      <div class="note">${Math.round(progress.percent)}% · ${this._t("of_goal", { goal: goalText })}</div>
    `;
  }

  private _renderGear(snapshot: ProfileSnapshot): TemplateResult | typeof nothing {
    const gear = snapshot.gear.filter((g) => g.status === "available" && g.distance_meters !== null);
    if (gear.length === 0) return nothing;
    return html`
      <section class="card" aria-labelledby="h-gear">
        <h2 id="h-gear">${this._t("section_gear")}</h2>
        <ul class="list">
          ${gear.map(
            (g) => html`<li>
              <span>${g.name ?? "—"}${g.retired ? html` <small>(${this._t("retired")})</small>` : nothing}</span>
              <strong>${formatDistance(this._fmt, g.distance_meters ?? 0)}</strong>
            </li>`,
          )}
        </ul>
      </section>
    `;
  }

  private _renderStatus(): TemplateResult | typeof nothing {
    const t = this._t;
    const info = this._profiles?.find((p) => p.profile_id === this._profileId);
    if (!info) return nothing;
    const counts = info.status.metric_counts;
    return html`
      <section class="card" aria-labelledby="h-status">
        <h2 id="h-status">${t("section_status")}</h2>
        <ul class="list">
          <li><span>${t("source_version")}</span><strong>${info.status.source_version ?? "—"}</strong></li>
          <li><span>${t("compatible")}</span><strong>${info.status.compatible ? t("compatible_yes") : t("compatible_no")}</strong></li>
          <li><span>${t("metrics_found")}</span><strong>${counts.resolved ?? 0}</strong></li>
          <li><span>${t("metrics_off")}</span><strong>${counts.disabled ?? 0}</strong></li>
          <li><span>${t("metrics_missing")}</span><strong>${(counts.missing ?? 0) + (counts.ambiguous ?? 0)}</strong></li>
        </ul>
      </section>
    `;
  }

  static override styles = css`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color);
      color: var(--primary-text-color);
      font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
    }
    header {
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 56px;
      padding: 0 16px;
      background: var(--app-header-background-color, var(--primary-color));
      color: var(--app-header-text-color, #fff);
    }
    h1 { font-size: 20px; font-weight: 400; margin: 0; flex: 1; }
    .profile { opacity: 0.85; }
    select { min-height: 44px; font: inherit; }
    button.icon {
      min-width: 44px; min-height: 44px; border: 0; background: none;
      color: inherit; font-size: 22px; cursor: pointer;
    }
    button:focus-visible, select:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
    main { padding: 16px; max-width: 1200px; margin: 0 auto; box-sizing: border-box; }
    .grid { display: grid; gap: 16px; grid-template-columns: 1fr; }
    @media (min-width: 700px) { .grid { grid-template-columns: repeat(2, 1fr); } }
    @media (min-width: 1100px) { .grid { grid-template-columns: repeat(3, 1fr); } }
    .card {
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      border: 1px solid var(--divider-color, transparent);
      padding: 16px;
      min-width: 0;
    }
    h2 { font-size: 16px; font-weight: 500; margin: 0 0 12px; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 12px; }
    .tile { min-width: 0; }
    .label { font-size: 13px; color: var(--secondary-text-color); }
    .value { font-size: 22px; font-weight: 500; overflow-wrap: anywhere; }
    .value.empty { color: var(--disabled-text-color, var(--secondary-text-color)); }
    .note { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; }
    .warn { color: var(--warning-color, #b26a00); }
    .progress { height: 6px; border-radius: 3px; background: var(--divider-color, #ddd); margin-top: 6px; overflow: hidden; }
    .bar { height: 100%; background: var(--primary-color); }
    .banner { padding: 12px 16px; border-radius: 8px; background: var(--card-background-color); margin: 0 0 16px; }
    .source { margin: 0 0 16px; color: var(--secondary-text-color); font-size: 14px; }
    .muted { color: var(--secondary-text-color); }
    .list { list-style: none; margin: 0; padding: 0; }
    .list li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--divider-color, #eee); }
    .list li:last-child { border-bottom: 0; }
    @media (prefers-reduced-motion: no-preference) { .bar { transition: width 0.3s ease; } }
  `;
}

if (!customElements.get("garmin-dashboard-panel")) {
  customElements.define("garmin-dashboard-panel", GarminDashboardPanel);
}
