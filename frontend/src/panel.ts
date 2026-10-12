import { LitElement, css, html, nothing, type PropertyValues, type TemplateResult } from "lit";

import "./activities";
import "./chart";
import "./route";
import "./settings";
import { CHARTS, TILE_SECTIONS, TREND_RANGES, type ChartDef, type Preferences, type SectionId } from "./catalog";
import type { ChartPayload } from "./chart-data";
import { categoryTone, formatDistance, formatMetric, formatNumber, goalProgress, type FormatContext } from "./format";
import { categoryMessage, hasMessage, sensorLabel, sportLabel, translator, type MessageKey, type Translate } from "./i18n";
import { METRIC_ICONS, SECTION_ICONS, TONE_ICONS, icon } from "./icons";
import {
  SCHEMA_VERSION,
  type HassLike,
  type Metric,
  type ProfileInfo,
  type ProfileSnapshot,
  type ProfilesResult,
  type PlannedWorkout,
  type Route,
  type TrainingPlan,
  type Section,
} from "./types";

const LAST_PROFILE_KEY = "garmin-dashboard:last-profile";
const SOURCE_PAGE = "/config/integrations/integration/garmin_connect";
const DASHBOARD_PAGE = "/config/integrations/integration/garmin_dashboard";

/** Navigate inside the HA frontend without a full page load. */
function navigateInApp(e: Event): void {
  const href = (e.currentTarget as HTMLAnchorElement).getAttribute("href");
  if (!href) return;
  e.preventDefault();
  history.pushState(null, "", href);
  window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
}

/** Per-browser convenience only; storage may be unavailable (private mode). */
function rememberedProfile(): string | null {
  try {
    return localStorage.getItem(LAST_PROFILE_KEY);
  } catch {
    return null;
  }
}

function rememberProfile(profileId: string): void {
  try {
    localStorage.setItem(LAST_PROFILE_KEY, profileId);
  } catch {
    // Not persisted; the first profile is used next time.
  }
}

/** Tiles that show progress toward a target from another metric. */
const TARGETS: Record<string, { metric: string; label: MessageKey }> = {
  steps: { metric: "steps_goal", label: "of_goal" },
  sleep_duration: { metric: "sleep_need", label: "of_need" },
};

/** Amounts gained or spent today, shown like Garmin does (+62 / −41), not as a level. */
const SIGNED: Record<string, string> = { bb_charged: "+", bb_drained: "−" };

