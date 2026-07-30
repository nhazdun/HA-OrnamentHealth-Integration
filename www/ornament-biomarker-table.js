/**
 * Ornament biomarker table — a Lovelace card that lists every biomarker the
 * Ornament Health integration exposes, with its reference range, status and a
 * sparkline of its measurement history.
 *
 * Everything is read from the sensors' own attributes (`biomarker_id`,
 * `history`, `reference_min` ...), so the card needs no recorder queries and
 * no entity list in its config.
 *
 * Usage:
 *   type: custom:ornament-biomarker-table
 */

const CARD_VERSION = "1.0.0";

const TEXT = {
  search: "Пошук біомаркера…",
  all: "Усі",
  columns: {
    name: "Біомаркер",
    category: "Категорія",
    value: "Значення",
    range: "Діапазон",
    chart: "Динаміка",
    status: "Статус",
    tested: "Дата аналізу",
  },
  status: {
    concern: "Поза нормою",
    watch: "Увага",
    normal: "Норма",
    optimal: "Оптимально",
  },
  sort: {
    label: "Сортування",
    category: "За категорією",
    status: "За статусом",
    name: "За назвою",
    date: "За датою",
  },
  empty: "Нічого не знайдено",
  noEntities:
    "Не знайдено жодного біомаркера Ornament. Перевірте, що інтеграція Ornament Health налаштована.",
  biomarkers: "біомаркерів",
  lastReport: "Останній аналіз",
};

const STATUS_ORDER = ["concern", "watch", "normal", "optimal"];

/** Order the status pills use, most severe first. */
const SEVERITY = { concern: 0, watch: 1, normal: 2, optimal: 3 };

/**
 * Classify a biomarker against its reference and optimal ranges.
 *
 * Ornament flags out-of-reference values itself (`is_abnormal`); the optimal
 * range is a narrower band inside the reference one, so a value that clears
 * the reference range but misses the optimal band is worth watching.
 */
function statusOf(attrs, value) {
  if (attrs.is_abnormal) return "concern";
  if (typeof value !== "number" || Number.isNaN(value)) return "normal";

  const { optimal_min: oMin, optimal_max: oMax } = attrs;
  const { reference_min: rMin, reference_max: rMax } = attrs;
  if (oMin == null && oMax == null) return "normal";

  const inOptimal =
    (oMin == null || value >= oMin) && (oMax == null || value <= oMax);
  if (!inOptimal) return "watch";

  const narrower =
    (oMin != null && rMin != null && oMin > rMin) ||
    (oMax != null && rMax != null && oMax < rMax);
  return narrower ? "optimal" : "normal";
}

