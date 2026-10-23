import React, { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Database, Loader2, Search, X } from "lucide-react";
import { getRecords } from "./api.js";

const CANNOT = "cannot be derived";

// Quick filters, served by GET /api/jobs/{id}/records?status=...
const FILTERS = [
  ["all", "All rows"],
  ["tnumber_derived", "T-number derived"],
  ["tnumber_unresolved", "Unresolved T-number"],
  ["site_id_unresolved", "Unresolved Site ID"],
  ["conflict", "Conflicts"],
  ["overridden", "Overridden by priority"]
];

const PAGE_SIZES = [25, 50, 100, 200];

const fmt = (n) => (typeof n === "number" ? n.toLocaleString() : "—");

export default function ResultsTable({ jobId }) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [rule, setRule] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  // Debounce typing so the backend is queried once the user pauses.
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(text.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [text]);

  useEffect(() => {
    const id = ++requestId.current;
    setLoading(true);
    getRecords(jobId, { q, status, rule, page, pageSize })
      .then((res) => {
        if (id !== requestId.current) return; // a newer request superseded this one
        setData(res);
        setError("");
      })
      .catch((err) => id === requestId.current && setError(err.message))
      .finally(() => id === requestId.current && setLoading(false));
  }, [jobId, q, status, rule, page, pageSize]);

  const choose = (setter) => (value) => {
    setter(value);
    setPage(1);
  };

  const clear = () => {
    setText("");
    setQ("");
    setStatus("all");
    setRule("");
    setPage(1);
  };

  const rows = data?.rows || [];
  const first = data && data.matching_rows ? (data.page - 1) * data.page_size + 1 : 0;
  const last = data ? first + rows.length - (rows.length ? 1 : 0) : 0;
  const filtered = q || status !== "all" || rule;

  return (
    <section className="panel results">
      <div className="panel-head">
        <div>
          <h3><Database size={17} /> Derived results</h3>
          <p>
            Search and filter all {fmt(data?.total_rows)} rows here. Hover a row to see its exception reason.
          </p>
        </div>
        {loading && <Loader2 size={16} className="spin muted-icon" />}
      </div>

      <div className="results-toolbar">
        <div className="search-box">
          <Search size={15} />
          <input
            type="search"
            value={text}
            maxLength={100}
            onChange={(e) => setText(e.target.value)}
            placeholder="Search T-number, Vendor Site Code, ALT, Site ID, reason or row no."
            aria-label="Search results"
          />
          {text && (
            <button type="button" aria-label="Clear search" onClick={() => setText("")}><X size={14} /></button>
          )}
        </div>
        <div className="select-box compact">
          <select value={rule} onChange={(e) => choose(setRule)(e.target.value)} aria-label="Filter by rule">
            <option value="">All rules</option>
            {(data?.rules || []).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <ChevronDown size={14} />
        </div>
        {filtered && (
          <button type="button" className="link-button" onClick={clear}>Clear filters</button>
        )}
      </div>

      <div className="filter-chips" role="tablist" aria-label="Quick filters">
        {FILTERS.map(([key, label]) => (
          <button
            type="button"
            key={key}
            role="tab"
            aria-selected={status === key}
            className={`chip ${status === key ? "is-active" : ""} ${key}`}
            onClick={() => choose(setStatus)(key)}
          >
            {label}
            <span className="chip-count">{fmt(data?.counts?.[key])}</span>
          </button>
        ))}
      </div>

      {error && <div className="notice is-error"><span>{error}</span></div>}

      <div className="table-scroll">
        <table className="results-table">
          <thead>
            <tr>
              <th>Row</th>
              <th>Vendor Site Code</th>
              <th>VENDOR_SITE_CODE_ALT</th>
              <th>Candidate T-number(s)</th>
              <th>TNUMBER</th>
              <th>SITE ID</th>
              <th>T rule</th>
              <th>Site rule</th>
              <th>Status</th>
              <th>Conflict</th>
              <th>Exception reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.row}
                className={r.conflict ? "is-conflict" : r.tnumber === CANNOT ? "is-unresolved" : ""}
                title={r.exception_reason || ""}
              >
                <td>{r.row}</td>
                <td>{r.vendor_site_code}</td>
                <td>{r.vendor_site_code_alt}</td>
                <td>{r.candidate_tnumbers}</td>
                <td className={r.tnumber === CANNOT ? "muted" : "strong"}>{r.tnumber}</td>
                <td className={r.site_id ? "strong" : "muted"}>{r.site_id || "unresolved"}</td>
                <td>{r.tnumber_rule}</td>
                <td>{r.site_id_rule}</td>
                <td>{r.tnumber_status} / {r.site_id_status}</td>
                <td>{r.conflict ? "Y" : "N"}</td>
                <td className="reason-cell">{r.exception_reason}</td>
              </tr>
            ))}
            {data && rows.length === 0 && (
              <tr>
                <td colSpan={11} className="empty-row">No rows match the current search and filters.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="pager">
        <span>
          {data ? `Showing ${fmt(first)}–${fmt(last)} of ${fmt(data.matching_rows)} matching rows` : "Loading…"}
          {data && filtered ? ` (${fmt(data.total_rows)} in total)` : ""}
        </span>
        <div className="pager-controls">
          <div className="select-box compact">
            <select value={pageSize} onChange={(e) => choose(setPageSize)(Number(e.target.value))} aria-label="Rows per page">
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} per page</option>)}
            </select>
            <ChevronDown size={14} />
          </div>
          <button
            type="button"
            className="button button-outline"
            disabled={!data || data.page <= 1}
            onClick={() => setPage(page - 1)}
            aria-label="Previous page"
          >
            <ChevronLeft size={14} />
          </button>
          <span className="page-label">Page {data?.page || 1} of {data?.pages || 1}</span>
          <button
            type="button"
            className="button button-outline"
            disabled={!data || data.page >= data.pages}
            onClick={() => setPage(page + 1)}
            aria-label="Next page"
          >
            <ChevronRight size={14} />
          </button>
        </div>
      </div>
    </section>
  );
}
