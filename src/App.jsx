
import React, { useRef, useState } from "react";
import {
  Activity, AlertCircle, ArrowRight, BarChart3, Check, CheckCircle2,
  ChevronDown, CircleHelp, Clock3, Database, FileCheck2, FileSpreadsheet,
  FileText, FolderOpen, Layers3, LayoutDashboard, LockKeyhole, Network,
  RefreshCw, ShieldCheck, Sparkles, UploadCloud, X, Zap, Landmark,
  PanelLeftClose, PanelLeftOpen, SlidersHorizontal, Download
} from "lucide-react";

const pipeline = [
  ["Validate files", "Confirm file types and expected columns", FileCheck2],
  ["Derive T-numbers", "Apply the configured matching rules", Network],
  ["Map site details", "Enrich records from reference datasets", Layers3],
  ["Build master database", "Prepare output and exception summaries", Database]
];

const prettySize = (n) =>
  n < 1024 * 1024
    ? `${Math.max(1, Math.round(n / 1024))} KB`
    : `${(n / 1024 / 1024).toFixed(1)} MB`;

function UploadCard({ title, subtitle, multiple, files, onChange }) {
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
        <span className={`tag ${multiple ? "tag-blue" : "tag-purple"}`}>
          {multiple ? "SUPPORTING" : "REQUIRED"}
        </span>
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
          accept={multiple ? ".xlsx,.xls,.csv,.pdf" : ".xlsx,.xls,.csv"}
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />

        <div className="cloud"><UploadCloud size={23} /></div>

        <div className="drop-copy">
          <strong>
            {multiple
              ? "Upload all the relevant files"
              : "Upload the base source file"}
          </strong>
          <span>
            {multiple
              ? "Choose multiple files or drag them here"
              : "Choose one Excel or CSV file"}
          </span>
          <small>
            XLSX · XLS · CSV{multiple ? " · PDF" : ""} <i>•</i> 200 MB per file
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

export default function App() {
  const [base, setBase] = useState([]);
  const [support, setSupport] = useState([]);
  const [collapsed, setCollapsed] = useState(false);
  const [format, setFormat] = useState("xlsx");
  const [retain, setRetain] = useState(true);
  const [synthetic, setSynthetic] = useState(true);
  const [strict, setStrict] = useState(false);
  const [status, setStatus] = useState("idle");
  const [notice, setNotice] = useState("");
  const [runAt, setRunAt] = useState("");

  const total = base.length + support.length;
  const bytes = [...base, ...support].reduce((a, f) => a + f.size, 0);

  const reset = () => {
    setStatus("idle");
    setNotice("");
    setRunAt("");
  };

  const validate = () => {
    if (!base.length) {
      setNotice("Please add the base source file first.");
      return;
    }
    if (!support.length) {
      setNotice("Please add at least one supporting reference file.");
      return;
    }

    setStatus("demo");
    setRunAt(new Date().toLocaleString());
    setNotice(
      "Your file selection is ready. This interface is a prototype; the actual data-processing engine is not connected yet."
    );
  };

  const download = () => {
    const summary = {
      application:
        "KPMG - Telecom Solution - Network cost Assurance and Optimisation",
      createdAt: new Date().toISOString(),
      baseFiles: base.map((f) => ({ name: f.name, size: f.size })),
      supportingFiles: support.map((f) => ({
        name: f.name,
        size: f.size
      })),
      settings: {
        format,
        retainAllRows: retain,
        syntheticTestValues: synthetic,
        strictValidation: strict
      },
      note: "Configuration summary only; no source data has been processed."
    };

    const blob = new Blob([JSON.stringify(summary, null, 2)], {
      type: "application/json"
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "telecom-run-summary.json";
    a.click();
    URL.revokeObjectURL(url);
  };

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
          <button className="nav-link active" title="Overview">
            <LayoutDashboard size={18} /><span>Overview</span>
          </button>
          <button
            className="nav-link"
            title="Master database"
            onClick={() =>
              setNotice("Master database output will appear here when the processing engine is connected.")
            }
          >
            <Database size={18} /><span>Master database</span>
            <span className="nav-count">01</span>
          </button>
          <button
            className="nav-link"
            onClick={() =>
              setNotice("Mapping review will be available when data processing is connected.")
            }
          >
            <Network size={18} /><span>Mapping review</span>
          </button>
          <button
            className="nav-link"
            onClick={() =>
              setNotice("Exception reporting will be available when data processing is connected.")
            }
          >
            <FileCheck2 size={18} /><span>Exceptions &amp; review</span>
          </button>
        </nav>

        <div className="side-rule" />
        <div className="workspace-label">RUN CONFIGURATION</div>

        <div className="side-control">
          <label htmlFor="format">Output format</label>
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
          <label className="switch-row">
            <input
              type="checkbox"
              checked={retain}
              onChange={(e) => setRetain(e.target.checked)}
            />
            <span className="switch-ui" />
            <span className="switch-text">
              <b>Retain all source rows</b>
              <small>Keep every payment record</small>
            </span>
          </label>
          <label className="switch-row">
            <input
              type="checkbox"
              checked={synthetic}
              onChange={(e) => setSynthetic(e.target.checked)}
            />
            <span className="switch-ui" />
            <span className="switch-text">
              <b>Synthetic test values</b>
              <small>Randomise designated fields</small>
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
              <small>Flag ambiguous matches</small>
            </span>
          </label>
        </div>

        <div className="side-bottom">
          <div className="security-card">
            <div className="security-icon"><LockKeyhole size={16} /></div>
            <div>
              <b>Controlled data handling</b>
              <p>Use only in your approved company environment.</p>
            </div>
          </div>
          <div className="side-version">
            <span className="online-dot" /> Local prototype <span>v1.1</span>
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
                setNotice("Upload the base payment source, then add the BTS Site Report Schedule, Operational Site List Summary and other approved reference files.")
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
            <div className="float-icon float-four"><Landmark size={17} /></div>
          </div>
        </section>

        <div className="section-title">
          <div>
            <div className="step-label">01 / INPUT</div>
            <h2>Source file upload</h2>
            <p>Start with the payment source, then add the relevant reference files.</p>
          </div>
          <div className="selection-pill">
            <FolderOpen size={16} /><b>{total}</b> files selected
          </div>
        </div>

        <section className="upload-grid">
          <UploadCard
            title="Base source file"
            subtitle="Primary payment report or source extract"
            multiple={false}
            files={base}
            onChange={setBase}
          />
          <UploadCard
            title="Supporting data files"
            subtitle="Site schedule, operational list and additional references"
            multiple
            files={support}
            onChange={setSupport}
          />
        </section>

        <section className="lower-grid">
          <div className="panel inventory">
            <div className="panel-head">
              <div>
                <h3><FolderOpen size={17} /> File inventory</h3>
                <p>Review selected files before running validation.</p>
              </div>
              <button
                className="link-button"
                onClick={() => {
                  setBase([]);
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
                  ...base.map((f) => ({ ...f, kind: "Base source" })),
                  ...support.map((f) => ({ ...f, kind: "Supporting file" }))
                ].map((f, i) => (
                  <div className="inventory-row" key={`${f.name}-${i}`}>
                    <div className="mini-file"><FileSpreadsheet size={16} /></div>
                    <div className="inventory-name">
                      <b title={f.name}>{f.name}</b>
                      <span>{f.kind} · {prettySize(f.size)}</span>
                    </div>
                    <span className="added"><Check size={12} /> Added</span>
                  </div>
                ))}
              </div>
            )}

            <div className="inventory-foot">
              <span><LockKeyhole size={12} /> Selection is shown in this browser session</span>
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
                <span className={base.length ? "ready-check" : "number-check"}>
                  {base.length ? <Check size={13} /> : "1"}
                </span>
                <div>
                  <b>Base source file</b>
                  <small>{base.length ? "File selected" : "Waiting for upload"}</small>
                </div>
              </div>
              <div className="readiness-row">
                <span className={support.length ? "ready-check" : "number-check"}>
                  {support.length ? <Check size={13} /> : "2"}
                </span>
                <div>
                  <b>Supporting references</b>
                  <small>
                    {support.length ? `${support.length} file(s) selected` : "Waiting for upload"}
                  </small>
                </div>
              </div>
              <div className="readiness-row">
                <span className={status === "demo" ? "ready-check" : "number-check"}>
                  {status === "demo" ? <Check size={13} /> : "3"}
                </span>
                <div>
                  <b>Processing engine</b>
                  <small>
                    {status === "demo" ? "Demo validation only" : "Backend connection required"}
                  </small>
                </div>
              </div>
            </div>

            <button className="button button-primary run-btn" onClick={validate}>
              <Zap size={16} /> Validate upload setup <ArrowRight size={15} />
            </button>
            <button className="reset-btn" onClick={reset}>
              <RefreshCw size={13} /> Reset status
            </button>
          </div>
        </section>

        <div className="section-title overview-title">
          <div>
            <div className="step-label">03 / MONITOR</div>
            <h2>Processing overview</h2>
            <p>Summary metrics and pipeline status for the current run.</p>
          </div>
          <div className={`status-pill ${status === "demo" ? "is-done" : ""}`}>
            <i />{status === "demo" ? "Demo validation complete" : "Awaiting input"}
          </div>
        </div>

        <section className="metrics">
          <Metric
            icon={FileText}
            label="Files selected"
            value={total}
            caption={`${base.length} base · ${support.length} supporting`}
            color="blue"
          />
          <Metric
            icon={BarChart3}
            label="Source rows"
            value="—"
            caption="Available after processing"
            color="purple"
          />
          <Metric
            icon={Network}
            label="T-numbers derived"
            value="—"
            caption="Rule engine not connected"
            color="green"
          />
          <Metric
            icon={AlertCircle}
            label="Exceptions"
            value="—"
            caption="Available after validation"
            color="orange"
          />
        </section>

        <section className="panel pipeline">
          <div className="panel-head">
            <div>
              <h3><Activity size={17} /> Automation pipeline</h3>
              <p>Planned processing stages for generating the master database.</p>
            </div>
            <span className="progress-value">{status === "demo" ? "25%" : "0%"}</span>
          </div>

          <div className="progress-track">
            <div style={{ width: status === "demo" ? "25%" : "0%" }} />
          </div>

          <div className="pipeline-grid">
            {pipeline.map(([name, desc, Icon], i) => (
              <div className="pipeline-stage" key={name}>
                <div className="stage-head">
                  <div className="stage-icon"><Icon size={17} /></div>
                  <span>0{i + 1}</span>
                </div>
                <b>{name}</b>
                <p>{desc}</p>
                <small>
                  <Clock3 size={12} />
                  {status === "demo" && i === 0 ? "UI check only" : "Backend pending"}
                </small>
              </div>
            ))}
          </div>

          {notice && (
            <div className="notice">
              <AlertCircle size={17} />
              <span>{notice}</span>
              <button onClick={() => setNotice("")}><X size={14} /></button>
            </div>
          )}

          {status === "demo" && (
            <div className="download-summary">
              <div className="summary-check"><CheckCircle2 size={19} /></div>
              <div className="summary-copy">
                <b>Configuration summary is ready</b>
                <span>{runAt}. This is not a generated master database.</span>
              </div>
              <button className="button button-outline" onClick={download}>
                <Download size={14} /> Download summary
              </button>
            </div>
          )}
        </section>

        <footer>
          <span>© KPMG Assurance and Consulting Service LLP</span>
          <span><LockKeyhole size={12} /> Prototype interface · Processing backend not connected</span>
        </footer>
      </main>
    </div>
  );
}
