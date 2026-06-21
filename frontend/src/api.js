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
  listClips: (tag) => req(`/clips${tag ? `?tag=${encodeURIComponent(tag)}` : ""}`),
  ingest: (limit) =>
    req("/ingest", { method: "POST", body: JSON.stringify({ limit }) }),
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
};

export const fileUrl = (id) => `/api/clips/${id}/file`;
export const thumbUrl = (id) => `/api/clips/${id}/thumb`;
