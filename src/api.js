// REST client for the local FastAPI backend (see backend/README.md).
export const API_BASE = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

async function parse(res) {
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const err = new Error(body?.message || `Request failed (${res.status})`);
    err.details = body?.details || [];
    err.status = res.status;
    throw err;
  }
  return body;
}

// One source file plus zero or more supporting files. T-number rules live in the backend configuration.
function uploadForm({ source, support, options = {} }) {
  const form = new FormData();
  source.forEach((f) => form.append("source_file", f));
  support.forEach((f) => form.append("supporting_files", f));
  Object.entries(options).forEach(([k, v]) => form.append(k, String(v)));
  return form;
}

export async function getHealth() {
  return parse(await fetch(`${API_BASE}/api/health`));
}

export async function validateFiles(files) {
  return parse(await fetch(`${API_BASE}/api/validate`, { method: "POST", body: uploadForm(files) }));
}

export async function startProcessing(files, options) {
  return parse(await fetch(`${API_BASE}/api/process`, { method: "POST", body: uploadForm({ ...files, options }) }));
}

export async function getJob(jobId) {
  return parse(await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}`));
}

export async function downloadOutput(jobId, kind) {
  const res = await fetch(`${API_BASE}/api/jobs/${encodeURIComponent(jobId)}/download/${kind}`);
  if (!res.ok) await parse(res);
  const disposition = res.headers.get("Content-Disposition") || "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `${kind}.xlsx`;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
