import React, { useState } from "react";
import { api } from "./api.js";

// The combine surface: an ordered tray of segments and text cards that renders
// into a single new clip. Lives pinned at the bottom of the app.
export default function Timeline({ items, setItems, onRendered }) {
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const move = (i, dir) => {
    const j = i + dir;
    if (j < 0 || j >= items.length) return;
    const next = items.slice();
    [next[i], next[j]] = [next[j], next[i]];
    setItems(next);
  };

  const remove = (i) => setItems(items.filter((_, k) => k !== i));

  const addCard = () =>
    setItems([
      ...items,
      { kind: "card", text: "Title", duration: 2.5, bg: "black" },
    ]);

  const editCard = (i, patch) =>
    setItems(items.map((it, k) => (k === i ? { ...it, ...patch } : it)));

  const render = async () => {
    setBusy(true);
    setErr(null);
    try {
      const payload = items.map((it) =>
        it.kind === "segment"
          ? { kind: "segment", clip_id: it.clip_id, start: it.start, end: it.end }
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
        <button
          className="primary"
          onClick={render}
          disabled={busy || items.length === 0}
        >
          {busy ? "rendering…" : `Render (${items.length})`}
        </button>
      </div>
      {err && <div className="error">⚠ {err}</div>}
      {items.length === 0 ? (
        <div className="tl-empty">
          Add segments from a clip, or drop in a text card, then render.
        </div>
      ) : (
        <ol className="tl-items">
          {items.map((it, i) => (
            <li key={i} className={`tl-item ${it.kind}`}>
              <div className="tl-order">
                <button onClick={() => move(i, -1)} disabled={i === 0}>
                  ↑
                </button>
                <button
                  onClick={() => move(i, 1)}
                  disabled={i === items.length - 1}
                >
                  ↓
                </button>
              </div>
              {it.kind === "segment" ? (
                <div className="tl-body">
                  <span className="tl-kind">▷ segment</span>
                  <span className="tl-label">
                    {it.label || it.clipLabel || `clip ${it.clip_id}`}
                  </span>
                  <span className="tl-time">
                    {it.start.toFixed(1)}–{it.end.toFixed(1)}s
                  </span>
                </div>
              ) : (
                <div className="tl-body card-edit">
                  <span className="tl-kind">▤ card</span>
                  <input
                    value={it.text}
                    onChange={(e) => editCard(i, { text: e.target.value })}
                  />
                  <input
                    type="number"
                    step="0.5"
                    min="0.5"
                    value={it.duration}
                    onChange={(e) => editCard(i, { duration: e.target.value })}
                    title="seconds"
                  />
                  <input
                    type="text"
                    className="bg"
                    value={it.bg}
                    onChange={(e) => editCard(i, { bg: e.target.value })}
                    title="background color"
                  />
                </div>
              )}
              <button className="tl-x" onClick={() => remove(i)}>
                ×
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
