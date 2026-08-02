// Thin wrapper around the Reeler API. Everything is same-origin via the Vite
// proxy in dev, or the mounted static build in prod.

async function req(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  health: () => req("/health"),
  igStatus: () => req("/ig/status"),
  listClips: (tag, collection) => {
    const q = new URLSearchParams();
    if (tag) q.set("tag", tag);
    if (collection) q.set("collection", collection);
    const s = q.toString();
    return req(`/clips${s ? `?${s}` : ""}`);
  },
  startSniff: () => req("/sniff/start", { method: "POST", body: "{}" }),
  stopSniff: () => req("/sniff/stop", { method: "POST", body: "{}" }),
  sniffProgress: () => req("/sniff/progress"),
  scanLibrary: () => req("/library/scan", { method: "POST", body: "{}" }),
  scanProgress: () => req("/library/scan/progress"),
  backfillCollections: () => req("/collections/backfill", { method: "POST", body: "{}" }),
  collectionsProgress: () => req("/collections/backfill/progress"),
  startIndex: () => req("/index/start", { method: "POST", body: "{}" }),
  stopIndex: () => req("/index/stop", { method: "POST", body: "{}" }),
  indexProgress: () => req("/index/progress"),
  ensure: (id) => req(`/clips/${id}/ensure`, { method: "POST", body: "{}" }),
  keep: (id, keep = true) =>
    req(`/clips/${id}/keep?keep=${keep}`, { method: "POST", body: "{}" }),
  cleanLibrary: () => req("/library/clean", { method: "POST", body: "{}" }),
  publish: () => req("/publish", { method: "POST", body: "{}" }),
  startSummarize: () => req("/summarize/start", { method: "POST", body: "{}" }),
  stopSummarize: () => req("/summarize/stop", { method: "POST", body: "{}" }),
  summarizeProgress: () => req("/summarize/progress"),
  upload: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/upload", { method: "POST", body: fd });
    if (!res.ok) throw new Error((await res.json()).detail || "upload failed");
    return res.json();
  },
  addTag: (id, name) =>
    req(`/clips/${id}/tags`, { method: "POST", body: JSON.stringify({ name }) }),
  removeTag: (id, name) =>
    req(`/clips/${id}/tags/${encodeURIComponent(name)}`, { method: "DELETE" }),
  trim: (id, start, end) =>
    req(`/clips/${id}/trim`, {
      method: "POST",
      body: JSON.stringify({ start, end }),
    }),
  speed: (id, factor) =>
    req(`/clips/${id}/speed`, {
      method: "POST",
      body: JSON.stringify({ factor }),
    }),
  combine: (clipIds) =>
    req("/combine", { method: "POST", body: JSON.stringify({ clip_ids: clipIds }) }),
  updateMeta: (id, meta) =>
    req(`/clips/${id}`, { method: "PATCH", body: JSON.stringify(meta) }),
  addSegment: (id, seg) =>
    req(`/clips/${id}/segments`, { method: "POST", body: JSON.stringify(seg) }),
  deleteSegment: (segId) =>
    req(`/segments/${segId}`, { method: "DELETE" }),
  renderTimeline: (items, title) =>
    req("/timeline", { method: "POST", body: JSON.stringify({ items, title }) }),
  caption: (id, cap) =>
    req(`/clips/${id}/caption`, { method: "POST", body: JSON.stringify(cap) }),
};

export const fileUrl = (id) => `/api/clips/${id}/file`;
export const thumbUrl = (id) => `/api/clips/${id}/thumb`;
