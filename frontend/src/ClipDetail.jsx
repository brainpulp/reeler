import React, { useRef, useState } from "react";
import { api, fileUrl } from "./api.js";

// Detail / editor panel for one clip:
//  - annotate: title + description (metadata) and free-text tags
//  - time-crop: mark labeled segments (the reusable units for combining)
//  - quick edits: trim and speed, each spawning a new derived clip
export default function ClipDetail({ clip, onClose, onChanged, onAddToTimeline }) {
  const videoRef = useRef(null);

  const [title, setTitle] = useState(clip.title || "");
  const [description, setDescription] = useState(clip.description || "");
  const [tags, setTags] = useState(clip.tags);
  const [segments, setSegments] = useState(clip.segments || []);
  const [newTag, setNewTag] = useState("");

  const [segStart, setSegStart] = useState(0);
  const [segEnd, setSegEnd] = useState(clip.duration || 0);
  const [segLabel, setSegLabel] = useState("");

  const [trimStart, setTrimStart] = useState(0);
  const [trimEnd, setTrimEnd] = useState(clip.duration || 0);
  const [factor, setFactor] = useState(1.5);

  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const playhead = () =>
    videoRef.current ? Number(videoRef.current.currentTime.toFixed(2)) : 0;

  const guard = (fn) => async () => {
    setBusy(true);
    setNote(null);
    try {
      await fn();
    } catch (e) {
      setNote(e.message);
    } finally {
      setBusy(false);
    }
  };

  const saveMeta = guard(async () => {
    await api.updateMeta(clip.id, { title, description });
    setNote("Saved");
    await onChanged();
  });

  const addTag = guard(async () => {
    if (!newTag.trim()) return;
    const updated = await api.addTag(clip.id, newTag.trim());
    setTags(updated.tags);
    setNewTag("");
    await onChanged();
  });

  const removeTag = (t) =>
    guard(async () => {
      const updated = await api.removeTag(clip.id, t);
      setTags(updated.tags);
      await onChanged();
    })();

  const addSegment = guard(async () => {
    const updated = await api.addSegment(clip.id, {
      start: Number(segStart),
      end: Number(segEnd),
      label: segLabel.trim() || null,
    });
    setSegments(updated.segments);
    setSegLabel("");
    await onChanged();
  });

  const removeSegment = (segId) =>
    guard(async () => {
      await api.deleteSegment(segId);
      setSegments(segments.filter((s) => s.id !== segId));
      await onChanged();
    })();

  const sendSegment = (s) =>
    onAddToTimeline({
      kind: "segment",
      clip_id: clip.id,
      start: s.start,
      end: s.end,
      label: s.label || title || clip.filename,
    });

  const doTrim = guard(async () => {
    await api.trim(clip.id, Number(trimStart), Number(trimEnd));
    setNote("Trimmed → new clip created");
    await onChanged();
  });

  const doSpeed = guard(async () => {
    await api.speed(clip.id, Number(factor));
    setNote(`Speed ×${factor} → new clip created`);
    await onChanged();
  });

  return (
    <div className="modal" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>
          ×
        </button>
        <video ref={videoRef} src={fileUrl(clip.id)} controls autoPlay />
        <div className="dims">
          {clip.width}×{clip.height} · {clip.duration?.toFixed(1)}s ·{" "}
          {clip.fps?.toFixed(0)}fps · {clip.source}
        </div>

        <section>
          <h3>Annotate</h3>
          <input
            className="full"
            placeholder="title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <textarea
            className="full"
            placeholder="description / notes"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button onClick={saveMeta} disabled={busy}>
            save
          </button>
        </section>

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
          <h3>Segments (time-crop)</h3>
          {segments.length > 0 && (
            <ul className="seglist">
              {segments.map((s) => (
                <li key={s.id}>
                  <span className="seglabel">{s.label || "segment"}</span>
                  <span className="segtime">
                    {s.start.toFixed(1)}–{s.end.toFixed(1)}s
                  </span>
                  <button onClick={() => sendSegment(s)} title="add to timeline">
                    → timeline
                  </button>
                  <button onClick={() => removeSegment(s.id)}>×</button>
                </li>
              ))}
            </ul>
          )}
          <div className="row">
            <label>
              start
              <input
                type="number"
                step="0.1"
                min="0"
                value={segStart}
                onChange={(e) => setSegStart(e.target.value)}
              />
            </label>
            <button onClick={() => setSegStart(playhead())} title="use playhead">
              ⌖
            </button>
            <label>
              end
              <input
                type="number"
                step="0.1"
                value={segEnd}
                onChange={(e) => setSegEnd(e.target.value)}
              />
            </label>
            <button onClick={() => setSegEnd(playhead())} title="use playhead">
              ⌖
            </button>
          </div>
          <div className="row">
            <input
              placeholder="label (optional)"
              value={segLabel}
              onChange={(e) => setSegLabel(e.target.value)}
            />
            <button onClick={addSegment} disabled={busy}>
              mark segment
            </button>
          </div>
        </section>

        <section>
          <h3>Trim → new clip</h3>
          <div className="row">
            <label>
              start
              <input
                type="number"
                step="0.1"
                min="0"
                value={trimStart}
                onChange={(e) => setTrimStart(e.target.value)}
              />
            </label>
            <label>
              end
              <input
                type="number"
                step="0.1"
                value={trimEnd}
                onChange={(e) => setTrimEnd(e.target.value)}
              />
            </label>
            <button onClick={doTrim} disabled={busy}>
              trim
            </button>
          </div>
        </section>

        <section>
          <h3>Speed → new clip</h3>
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
