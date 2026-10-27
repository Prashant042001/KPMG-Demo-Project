import React, { useState } from "react";
import { BarChart3, Table2, X } from "lucide-react";

// Two series, validated with the dataviz palette checker (lightness band, CVD and normal-vision separation, contrast).
const SERIES = [
  { key: "rental", label: "Rental + Fixed", color: "#1e49e2" },
  { key: "electricity", label: "Variable Electricity", color: "#00b8f5" }
];

const W = 640;
const H = 260;
const M = { top: 16, right: 12, bottom: 30, left: 52 };
const BAR = 24; // max bar thickness
const GAP = 2; // surface gap between the two bars of a cluster

const money = (n) => `R ${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const compact = (n) =>
  n >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${+(n / 1e3).toFixed(1)}K` : `${+n.toFixed(0)}`;

// Clean axis maximum and step: 1, 2, 2.5 or 5 x 10^n, four intervals.
function niceScale(max) {
  if (max <= 0) return { top: 1, step: 0.25 };
  const raw = max / 4;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  return { top: step * Math.ceil(max / step), step };
}

// Column with a 4px rounded data end and a square baseline.
function barPath(x, y, w, h) {
  if (h <= 0) return "";
  const r = Math.min(4, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

export default function PaymentChart({ chart, scope, onClear }) {
  const [hover, setHover] = useState(null); // { q, s }
  const [table, setTable] = useState(false);
  const quarters = chart?.quarters || [];
  const totals = SERIES.map((s) => quarters.reduce((a, q) => a + q[s.key], 0));
  const empty = totals.every((t) => t === 0);
  const { top, step } = niceScale(Math.max(0, ...quarters.flatMap((q) => SERIES.map((s) => q[s.key]))));

  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const band = plotW / Math.max(quarters.length, 1);
  const barW = Math.min(BAR, (band * 0.6 - GAP) / 2);
  const y = (v) => M.top + plotH - (v / top) * plotH;
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step);

  const tip = hover && quarters[hover.q];
  const tipX = hover ? ((M.left + band * hover.q + band / 2) / W) * 100 : 0;

  return (
    <section className="panel pay-chart" aria-label={`Quarterly payments ${chart?.year ?? ""}`}>
      <div className="pay-chart-head">
        <div>
          <h4><BarChart3 size={16} /> Quarterly payments {chart?.year}</h4>
          <p className="gis-muted">
            {scope ? <>Site <b>{scope}</b></> : "All payments"} · Rental + Fixed (invoice number starts with PN) vs
            Variable Electricity
          </p>
        </div>
        <div className="pay-chart-actions">
          {scope && (
            <button type="button" className="button button-outline" onClick={onClear}>
              <X size={14} /> Show all payments
            </button>
          )}
          <button type="button" className="button button-outline" aria-pressed={table} onClick={() => setTable(!table)}>
            {table ? <BarChart3 size={14} /> : <Table2 size={14} />} {table ? "Chart" : "Table"}
          </button>
        </div>
      </div>

      <div className="pay-legend">
        {SERIES.map((s, i) => (
          <span key={s.key}>
            <i style={{ background: s.color }} /> {s.label} <b>{money(totals[i])}</b>
          </span>
        ))}
      </div>

      {chart && !chart.has_dates ? (
        <p className="gis-muted">The payment data has no Payment Date column, so payments cannot be grouped by quarter.</p>
      ) : empty && !table ? (
        <p className="gis-muted pay-empty">No {chart?.year} payments {scope ? "for this site" : "in the payment data"}.</p>
      ) : table ? (
        <div className="table-scroll">
          <table className="results-table">
            <thead>
              <tr><th>Quarter</th>{SERIES.map((s) => <th key={s.key} className="num">{s.label}</th>)}<th className="num">Total</th></tr>
            </thead>
            <tbody>
              {quarters.map((q) => (
                <tr key={q.quarter}>
                  <td>{q.quarter} {chart.year}</td>
                  {SERIES.map((s) => <td key={s.key} className="num">{money(q[s.key])} <small>({q[`${s.key}_count`]})</small></td>)}
                  <td className="num">{money(q.rental + q.electricity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="pay-plot" onMouseLeave={() => setHover(null)}>
          <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Clustered bar chart of rental and electricity payments per quarter">
            {ticks.map((t) => (
              <g key={t}>
                <line x1={M.left} x2={W - M.right} y1={y(t)} y2={y(t)} className="pay-grid" />
                <text x={M.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="pay-axis">{compact(t)}</text>
              </g>
            ))}
            {quarters.map((q, qi) => {
              const cx = M.left + band * qi + band / 2;
              return (
                <g key={q.quarter}>
                  {SERIES.map((s, si) => {
                    const x = cx - barW - GAP / 2 + si * (barW + GAP);
                    const active = hover?.q === qi && hover?.s === si;
                    const dim = hover && hover.q === qi && !active;
                    return (
                      <g key={s.key}>
                        <path d={barPath(x, y(q[s.key]), barW, y(0) - y(q[s.key]))} fill={s.color} opacity={dim ? 0.45 : 1} />
                        <rect
                          x={x - GAP / 2} y={M.top} width={barW + GAP} height={plotH}
                          fill="transparent" onMouseEnter={() => setHover({ q: qi, s: si })}
                          onFocus={() => setHover({ q: qi, s: si })} tabIndex={0}
                          aria-label={`${q.quarter} ${s.label}: ${money(q[s.key])}`}
                        />
                      </g>
                    );
                  })}
                  <text x={cx} y={H - 10} textAnchor="middle" className="pay-axis">{q.quarter}</text>
                </g>
              );
            })}
            <line x1={M.left} x2={W - M.right} y1={y(0)} y2={y(0)} className="pay-baseline" />
          </svg>
          {tip && (
            <div className="pay-tip" style={{ left: `${tipX}%` }} role="status">
              <b>{tip.quarter} {chart.year}</b>
              {SERIES.map((s, si) => (
                <span key={s.key} className={hover.s === si ? "is-active" : ""}>
                  <i style={{ background: s.color }} /> {s.label}
                  <em>{money(tip[s.key])} · {tip[`${s.key}_count`]} pmt{tip[`${s.key}_count`] === 1 ? "" : "s"}</em>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
