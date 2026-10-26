import React, { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  AlertTriangle, ArrowLeft, Database, Loader2, MapPin, Search, Zap
} from "lucide-react";
import { getGis, getGisSite } from "./api.js";

// Map tiles: only the visible map area is requested from the tile server; no site or payment data is sent.
// Point VITE_MAP_TILE_URL at a company-approved tile server if public OpenStreetMap tiles are not allowed.
const TILE_URL = import.meta.env.VITE_MAP_TILE_URL || "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION = import.meta.env.VITE_MAP_TILE_ATTRIBUTION || "&copy; OpenStreetMap contributors";

const COLORS = { paid: "#00338d", unpaid: "#9aa6b4", selected: "#f28c28" };

const fmt = (n) => (typeof n === "number" ? n.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—");

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

function SiteDetail({ detail, onBack }) {
  const { site, fields, payments } = detail;
  const label = (key, fallback) => fields?.[key] || fallback;
  return (
    <div className="gis-detail">
      <button type="button" className="link-button back-link" onClick={onBack}>
        <ArrowLeft size={14} /> All sites
      </button>
      <h4><MapPin size={16} /> Site {site.site_id}</h4>
      {!site.in_site_list && (
        <div className="notice"><AlertTriangle size={15} /><span>Paid in the master data but not in the Operational Site List Summary.</span></div>
      )}
      <table className="kv-table">
        <tbody>
          <tr><th>Site ID</th><td>{site.site_id}</td></tr>
          {site.site_name && <tr><th>Site Name</th><td>{site.site_name}</td></tr>}
          <tr><th>Property Owner</th><td>{site.property_owner || "—"}</td></tr>
          <tr><th>Region</th><td>{site.region || "—"}</td></tr>
          <tr><th>T-number</th><td>{site.tnumber || "not derived in the master data"}</td></tr>
          <tr><th>Coordinates</th><td>{site.has_coordinates ? `${site.lat}, ${site.lon}` : "not available"}</td></tr>
          <tr><th>Payment rows</th><td>{site.payment_count}{site.payment_total != null ? ` · total ${fmt(site.payment_total)}` : ""}</td></tr>
        </tbody>
      </table>

      <h5>Payments from the master database</h5>
      {payments.length === 0 ? (
        <p className="gis-muted">No master-database rows are linked to this Site ID.</p>
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
                <tr key={p.row} title={`Source row ${p.row} · ${p.tnumber}`}>
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

export default function GisView({ job, onGoToDerivation }) {
  const ready = job?.status === "completed";
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [tileError, setTileError] = useState(false);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    if (!ready) return;
    setData(null);
    setSelected(null);
    setDetail(null);
    getGis(job.job_id).then(setData).catch((e) => setError(e.message));
  }, [ready, job?.job_id]);

  useEffect(() => {
    if (!selected) return setDetail(null);
    let live = true;
    getGisSite(job.job_id, selected)
      .then((d) => live && setDetail(d))
      .catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [selected]);

  const list = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return (data?.sites || []).filter((s) =>
      !term || [s.site_id, s.site_name, s.region, s.property_owner, s.tnumber].some((v) => (v || "").toLowerCase().includes(term))
    );
  }, [data, filter]);

  if (!ready) {
    return (
      <section className="panel gis-empty">
        <Database size={26} />
        <h3>Generate the master database first</h3>
        <p>
          The GIS view links each site in the Operational Site List Summary to its payment rows in the master
          database. Run the T-number &amp; Site ID derivation with your source file and an Operational Site List
          Summary that has Latitude and Longitude columns, then come back here.
        </p>
        {job && (job.status === "queued" || job.status === "running") && (
          <p className="gis-muted"><Loader2 size={14} className="spin" /> A run is in progress ({job.progress}%).</p>
        )}
        <button type="button" className="button button-primary gis-cta" onClick={onGoToDerivation}>
          <Zap size={15} /> Go to T-number derivation
        </button>
      </section>
    );
  }

  const stats = data?.stats;
  return (
    <section className="gis-layout">
      <aside className="panel gis-side">
        {error && <div className="notice is-error"><span>{error}</span></div>}
        {!data && !error && <p className="gis-muted"><Loader2 size={14} className="spin" /> Loading sites…</p>}
        {data && detail && <SiteDetail detail={detail} onBack={() => setSelected(null)} />}
        {data && !detail && (
          <>
            <h4><MapPin size={16} /> Sites</h4>
            <p className="gis-muted">
              {stats.sites_in_site_list} sites · {stats.sites_with_coordinates} on the map · {stats.sites_with_payments} with
              payments ({stats.master_rows_linked_to_listed_sites} master rows)
            </p>
            {data.notes.map((n) => (
              <div className="notice" key={n}><AlertTriangle size={15} /><span>{n}</span></div>
            ))}
            {stats.paid_site_ids_not_in_site_list > 0 && (
              <div className="notice">
                <AlertTriangle size={15} />
                <span>
                  {stats.paid_site_ids_not_in_site_list} Site ID(s) paid in the master data are not in the Operational
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
          <span><i className="dot" /> No payments in master data</span>
          <span><i className="dot selected" /> Selected</span>
        </div>
      </div>
    </section>
  );
}
