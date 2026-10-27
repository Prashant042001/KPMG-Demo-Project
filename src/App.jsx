
import React, { useEffect, useRef, useState } from "react";
import {
  Activity, AlertCircle, ArrowRight, BarChart3, Check, CheckCircle2,
  ChevronDown, CircleHelp, Clock3, Database, FileCheck2, FileSpreadsheet,
  FileText, FolderOpen, Layers3, LayoutDashboard, ListChecks, LockKeyhole, Network,
  RadioTower, RefreshCw, ShieldCheck, Sparkles, UploadCloud, X, Zap,
  PanelLeftClose, PanelLeftOpen, SlidersHorizontal, Download, AlertTriangle, Loader2, MapPin
} from "lucide-react";
import {
  downloadOutput, getHealth, getJob, startProcessing, validateFiles
} from "./api.js";
import ResultsTable from "./ResultsTable.jsx";
import GisView from "./GisView.jsx";

const CANNOT = "cannot be derived";

// Backend stages (job.stage) mapped onto the four pipeline cards.
const pipeline = [
  ["Validate files", "Check file types, worksheets, headers and columns", FileCheck2, ["validate"]],
  ["Load rules", "Apply the approved backend rule configuration", ListChecks, ["load_rules"]],
  ["Derive T-number & Site ID", "Apply reference look-ups and pattern rules", Network, ["derive"]],
  ["Build master database", "Generate the master workbook and reports", Database, ["build_outputs"]]
];

// Modules. Entries with a view open it; the rest are placeholders for later releases.
const modules = [
  ["GIS Analysis", "Map sites and their master-database payments", MapPin, "gis"],
  ["Invoice Validation", "Check invoices against approved site and payment data", FileCheck2],
  ["Master Database Generation", "Build the consolidated master database", Database],
  ["Data Analysis", "Analyse costs, trends and exceptions", BarChart3]
];

const LAST_JOB_KEY = "nca.lastJobId";

const ROLE_LABELS = {
  source: "Source file",
  bts: "BTS Site Report Schedule",
  ops: "Operational Site List Summary",
  latest_payment: "Latest Payment Data"
};

const prettySize = (n) =>
  n < 1024 * 1024
    ? `${Math.max(1, Math.round(n / 1024))} KB`
    : `${(n / 1024 / 1024).toFixed(1)} MB`;

const fmt = (n) => (typeof n === "number" ? n.toLocaleString() : "—");

