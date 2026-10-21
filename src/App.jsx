import React, { useMemo, useRef, useState } from "react";
import {
  Activity, AlertCircle, ArrowRight, BarChart3, Check, CheckCircle2,
  ChevronDown, CircleHelp, Database, FileCheck2, FileSpreadsheet,
  FileText, FolderUp, Gauge, Layers3, ListChecks, LockKeyhole,
  RefreshCw, Settings2, ShieldCheck, Sparkles, UploadCloud, X,
  Zap, Clock3, Download, Network, Landmark
} from "lucide-react";

const stages = [
  { title: "File validation", detail: "Check uploaded files and required columns", icon: FileCheck2 },
  { title: "T-number derivation", detail: "Apply configured identification rules", icon: Network },
  { title: "Site mapping & enrichment", detail: "Match site and vendor reference data", icon: Layers3 },
  { title: "Master database generation", detail: "Build output and exception reports", icon: Database },
];

function formatBytes(bytes) {
  if (!bytes) return "0 KB";
  const kb = bytes / 1024;
  return kb > 1024 ? `${(kb / 1024).toFixed(1)} MB` : `${kb.toFixed(0)} KB`;
}

function FileDrop({ title, subtitle, files, onFiles, multiple = false, accept = ".xlsx,.xls,.csv,.pdf" }) {
  const inputRef = useRef(null);
  const [dragging, setDragging] = useState(false);

  function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    if (!incoming.length) return;
    onFiles(multiple ? [...files, ...incoming] : [incoming[0]]);
  }

  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files); }}
    >
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }}
      />
      <div className="drop-icon"><UploadCloud size={22} /></div>
      <div className="drop-copy">
        <strong>{title}</strong>
        <span>{subtitle}</span>
      </div>
      <button className="btn btn-outline upload-btn" onClick={() => inputRef.current?.click()}>
        Browse files
      </button>
      {files.length > 0 && (
        <div className="selected-files">
          {files.map((file, i) => (
            <div className="file-chip" key={`${file.name}-${i}`}>
              <FileSpreadsheet size={15} />
              <span title={file.name}>{file.name}</span>
              <small>{formatBytes(file.size)}</small>
              <button aria-label={`Remove ${file.name}`} onClick={() => onFiles(files.filter((_, idx) => idx !== i))}><X size={14} /></button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value, note, icon: Icon, tone }) {
  return (
    <div className={`metric metric-${tone}`}>
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon"><Icon size={18} /></span>
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

export default function App() {
  const [baseFiles, setBaseFiles] = useState([]);
  const [supportFiles, setSupportFiles] = useState([]);
  const [outputFormat, setOutputFormat] = useState("xlsx");
  const [retainRows, setRetainRows] = useState(true);
  const [syntheticData, setSyntheticData] = useState(true);
  const [strictValidation, setStrictValidation] = useState(false);
  const [status, setStatus] = useState("idle");
  const [message, setMessage] = useState("");
  const [completedStages, setCompletedStages] = useState([]);
  const [runTime, setRunTime] = useState(null);

  const totalFiles = baseFiles.length + supportFiles.length;
  const canRun = baseFiles.length > 0 && totalFiles > 1 && status !== "processing";
  const progress = status === "complete" ? 100 : status === "processing" ? 45 : 0;

  const fileSummary = useMemo(() => ({
    base: baseFiles.length,
    supporting: supportFiles.length,
    totalSize: [...baseFiles, ...supportFiles].reduce((sum, file) => sum + file.size, 0)
  }), [baseFiles, supportFiles]);

  function runDemo() {
    if (!baseFiles.length) {
      setMessage("Upload the base source file before starting.");
      return;
    }
    if (!supportFiles.length) {
      setMessage("Upload at least one relevant supporting file to continue.");
      return;
    }
    setStatus("complete");
    setCompletedStages(stages.map((s) => s.title));
    setRunTime(new Date().toLocaleString());
    setMessage("Demo run completed. This front end currently validates the upload selection only; connect a backend processing engine to generate the actual master database.");
  }

  function resetRun() {
    setStatus("idle");
    setMessage("");
    setCompletedStages([]);
    setRunTime(null);
  }

  function downloadRunSummary() {
    const summary = {
      application: "KPMG - Telecom Solution - Network cost Assurance and Optimisation",
      generatedAt: new Date().toISOString(),
      baseFiles: baseFiles.map(({ name, size, type }) => ({ name, size, type })),
      supportingFiles: supportFiles.map(({ name, size, type }) => ({ name, size, type })),
      settings: { outputFormat, retainRows, syntheticData, strictValidation },
      note: "Front-end prototype only. No source files were processed and no master database was generated."
    };
    const blob = new Blob([JSON.stringify(summary, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "telecom-tool-run-summary.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">K</div>
          <div>
            <div className="brand-name">KPMG</div>
            <div className="brand-sub">TELECOM SOLUTION</div>
          </div>
        </div>

        <div className="sidebar-label">WORKSPACE</div>
        <button className="nav-item active"><Gauge size={17} /> <span>Network cost assurance</span></button>
        <button className="nav-item" onClick={() => setMessage("Mapping review will be available when the backend is connected.")}><Network size={17} /> <span>Mapping review</span><span className="nav-soon">SOON</span></button>
        <button className="nav-item" onClick={() => setMessage("Exception reports will be available when the backend is connected.")}><ListChecks size={17} /> <span>Exception reports</span><span className="nav-soon">SOON</span></button>

        <div className="sidebar-divider" />
        <div className="sidebar-label">RUN CONFIGURATION</div>
        <div className="config-block">
          <label htmlFor="format">Output format</label>
          <div className="select-wrap">
            <select id="format" value={outputFormat} onChange={(e) => setOutputFormat(e.target.value)}>
              <option value="xlsx">Excel workbook (.xlsx)</option>
              <option value="csv">CSV file (.csv)</option>
            </select>
            <ChevronDown size={15} />
          </div>
        </div>
        <div className="config-check">
          <label><input type="checkbox" checked={retainRows} onChange={(e) => setRetainRows(e.target.checked)} /> <span>Retain all source rows</span></label>
          <p>Do not remove payment records when a site ID cannot be derived.</p>
        </div>
        <div className="config-check">
          <label><input type="checkbox" checked={syntheticData} onChange={(e) => setSyntheticData(e.target.checked)} /> <span>Use synthetic test values</span></label>
          <p>For fields designated for anonymisation/testing only.</p>
        </div>
        <div className="config-check">
          <label><input type="checkbox" checked={strictValidation} onChange={(e) => setStrictValidation(e.target.checked)} /> <span>Strict validation</span></label>
          <p>Flag ambiguous matches for review instead of silently selecting one.</p>
        </div>

        <div className="sidebar-spacer" />
        <div className="privacy-card">
          <div className="privacy-icon"><LockKeyhole size={17} /></div>
          <div><strong>Designed for controlled data handling</strong><p>Connect and run the processing engine in your approved environment.</p></div>
        </div>
        <div className="sidebar-footer"><span className="status-dot" /> Front-end prototype <span>v1.0</span></div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span>/</span><strong>Network cost assurance</strong></div>
          <div className="topbar-right"><span className="environment"><span className="status-dot" /> Local environment</span><button className="icon-button" title="Help" onClick={() => setMessage("Upload a base payment/source file and supporting reference files. The processing engine still needs to be connected.")}><CircleHelp size={18} /></button></div>
        </header>

        <section className="hero">
          <div className="hero-copy">
            <div className="eyebrow"><Sparkles size={13} /> TELECOM DATA AUTOMATION</div>
            <h1>KPMG - Telecom Solution -<br /><span>Network cost Assurance and Optimisation</span></h1>
            <p>Consolidate payment, site and reference data into a structured master database — with rule-based T-number derivation, site mapping and validation.</p>
            <div className="hero-tags"><span><ShieldCheck size={14} /> Rule-based processing</span><span><Database size={14} /> Master database output</span><span><Activity size={14} /> Exception visibility</span></div>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
            <div className="art-core"><Network size={36} /></div>
            <div className="art-node node-a"><FileSpreadsheet size={17} /></div>
            <div className="art-node node-b"><Zap size={17} /></div>
            <div className="art-node node-c"><Database size={17} /></div>
            <div className="art-node node-d"><Landmark size={17} /></div>
          </div>
        </section>

        <div className="section-heading">
          <div><div className="section-kicker">STEP 01</div><h2>Upload source files</h2><p>Choose the base source file and the relevant supporting files for mapping and enrichment.</p></div>
          <div className="file-count"><FolderUp size={16} /><strong>{totalFiles}</strong> files selected</div>
        </div>

        <section className="upload-grid">
          <div className="panel upload-panel">
            <div className="panel-heading"><div className="panel-icon purple"><FileSpreadsheet size={19} /></div><div><h3>Base source file</h3><p>Required · Payment report / source extract</p></div><span className="required-badge">REQUIRED</span></div>
            <FileDrop title="Upload the base source file" subtitle="Select one Excel or CSV file" files={baseFiles} onFiles={setBaseFiles} accept=".xlsx,.xls,.csv" />
          </div>
          <div className="panel upload-panel">
            <div className="panel-heading"><div className="panel-icon blue"><Layers3 size={19} /></div><div><h3>Supporting data files</h3><p>Site schedule, operational list and other references</p></div><span className="optional-badge">MULTIPLE</span></div>
            <FileDrop title="Upload all the relevant files" subtitle="Select or drag multiple Excel, CSV or PDF files" files={supportFiles} onFiles={setSupportFiles} multiple />
          </div>
        </section>

        <section className="content-grid">
          <div className="panel inventory-panel">
            <div className="panel-title-row"><div><h3><FileText size={18} /> File inventory</h3><p>Review the files selected for this run.</p></div><button className="text-button" onClick={() => { setBaseFiles([]); setSupportFiles([]); resetRun(); }}>Clear all</button></div>
            {totalFiles === 0 ? (
              <div className="empty-state"><div className="empty-icon"><FolderUp size={24} /></div><strong>No files uploaded yet</strong><span>Your selected files will appear here.</span></div>
            ) : (
              <div className="inventory-list">
                {[...baseFiles.map(f => ({...f, kind:"Base source"})), ...supportFiles.map(f => ({...f, kind:"Supporting"}))].map((file, idx) => (
                  <div className="inventory-row" key={`${file.name}-${idx}`}>
                    <div className="file-type-icon"><FileSpreadsheet size={17} /></div>
                    <div className="inventory-name"><strong title={file.name}>{file.name}</strong><span>{file.kind} · {formatBytes(file.size)}</span></div>
                    <span className="file-ready"><Check size={13} /> Added</span>
                  </div>
                ))}
              </div>
            )}
            <div className="inventory-foot"><span><LockKeyhole size={13} /> File selection shown locally in this page</span><span>{(fileSummary.totalSize / (1024 * 1024)).toFixed(2)} MB total</span></div>
          </div>

          <div className="panel run-panel">
            <div className="panel-title-row"><div><h3><Settings2 size={18} /> Processing controls</h3><p>Review before starting the run.</p></div><span className="step-pill">STEP 02</span></div>
            <div className="run-checklist">
              <div className="checklist-row"><span className={`check-circle ${baseFiles.length ? "checked" : ""}`}>{baseFiles.length ? <Check size={13} /> : "1"}</span><div><strong>Base source file</strong><span>{baseFiles.length ? "File selected" : "Waiting for upload"}</span></div></div>
              <div className="checklist-row"><span className={`check-circle ${supportFiles.length ? "checked" : ""}`}>{supportFiles.length ? <Check size={13} /> : "2"}</span><div><strong>Supporting references</strong><span>{supportFiles.length ? `${supportFiles.length} file(s) selected` : "Waiting for upload"}</span></div></div>
              <div className="checklist-row"><span className={`check-circle ${status === "complete" ? "checked" : ""}`}>{status === "complete" ? <Check size={13} /> : "3"}</span><div><strong>Processing engine</strong><span>{status === "complete" ? "Demo status only" : "Not connected yet"}</span></div></div>
            </div>
            <button className="btn btn-primary run-button" onClick={runDemo} disabled={!canRun}>
              <Zap size={17} /> Validate upload setup <ArrowRight size={16} />
            </button>
            <button className="btn btn-quiet reset-button" onClick={resetRun}><RefreshCw size={15} /> Reset run status</button>
            {!canRun && status !== "complete" && <div className="helper-text"><AlertCircle size={14} /> Add one base file and at least one supporting file to enable validation.</div>}
          </div>
        </section>

        <div className="section-heading lower-heading">
          <div><div className="section-kicker">STEP 03</div><h2>Processing overview</h2><p>These indicators will be driven by the processing engine once it is connected.</p></div>
          <span className={`run-status ${status === "complete" ? "success" : ""}`}><span className="status-dot" /> {status === "complete" ? "Demo run complete" : "Awaiting input"}</span>
        </div>

        <section className="metrics-grid">
          <Metric label="Files selected" value={totalFiles} note={`${baseFiles.length} base · ${supportFiles.length} supporting`} icon={FileText} tone="blue" />
          <Metric label="Source data rows" value="—" note="Available after backend processing" icon={BarChart3} tone="purple" />
          <Metric label="T-numbers derived" value="—" note="Rule engine not connected" icon={Network} tone="green" />
          <Metric label="Exceptions flagged" value="—" note="Available after validation" icon={AlertCircle} tone="orange" />
        </section>

        <section className="panel pipeline-panel">
          <div className="panel-title-row"><div><h3><Activity size={18} /> Automation pipeline</h3><p>Planned processing sequence from upload through master database generation.</p></div><span className="progress-label">{progress}%</span></div>
          <div className="progress-track"><div className="progress-fill" style={{ width: `${progress}%` }} /></div>
          <div className="pipeline-grid">
            {stages.map((stage, idx) => {
              const Icon = stage.icon;
              const done = completedStages.includes(stage.title);
              return <div className={`pipeline-stage ${done ? "done" : ""}`} key={stage.title}>
                <div className="stage-top"><div className="stage-icon"><Icon size={18} /></div><span className="stage-number">0{idx + 1}</span></div>
                <strong>{stage.title}</strong><p>{stage.detail}</p>
                <span className={`stage-state ${done ? "done-state" : ""}`}>{done ? <><CheckCircle2 size={13} /> Demo complete</> : <><Clock3 size={13} /> Pending connection</>}</span>
              </div>;
            })}
          </div>
          {message && <div className={`message-banner ${status === "complete" ? "message-info" : "message-warn"}`}><AlertCircle size={17} /><div><strong>{status === "complete" ? "Prototype status" : "Action needed"}</strong><span>{message}</span></div><button onClick={() => setMessage("")} aria-label="Dismiss message"><X size={15} /></button></div>}
          {status === "complete" && <div className="output-strip"><div className="output-icon"><Download size={18} /></div><div><strong>Run summary available</strong><span>Run timestamp: {runTime}. This is a configuration summary, not a generated master database.</span></div><button className="btn btn-outline" onClick={downloadRunSummary}>Download run summary</button></div>}
        </section>

        <footer className="page-footer"><span>© KPMG · Telecom Solution</span><span><LockKeyhole size={13} /> Prototype UI only · No backend data processing connected</span></footer>
      </main>
    </div>
  );
}