function formatNumber(value, locale) {
  if (typeof value !== "number" || Number.isNaN(value)) return String(value);
  const magnitude = Math.abs(value);
  const digits = magnitude >= 100 ? 1 : magnitude >= 10 ? 2 : 3;
  return value.toLocaleString(locale, { maximumFractionDigits: digits });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Strip the device prefix Home Assistant prepends to the entity name, e.g.
 * "Ornament Nazariy Lipids Cholesterol" -> "Cholesterol".
 */
function biomarkerTitle(friendlyName, category) {
  if (!friendlyName) return "";
  if (category) {
    const marker = `${category} `;
    const at = friendlyName.indexOf(marker);
    if (at >= 0) return friendlyName.slice(at + marker.length);
  }
  return friendlyName;
}

/**
 * Build a sparkline of the measurement history.
 *
 * `band` draws the reference bounds as dashed guides. The vertical scale comes
 * from the data alone, so a bound only shows up when the series actually runs
 * close to it — which is when it tells you something.
 */
function sparkline(values, { band, step = false, width = 116, height = 30 }) {
  if (!values || values.length < 2) return '<span class="muted">—</span>';

  const pad = 4;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (max === min) {
    min -= 1;
    max += 1;
  } else {
    const margin = (max - min) * 0.12;
    min -= margin;
    max += margin;
  }

  const x = (i) => pad + (i / (values.length - 1)) * innerW;
  const y = (v) => pad + innerH - ((v - min) / (max - min)) * innerH;

  let line = `M ${x(0).toFixed(1)} ${y(values[0]).toFixed(1)}`;
  for (let i = 1; i < values.length; i += 1) {
    if (step) line += ` L ${x(i).toFixed(1)} ${y(values[i - 1]).toFixed(1)}`;
    line += ` L ${x(i).toFixed(1)} ${y(values[i]).toFixed(1)}`;
  }
  let guides = "";
  if (band) {
    for (const bound of [band.min, band.max]) {
      if (bound == null || bound <= min || bound >= max) continue;
      const at = y(bound).toFixed(1);
      guides +=
        `<line class="guide" x1="${pad}" y1="${at}" ` +
        `x2="${width - pad}" y2="${at}" />`;
    }
  }

  const lastX = x(values.length - 1).toFixed(1);
  const lastY = y(values[values.length - 1]).toFixed(1);

  return (
    `<svg class="spark" viewBox="0 0 ${width} ${height}" width="${width}" ` +
    `height="${height}" preserveAspectRatio="none" aria-hidden="true">` +
    guides +
    `<path class="line" d="${line}" />` +
    `<circle class="head" cx="${lastX}" cy="${lastY}" r="2.6" />` +
    `</svg>`
  );
}

/** Render the min ... marker ... max range strip. */
function rangeStrip(row) {
  const { referenceMin: min, referenceMax: max } = row;
  if (min == null || max == null || max <= min || typeof row.value !== "number") {
    return '<span class="muted">—</span>';
  }

  const pos = Math.min(100, Math.max(0, ((row.value - min) / (max - min)) * 100));
  const { optimalMin: oMin, optimalMax: oMax } = row;
  let optimal = "";
  if (oMin != null && oMax != null && oMax > oMin) {
    const left = Math.min(100, Math.max(0, ((oMin - min) / (max - min)) * 100));
    const right = Math.min(100, Math.max(0, ((oMax - min) / (max - min)) * 100));
    if (right > left) {
      optimal = `<span class="optimal" style="left:${left.toFixed(
        1
      )}%;width:${(right - left).toFixed(1)}%"></span>`;
    }
  }

  return (
    `<span class="bound">${escapeHtml(row.minLabel)}</span>` +
    `<span class="track">${optimal}` +
    `<span class="marker" style="left:${pos.toFixed(1)}%"></span></span>` +
    `<span class="bound">${escapeHtml(row.maxLabel)}</span>`
  );
}

const STYLES = `
  :host { display: block; }
  ha-card { padding: 0; overflow: hidden; }

  .head { padding: 20px 20px 4px; }
  .title {
    font-size: 22px;
    font-weight: 600;
    color: var(--primary-text-color);
  }
  .subtitle {
    margin-top: 4px;
    font-size: 13px;
    color: var(--secondary-text-color);
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
    padding: 16px 20px 0;
  }
  .search {
    flex: 1 1 220px;
    min-width: 180px;
    padding: 9px 12px;
    font: inherit;
    font-size: 14px;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    border-radius: 10px;
    box-sizing: border-box;
  }
  .search:focus {
    outline: none;
    border-color: var(--primary-color);
  }
  .sort {
    padding: 9px 10px;
    font: inherit;
    font-size: 13px;
    color: var(--primary-text-color);
    background: var(--card-background-color);
    border: 1px solid var(--divider-color);
    border-radius: 10px;
  }

  .chips, .pills {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    padding: 14px 20px 0;
  }
  .chip, .pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 5px 12px;
    font-size: 12.5px;
    line-height: 1.5;
    color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border: 1px solid transparent;
    border-radius: 999px;
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }
  .chip:hover, .pill:hover { color: var(--primary-text-color); }
  .chip[data-active="true"] {
    color: var(--primary-color);
    background: rgba(3, 169, 244, 0.12);
    background: color-mix(in srgb, var(--primary-color) 14%, transparent);
    font-weight: 500;
  }
  .pill .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--st, var(--secondary-text-color));
  }
  .pill .count { opacity: 0.7; }
  .pill[data-active="true"] {
    color: var(--st, var(--primary-text-color));
    border-color: var(--st, var(--divider-color));
    background: rgba(0, 0, 0, 0.04);
    background: color-mix(in srgb, var(--st, currentColor) 12%, transparent);
    font-weight: 600;
  }

  .scroller { margin-top: 16px; overflow-x: auto; }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13.5px;
  }
  thead th {
    position: sticky;
    top: 0;
    z-index: 1;
    padding: 10px 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-align: left;
    white-space: nowrap;
    color: var(--secondary-text-color);
    background: var(--card-background-color);
    border-bottom: 1px solid var(--divider-color);
  }
  thead th:first-child { padding-left: 20px; }
  thead th:last-child { padding-right: 20px; }

  tbody td {
    padding: 9px 12px;
    vertical-align: middle;
    border-bottom: 1px solid var(--divider-color);
  }
  tbody td:first-child { padding-left: 20px; }
  tbody td:last-child { padding-right: 20px; }
  tbody tr.row { cursor: pointer; }
  tbody tr.row:hover td { background: var(--secondary-background-color); }

  tr.group td {
    padding: 8px 20px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-bottom: 1px solid var(--divider-color);
  }

  .name {
    font-weight: 500;
    color: var(--st, var(--primary-text-color));
  }
  .category { color: var(--secondary-text-color); white-space: nowrap; }
  .value { font-weight: 600; color: var(--primary-text-color); }
  .unit {
    margin-left: 3px;
    font-size: 11.5px;
    font-weight: 400;
    color: var(--secondary-text-color);
  }
  .muted { color: var(--secondary-text-color); opacity: 0.6; }

  .range { display: flex; align-items: center; gap: 8px; min-width: 168px; }
  .bound { font-size: 11px; color: var(--secondary-text-color); white-space: nowrap; }
  .track {
    position: relative;
    flex: 1;
    height: 3px;
    min-width: 84px;
    border-radius: 2px;
    background: var(--divider-color);
  }
  .track .optimal {
    position: absolute;
    top: 0;
    height: 100%;
    border-radius: 2px;
    background: var(--success-color, #2e9e5b);
    opacity: 0.45;
  }
  .track .marker {
    position: absolute;
    top: 50%;
    width: 11px;
    height: 11px;
    margin-left: -5.5px;
    border: 2px solid var(--st, var(--primary-color));
    border-radius: 50%;
    background: var(--card-background-color);
    transform: translateY(-50%);
    box-sizing: border-box;
  }

  .chart { display: flex; align-items: center; gap: 8px; min-width: 158px; }
  .spark { display: block; overflow: visible; }
  .spark .line {
    fill: none;
    stroke: var(--st, var(--primary-color));
    stroke-width: 1.6;
    stroke-linejoin: round;
    stroke-linecap: round;
  }
  .spark .head { fill: var(--st, var(--primary-color)); }
  .spark .guide {
    stroke: var(--secondary-text-color);
    stroke-width: 1;
    stroke-dasharray: 2 3;
    opacity: 0.45;
  }
  /* Deliberately neutral: falling is good for some biomarkers and bad for
     others, so the arrow states the direction and nothing more. */
  .delta { font-size: 11.5px; white-space: nowrap; color: var(--secondary-text-color); }

  .badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    white-space: nowrap;
    color: var(--st);
    border-radius: 999px;
    background: rgba(0, 0, 0, 0.05);
    background: color-mix(in srgb, var(--st) 14%, transparent);
  }
  .badge .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--st); }
  .date { color: var(--secondary-text-color); white-space: nowrap; }

  .empty {
    padding: 32px 20px;
    text-align: center;
    color: var(--secondary-text-color);
  }

  [data-status="concern"] { --st: var(--error-color, #db4437); }
  [data-status="watch"] { --st: var(--warning-color, #f5a524); }
  [data-status="normal"] { --st: var(--info-color, #3b82f6); }
  [data-status="optimal"] { --st: var(--success-color, #2e9e5b); }

  @media (max-width: 1000px) {
    .col-category { display: none; }
  }
  @media (max-width: 800px) {
    .col-range { display: none; }
  }
  @media (max-width: 560px) {
    .col-date { display: none; }
    thead th:first-child, tbody td:first-child { padding-left: 12px; }
    thead th:last-child, tbody td:last-child { padding-right: 12px; }
  }
`;

class OrnamentBiomarkerTable extends HTMLElement {
  static getStubConfig() {
    return { type: "custom:ornament-biomarker-table" };
  }

  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._filters = { search: "", category: "all", status: "all" };
    this._sort = "category";
    this._shell = false;
    this._signature = "";
  }

  setConfig(config) {
    this._config = {
      title: "Бібліотека біомаркерів",
      chart_points: 12,
      ...config,
    };
    this._signature = "";
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  getCardSize() {
    return 20;
  }

  /** Collect one row per biomarker sensor. */
  _collect() {
    const hass = this._hass;
    const locale = hass.locale?.language || "uk";
    const rows = [];

    for (const entityId of Object.keys(hass.states)) {
      if (!entityId.startsWith("sensor.")) continue;
      const state = hass.states[entityId];
      const attrs = state.attributes || {};
      if (attrs.biomarker_id === undefined) continue;
      if (state.state === "unavailable" || state.state === "unknown") continue;

      const isQualitative = Array.isArray(attrs.options) && attrs.options.length > 0;
      const numeric = Number(state.state);
      const value = isQualitative || Number.isNaN(numeric) ? state.state : numeric;
      const status = statusOf(attrs, typeof value === "number" ? value : null);
      const history = Array.isArray(attrs.history) ? attrs.history : [];
      const points = history
        .slice(-this._config.chart_points)
        .map((item) =>
          isQualitative ? attrs.options.indexOf(item.value) : Number(item.value)
        )
        .filter((item) => typeof item === "number" && !Number.isNaN(item) && item >= 0);

      rows.push({
        entityId,
        status,
        category: attrs.category || "—",
        title: biomarkerTitle(attrs.friendly_name, attrs.category),
        value,
        valueLabel:
          typeof value === "number" ? formatNumber(value, locale) : String(value),
        unit: isQualitative ? "" : attrs.unit_of_measurement || "",
        isQualitative,
        referenceMin: attrs.reference_min ?? null,
        referenceMax: attrs.reference_max ?? null,
        optimalMin: attrs.optimal_min ?? null,
        optimalMax: attrs.optimal_max ?? null,
        minLabel: formatNumber(attrs.reference_min, locale),
        maxLabel: formatNumber(attrs.reference_max, locale),
        previous: attrs.previous_value ?? null,
        measuredAt: attrs.measured_at || null,
        measurementCount: attrs.measurement_count || history.length,
        points,
      });
    }
    return rows;
  }

  _update() {
    if (!this._hass || !this._config) return;
    const rows = this._collect();
    const signature = rows
      .map((row) => `${row.entityId}:${row.valueLabel}:${row.measuredAt}`)
      .join("|");
    if (signature === this._signature && this._shell) return;
    this._signature = signature;
    this._rows = rows;

    if (!this._shell) this._renderShell();
    this._renderHeader();
    this._renderBody();
  }

  _renderShell() {
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        <div class="head">
          <div class="title"></div>
          <div class="subtitle"></div>
        </div>
        <div class="toolbar">
          <input class="search" type="search" placeholder="${TEXT.search}" />
          <select class="sort" aria-label="${TEXT.sort.label}">
            <option value="category">${TEXT.sort.category}</option>
            <option value="status">${TEXT.sort.status}</option>
            <option value="name">${TEXT.sort.name}</option>
            <option value="date">${TEXT.sort.date}</option>
          </select>
        </div>
        <div class="chips"></div>
        <div class="pills"></div>
        <div class="scroller">
          <table>
            <thead>
              <tr>
                <th>${TEXT.columns.name}</th>
                <th class="col-category">${TEXT.columns.category}</th>
                <th>${TEXT.columns.value}</th>
                <th class="col-range">${TEXT.columns.range}</th>
                <th>${TEXT.columns.chart}</th>
                <th>${TEXT.columns.status}</th>
                <th class="col-date">${TEXT.columns.tested}</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </ha-card>
    `;

    const root = this.shadowRoot;
    root.querySelector(".search").addEventListener("input", (event) => {
      this._filters.search = event.target.value.trim().toLowerCase();
      this._renderHeader();
      this._renderBody();
    });
    root.querySelector(".sort").addEventListener("change", (event) => {
      this._sort = event.target.value;
      this._renderBody();
    });
    root.querySelector(".chips").addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      this._filters.category = chip.dataset.value;
      this._renderHeader();
      this._renderBody();
    });
    root.querySelector(".pills").addEventListener("click", (event) => {
      const pill = event.target.closest(".pill");
      if (!pill) return;
      this._filters.status = pill.dataset.value;
      this._renderHeader();
      this._renderBody();
    });
    root.querySelector("tbody").addEventListener("click", (event) => {
      const row = event.target.closest("tr.row");
      if (!row) return;
      const detail = { entityId: row.dataset.entity };
      const moreInfo = new Event("hass-more-info", {
        bubbles: true,
        composed: true,
      });
      moreInfo.detail = detail;
      this.dispatchEvent(moreInfo);
    });

    this._shell = true;
  }

  /** Rows left after the category and search filters, before the status filter. */
  _scoped() {
    const { search, category } = this._filters;
    return this._rows.filter((row) => {
      if (category !== "all" && row.category !== category) return false;
      if (!search) return true;
      return (
        row.title.toLowerCase().includes(search) ||
        row.category.toLowerCase().includes(search)
      );
    });
  }

  _visible() {
    const { status } = this._filters;
    const rows = this._scoped().filter(
      (row) => status === "all" || row.status === status
    );

    const byName = (a, b) => a.title.localeCompare(b.title);
    if (this._sort === "name") return rows.sort(byName);
    if (this._sort === "status")
      return rows.sort(
        (a, b) => SEVERITY[a.status] - SEVERITY[b.status] || byName(a, b)
      );
    if (this._sort === "date")
      return rows.sort(
        (a, b) =>
          new Date(b.measuredAt || 0) - new Date(a.measuredAt || 0) || byName(a, b)
      );
    return rows.sort(
      (a, b) => a.category.localeCompare(b.category) || byName(a, b)
    );
  }

  _renderHeader() {
    const root = this.shadowRoot;
    const locale = this._hass.locale?.language || "uk";
    const dates = this._rows
      .map((row) => row.measuredAt)
      .filter(Boolean)
      .sort();
    const latest = dates.length ? new Date(dates[dates.length - 1]) : null;

    root.querySelector(".title").textContent = this._config.title;
    const total = `${this._rows.length} ${TEXT.biomarkers}`;
    root.querySelector(".subtitle").textContent = latest
      ? `${total} · ${TEXT.lastReport}: ${latest.toLocaleDateString(locale, {
          day: "numeric",
          month: "long",
          year: "numeric",
        })}`
      : total;

    const categories = [...new Set(this._rows.map((row) => row.category))].sort();
    root.querySelector(".chips").innerHTML = [
      { value: "all", label: `${TEXT.all} (${this._rows.length})` },
      ...categories.map((category) => ({
        value: category,
        label: `${category} (${
          this._rows.filter((row) => row.category === category).length
        })`,
      })),
    ]
      .map(
        (chip) =>
          `<span class="chip" data-value="${escapeHtml(chip.value)}" ` +
          `data-active="${this._filters.category === chip.value}">` +
          `${escapeHtml(chip.label)}</span>`
      )
      .join("");

    const scoped = this._scoped();
    root.querySelector(".pills").innerHTML = [
      `<span class="pill" data-value="all" data-active="${
        this._filters.status === "all"
      }">${TEXT.all}<span class="count">${scoped.length}</span></span>`,
      ...STATUS_ORDER.map((status) => {
        const count = scoped.filter((row) => row.status === status).length;
        return (
          `<span class="pill" data-status="${status}" data-value="${status}" ` +
          `data-active="${this._filters.status === status}">` +
          `<span class="dot"></span>${TEXT.status[status]}` +
          `<span class="count">${count}</span></span>`
        );
      }),
    ].join("");
  }

  _renderBody() {
    const body = this.shadowRoot.querySelector("tbody");
    const rows = this._visible();
    const locale = this._hass.locale?.language || "uk";

    if (!this._rows.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">${TEXT.noEntities}</td></tr>`;
      return;
    }
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="7" class="empty">${TEXT.empty}</td></tr>`;
      return;
    }

    const grouped = this._sort === "category";
    let currentGroup = null;
    const html = [];

    for (const row of rows) {
      if (grouped && row.category !== currentGroup) {
        currentGroup = row.category;
        html.push(
          `<tr class="group"><td colspan="7">${escapeHtml(currentGroup)}</td></tr>`
        );
      }

      const chart = sparkline(row.points, {
        step: row.isQualitative,
        band: row.isQualitative
          ? null
          : { min: row.referenceMin, max: row.referenceMax },
      });

      let delta = "";
      if (
        typeof row.value === "number" &&
        typeof row.previous === "number" &&
        row.previous !== 0
      ) {
        const change = ((row.value - row.previous) / Math.abs(row.previous)) * 100;
        const direction =
          Math.abs(change) < 0.05 ? "flat" : change > 0 ? "up" : "down";
        const arrow = direction === "flat" ? "→" : direction === "up" ? "↑" : "↓";
        delta = `<span class="delta ${direction}">${arrow} ${Math.abs(
          change
        ).toFixed(change >= 10 ? 0 : 1)}%</span>`;
      }

      const measured = row.measuredAt
        ? new Date(row.measuredAt).toLocaleDateString(locale, {
            day: "numeric",
            month: "short",
            year: "numeric",
          })
        : "—";

      html.push(
        `<tr class="row" data-status="${row.status}" data-entity="${escapeHtml(
          row.entityId
        )}">` +
          `<td><span class="name">${escapeHtml(row.title)}</span></td>` +
          `<td class="col-category category">${escapeHtml(row.category)}</td>` +
          `<td><span class="value">${escapeHtml(row.valueLabel)}</span>` +
          (row.unit ? `<span class="unit">${escapeHtml(row.unit)}</span>` : "") +
          `</td>` +
          `<td class="col-range"><div class="range">${rangeStrip(row)}</div></td>` +
          `<td><div class="chart">${chart}${delta}</div></td>` +
          `<td><span class="badge"><span class="dot"></span>${
            TEXT.status[row.status]
          }</span></td>` +
          `<td class="col-date date">${escapeHtml(measured)}</td>` +
          `</tr>`
      );
    }

    body.innerHTML = html.join("");
  }
}

customElements.define("ornament-biomarker-table", OrnamentBiomarkerTable);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "ornament-biomarker-table",
  name: "Ornament biomarker table",
  description:
    "Таблиця біомаркерів Ornament з діапазонами, статусами та спарклайнами динаміки.",
  preview: false,
});

console.info(`%c ORNAMENT-BIOMARKER-TABLE %c ${CARD_VERSION} `,
  "color: white; background: #2e9e5b; font-weight: 700;",
  "color: #2e9e5b; background: white; font-weight: 700;");
