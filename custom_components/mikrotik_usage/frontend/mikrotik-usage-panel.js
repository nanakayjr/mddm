/* Mikrotik Data Usage – dashboard panel (vanilla web component, no dependencies). */
const RX = "#2f7fc1", TX = "#e39a3b";
const PERIODS = { day: "Today", month: "This month", year: "This year" };
const MODES = {
  measured:  ["Measured", "Real router counters of the LAN device this integration talks to"],
  estimated: ["Estimated", "Cloud integration: polls per day x typical payload"],
  lan:       ["LAN estimate", "Local device that is not tracked; estimated from polling"],
  unmodelled:["Not estimable", "Streaming / media / camera: depends on use"],
};
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (b) => {
  if (b == null) return "–";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0, v = Math.abs(b);
  while (v >= 1000 && i < 4) { v /= 1000; i++; }
  return (i === 0 ? v.toFixed(0) : v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)) + " " + u[i];
};

const CSS = `
:host{display:block;min-height:100%;background:var(--primary-background-color);color:var(--primary-text-color);
  font-family:var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);--rx:${RX};--tx:${TX};
  --line:var(--divider-color,rgba(127,127,127,.25));--mute:var(--secondary-text-color)}
*{box-sizing:border-box}
header{display:flex;align-items:center;gap:12px;padding:12px 20px;background:var(--app-header-background-color,var(--card-background-color));
  border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header h1{font-size:20px;font-weight:500;margin:0;flex:1}
.menu{background:none;border:0;color:inherit;cursor:pointer;padding:6px;border-radius:50%;display:none}
.menu:focus-visible,.tab:focus-visible,.row:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}
:host([narrow]) .menu{display:inline-flex}
.tabs{display:flex;background:var(--secondary-background-color);border-radius:999px;padding:3px}
.tab{border:0;background:none;color:var(--mute);font:inherit;font-size:14px;padding:6px 16px;border-radius:999px;cursor:pointer}
.tab[aria-pressed=true]{background:var(--primary-color);color:var(--text-primary-color,#fff)}
main{max-width:1180px;margin:0 auto;padding:20px;display:grid;gap:20px;grid-template-columns:repeat(12,1fr)}
section{background:var(--card-background-color);border-radius:var(--ha-card-border-radius,14px);padding:20px;
  border:1px solid var(--line);min-width:0}
.sum{grid-column:span 5}.hist{grid-column:span 7}.rank{grid-column:span 12}.svc{grid-column:span 12}
@media(max-width:900px){.sum,.hist{grid-column:span 12}main{padding:12px;gap:12px}}
h2{font-size:16px;font-weight:500;margin:0 0 4px}
.sub{color:var(--mute);font-size:13px;margin:0 0 16px}
.big{font-size:44px;font-weight:300;letter-spacing:-.02em;line-height:1.1;font-variant-numeric:tabular-nums}
.split{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:16px 0 10px;background:var(--line)}
.split i{display:block;height:100%}
.legend{display:flex;gap:20px;font-size:14px;font-variant-numeric:tabular-nums}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.legend b{font-weight:500}
.top{margin-top:18px;font-size:14px;color:var(--mute)}.top b{color:var(--primary-text-color);font-weight:500}
svg text{fill:var(--mute);font-size:11px}
.axis{display:grid;grid-template-columns:minmax(90px,170px) 1fr minmax(0,0px);gap:0 12px;font-size:12px;color:var(--mute);margin-bottom:6px}
.axis div:nth-child(2){display:flex;justify-content:space-between}
.row{display:grid;grid-template-columns:minmax(90px,170px) 1fr 84px;gap:12px;align-items:center;padding:7px 8px;margin:0 -8px;
  border-radius:8px;cursor:pointer;font-size:14px}
.row:hover{background:var(--secondary-background-color)}
.row.static{cursor:default}.row.static:hover{background:none}
.row[aria-selected=true]{background:var(--secondary-background-color);box-shadow:inset 3px 0 0 var(--primary-color)}
.name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pct{color:var(--mute);font-size:12px}
.bars{display:grid;grid-template-columns:1fr 1px 1fr;align-items:center;height:20px}
.bars .l,.bars .r{height:100%;display:flex}.bars .l{justify-content:flex-end}
.bars .l i{background:var(--rx);border-radius:4px 0 0 4px;min-width:2px}
.bars .r i{background:var(--tx);border-radius:0 4px 4px 0;min-width:2px}
.bars .ax{height:100%;background:var(--mute);opacity:.5}
.val{text-align:right;font-variant-numeric:tabular-nums}
.cmp{display:flex;gap:24px;flex-wrap:wrap;margin:0 0 16px;font-size:14px}
.cmp div b{display:block;font-size:22px;font-weight:400;font-variant-numeric:tabular-nums}
.cmp span{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}
th{font-weight:500;text-align:left;color:var(--mute);font-size:13px;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:8px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
th.n,td.n{text-align:right}
.tag{font-size:12px;padding:2px 9px;border-radius:999px;background:var(--secondary-background-color);color:var(--mute);white-space:nowrap}
.tag.measured{background:color-mix(in srgb,var(--rx) 18%,transparent);color:var(--primary-text-color)}
.scroll{overflow-x:auto}.note{color:var(--mute);font-size:12.5px;margin:14px 0 0;max-width:70ch}
.empty{padding:40px 12px;text-align:center;color:var(--mute)}
`;

class MikrotikUsagePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._period = null; this._sel = null; this._hist = null; this._histKey = ""; this._histTs = 0; this._raf = 0;
    this.shadowRoot.innerHTML = `<style>${CSS}</style><div id="app"></div>`;
    this.shadowRoot.addEventListener("click", (e) => {
      const t = e.target.closest("[data-period],[data-key],.menu"); if (!t) return;
      if (t.classList.contains("menu")) this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
      else if (t.dataset.period) { this._period = t.dataset.period; this._render(); }
      else { this._sel = this._sel === t.dataset.key ? null : t.dataset.key; this._render(); }
    });
    this.shadowRoot.addEventListener("keydown", (e) => {
      if ((e.key === "Enter" || e.key === " ") && e.target.dataset && e.target.dataset.key) { e.preventDefault(); e.target.click(); }
    });
  }
  set narrow(v) { v ? this.setAttribute("narrow", "") : this.removeAttribute("narrow"); }
  set panel(_) {}
  set hass(h) {
    this._hass = h;
    if (!this._raf) this._raf = requestAnimationFrame(() => { this._raf = 0; this._render(); });
  }

  _data() {
    const out = { ranking: {}, network: {}, addons: {}, services: null, entry: null };
    for (const s of Object.values(this._hass.states)) {
      const a = s.attributes || {};
      if (!a.mu_kind) continue;
      out.entry = a.mu_entry;
      if (a.mu_kind === "ranking") out.ranking[a.period] = a;
      else if (a.mu_kind === "network") out.network[a.period] = a;
      else if (a.mu_kind === "addons") out.addons[a.period] = a;
      else if (a.mu_kind === "services") out.services = a;
    }
    return out;
  }

  async _loadHistory(entry) {
    const k = entry + "|" + this._sel;
    if (this._histKey === k && Date.now() - this._histTs < 300000) return;
    this._histKey = k; this._histTs = Date.now();
    try {
      this._hist = await this._hass.callWS({ type: "mikrotik_usage/history", entry_id: entry, days: 30 });
      this._render();
    } catch (e) { this._hist = null; }
  }

  _render() {
    if (!this._hass) return;
    const d = this._data();
    const periods = Object.keys(PERIODS).filter((p) => d.ranking[p]);
    const app = this.shadowRoot.getElementById("app");
    const head = (tabs) => `<header><button class="menu" aria-label="Menu"><ha-icon icon="mdi:menu"></ha-icon></button>
      <h1>Data usage</h1>${tabs}</header>`;
    if (!periods.length) {
      app.innerHTML = head("") + `<main><section class="rank"><div class="empty">No usage sensors yet. Add devices in Settings &rarr; Devices &amp; services &rarr; Mikrotik Data Usage.</div></section></main>`;
      return;
    }
    if (!periods.includes(this._period)) this._period = periods.includes("month") ? "month" : periods[0];
    const p = this._period, rk = d.ranking[p], items = rk.items || [];
    const net = d.network[p] || { rx: 0, tx: 0 };
    const total = (net.rx || 0) + (net.tx || 0);
    const pr = total ? (net.rx / total) * 100 : 50;
    const tabs = `<div class="tabs" role="group" aria-label="Period">${periods.map((x) =>
      `<button class="tab" data-period="${x}" aria-pressed="${x === p}">${PERIODS[x]}</button>`).join("")}</div>`;
    const top = items[0] && items[0].total > 0 ? items[0] : null;
    const maxSide = Math.max(1, ...items.map((i) => Math.max(i.rx, i.tx)));
    const sel = this._sel && items.find((i) => i.key === this._sel);

    app.innerHTML = head(tabs) + `<main>
      <section class="sum"><h2>${PERIODS[p]}</h2><p class="sub">All tracked devices</p>
        <div class="big">${fmt(total)}</div>
        <div class="split" aria-hidden="true"><i style="width:${pr}%;background:var(--rx)"></i><i style="width:${100 - pr}%;background:var(--tx)"></i></div>
        <div class="legend"><span><span class="dot" style="background:var(--rx)"></span>RX <b>${fmt(net.rx)}</b></span>
          <span><span class="dot" style="background:var(--tx)"></span>TX <b>${fmt(net.tx)}</b></span></div>
        ${top ? `<p class="top"><b>${esc(top.name)}</b> is using the most: ${fmt(top.total)} (${top.share}% of the total)</p>` : ""}
      </section>
      <section class="hist"><h2>Last 30 days</h2><p class="sub">${sel ? esc(sel.name) : "All tracked devices"}${sel ? " &middot; click the row again to show all" : ""}</p>
        <div id="chart">${this._chart()}</div></section>
      <section class="rank"><h2>Devices by usage</h2><p class="sub">Click a device to see its daily history</p>
        ${items.length ? `<div class="axis"><div></div><div><span style="color:${RX}">&larr; RX</span><span style="color:${TX}">TX &rarr;</span></div><div></div></div>` : ""}
        ${this._rows(items, maxSide, true)}
      </section>
      ${this._addons(d.addons[p], p)}
      ${d.services ? this._services(d.services, p) : ""}</main>`;
    if (d.entry) this._loadHistory(d.entry);
  }

  _rows(items, maxSide, selectable) {
    return items.map((i) => `<div class="row${selectable ? "" : " static"}" ${selectable ? `role="button" tabindex="0" data-key="${esc(i.key)}" aria-selected="${i.key === this._sel}"` : ""}
        title="RX ${fmt(i.rx)} / TX ${fmt(i.tx)}">
      <div class="name">${esc(i.name)}</div>
      <div class="bars"><div class="l"><i style="width:${(i.rx / maxSide) * 100}%"></i></div><div class="ax"></div>
        <div class="r"><i style="width:${(i.tx / maxSide) * 100}%"></i></div></div>
      <div class="val">${fmt(i.total)}<div class="pct">${i.share}%</div></div></div>`).join("");
  }

  _addons(a, p) {
    if (!a) return "";
    const items = (a.items || []).filter((i) => i.total > 0);
    const maxSide = Math.max(1, ...items.map((i) => Math.max(i.rx, i.tx)));
    const ex = a.excluded || [];
    return `<section class="rank"><h2>Add-ons (apps) by usage</h2>
      <p class="sub">${PERIODS[p]} &middot; measured from each add-on container's network counters (LAN and internet)</p>
      ${items.length ? `<div class="axis"><div></div><div><span style="color:${RX}">&larr; RX</span><span style="color:${TX}">TX &rarr;</span></div><div></div></div>${this._rows(items, maxSide, false)}`
        : `<div class="empty">No add-on traffic recorded yet for this period.</div>`}
      ${ex.length ? `<p class="note">Not ranked, because they use the host network and report whole-host counters: ${ex.map(esc).join(", ")}.</p>` : ""}
    </section>`;
  }

  _chart() {
    if (!this._hist) return `<div class="empty">Loading history…</div>`;
    const series = this._sel && this._hist.devices[this._sel] ? this._hist.devices[this._sel].days : this._hist.network;
    const W = 640, H = 220, L = 44, B = 22, T = 8, n = series.length;
    const max = Math.max(1, ...series.map((s) => s.rx + s.tx));
    const bw = (W - L) / n, ch = H - B - T;
    let g = "";
    for (let k = 0; k <= 3; k++) {
      const y = T + ch - (ch * k) / 3;
      g += `<line x1="${L}" x2="${W}" y1="${y}" y2="${y}" stroke="var(--line)" stroke-width="1"/><text x="${L - 6}" y="${y + 4}" text-anchor="end">${k ? fmt((max * k) / 3) : "0"}</text>`;
    }
    series.forEach((s, i) => {
      const x = L + i * bw + 1.5, w = Math.max(1, bw - 3);
      const hr = (s.rx / max) * ch, ht = (s.tx / max) * ch;
      g += `<g><title>${s.date}: RX ${fmt(s.rx)}, TX ${fmt(s.tx)}</title>
        <rect x="${x}" y="${T + ch - hr}" width="${w}" height="${hr}" fill="${RX}"/>
        <rect x="${x}" y="${T + ch - hr - ht}" width="${w}" height="${ht}" fill="${TX}"/></g>`;
    });
    g += `<text x="${L}" y="${H - 5}">${esc(series[0].date.slice(5))}</text><text x="${W}" y="${H - 5}" text-anchor="end">${esc(series[n - 1].date.slice(5))}</text>`;
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Daily usage, last 30 days">${g}</svg>`;
  }

  _services(s, p) {
    const key = p === "day" ? "day" : "month";
    const rows = (s.rows || []).filter((r) => r.mode !== "lan" || r[key] > 0 || r.mode === "lan");
    const host = s.host, est = key === "day" ? s.est_day : s.est_month;
    const addon = key === "day" ? (s.addon_day || 0) : (s.addon_month || 0);
    const hostV = host ? host[key] : null;
    const label = key === "day" ? "today" : "this month";
    const cmp = `<div class="cmp">
      <div><b>${fmt(est)}</b><span>estimated for services ${label}</span></div>
      ${host ? `<div><b>${fmt(hostV)}</b><span>measured for ${esc(host.name)}</span></div>
      <div><b>${fmt(addon)}</b><span>add-ons (measured)</span></div>
      <div><b>${fmt(Math.max(0, hostV - est - addon))}</b><span>everything else (updates, backups, media…)</span></div>` : ""}</div>`;
    return `<section class="svc"><h2>Home Assistant services</h2>
      <p class="sub">Estimated data demand per integration (${key === "day" ? "per day" : "per month"})</p>${cmp}
      <div class="scroll"><table><thead><tr><th>Integration</th><th>Method</th><th class="n">Polls / day</th><th class="n">${key === "day" ? "Day" : "Month"}</th></tr></thead><tbody>
      ${rows.map((r) => { const m = MODES[r.mode] || [r.mode, ""]; return `<tr><td>${esc(r.title)}${r.host ? `<div class="pct">${esc(r.host)}</div>` : ""}</td>
        <td><span class="tag ${esc(r.mode)}" title="${esc(m[1])}">${m[0]}</span></td>
        <td class="n">${r.polls_per_day ?? "–"}</td><td class="n">${fmt(r[key])}</td></tr>`; }).join("")}
      </tbody></table></div>
      <p class="note">${esc(s.note || "")} Home Assistant exposes no per-integration traffic counters, so estimated rows are indicative only; measured rows come from your router.</p></section>`;
  }
}
customElements.define("mikrotik-usage-panel", MikrotikUsagePanel);
