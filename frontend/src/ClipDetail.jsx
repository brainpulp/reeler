import React, { useState } from "react";
import { api, fileUrl } from "./api.js";

// Detail / editor panel for a single clip: play it, tag it, and run the
// edit + manipulate operations (trim, speed) which spawn new derived clips.
export default function ClipDetail({ clip, onClose, onChanged }) {
  const [tags, setTags] = useState(clip.tags);
  const [newTag, setNewTag] = useState("");
  const [start, setStart] = useState(0);
  const [end, setEnd] = useState(clip.duration || 0);
  const [factor, setFactor] = useState(1.5);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const guard = (fn) => async () => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
      await onChanged();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  };

  const addTag = guard(async () => {
    if (!newTag.trim()) return;
    const updated = await api.addTag(clip.id, newTag.trim());
    setTags(updated.tags);
    setNewTag("");
  });

  const removeTag = (t) =>
    guard(async () => {
      const updated = await api.removeTag(clip.id, t);
      setTags(updated.tags);
    })();

  const doTrim = guard(async () => {
    await api.trim(clip.id, Number(start), Number(end));
    setNote("Trimmed → new clip created");
  });

  const doSpeed = guard(async () => {
    await api.speed(clip.id, Number(factor));
    setNote(`Speed ×${factor} → new clip created`);
  });

  return (
    <div className="modal" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>
          ×
        </button>
        <video src={fileUrl(clip.id)} controls autoPlay />

        <div className="info">
          <div className="title">
            {clip.ig_owner ? `@${clip.ig_owner}` : clip.filename}
          </div>
          {clip.caption && <p className="caption">{clip.caption}</p>}
          <div className="dims">
            {clip.width}×{clip.height} · {clip.duration?.toFixed(1)}s ·{" "}
            {clip.fps?.toFixed(0)}fps · {clip.source}
          </div>
        </div>

        <section>
          <h3>Tags</h3>
          <div className="tags">
            {tags.map((t) => (
              <span key={t} className="tag">
                #{t}
                <button onClick={() => removeTag(t)}>×</button>
              </span>
            ))}
          </div>
          <div className="row">
            <input
              value={newTag}
              placeholder="add tag…"
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addTag()}
            />
            <button onClick={addTag} disabled={busy}>
              add
            </button>
          </div>
        </section>

        <section>
          <h3>Trim</h3>
          <div className="row">
            <label>
              start
              <input
                type="number"
                step="0.1"
                min="0"
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              end
              <input
                type="number"
                step="0.1"
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <button onClick={doTrim} disabled={busy}>
              trim
            </button>
          </div>
        </section>

        <section>
          <h3>Speed</h3>
          <div className="row">
            <input
              type="range"
              min="0.25"
              max="4"
              step="0.25"
              value={factor}
              onChange={(e) => setFactor(e.target.value)}
            />
            <span>×{factor}</span>
            <button onClick={doSpeed} disabled={busy}>
              apply
            </button>
          </div>
        </section>

        {note && <div className="note">{note}</div>}
      </div>
    </div>
  );
}
