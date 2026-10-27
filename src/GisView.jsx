import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  AlertTriangle, ArrowLeft, Database, Loader2, Map as MapIcon, MapPin, Search, Upload, Zap
} from "lucide-react";
import { createGis, getGis, getGisSite } from "./api.js";
import PaymentChart from "./PaymentChart.jsx";

// Map tiles: only the visible map area is requested from the tile server; no site or payment data is sent.
// Point VITE_MAP_TILE_URL at a company-approved tile server if public OpenStreetMap tiles are not allowed.
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION = import.meta.env.VITE_MAP_TILE_ATTRIBUTION || "&copy; OpenStreetMap contributors";

const COLORS = { paid: "#00338d", unpaid: "#9aa6b4", selected: "#f28c28" };

const fmt = (n) => (typeof n === "number" ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—");

// Wording that depends on where the payment rows come from.
const WORDS = {
  derived: { rows: "master rows", data: "master data", from: "the master database", tnumber: "not derived in the master data" },
  direct: { rows: "payment rows", data: "payment file", from: "the payment file", tnumber: "not in the payment file" }
};

function SiteMap({ sites, selectedId, onSelect, onTileError }) {
  const el = useRef(null);
  const map = useRef(null);
  const layer = useRef(null);
  const markers = useRef({});

  useEffect(() => {
    map.current = L.map(el.current, { zoomControl: true, preferCanvas: true }).setView([-28.5, 24.5], 5);
    const tiles = L.tileLayer(TILE_URL, { maxZoom: 18, attribution: TILE_ATTRIBUTION }).addTo(map.current);
    let reported = false;
    tiles.on("tileerror", () => {
      if (!reported) onTileError();
      reported = true;
    });
    layer.current = L.layerGroup().addTo(map.current);
    return () => map.current.remove();
  }, []);

  useEffect(() => {
    layer.current.clearLayers();
    markers.current = {};
    const plotted = sites.filter((s) => s.has_coordinates);
    plotted.forEach((s) => {
      const m = L.circleMarker([s.lat, s.lon], {
        radius: 8,
        weight: 2,
        color: "#ffffff",
        fillColor: s.payment_count ? COLORS.paid : COLORS.unpaid,
        fillOpacity: 0.9
      })
        .bindTooltip(`${s.site_id}${s.site_name ? ` · ${s.site_name}` : ""} — ${s.payment_count} payment row(s)`)
        .on("click", () => onSelect(s.site_id))
        .addTo(layer.current);
      markers.current[s.site_id] = m;
    });
    if (plotted.length) {
      map.current.fitBounds(L.latLngBounds(plotted.map((s) => [s.lat, s.lon])).pad(0.2), { maxZoom: 12 });
    }
  }, [sites]);

  useEffect(() => {
    Object.entries(markers.current).forEach(([id, m]) => {
      const site = sites.find((s) => s.site_id === id);
      const selected = id === selectedId;
      m.setStyle({
        radius: selected ? 11 : 8,
        fillColor: selected ? COLORS.selected : site?.payment_count ? COLORS.paid : COLORS.unpaid
      });
      if (selected) {
        m.bringToFront();
        map.current.panTo(m.getLatLng());
      }
    });
  }, [selectedId, sites]);

  return <div ref={el} className="gis-map" role="region" aria-label="Site map" />;
}

function SiteDetail({ detail, words, onBack }) {
  const { site, fields, payments } = detail;
  const label = (key, fallback) => fields?.[key] || fallback;
  return (
    <div className="gis-detail">
      <button type="button" className="link-button back-link" onClick={onBack}>
        <ArrowLeft size={14} /> All sites
      </button>
      <h4><MapPin size={16} /> Site {site.site_id}</h4>
      {!site.in_site_list && (
        <div className="notice"><AlertTriangle size={15} /><span>Paid in the {words.data} but not in the Operational Site List Summary.</span></div>
      )}
      <table className="kv-table">
        <tbody>
          <tr><th>Site ID</th><td>{site.site_id}</td></tr>
          {site.site_name && <tr><th>Site Name</th><td>{site.site_name}</td></tr>}
          <tr><th>Property Owner</th><td>{site.property_owner || "—"}</td></tr>
          <tr><th>Region</th><td>{site.region || "—"}</td></tr>
          <tr><th>T-number</th><td>{site.tnumber || words.tnumber}</td></tr>
          <tr><th>Coordinates</th><td>{site.has_coordinates ? `${site.lat}, ${site.lon}` : "not available"}</td></tr>
          <tr><th>Payment rows</th><td>{site.payment_count}{site.payment_total != null ? ` · total ${fmt(site.payment_total)}` : ""}</td></tr>
        </tbody>
      </table>

      <h5>Payments from {words.from}</h5>
      {payments.length === 0 ? (
        <p className="gis-muted">No rows in {words.from} are linked to this Site ID.</p>
      ) : (
        <div className="table-scroll gis-payments">
          <table className="results-table">
            <thead>
              <tr>
                <th>{label("vendor_name", "Vendor Name")}</th>
                <th>{label("vendor_site_code", "VENDOR_SITE_CODE")}</th>
                <th>{label("payment_date", "Payment Date")}</th>
                <th>{label("payment_amount", "Payment Amount")}</th>
              </tr>
            </thead>
            <tbody>
              {payments.map((p) => (
                <tr key={p.row} title={`Source row ${p.row}${p.tnumber ? ` · ${p.tnumber}` : ""}`}>
                  <td>{p.vendor_name}</td>
                  <td>{p.vendor_site_code}</td>
                  <td>{p.payment_date}</td>
                  <td className="num">{p.payment_amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail.payments_truncated && <p className="gis-muted">Showing the first {payments.length} rows.</p>}
    </div>
  );
}

// Builds the map without T-number derivation: site list file(s) plus an optional payment file.
function DirectUpload({ busy, error, onLoad }) {
  const [sites, setSites] = useState([]);
  const [payments, setPayments] = useState([]);
  return (
    <section className="panel gis-upload">
      <h4><Upload size={16} /> Map without T-number derivation</h4>
      <p className="gis-muted">
        Upload the Operational Site List Summary to see every site and its details. Add a payment file to see payments
        per site: rows are linked by their own Site ID column, or else where the Vendor Site Code equals the site's
        Account Number.
      </p>
      <div className="gis-upload-grid">
        <label className="gis-file">
          <b>Operational Site List Summary <span className="req">required</span></b>
          <input type="file" accept=".xlsx,.xls,.csv" multiple onChange={(e) => setSites([...e.target.files])} />
          <small>{sites.length ? sites.map((f) => f.name).join(", ") : "Account Number, Site ID and latitude / longitude columns"}</small>
        </label>
        <label className="gis-file">
          <b>Payment file <span className="opt">optional</span></b>
          <input type="file" accept=".xlsx,.xls,.csv" onChange={(e) => setPayments([...e.target.files])} />
          <small>{payments.length ? payments[0].name : "Site ID or Vendor Site Code, plus vendor, date and amount columns"}</small>
        </label>
      </div>
      {error && (
        <div className="notice is-error">
          <AlertTriangle size={15} />
          <span>{error.message}{error.details?.length > 0 && <ul className="message-list">{error.details.map((d) => <li key={d}>{d}</li>)}</ul>}</span>
        </div>
      )}
      <button
        type="button"
        className="button button-primary gis-cta"
        disabled={!sites.length || busy}
        onClick={() => onLoad({ sites, payments })}
      >
        {busy ? <Loader2 size={15} className="spin" /> : <MapIcon size={15} />} Show sites on map
      </button>
    </section>
  );
}

export default function GisView({ job, onGoToDerivation }) {
  const ready = job?.status === "completed";
  const [mode, setMode] = useState(ready ? "derived" : "direct"); // "derived" | "direct"
  const [directJobId, setDirectJobId] = useState(null);
  const [directBusy, setDirectBusy] = useState(false);
  const [directError, setDirectError] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tileError, setTileError] = useState(false);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState("");

  const jobId = mode === "derived" ? (ready ? job.job_id : null) : directJobId;
  const words = WORDS[mode];

  useEffect(() => {
    setData(null);
    setError("");
    setSelected(null);
    setDetail(null);
    if (!jobId) return;
    let live = true;
    getGis(jobId).then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [jobId]);

  useEffect(() => {
    if (!selected || !jobId) return setDetail(null);
    let live = true;
    getGisSite(jobId, selected)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [selected, jobId]);

  const loadDirect = async (files) => {
    setDirectBusy(true);
    setDirectError(null);
    try {
      const res = await createGis(files);
      setDirectJobId(res.job_id);
    } catch (e) {
      setDirectError(e instanceof TypeError
        ? { message: "The processing backend is not reachable. Start the FastAPI server and try again." }
        : { message: e.message, details: e.details });
    } finally {
      setDirectBusy(false);
    }
  };

  const list = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return (data?.sites || []).filter((s) =>
      !term || [s.site_id, s.site_name, s.region, s.property_owner, s.tnumber].some((v) => (v || "").toLowerCase().includes(term))
    );
  }, [data, filter]);

  const modeSwitch = (
    <div className="gis-modes" role="tablist" aria-label="GIS data source">
      <button type="button" role="tab" aria-selected={mode === "derived"} className={mode === "derived" ? "active" : ""} onClick={() => setMode("derived")}>
        <Zap size={15} /> With T-number derivation
        <small>{ready ? "Uses the latest derivation run" : "Run the derivation first"}</small>
      </button>
      <button type="button" role="tab" aria-selected={mode === "direct"} className={mode === "direct" ? "active" : ""} onClick={() => setMode("direct")}>
        <MapIcon size={15} /> Without T-number derivation
        <small>Upload a site list and, optionally, payments</small>
      </button>
    </div>
  );

  if (mode === "direct" && !directJobId) {
    return (
      <>
        {modeSwitch}
        <DirectUpload busy={directBusy} error={directError} onLoad={loadDirect} />
      </>
    );
  }

  if (mode === "derived" && !ready) {
    return (
      <>
      {modeSwitch}
      <section className="panel gis-empty">
        <Database size={26} />
        <h3>Generate the master database first</h3>
        <p>
          The GIS view links each site in the Operational Site List Summary to its payment rows in the master
          database. Run the T-number &amp; Site ID derivation with your source file and an Operational Site List
          Summary that has Latitude and Longitude columns, then come back here. To see site and payment details
          without running the derivation, choose <b>Without T-number derivation</b> above.
        </p>
        {job && (job.status === "queued" || job.status === "running") && (
          <p className="gis-muted"><Loader2 size={14} className="spin" /> A run is in progress ({job.progress}%).</p>
        )}
        <div className="gis-empty-actions">
          <button type="button" className="button button-primary gis-cta" onClick={onGoToDerivation}>
            <Zap size={15} /> Go to T-number derivation
          </button>
          <button type="button" className="button button-outline gis-cta" onClick={() => setMode("direct")}>
            <MapIcon size={15} /> Map without derivation
          </button>
        </div>
      </section>
      </>
    );
  }

  const stats = data?.stats;
  return (
    <>
    {modeSwitch}
    {mode === "direct" && (
      <div className="gis-direct-bar">
        <span>
          <MapIcon size={15} /> Without T-number derivation
          {data?.payment_file ? ` · payments from ${data.payment_file}` : " · site details only"}
        </span>
        <button type="button" className="link-button" onClick={() => setDirectJobId(null)}>Upload different files</button>
      </div>
    )}
    <section className="gis-layout">
      <aside className="panel gis-side">
        {error && <div className="notice is-error"><span>{error}</span></div>}
        {!data && !error && <p className="gis-muted"><Loader2 size={14} className="spin" /> Loading sites…</p>}
        {data && detail && <SiteDetail detail={detail} words={words} onBack={() => setSelected(null)} />}
        {data && !detail && (
          <>
            <h4><MapPin size={16} /> Sites</h4>
            <p className="gis-muted">
              {stats.sites_in_site_list} sites · {stats.sites_with_coordinates} on the map · {stats.sites_with_payments} with
              payments ({stats.master_rows_linked_to_listed_sites} {words.rows})
            </p>
            {data.notes.map((n) => (
              <div className="notice" key={n}><AlertTriangle size={15} /><span>{n}</span></div>
            ))}
            {stats.paid_site_ids_not_in_site_list > 0 && (
              <div className="notice">
                <AlertTriangle size={15} />
                <span>
                  {stats.paid_site_ids_not_in_site_list} Site ID(s) paid in the {words.data} are not in the Operational
                  Site List, so they cannot be mapped. Click one to see its payments:
                  <span className="unlisted-ids">
                    {stats.unlisted_site_ids.map((id) => (
                      <button type="button" key={id} className="link-button" onClick={() => setSelected(id)}>{id}</button>
                    ))}
                  </span>
                </span>
              </div>
            )}
            <div className="search-box">
              <Search size={15} />
              <input
                type="search"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Find site ID, name, region, owner, T-number"
                aria-label="Find site"
              />
            </div>
            <ul className="site-list">
              {list.map((s) => (
                <li key={s.site_id}>
                  <button type="button" onClick={() => setSelected(s.site_id)}>
                    <span className={`dot ${s.payment_count ? "paid" : ""}`} />
                    <span className="site-main">
                      <b>{s.site_id}</b> {s.site_name}
                      <small>{[s.region, s.property_owner].filter(Boolean).join(" · ")}</small>
                    </span>
                    <span className="site-meta">
                      {s.payment_count} pmt{s.payment_count === 1 ? "" : "s"}
                      {!s.has_coordinates && <em>no coordinates</em>}
                    </span>
                  </button>
                </li>
              ))}
              {list.length === 0 && <li className="gis-muted">No sites match.</li>}
            </ul>
          </>
        )}
      </aside>

      <div className="panel gis-map-panel">
        {tileError && (
          <div className="notice gis-tile-note">
            <AlertTriangle size={15} />
            <span>Map background tiles could not be loaded (offline or blocked). Sites are still plotted; set VITE_MAP_TILE_URL to an approved tile server.</span>
          </div>
        )}
        <SiteMap
          sites={data?.sites || []}
          selectedId={selected}
          onSelect={setSelected}
          onTileError={() => setTileError(true)}
        />
        <div className="gis-legend">
          <span><i className="dot paid" /> Payments linked</span>
          <span><i className="dot" /> No payments in {words.data}</span>
          <span><i className="dot selected" /> Selected</span>
        </div>
      </div>
    </section>
    {data && (
      <PaymentChart
        chart={detail ? detail.chart : data.chart}
        scope={detail ? detail.site.site_id : null}
        onClear={() => setSelected(null)}
      />
    )}
    </>
  );
}