// "Today" charts follow live data; refetch them at most this often.
const TODAY_REFRESH_MS = 60_000;

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
    _prefs: { state: true },
    _view: { state: true },
    _charts: { state: true },
    _chartErrors: { state: true },
    _refreshing: { state: true },
    _trendRange: { state: true },
    _saving: { state: true },
    _notice: { state: true },
    _route: { state: true },
    _routeHidden: { state: true },
    _refreshBusy: { state: true },
  };

  hass?: HassLike;
  narrow = false;
  private _profiles?: ProfileInfo[];
  private _snapshot?: ProfileSnapshot;
  private _error?: string;
  private _disconnected = false;
  private _prefs?: Preferences;
  private _view: "dashboard" | "settings" = "dashboard";
  private _charts: Record<string, ChartPayload> = {};
  private _chartErrors: Record<string, MessageKey> = {};
  private _refreshing = new Set<string>();
  private _trendRange = 30;
  private _saving = false;
  private _notice?: MessageKey;
  private _todayLoadedAt = 0;
  // Preferences and the first snapshot arrive in either order; load charts once both are in.
  private _chartsLoaded = false;
  private _route?: Route | null;
  private _routeHidden = false;
  private _refreshBusy = false;
  // Refetch the route only when the newest activity changes.
  private _routeKey?: string;
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
    if (changed.has("hass")) this.toggleAttribute("dark", Boolean(this.hass?.themes?.darkMode));
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
      const wanted = this._profileId ?? rememberedProfile();
      const keep = result.profiles.find((p) => p.profile_id === wanted);
      const next = keep ?? result.profiles[0];
      if (next) this._selectProfile(next.profile_id);
    } catch {
      this._error = "source_offline";
    }
  }

  private _selectProfile(profileId: string): void {
    if (!this.hass) return;
    rememberProfile(profileId);
    // An open settings draft belongs to the previous profile.
    if (profileId !== this._profileId) this._view = "dashboard";
    this._stopSnapshot();
    if (profileId !== this._profileId) {
      this._snapshot = undefined;
      this._charts = {};
      this._chartErrors = {};
      this._prefs = undefined;
      this._todayLoadedAt = 0;
      this._chartsLoaded = false;
      this._route = undefined;
      this._routeKey = undefined;
    }
    this._profileId = profileId;
    this._lastRevision = -1;
    void this._loadPreferences(profileId);
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
    // The route needs only the snapshot; the backend applies the route preference.
    this._maybeLoadRoute();
    if (!this._prefs) return;
    if (!this._chartsLoaded) void this._loadCharts();
    else if (Date.now() - this._todayLoadedAt > TODAY_REFRESH_MS) void this._loadCharts("today");
  }

  private async _loadPreferences(profileId: string): Promise<void> {
    try {
      const prefs = await this.hass!.callWS<Preferences>({ type: "garmin_dashboard/preferences/get", profile_id: profileId });
      if (profileId !== this._profileId) return;
      this._prefs = prefs;
      this._trendRange = prefs.trend_range_days;
      void this._loadCharts();
    } catch {
      this._error = "source_offline";
    }
  }

  /** Charts the account can draw and the user has not hidden. */
  private _visibleCharts(group: ChartDef["group"]): ChartDef[] {
    const snapshot = this._snapshot;
    const prefs = this._prefs;
    if (!snapshot || !prefs) return [];
    return CHARTS.filter(
      (c) =>
        c.group === group &&
        !prefs.hidden_charts.includes(c.id) &&
        c.metrics.some((m) => {
          const metric = snapshot.metrics[m];
          return metric !== undefined && !HIDDEN_STATUSES.has(metric.status);
        }),
    );
  }

  private async _loadCharts(group?: ChartDef["group"]): Promise<void> {
    const profileId = this._profileId;
    if (!this.hass || !profileId || !this._snapshot) return;
    const groups: ChartDef["group"][] = group ? [group] : ["today", "trends"];
    if (!group) this._chartsLoaded = true;
    if (groups.includes("today")) this._todayLoadedAt = Date.now();
    const charts = groups.flatMap((g) => this._visibleCharts(g));
    await Promise.all(charts.map(async (chart) => {
      this._refreshing = new Set(this._refreshing).add(chart.id);
      try {
        const payload = await this.hass!.callWS<ChartPayload>({
          type: "garmin_dashboard/chart",
          profile_id: profileId,
          chart_id: chart.id,
          ...(chart.group === "trends" ? { range_days: this._trendRange } : {}),
        });
        // A late answer for a profile we already left must not be shown.
        if (profileId !== this._profileId) return;
        this._charts = { ...this._charts, [chart.id]: payload };
        const { [chart.id]: _, ...rest } = this._chartErrors;
        this._chartErrors = rest;
      } catch (err) {
        if (profileId !== this._profileId) return;
        const code = (err as { code?: string }).code;
        this._chartErrors = { ...this._chartErrors, [chart.id]: code === "recorder_unavailable" ? "chart_recorder_off" : "chart_error" };
      } finally {
        const next = new Set(this._refreshing);
        next.delete(chart.id);
        this._refreshing = next;
      }
    }));
  }

  private _maybeLoadRoute(force = false): void {
    const snapshot = this._snapshot;
    const profileId = this._profileId;
    if (!this.hass || !snapshot || !profileId || !snapshot.capabilities.includes("route")) return;
    const key = `${snapshot.activities[0]?.id ?? ""}`;
    if (!force && key === this._routeKey) return;
    this._routeKey = key;
    void this.hass
      .callWS<{ hidden: boolean; route?: Route | null }>({ type: "garmin_dashboard/route", profile_id: profileId })
      .then((result) => {
        if (profileId !== this._profileId) return;
        this._routeHidden = result.hidden;
        this._route = result.hidden ? null : (result.route ?? null);
      })
      .catch(() => {
        if (profileId === this._profileId) this._route = null;
      });
  }

  /** Re-read HA's data (never Garmin), then reload charts, route and status counts. */
  private async _refresh(): Promise<void> {
    const profileId = this._profileId;
    if (!this.hass || !profileId || this._refreshBusy) return;
    this._refreshBusy = true;
    try {
      await this.hass.callWS({ type: "garmin_dashboard/refresh", profile_id: profileId });
      const result = await this.hass.callWS<ProfilesResult>({ type: "garmin_dashboard/profiles" });
      if (profileId !== this._profileId) return;
      this._profiles = result.profiles;
      this._todayLoadedAt = 0;
      void this._loadCharts();
      this._maybeLoadRoute(true);
      this._notice = "status_refreshed";
    } catch {
      this._notice = "chart_error";
    } finally {
      this._refreshBusy = false;
    }
  }

  /** Sections hidden because this account has no data for them, with their names. */
  private _emptySections(snapshot: ProfileSnapshot): string[] {
    const t = this._t;
    const empty = TILE_SECTIONS.filter((section) =>
      section.keys.every((key) => {
        const metric = snapshot.metrics[key];
        return metric === undefined || HIDDEN_STATUSES.has(metric.status);
      }),
    ).map((section) => t(`section_${section.id}`));
    if (!snapshot.gear.length && !(snapshot.sensors ?? []).length) empty.push(t("section_gear"));
    if (!snapshot.capabilities.includes("activities") && !snapshot.capabilities.includes("route")) {
      empty.push(t("section_activities"));
    }
    return empty;
  }

  private _setTrendRange(days: number): void {
    if (days === this._trendRange) return;
    this._trendRange = days;
    void this._loadCharts("trends");
  }

  private async _savePreferences(prefs: Preferences | "reset"): Promise<void> {
    const profileId = this._profileId;
    if (!this.hass || !profileId) return;
    this._saving = true;
    try {
      const saved = await this.hass.callWS<Preferences>(
        prefs === "reset"
          ? { type: "garmin_dashboard/preferences/reset", profile_id: profileId }
          : { type: "garmin_dashboard/preferences/set", profile_id: profileId, preferences: prefs },
      );
      if (profileId !== this._profileId) return;
      this._prefs = saved;
      this._trendRange = saved.trend_range_days;
      this._view = "dashboard";
      this._notice = "saved";
      void this._loadCharts();
      this._maybeLoadRoute(true);
    } catch {
      this._notice = "save_failed";
    } finally {
      this._saving = false;
    }
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
      massUnit: this.hass?.config.unit_system.mass ?? "kg",
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
        ${this._prefs
          ? html`<button class="icon" aria-pressed=${this._view === "settings"} aria-label=${t("settings")} title=${t("settings")}
              @click=${() => { this._view = this._view === "settings" ? "dashboard" : "settings"; this._notice = undefined; }}>⚙</button>`
          : nothing}
      </header>
      ${this._disconnected ? html`<p class="banner" role="status">${t("connection_lost")}</p>` : nothing}
      ${this._notice ? html`<p class="banner notice" role="status">${t(this._notice)}</p>` : nothing}
      <main>${this._view === "settings" ? this._renderSettings() : this._renderBody()}</main>
    `;
  }

  private _renderProfilePicker(): TemplateResult | typeof nothing {
    const profiles = this._profiles ?? [];
    if (profiles.length < 2) {
      return this._snapshot ? html`<span class="profile">${this._snapshot.display_name}</span>` : nothing;
    }
    return html`
      <select
        class="profiles"
        aria-label=${this._t("profile")}
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
    const prefs = this._prefs;
    const order: SectionId[] = prefs?.section_order ?? ["movement", "recovery", "training", "body", "gear"];
    const hidden = new Set(prefs?.hidden_sections ?? []);
    const shown = order.filter((s) => !hidden.has(s));
    const sections = shown.map((id) => {
      if (id === "gear") return this._renderGear(snapshot);
      if (id === "activities") return this._renderActivities(snapshot);
      const def = TILE_SECTIONS.find((s) => s.id === id);
      return def ? this._renderSection(snapshot, def.id, def.keys) : nothing;
    });
    return html`
      ${this._renderSourceState(snapshot)}
      ${shown.length === 0
        ? html`<p class="banner">${t("all_hidden")}
            <button class="link" @click=${() => (this._view = "settings")}>${t("open_settings")}</button></p>`
        : nothing}
      <div class="grid">
        ${sections}
        ${this._renderStatus()}
      </div>
      ${this._renderChartGroup("today")}
      ${this._renderChartGroup("trends")}
    `;
  }

  private _renderActivities(snapshot: ProfileSnapshot): TemplateResult | typeof nothing {
    const t = this._t;
    const info = this._profiles?.find((p) => p.profile_id === this._profileId);
    const sensors = Object.values(info?.status.activity_sensors ?? {});
    const hasList = snapshot.capabilities.includes("activities");
    const disabled = !hasList && sensors.includes("disabled");
    const hasRoute = snapshot.capabilities.includes("route");
    // Nothing to show and nothing to switch on: this account has no activity data.
    if (!hasList && !disabled && !hasRoute) return nothing;
    return html`
      <section class="card wide" aria-labelledby="h-activities">
        <h2 id="h-activities">${this._heading("activities")}</h2>
        <div class="activities-layout">
          <garmin-activities
            .activities=${snapshot.activities}
            ?truncated=${Boolean(snapshot.activities_truncated)}
            ?disabled=${disabled}
            .fmt=${this._fmt}
            .t=${t}
          ></garmin-activities>
          ${hasRoute
            ? html`<div class="route">
                <h3>${t("route_title")}</h3>
                <garmin-route .route=${this._route} ?route-hidden=${this._routeHidden} .t=${t}></garmin-route>
              </div>`
            : nothing}
        </div>
      </section>
    `;
  }

  private _renderChartGroup(group: ChartDef["group"]): TemplateResult | typeof nothing {
    const t = this._t;
    const charts = this._visibleCharts(group);
    if (!charts.length) return nothing;
    return html`
      <section class="charts" aria-labelledby="h-${group}">
        <div class="charts-head">
          <h2 id="h-${group}">${t(`group_${group}`)}</h2>
          ${group === "trends"
            ? html`<div class="segmented" role="radiogroup" aria-label=${t("range_label")}>
                ${TREND_RANGES.map((d) => html`<button role="radio" aria-checked=${this._trendRange === d}
                  @click=${() => this._setTrendRange(d)}>${t("range_days", { days: String(d) })}</button>`)}
              </div>`
            : nothing}
        </div>
        <div class="chart-grid">
          ${charts.map((chart) => html`
            <div class="card">
              ${this._chartErrors[chart.id]
                ? html`<h3 class="chart-title">${t(`chart_${chart.id}` as MessageKey)}</h3>
                    <p class="muted">${t(this._chartErrors[chart.id]!)}</p>`
                : html`<garmin-chart
                    .payload=${this._charts[chart.id]}
                    .fmt=${this._fmt}
                    .t=${t}
                    .heading=${t(`chart_${chart.id}` as MessageKey)}
                    .seriesLabels=${this._seriesLabels(chart)}
                    ?refreshing=${this._refreshing.has(chart.id) && this._charts[chart.id] !== undefined}
                  ></garmin-chart>`}
            </div>`)}
        </div>
      </section>
    `;
  }

  private _seriesLabels(chart: ChartDef): Record<string, string> {
    const t = this._t;
    return Object.fromEntries(
      chart.metrics.map((m) => [m, hasMessage(`metric_${m}`) ? t(`metric_${m}` as MessageKey) : m]),
    );
  }

  private _renderSettings(): TemplateResult {
    const snapshot = this._snapshot;
    const available = new Set(
      Object.values(snapshot?.metrics ?? {})
        .filter((m) => !HIDDEN_STATUSES.has(m.status))
        .map((m) => m.key),
    );
    return html`
      <garmin-settings
        .preferences=${this._prefs}
        .available=${available}
        .t=${this._t}
        ?busy=${this._saving}
        @save=${(e: CustomEvent<Preferences>) => this._savePreferences(e.detail)}
        @reset=${() => this._savePreferences("reset")}
        @cancel=${() => (this._view = "dashboard")}
      ></garmin-settings>
    `;
  }

  private _renderSourceState(snapshot: ProfileSnapshot): TemplateResult {
    const t = this._t;
    const sync = snapshot.source_synced_at
      ? [
          `${t("last_sync")}: ${new Date(snapshot.source_synced_at).toLocaleString(this._fmt.locale, { dateStyle: "medium", timeStyle: "short" })}`,
          snapshot.source_sync_device,
        ]
          .filter(Boolean)
          .join(" · ")
      : t("last_sync_unknown");
    const warn = snapshot.source_status !== "ready";
    return html`
      <p class="source ${warn ? "warn" : ""}" role=${warn ? "alert" : "status"}>
        ${warn
          ? html`<strong class="alert"><span aria-hidden="true">⚠</span> ${t(`source_${snapshot.source_status}`)}
              ${snapshot.source_status === "reauth" || snapshot.source_status === "offline"
                ? html`<a href=${SOURCE_PAGE} @click=${navigateInApp}>${t("open_garmin_connect")}</a>`
                : nothing}</strong>`
          : nothing}
        <span>${sync}</span>
      </p>
    `;
  }

  private _renderSection(snapshot: ProfileSnapshot, section: Section, keys: string[]): TemplateResult | typeof nothing {
    const hiddenMetrics = new Set(this._prefs?.hidden_metrics ?? []);
    const metrics = keys
      .filter((key) => !hiddenMetrics.has(key))
      .map((key) => snapshot.metrics[key])
      .filter((m): m is Metric => m !== undefined && !HIDDEN_STATUSES.has(m.status));
    const plan = section === "training" ? (snapshot.plan ?? null) : null;
    // A section the account never provides is hidden (e.g. no sleep data on a bike-only setup).
    if (metrics.length === 0 && !plan) return nothing;
    return html`
      <section class="card" aria-labelledby="h-${section}">
        <h2 id="h-${section}">${this._heading(section)}</h2>
        ${metrics.length ? html`<div class="tiles">${metrics.map((m) => this._renderMetric(snapshot, m))}</div>` : nothing}
        ${plan ? this._renderPlan(plan) : nothing}
      </section>
    `;
  }

  /** Card heading with its section icon in a tinted badge. */
  private _heading(section: keyof typeof SECTION_ICONS): TemplateResult {
    return html`<span class="badge" aria-hidden="true">${icon(SECTION_ICONS[section], 18)}</span>${this._t(`section_${section}`)}`;
  }

  private _renderMetric(snapshot: ProfileSnapshot, metric: Metric): TemplateResult {
    const t = this._t;
    const labelKey = `metric_${metric.key}`;
    const label = hasMessage(labelKey) ? t(labelKey) : metric.key;
    const showable = metric.status === "available" || metric.status === "unavailable";
    const category = metric.kind === "category" && typeof metric.value === "string" ? categoryMessage(metric.value) : null;
    const signed = SIGNED[metric.key];
    const shown = !showable
      ? null
      : category
        ? t(category)
        : signed && typeof metric.value === "number"
          ? `${signed}${new Intl.NumberFormat(this._fmt.locale).format(metric.value)}`
          : formatMetric(this._fmt, metric);
    const tone = category && typeof metric.value === "string" ? categoryTone(metric.key, metric.value) : null;
    const statusKey = `status_${metric.status}`;
    const stale = metric.freshness === "stale";
    return html`
      <div class="tile">
        <div class="label">${METRIC_ICONS[metric.key] ? icon(METRIC_ICONS[metric.key]!, 16) : nothing}<span>${label}</span></div>
        ${shown !== null
          ? tone
            ? html`<div class="value status ${tone}">${icon(TONE_ICONS[tone], 20)}<span>${shown}</span></div>`
            : html`<div class="value">${shown}</div>`
          : html`<div class="value empty">—</div>`}
        ${TARGETS[metric.key] ? this._renderGoal(snapshot, metric) : nothing}
        ${metric.status !== "available" && hasMessage(statusKey)
          ? html`<div class="note">${t(statusKey)}</div>`
          : nothing}
        ${stale ? html`<div class="note warn">⚠ ${t("stale")}</div>` : nothing}
      </div>
    `;
  }

  private _renderPlan(plan: TrainingPlan): TemplateResult {
    const t = this._t;
    const day = (iso: string) =>
      new Date(`${iso}T12:00:00`).toLocaleDateString(this._fmt.locale, { weekday: "short", day: "numeric", month: "short" });
    const row = (label: string, w: PlannedWorkout) => html`<li>
      <span class="plan-label">${label}</span>
      <span class="plan-main">${w.title}${w.sport ? html` <small>${sportLabel(t, w.sport)}</small>` : nothing}</span>
      <span class="plan-when">${day(w.date)}</span>
    </li>`;
    const goal = plan.goal;
    return html`
      <h3 class="sub">${t("plan_title")}</h3>
      <ul class="list plan">
        ${plan.today ? row(t("plan_today"), plan.today) : nothing}
        ${plan.next ? row(t("plan_next"), plan.next) : nothing}
        ${plan.upcoming.map((w) => row(t("plan_upcoming"), w))}
        ${goal
          ? html`<li>
              <span class="plan-label">${t("plan_goal")}</span>
              <span class="plan-main">${goal.name}
                <small>${[
                  goal.distance_meters !== null ? formatDistance(this._fmt, goal.distance_meters) : null,
                  goal.predicted_seconds !== null
                    ? t("plan_predicted", { time: formatNumber(this._fmt, "duration", goal.predicted_seconds) })
                    : null,
                ]
                  .filter(Boolean)
                  .join(" · ")}</small></span>
              <span class="plan-when"><strong>${goal.days_until === 0
                ? t("plan_race_day")
                : t("plan_days_left", { n: String(goal.days_until) })}</strong> · ${day(goal.date)}</span>
            </li>`
          : nothing}
      </ul>
    `;
  }

  private _renderGoal(snapshot: ProfileSnapshot, metric: Metric): TemplateResult | typeof nothing {
    const target = TARGETS[metric.key];
    if (!target) return nothing;
    const goal = snapshot.metrics[target.metric];
    const progress = goalProgress(
      typeof metric.value === "number" ? metric.value : null,
      goal?.status === "available" && typeof goal.value === "number" ? goal.value : null,
    );
    if (!progress || !goal) return nothing;
    const goalText = formatMetric(this._fmt, goal) ?? "";
    return html`
      <div class="progress" role="progressbar" aria-valuenow=${Math.round(progress.percent)} aria-valuemin="0">
        <div class="bar" style="width: ${progress.bar}%"></div>
      </div>
      <div class="note">${Math.round(progress.percent)}% · ${this._t(target.label, { goal: goalText })}</div>
    `;
  }

  private _renderGear(snapshot: ProfileSnapshot): TemplateResult | typeof nothing {
    const t = this._t;
    const gear = snapshot.gear.filter((g) => g.status === "available" && g.distance_meters !== null);
    const sensors = snapshot.sensors ?? [];
    if (gear.length === 0 && sensors.length === 0) return nothing;
    return html`
      <section class="card" aria-labelledby="h-gear">
        <h2 id="h-gear">${this._heading("gear")}</h2>
        ${gear.length
          ? html`<ul class="list">
              ${gear.map(
                (g) => html`<li>
                  <span>${g.name ?? "—"}${g.retired ? html` <small>(${t("retired")})</small>` : nothing}</span>
                  <strong>${formatDistance(this._fmt, g.distance_meters ?? 0)}</strong>
                </li>`,
              )}
            </ul>`
          : nothing}
        ${sensors.length
          ? html`<h3 class="sub">${t("sensors_title")}</h3>
              <ul class="list">
                ${sensors.map((s) => {
                  const status = (s.battery_status ?? "unknown").toLowerCase();
                  const key = `battery_${status}`;
                  const warn = status === "low" || status === "critical";
                  return html`<li>
                    <span>${sensorLabel(t, s.type)}${s.manufacturer ? html` <small>${s.manufacturer}</small>` : nothing}</span>
                    <span class=${warn ? "battery warn" : "battery"}>
                      ${warn ? html`<span aria-hidden="true">⚠</span> ` : nothing}${hasMessage(key) ? t(key) : s.battery_status}${s.battery_level !== null ? ` · ${s.battery_level}%` : ""}
                    </span>
                  </li>`;
                })}
              </ul>`
          : nothing}
      </section>
    `;
  }

  private _renderStatus(): TemplateResult | typeof nothing {
    const t = this._t;
    const info = this._profiles?.find((p) => p.profile_id === this._profileId);
    if (!info) return nothing;
    const counts = info.status.metric_counts;
    const snapshot = this._snapshot;
    const empty = snapshot ? this._emptySections(snapshot) : [];
    const readAt = snapshot?.observed_at
      ? new Date(snapshot.observed_at).toLocaleTimeString(this._fmt.locale, { hour: "2-digit", minute: "2-digit" })
      : "—";
    return html`
      <section class="card" aria-labelledby="h-status">
        <div class="status-head">
          <h2 id="h-status">${this._heading("status")}</h2>
          <button class="refresh" ?disabled=${this._refreshBusy} title=${t("status_refresh_hint")}
            @click=${() => this._refresh()}>${this._refreshBusy ? t("status_refreshing") : t("status_refresh")}</button>
        </div>
        <ul class="list">
          <li><span>${t("status_read_at")}</span><strong>${readAt}</strong></li>
          <li><span>${t("source_version")}</span><strong>${info.status.source_version ?? "—"}</strong></li>
          <li><span>${t("compatible")}</span><strong>${
            !info.status.compatible ? t("compatible_no") : info.status.verified ? t("compatible_yes") : t("compatible_series")
          }</strong></li>
          <li><span>${t("metrics_found")}</span><strong>${counts.resolved ?? 0}</strong></li>
          <li><span>${t("metrics_off")}</span><strong>${counts.disabled ?? 0}</strong></li>
          <li><span>${t("metrics_missing")}</span><strong>${(counts.missing ?? 0) + (counts.ambiguous ?? 0)}</strong></li>
          ${empty.length
            ? html`<li><span>${t("status_no_data_sections")}</span><strong class="wrap">${empty.join(", ")}</strong></li>`
            : nothing}
          <li>
            <span>${t("status_diagnostics")}</span>
            <span class="stack-right">
              <a href=${DASHBOARD_PAGE} @click=${navigateInApp}>${t("status_diagnostics_open")}</a>
              <small>${t("status_diagnostics_hint")}</small>
            </span>
          </li>
        </ul>
        <p class="hint">${t("status_refresh_hint")}</p>
      </section>
    `;
  }

  static override styles = css`
    :host {
      /* Chart palette, validated on HA's light and dark card surfaces. */
      --gd-series-1: #2a78d6;
      --gd-series-2: #eb6834;
      --gd-series-3: #1baf7a;
      --gd-series-4: #eda100;
      --gd-surface: var(--card-background-color, #fff);
      --gd-grid: var(--divider-color, #e8e8e8);
      /* Status colors are fixed across themes and always paired with an icon and a label. */
      --gd-good: #0ca30c;
      --gd-warning: #fab219;
      --gd-serious: #ec835a;
      --gd-zone-1: #86b6ef;
      --gd-zone-2: #5598e7;
      --gd-zone-3: #2a78d6;
      --gd-zone-4: #1c5cab;
      --gd-zone-5: #104281;
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
    select.profiles {
      max-width: 40vw; padding: 0 8px; border-radius: 8px; color: inherit; cursor: pointer;
      background: rgba(255, 255, 255, 0.15); border: 1px solid rgba(255, 255, 255, 0.4);
    }
    select.profiles option { color: var(--primary-text-color); background: var(--card-background-color); }
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
      box-shadow: var(--ha-card-box-shadow, none);
      padding: 16px;
      min-width: 0;
    }
    h2 { font-size: 16px; font-weight: 500; margin: 0 0 14px; display: flex; align-items: center; gap: 10px; }
    .badge {
      display: inline-grid; place-items: center; width: 32px; height: 32px; flex: none; border-radius: 50%;
      color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    }
    .mdi { display: block; flex: none; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); gap: 16px 12px; }
    .tile { min-width: 0; }
    .label { font-size: 13px; color: var(--secondary-text-color); display: flex; align-items: flex-start; gap: 6px; }
    .label .mdi { margin-top: 1px; opacity: 0.8; }
    .value { font-size: 24px; font-weight: 500; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; margin-top: 2px; }
    .value.status { display: flex; align-items: center; gap: 6px; }
    .value.status .mdi { margin-top: 1px; }
    .value.good .mdi { color: var(--gd-good); }
    .value.warning .mdi { color: var(--gd-warning); }
    .value.serious .mdi { color: var(--gd-serious); }
    .value.neutral .mdi { color: var(--secondary-text-color); }
    .value.empty { color: var(--disabled-text-color, var(--secondary-text-color)); }
    .note { font-size: 12px; color: var(--secondary-text-color); margin-top: 2px; }
    .warn { color: var(--warning-color, #b26a00); }
    .progress { height: 6px; border-radius: 3px; background: var(--divider-color, #ddd); margin-top: 6px; overflow: hidden; }
    .bar { height: 100%; background: var(--primary-color); }
    .banner { padding: 12px 16px; border-radius: 8px; background: var(--card-background-color); margin: 0 0 16px; }
    .source { margin: 0 0 16px; color: var(--secondary-text-color); font-size: 14px; display: flex; flex-direction: column; gap: 6px; }
    .source .alert {
      color: var(--primary-text-color); font-weight: 500; padding: 10px 12px; border-radius: 8px;
      background: var(--card-background-color); border-left: 4px solid var(--warning-color, #b26a00);
    }
    .source .alert span { color: var(--warning-color, #b26a00); }
    .source .alert a { color: var(--primary-color); margin-left: 6px; white-space: nowrap; }
    .muted { color: var(--secondary-text-color); }
    .list { list-style: none; margin: 0; padding: 0; }
    .list li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px solid var(--divider-color, #eee); }
    .list li:last-child { border-bottom: 0; }
    @media (prefers-reduced-motion: no-preference) { .bar { transition: width 0.3s ease; } }
    :host([dark]) {
      --gd-zone-1: #184f95;
      --gd-zone-2: #256abf;
      --gd-zone-3: #3987e5;
      --gd-zone-4: #6da7ec;
      --gd-zone-5: #9ec5f4;
      --gd-series-1: #3987e5;
      --gd-series-2: #d95926;
      --gd-series-3: #199e70;
      --gd-series-4: #c98500;
    }
    .notice { margin: 16px 16px 0; }
    .card.wide { grid-column: 1 / -1; }
    .status-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
    .status-head h2 { margin: 0; }
    button.refresh {
      min-height: 44px; padding: 0 16px; border-radius: 8px; font: inherit; cursor: pointer;
      border: 1px solid var(--divider-color, #ccc); background: var(--card-background-color); color: var(--primary-text-color);
    }
    button.refresh:disabled { opacity: 0.6; cursor: default; }
    button.refresh:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }
    .list strong.wrap { text-align: right; }
    .list a { color: var(--primary-color); text-align: right; }
    .stack-right { display: flex; flex-direction: column; align-items: flex-end; text-align: right; }
    .stack-right small { color: var(--secondary-text-color); font-size: 12px; }
    .hint { font-size: 12px; color: var(--secondary-text-color); margin: 8px 0 0; }
    h3.sub { font-size: 13px; font-weight: 500; color: var(--secondary-text-color); margin: 12px 0 4px; }
    .plan li {
      display: grid; grid-template-columns: 1fr auto; grid-template-areas: "label when" "main main";
      align-items: baseline; gap: 2px 8px;
    }
    .plan-label { grid-area: label; }
    .plan-main { grid-area: main; }
    .plan-when { grid-area: when; }
    .plan-label { font-size: 12px; color: var(--secondary-text-color); }
    .plan-main { min-width: 0; overflow-wrap: anywhere; }
    .plan-main small { color: var(--secondary-text-color); margin-left: 4px; }
    .plan-when { font-size: 13px; white-space: nowrap; color: var(--secondary-text-color); }
    .plan-when strong { color: var(--primary-text-color); }
    .battery { white-space: nowrap; }
    .battery.warn { color: var(--warning-color, #b26a00); font-weight: 500; }
    .activities-layout { display: grid; gap: 16px; grid-template-columns: 1fr; }
    @media (min-width: 1000px) { .activities-layout { grid-template-columns: 3fr 2fr; } }
    .route h3 { font-size: 14px; font-weight: 500; margin: 0 0 6px; }
    .link { border: 0; background: none; color: var(--primary-color); font: inherit; cursor: pointer; min-height: 44px; }
    .charts { margin-top: 24px; }
    .charts-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }
    .charts-head h2 { margin: 0; }
    .chart-grid { display: grid; gap: 16px; grid-template-columns: 1fr; }
    @media (min-width: 900px) { .chart-grid { grid-template-columns: repeat(2, 1fr); } }
    .chart-title { font-size: 14px; font-weight: 500; margin: 0 0 6px; }
    .segmented { display: inline-flex; border: 1px solid var(--divider-color, #ccc); border-radius: 8px; overflow: hidden; }
    .segmented button {
      min-height: 44px; padding: 0 14px; border: 0; background: var(--card-background-color);
      color: var(--primary-text-color); font: inherit; cursor: pointer;
    }
    .segmented button + button { border-left: 1px solid var(--divider-color, #ccc); }
    .segmented button[aria-checked="true"] { background: var(--primary-color); color: var(--text-primary-color, #fff); }
    .segmented button:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  `;
}

if (!customElements.get("garmin-dashboard-panel")) {
  customElements.define("garmin-dashboard-panel", GarminDashboardPanel);
}
