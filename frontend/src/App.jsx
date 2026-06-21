import React, { useEffect, useState, useCallback } from "react";
import { api, fileUrl, thumbUrl } from "./api.js";
import ClipDetail from "./ClipDetail.jsx";
import Timeline from "./Timeline.jsx";

export default function App() {
  const [clips, setClips] = useState([]);
  const [tags, setTags] = useState([]);
  const [activeTag, setActiveTag] = useState(null);
  const [selected, setSelected] = useState([]); // ids picked for combine
  const [open, setOpen] = useState(null); // clip in detail view
  const [timeline, setTimeline] = useState([]); // ordered combine items
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const addToTimeline = (item) => setTimeline((t) => [...t, item]);

  const refresh = useCallback(async () => {
    const data = await api.listClips(activeTag);
    setClips(data.clips);
    setTags(data.tags);
  }, [activeTag]);

  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, [refresh]);

  const run = async (fn) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const onIngest = () => run(() => api.ingest(12));
  const onUpload = (e) => {
    const file = e.target.files?.[0];
    if (file) run(() => api.upload(file));
    e.target.value = "";
  };

  const toggleSelect = (id) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  // Drop the selected clips into the timeline as full-length segments.
  const onAddSelected = () => {
    const byId = Object.fromEntries(clips.map((c) => [c.id, c]));
    selected.forEach((id) => {
      const c = byId[id];
      if (!c) return;
      addToTimeline({
        kind: "segment",
        clip_id: id,
        start: 0,
        end: c.duration || 0,
        label: c.title || (c.ig_owner ? `@${c.ig_owner}` : c.filename),
      });
    });
    setSelected([]);
  };

  return (
    <div className="app">
      <header>
        <h1>🎬 Reeler</h1>
        <div className="toolbar">
          <button onClick={onIngest} disabled={busy}>
            Sniff saved reels
          </button>
          <label className="upload-btn">
            Import file
            <input type="file" accept="video/*" hidden onChange={onUpload} />
          </label>
          <button
            onClick={onAddSelected}
            disabled={busy || selected.length === 0}
            title="Add selected clips to the timeline as full segments"
          >
            Add selected → timeline ({selected.length})
          </button>
        </div>
      </header>

      {error && <div className="error">⚠ {error}</div>}

      <div className="tagbar">
        <button
          className={!activeTag ? "tag active" : "tag"}
          onClick={() => setActiveTag(null)}
        >
          all
        </button>
        {tags.map((t) => (
          <button
            key={t}
            className={activeTag === t ? "tag active" : "tag"}
            onClick={() => setActiveTag(t)}
          >
            #{t}
          </button>
        ))}
      </div>

      {clips.length === 0 ? (
        <div className="empty">
          No clips yet. Sniff your saved reels or import a file to begin.
        </div>
      ) : (
        <div className="grid">
          {clips.map((c) => (
            <div
              key={c.id}
              className={
                "card" +
                (selected.includes(c.id) ? " sel" : "") +
                (c.source === "derived" ? " derived" : "")
              }
            >
              <div className="thumb" onClick={() => setOpen(c)}>
                {c.thumb_rel ? (
                  <img src={thumbUrl(c.id)} alt="" loading="lazy" />
                ) : (
                  <video src={fileUrl(c.id)} muted />
                )}
                <span className="dur">
                  {c.duration ? `${c.duration.toFixed(1)}s` : ""}
                </span>
              </div>
              <div className="meta">
                <span className="owner">
                  {c.source === "derived"
                    ? `↳ ${c.op?.type || "edit"}`
                    : c.ig_owner
                    ? `@${c.ig_owner}`
                    : c.filename}
                </span>
                <input
                  type="checkbox"
                  checked={selected.includes(c.id)}
                  onChange={() => toggleSelect(c.id)}
                  title="select for combine"
                />
              </div>
              {c.tags.length > 0 && (
                <div className="cardtags">
                  {c.tags.map((t) => (
                    <span key={t} className="minitag">
                      #{t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {open && (
        <ClipDetail
          clip={open}
          onClose={() => setOpen(null)}
          onAddToTimeline={addToTimeline}
          onChanged={async () => {
            await refresh();
          }}
        />
      )}

      <Timeline items={timeline} setItems={setTimeline} onRendered={refresh} />
    </div>
  );
}
