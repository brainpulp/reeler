import React, { useState } from "react";
import { useDroppable } from "@dnd-kit/core";
import {
  SortableContext,
  useSortable,
  horizontalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api } from "./api.js";
import TimelinePreview from "./TimelinePreview.jsx";

const clampNum = (v, lo, hi) => {
  const n = Number(v);
  if (Number.isNaN(n)) return lo;
  return Math.min(hi, Math.max(lo, n));
};

// One block on the track — a video segment (with in/out crop) or a text card.
// Drag the ⠿ handle to reorder; reordering is resolved in App's onDragEnd.
function SortableBlock({ item, onChange, onRemove }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: `block-${item.uid}`, data: { type: "block", uid: item.uid } });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  const dur = item.duration || item.end || 0;

  return (
    <li ref={setNodeRef} style={style} className={"tl-block " + item.kind + (item.error ? " err" : "")}>
      <div className="tl-grip" {...attributes} {...listeners} title="drag to reorder">
        ⠿
      </div>
      {item.kind === "segment" ? (
        <div className="tl-block-body">
          <div className="tl-block-label" title={item.label}>
            {item.label || `clip ${item.clip_id}`}
          </div>
          {item.downloading ? (
            <div className="tl-dl">⭳ downloading…</div>
          ) : item.error ? (
            <div className="tl-dl err">download failed</div>
          ) : (
            <div className="tl-crop">
              <label>
                in
                <input
                  type="number" min="0" max={dur} step="0.1" value={item.start}
                  onChange={(e) => onChange({ start: clampNum(e.target.value, 0, item.end) })}
                />
              </label>
              <label>
                out
                <input
                  type="number" min="0" max={dur} step="0.1" value={item.end}
                  onChange={(e) => onChange({ end: clampNum(e.target.value, item.start, dur) })}
                />
              </label>
              <span className="tl-seg-dur">{Math.max(0, item.end - item.start).toFixed(1)}s</span>
            </div>
          )}
        </div>
      ) : (
        <div className="tl-block-body card-edit">
          <input value={item.text} onChange={(e) => onChange({ text: e.target.value })} />
          <div className="tl-crop">
            <label>
              sec
              <input
                type="number" step="0.5" min="0.5" value={item.duration}
                onChange={(e) => onChange({ duration: e.target.value })}
              />
            </label>
            <input
              className="bg" type="text" value={item.bg} title="background color"
              onChange={(e) => onChange({ bg: e.target.value })}
            />
          </div>
        </div>
      )}
      <button className="tl-x" onClick={onRemove}>×</button>
    </li>
  );
}

// The combine surface: a horizontal track you drag reels onto, crop, reorder,
// and render into one clip. Pinned at the bottom of the app.
export default function Timeline({ items, setItems, onRendered }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [preview, setPreview] = useState(false);

  const { setNodeRef, isOver } = useDroppable({ id: "timeline-drop" });

  const patch = (uid, p) =>
    setItems(items.map((it) => (it.uid === uid ? { ...it, ...p } : it)));
  const remove = (uid) => setItems(items.filter((it) => it.uid !== uid));

  const addCard = () =>
    setItems([
      ...items,
      { uid: Date.now(), kind: "card", text: "Title", duration: 2.5, bg: "black" },
    ]);

  const pending = items.some((it) => it.downloading);
  const renderable = items.filter((it) => !it.downloading && !it.error);

  const render = async () => {
    setBusy(true);
    setErr(null);
    try {
      const payload = renderable.map((it) =>
        it.kind === "segment"
          ? { kind: "segment", clip_id: it.clip_id, start: Number(it.start), end: Number(it.end) }
          : { kind: "card", text: it.text, duration: Number(it.duration), bg: it.bg }
      );
      await api.renderTimeline(payload, title || null);
      setItems([]);
      setTitle("");
      await onRendered();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="timeline">
      <div className="tl-head">
        <strong>Timeline</strong>
        <input
          className="tl-title"
          placeholder="output title (optional)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button onClick={addCard}>+ text card</button>
        <button onClick={() => setPreview(true)} disabled={renderable.length === 0}>
          ▶ preview
        </button>
        <button
          className="primary"
          onClick={render}
          disabled={busy || pending || renderable.length === 0}
          title={pending ? "waiting for a download to finish" : "combine into one clip"}
        >
          {busy ? "rendering…" : pending ? "downloading…" : `Render (${renderable.length})`}
        </button>
      </div>

      {preview && <TimelinePreview items={renderable} onClose={() => setPreview(false)} />}
      {err && <div className="error">⚠ {err}</div>}

      <SortableContext
        items={items.map((it) => `block-${it.uid}`)}
        strategy={horizontalListSortingStrategy}
      >
        <ol
          ref={setNodeRef}
          className={"tl-track" + (isOver ? " over" : "") + (items.length === 0 ? " empty" : "")}
        >
          {items.length === 0 ? (
            <li className="tl-hint">
              Drag reels here (⠿ handle) to crop &amp; combine — they download automatically.
            </li>
          ) : (
            items.map((it) => (
              <SortableBlock
                key={it.uid}
                item={it}
                onChange={(p) => patch(it.uid, p)}
                onRemove={() => remove(it.uid)}
              />
            ))
          )}
        </ol>
      </SortableContext>
    </div>
  );
}
