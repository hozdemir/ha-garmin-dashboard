import { LitElement, css, html, nothing, svg, type TemplateResult } from "lit";

import type { Translate } from "./i18n";
import { projectRoute } from "./route-geometry";
import type { Route } from "./types";

const MAX_HEIGHT = 280;

/** The last synced route as a plain trace: no basemap, no network requests. */
export class GarminRoute extends LitElement {
  static override properties = {
    route: { attribute: false },
    hidden: { type: Boolean },
    t: { attribute: false },
    _width: { state: true },
  };

  route?: Route | null;
  override hidden = false;
  t?: Translate;
  private _width = 0;
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

  protected override render(): TemplateResult {
    const t = this.t;
    if (!t) return html``;
    if (this.hidden) return html`<p class="note">${t("route_hidden")}</p>`;
    if (this.route === undefined) return html`<div class="placeholder"></div>`;
    if (this.route === null) return html`<p class="note">${t("route_none")}</p>`;
    const p = this._width ? projectRoute(this.route.points, this._width, MAX_HEIGHT) : null;
    return html`
      ${this.route.title ? html`<p class="name">${this.route.title}</p>` : nothing}
      ${p
        ? html`<svg width=${p.width} height=${p.height} role="img" aria-label=${t("route_title")}>
            <path class="trace" d=${p.path}></path>
            ${svg`<circle class="start" cx=${p.start[0]} cy=${p.start[1]} r="5"><title>${t("route_start")}</title></circle>`}
            ${svg`<circle class="end" cx=${p.end[0]} cy=${p.end[1]} r="5"><title>${t("route_end")}</title></circle>`}
          </svg>
          <ul class="legend">
            <li><span class="key start"></span>${t("route_start")}</li>
            <li><span class="key end"></span>${t("route_end")}</li>
          </ul>`
        : html`<div class="placeholder"></div>`}
      <p class="note">${t("route_hint")}
        ${this.route.simplified ? html` ${t("route_simplified", { count: String(this.route.points.length) })}` : nothing}</p>
    `;
  }

  static override styles = css`
    :host { display: block; min-width: 0; }
    svg { display: block; }
    .trace { fill: none; stroke: var(--gd-series-1); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
    circle { stroke: var(--gd-surface); stroke-width: 2; }
    .start { fill: var(--gd-series-3); }
    .end { fill: var(--gd-series-2); }
    .name { margin: 0 0 6px; font-weight: 500; overflow-wrap: anywhere; }
    .note { font-size: 12px; color: var(--secondary-text-color); margin: 6px 0 0; }
    .legend { list-style: none; display: flex; gap: 16px; margin: 6px 0 0; padding: 0; font-size: 13px; }
    .legend li { display: flex; align-items: center; gap: 6px; }
    .key { width: 10px; height: 10px; border-radius: 50%; }
    .key.start { background: var(--gd-series-3); }
    .key.end { background: var(--gd-series-2); }
    .placeholder { height: 160px; }
  `;
}

if (!customElements.get("garmin-route")) {
  customElements.define("garmin-route", GarminRoute);
}