function UploadCard({ title, subtitle, multiple, files, onChange, tag, tagClass, dropTitle, dropHint }) {
  const ref = useRef(null);

  const add = (list) => {
    const incoming = Array.from(list || []);
    if (!incoming.length) return;
    onChange(multiple ? [...files, ...incoming] : [incoming[0]]);
  };

  return (
    <div className="upload-card">
      <div className="upload-heading">
        <div className="file-icon"><FileSpreadsheet size={19} /></div>
        <div className="grow">
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <span className={`tag ${tagClass}`}>{tag}</span>
      </div>

      <div
        className="dropzone"
        onDragOver={(e) => {
          e.preventDefault();
          e.currentTarget.classList.add("is-over");
        }}
        onDragLeave={(e) =>
          e.currentTarget.classList.remove("is-over")
        }
        onDrop={(e) => {
          e.preventDefault();
          e.currentTarget.classList.remove("is-over");
          add(e.dataTransfer.files);
        }}
      >
        <input
          ref={ref}
          type="file"
          hidden
          multiple={multiple}
          accept=".xlsx,.xls,.csv"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />

        <div className="cloud"><UploadCloud size={23} /></div>

        <div className="drop-copy">
          <strong>{dropTitle}</strong>
          <span>{dropHint}</span>
          <small>
            XLSX · XLS · CSV <i>•</i> 200 MB per file
          </small>
        </div>

        <button
          type="button"
          className="button button-outline"
          onClick={() => ref.current?.click()}
        >
          Browse files <ArrowRight size={14} />
        </button>
      </div>

      {files.length > 0 && (
        <div className="picked-list">
          {files.map((f, i) => (
            <div className="picked" key={`${f.name}-${i}`}>
              <FileText size={15} />
              <span title={f.name}>{f.name}</span>
              <small>{prettySize(f.size)}</small>
              <button
                type="button"
                aria-label={`Remove ${f.name}`}
                onClick={() =>
                  onChange(files.filter((_, j) => i !== j))
                }
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ icon: Icon, label, value, caption, color }) {
  return (
    <div className="metric">
      <div className={`metric-icon ${color}`}><Icon size={19} /></div>
      <div className="metric-text">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{caption}</small>
      </div>
    </div>
  );
}

function MessageList({ kind, title, items = [] }) {
  return (
    <div className={`notice ${kind === "error" ? "is-error" : ""}`}>
      {kind === "error" ? <AlertCircle size={17} /> : <AlertTriangle size={17} />}
      <span>
        <b>{title}</b>
        {items.length > 0 && (
          <ul className="message-list">
            {items.map((m, i) => <li key={i}>{m}</li>)}
          </ul>
        )}
      </span>
    </div>
  );
}

export default function App() {
  const [source, setSource] = useState([]);
  const [support, setSupport] = useState([]);
  const [collapsed, setCollapsed] = useState(false);
  const [format, setFormat] = useState("xlsx");
  const [strict, setStrict] = useState(false);
  const [notice, setNotice] = useState("");
  const [moduleNotice, setModuleNotice] = useState("");
  const [view, setView] = useState("overview"); // "overview" | "gis"
  const [apiOnline, setApiOnline] = useState(null);
  const [validation, setValidation] = useState(null);
  const [requestError, setRequestError] = useState(null);
  const [busy, setBusy] = useState("");
  const [job, setJob] = useState(null);
  const pollRef = useRef(null);

  const total = source.length + support.length;
  const bytes = [...source, ...support].reduce((a, f) => a + f.size, 0);
  const running = job && (job.status === "queued" || job.status === "running");
  const completed = job?.status === "completed";
  const failed = job?.status === "failed";
  const metrics = completed ? job.metrics : null;

  const checkHealth = () =>
    getHealth().then(() => setApiOnline(true)).catch(() => setApiOnline(false));

  useEffect(() => {
    checkHealth();
    // Reconnect to the latest run (kept in backend memory for a limited time) after a page refresh.
    const last = sessionStorage.getItem(LAST_JOB_KEY);
    if (last) {
      getJob(last)
        .then((j) => {
          setJob(j);
          if (j.validation) setValidation(j.validation);
          if (j.status === "queued" || j.status === "running") poll(j.job_id);
        })
        .catch(() => sessionStorage.removeItem(LAST_JOB_KEY));
    }
    return () => clearInterval(pollRef.current);
  }, []);

  // Any change to the selected files invalidates earlier validation and results.
  const changeFiles = (setter) => (files) => {
    setter(files);
    setValidation(null);
    setRequestError(null);
    if (!running) setJob(null);
  };

  const reset = () => {
    clearInterval(pollRef.current);
    setValidation(null);
    setRequestError(null);
    setJob(null);
    setNotice("");
  };

  const localCheck = () => {
    // Only the source file is mandatory; supporting files are optional reference data.
    if (!source.length) return "Please add the source file first.";
    return "";
  };

  const failRequest = (err) => {
    if (err instanceof TypeError) {
      setApiOnline(false);
      setRequestError({ message: "The processing backend is not reachable. Start the FastAPI server and try again.", details: [] });
    } else {
      setRequestError({ message: err.message, details: err.details || [] });
    }
  };

  const validate = async () => {
    const problem = localCheck();
    if (problem) return setNotice(problem);
    setNotice("");
    setRequestError(null);
    setBusy("validate");
    try {
      const res = await validateFiles({ source, support });
      setApiOnline(true);
      setValidation(res);
    } catch (err) {
      failRequest(err);
    } finally {
      setBusy("");
    }
  };

  const poll = (jobId) => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await getJob(jobId);
        setJob(j);
        if (j.status === "completed" || j.status === "failed") {
          clearInterval(pollRef.current);
          if (j.validation) setValidation(j.validation);
        }
      } catch (err) {
        clearInterval(pollRef.current);
        failRequest(err);
      }
    }, 700);
  };

  const run = async () => {
    const problem = localCheck();
    if (problem) return setNotice(problem);
    setNotice("");
    setRequestError(null);
    setBusy("process");
    try {
      const res = await startProcessing(
        { source, support },
        { strict_matching: strict, output_format: format }
      );
      setApiOnline(true);
      setJob({ job_id: res.job_id, status: res.status, stage: "queued", progress: 0 });
      sessionStorage.setItem(LAST_JOB_KEY, res.job_id);
      poll(res.job_id);
    } catch (err) {
      failRequest(err);
    } finally {
      setBusy("");
    }
  };

  const download = async (kind) => {
    if (!completed) {
      setNotice("Outputs become available after a processing run completes successfully.");
      return;
    }
    try {
      await downloadOutput(job.job_id, kind);
    } catch (err) {
      failRequest(err);
    }
  };

  // Role detected by the backend for each uploaded file (after validation).
  const fileInfo = (name) => validation?.files?.find((f) => f.name === name);

  const stageState = (i) => {
    if (!job) return "pending";
    if (completed) return "done";
    const current = pipeline.findIndex(([, , , stages]) => stages.includes(job.stage));
    if (failed) return i < Math.max(current, 0) ? "done" : i === Math.max(current, 0) ? "failed" : "pending";
    if (current < 0) return "pending";
    return i < current ? "done" : i === current ? "active" : "pending";
  };

  const statusText = completed
    ? "Processing complete"
    : failed
      ? "Processing failed"
      : running
        ? "Processing…"
        : validation?.valid
          ? "Files validated"
          : "Awaiting input";

  const confirmations = (job?.validation?.rules || validation?.rules)?.requires_confirmation || [];

  return (
    <div className={`layout ${collapsed ? "collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div className="brand-copy">
            <b>KPMG</b>
            <span>TELECOM SOLUTION</span>
          </div>
          <button
            type="button"
            className="collapse-btn"
            onClick={() => setCollapsed(!collapsed)}
            title="Collapse sidebar"
          >
            {collapsed
              ? <PanelLeftOpen size={17} />
              : <PanelLeftClose size={17} />}
          </button>
        </div>

        <div className="workspace-label">WORKSPACE</div>
        <nav className="nav">
          <button className={`nav-link ${view === "overview" ? "active" : ""}`} title="Overview" onClick={() => setView("overview")}>
            <LayoutDashboard size={18} /><span>Overview</span>
          </button>
          <button className={`nav-link ${view === "gis" ? "active" : ""}`} title="GIS analysis" onClick={() => setView("gis")}>
            <MapPin size={18} /><span>GIS analysis</span>
          </button>
        </nav>

        <div className="side-rule" />
        <div className="workspace-label">RUN CONFIGURATION</div>

        <div className="side-control">
          <label htmlFor="format">Report format</label>
          <div className="select-box">
            <select
              id="format"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
            >
              <option value="xlsx">Excel workbook (.xlsx)</option>
              <option value="csv">CSV file (.csv)</option>
            </select>
            <ChevronDown size={14} />
          </div>
        </div>

        <div className="switch-list">
          <label className="switch-row" title="Every source row is always kept in the master database">
            <input type="checkbox" checked readOnly disabled />
            <span className="switch-ui" />
            <span className="switch-text">
              <b>Retain all source rows</b>
              <small>Always on · no record is dropped</small>
            </span>
          </label>
          <label className="switch-row">
            <input
              type="checkbox"
              checked={strict}
              onChange={(e) => setStrict(e.target.checked)}
            />
            <span className="switch-ui" />
            <span className="switch-text">
              <b>Strict matching</b>
              <small>Withhold conflicting values</small>
            </span>
          </label>
        </div>

        <div className="side-bottom">
          <div className="security-card">
            <div className="security-icon"><LockKeyhole size={16} /></div>
            <div>
              <b>Controlled data handling</b>
              <p>Files are processed locally and held in memory only.</p>
            </div>
          </div>
          <div className="side-version">
            <span className={`online-dot ${apiOnline === false ? "is-offline" : ""}`} />
            {apiOnline === null ? "Checking backend" : apiOnline ? "Backend online" : "Backend offline"}
            <span>v1.1</span>
          </div>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="crumb">
            <span>Workspace</span><b>/</b>
            <strong>Network cost assurance</strong>
          </div>
          <div className="top-actions">
            <span className="local-pill"><i />Local environment</span>
            <button
              className="help-btn"
              title="Help"
              onClick={() =>
                setNotice("Upload the source file you want to process. Optionally add supporting reference files (for example a BTS Site Report Schedule or Operational Site List Summary); they are recognised from their columns. The approved T-number rules are built into the backend. Validate the files, then run the derivation to produce TNUMBER and SITE ID.")
              }
            >
              <CircleHelp size={18} />
            </button>
            <div className="avatar">TS</div>
          </div>
        </header>

        <section className="hero">
          <div className="hero-content">
            <div className="eyebrow">
              <Sparkles size={13} /> TELECOM DATA AUTOMATION
            </div>
            <h1>KPMG - Telecom Solution</h1>
            <h2>Network cost Assurance and Optimisation</h2>
            <p>
              Bring payment and site reference data together in one structured,
              traceable master database.
            </p>
            <div className="hero-pills">
              <span><ShieldCheck size={14} /> Rule-led processing</span>
              <span><Database size={14} /> Unified data</span>
              <span><Activity size={14} /> Clear exceptions</span>
            </div>
          </div>

          <div className="hero-visual">
            <div className="ring ring-a" />
            <div className="ring ring-b" />
            <div className="hero-center"><Network size={32} /></div>
            <div className="float-icon float-one"><FileSpreadsheet size={17} /></div>
            <div className="float-icon float-two"><Zap size={17} /></div>
            <div className="float-icon float-three"><Database size={17} /></div>
            <div className="float-icon float-four"><RadioTower size={17} /></div>
          </div>
        </section>

        <section className="module-bar" aria-label="Modules">
          {modules.map(([name, desc, Icon, target]) => (
            <button
              type="button"
              className={`module-btn ${target && view === target ? "is-active" : ""}`}
              key={name}
              onClick={() => {
                if (target) {
                  setModuleNotice("");
                  setView(target);
                } else {
                  setModuleNotice(`${name} is not available yet. Its functionality will be added in a later release.`);
                }
              }}
            >
              <span className="module-head">
                <span className="module-icon"><Icon size={18} /></span>
                <span className={`tag ${target ? "tag-purple" : "tag-blue"}`}>{target ? "OPEN" : "COMING SOON"}</span>
              </span>
              <span className="module-copy">
                <b>{name}</b>
                <small>{desc}</small>
              </span>
            </button>
          ))}
        </section>
        {moduleNotice && (
          <div className="notice">
            <Clock3 size={17} />
            <span>{moduleNotice}</span>
            <button onClick={() => setModuleNotice("")}><X size={14} /></button>
          </div>
        )}

        {view === "gis" && (
          <>
            <div className="section-title">
              <div>
                <div className="step-label">GIS ANALYSIS</div>
                <h2>Sites and payments map</h2>
                <p>Click a site to see its details and linked payments, with or without running the T-number derivation.</p>
              </div>
              {job?.status === "completed" && (
                <div className="selection-pill"><Database size={16} /> Run finished {job.finished_at?.replace("T", " ")}</div>
              )}
            </div>
            <GisView
              job={job}
              onGoToDerivation={() => {
                setView("overview");
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            />
          </>
        )}

        {view === "overview" && (
          <>
        <div className="section-title">
          <div>
            <div className="step-label">01 / INPUT</div>
            <h2>Source file upload</h2>
            <p>Add the source file to process, then any supporting reference files you have.</p>
          </div>
          <div className="selection-pill">
            <FolderOpen size={16} /><b>{total}</b> files selected
          </div>
        </div>

        <section className="upload-grid">
          <UploadCard
            title="Source File"
            subtitle="The dataset to process; every row is kept in the output"
            multiple={false}
            files={source}
            onChange={changeFiles(setSource)}
            tag="REQUIRED"
            tagClass="tag-purple"
            dropTitle="Upload the source file"
            dropHint="Choose one Excel or CSV file (any name)"
          />
          <UploadCard
            title="Supporting Data File(s)"
            subtitle="Optional reference data, recognised from its columns"
            multiple
            files={support}
            onChange={changeFiles(setSupport)}
            tag="OPTIONAL"
            tagClass="tag-blue"
            dropTitle="Upload any supporting files"
            dropHint="Choose zero, one or several files, or drag them here"
          />
        </section>

        <section className="lower-grid">
          <div className="panel inventory">
            <div className="panel-head">
              <div>
                <h3><FolderOpen size={17} /> File inventory</h3>
                <p>Review selected files. Roles are detected by the backend during validation.</p>
              </div>
              <button
                className="link-button"
                onClick={() => {
                  setSource([]);
                  setSupport([]);
                  reset();
                }}
              >
                Clear all
              </button>
            </div>

            {total === 0 ? (
              <div className="empty">
                <div className="empty-folder"><FolderOpen size={23} /></div>
                <b>No files selected</b>
                <span>Uploaded files will be listed here.</span>
              </div>
            ) : (
              <div className="inventory-list">
                {[
                  ...source.map((f) => ({ file: f, kind: "Source file" })),
                  ...support.map((f) => ({ file: f, kind: "Supporting file" }))
                ].map(({ file, kind }, i) => {
                  const info = fileInfo(file.name);
                  const role = info?.role
                    ? info.role.split(", ").map((r) => ROLE_LABELS[r] || r).join(", ")
                    : null;
                  return (
                    <div className="inventory-row" key={`${file.name}-${i}`}>
                      <div className="mini-file"><FileSpreadsheet size={16} /></div>
                      <div className="inventory-name">
                        <b title={file.name}>{file.name}</b>
                        <span>{kind} · {prettySize(file.size)}{role ? ` · ${role}` : ""}</span>
                      </div>
                      {!info && <span className="added"><Check size={12} /> Added</span>}
                      {info?.status === "ok" && <span className="added"><Check size={12} /> Recognised</span>}
                      {info?.status === "ignored" && <span className="added is-warn"><AlertTriangle size={12} /> Not used</span>}
                      {info?.status === "error" && <span className="added is-error"><AlertCircle size={12} /> Error</span>}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="inventory-foot">
              <span><LockKeyhole size={12} /> Files are sent only to the local backend</span>
              <b>{(bytes / 1024 / 1024).toFixed(2)} MB</b>
            </div>
          </div>

          <div className="panel controls">
            <div className="panel-head">
              <div>
                <h3><SlidersHorizontal size={17} /> Run readiness</h3>
                <p>Check your inputs before processing.</p>
              </div>
              <span className="step-tag">02 / RUN</span>
            </div>

            <div className="readiness">
              <div className="readiness-row">
                <span className={source.length ? "ready-check" : "number-check"}>
                  {source.length ? <Check size={13} /> : "1"}
                </span>
                <div>
                  <b>Source file</b>
                  <small>{source.length ? "File selected" : "Waiting for upload"}</small>
                </div>
              </div>
              <div className="readiness-row">
                <span className={support.length ? "ready-check" : "number-check"}>
                  {support.length ? <Check size={13} /> : "2"}
                </span>
                <div>
                  <b>Supporting data (optional)</b>
                  <small>
                    {support.length ? `${support.length} file(s) selected` : "None selected · reference look-ups will be skipped"}
                  </small>
                </div>
              </div>
              <div className="readiness-row">
                <span className={validation?.valid ? "ready-check" : "number-check"}>
                  {validation?.valid ? <Check size={13} /> : "3"}
                </span>
                <div>
                  <b>Validation</b>
                  <small>
                    {validation
                      ? validation.valid
                        ? `Passed · ${fmt(validation.source_rows)} source rows`
                        : `${validation.errors.length} issue(s) to resolve`
                      : apiOnline === false
                        ? "Backend offline"
                        : "Not run yet"}
                  </small>
                </div>
              </div>
            </div>

            <button
              className="button button-outline full-width"
              onClick={validate}
              disabled={!!busy || running}
            >
              {busy === "validate" ? <Loader2 size={15} className="spin" /> : <FileCheck2 size={15} />}
              Validate files
            </button>
            <button
              className="button button-primary run-btn"
              onClick={run}
              disabled={!!busy || running}
            >
              {running || busy === "process" ? <Loader2 size={16} className="spin" /> : <Zap size={16} />}
              {running ? "Processing…" : "Run T-number & Site ID derivation"} <ArrowRight size={15} />
            </button>
            <button className="reset-btn" onClick={reset} disabled={running}>
              <RefreshCw size={13} /> Reset status
            </button>
          </div>
        </section>

        {requestError && (
          <MessageList kind="error" title={requestError.message} items={requestError.details} />
        )}
        {validation?.errors?.length > 0 && (
          <MessageList kind="error" title="Validation errors" items={validation.errors} />
        )}
        {validation?.warnings?.length > 0 && (
          <MessageList kind="warn" title="Validation warnings" items={validation.warnings} />
        )}

        <div className="section-title overview-title">
          <div>
            <div className="step-label">03 / MONITOR</div>
            <h2>Processing overview</h2>
            <p>Summary metrics and pipeline status for the current run.</p>
          </div>
          <div className={`status-pill ${completed ? "is-done" : ""} ${failed ? "is-failed" : ""}`}>
            <i />{statusText}
          </div>
        </div>

        <section className="metrics six">
          <Metric
            icon={BarChart3}
            label="Total input rows"
            value={fmt(metrics?.input_rows)}
            caption={metrics ? `${fmt(metrics.output_rows)} rows in master output` : "Available after processing"}
            color="blue"
          />
          <Metric
            icon={Network}
            label="T-numbers derived"
            value={fmt(metrics?.tnumber_derived)}
            caption={metrics ? `${metrics.tnumber_match_rate_pct}% of records` : "Available after processing"}
            color="green"
          />
          <Metric
            icon={RadioTower}
            label="Site IDs derived"
            value={fmt(metrics?.site_id_derived)}
            caption={metrics ? `${metrics.site_id_match_rate_pct}% of records` : "Available after processing"}
            color="green"
          />
          <Metric
            icon={AlertCircle}
            label="Unresolved T-numbers"
            value={fmt(metrics?.tnumber_unresolved)}
            caption={metrics ? `Shown as “${CANNOT}”` : "Available after processing"}
            color="orange"
          />
          <Metric
            icon={AlertCircle}
            label="Unresolved Site IDs"
            value={fmt(metrics?.site_id_unresolved)}
            caption={metrics ? "Left blank and flagged" : "Available after processing"}
            color="orange"
          />
          <Metric
            icon={Layers3}
            label="Conflicting mappings"
            value={fmt(metrics?.conflicting_records)}
            caption={metrics ? "Records flagged for review" : "Available after processing"}
            color="purple"
          />
        </section>

        <section className="panel pipeline">
          <div className="panel-head">
            <div>
              <h3><Activity size={17} /> Automation pipeline</h3>
              <p>Processing stages for generating the master database.</p>
            </div>
            <span className="progress-value">{job ? `${job.progress}%` : "0%"}</span>
          </div>

          <div className="progress-track">
            <div style={{ width: `${job ? job.progress : 0}%` }} />
          </div>

          <div className="pipeline-grid">
            {pipeline.map(([name, desc, Icon], i) => {
              const state = stageState(i);
              return (
                <div className={`pipeline-stage is-${state}`} key={name}>
                  <div className="stage-head">
                    <div className="stage-icon"><Icon size={17} /></div>
                    <span>0{i + 1}</span>
                  </div>
                  <b>{name}</b>
                  <p>{desc}</p>
                  <small>
                    {state === "done" && <><CheckCircle2 size={12} /> Complete</>}
                    {state === "active" && <><Loader2 size={12} className="spin" /> In progress</>}
                    {state === "failed" && <><AlertCircle size={12} /> Failed</>}
                    {state === "pending" && <><Clock3 size={12} /> Pending</>}
                  </small>
                </div>
              );
            })}
          </div>

          {notice && (
            <div className="notice">
              <AlertCircle size={17} />
              <span>{notice}</span>
              <button onClick={() => setNotice("")}><X size={14} /></button>
            </div>
          )}

          {failed && (
            <MessageList
              kind="error"
              title={job.error || "Processing failed."}
              items={job.validation?.errors || []}
            />
          )}

          {completed && (
            <div className="download-summary">
              <div className="summary-check"><CheckCircle2 size={19} /></div>
              <div className="summary-copy">
                <b>Master database generated</b>
                <span>Completed {job.finished_at?.replace("T", " ")}. Download the outputs below.</span>
              </div>
              <div className="download-actions">
                <button className="button button-outline" onClick={() => download("master")}>
                  <Download size={14} /> Master workbook
                </button>
                <button className="button button-outline" onClick={() => download("mapping")}>
                  <Download size={14} /> Mapping summary
                </button>
                <button className="button button-outline" onClick={() => download("exceptions")}>
                  <Download size={14} /> Exception report
                </button>
              </div>
            </div>
          )}
        </section>

        {confirmations.length > 0 && (
          <section className="panel results">
            <div className="panel-head">
              <div>
                <h3><ListChecks size={17} /> Rules requiring business confirmation</h3>
                <p>These rules were not executed. They are listed in the Rule Audit and Exceptions sheets.</p>
              </div>
            </div>
            <ul className="message-list confirm-list">
              {confirmations.map((r) => (
                <li key={r.rule_id}><b>{r.rule_id}</b> · {r.reason}</li>
              ))}
            </ul>
          </section>
        )}

        {completed && <ResultsTable jobId={job.job_id} />}

          </>
        )}

        <footer>
          <span>© KPMG Assurance and Consulting Service LLP</span>
          <span>
            <LockKeyhole size={12} /> Local processing · {apiOnline ? "Backend connected" : "Backend not connected"}
          </span>
        </footer>
      </main>
    </div>
  );
}
