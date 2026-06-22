import React, { useEffect, useRef, useState } from "react";
import { fileUrl } from "./api.js";

// WYSIWYG preview of the timeline without rendering on the server. Plays each
// item in order in one <video>: segments seek to their [start,end] range, text
// cards show as a styled overlay for their duration. This is an approximation
// (no re-encoding, browser-side), so the final render is the source of truth.
export default function TimelinePreview({ items, onClose }) {
  const videoRef = useRef(null);
  const idxRef = useRef(0);
  const timerRef = useRef(null);
  const [idx, setIdx] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [card, setCard] = useState(null);

  const durations = items.map((it) =>
    it.kind === "card" ? Number(it.duration) || 0 : (it.end - it.start) || 0
  );
  const total = durations.reduce((a, b) => a + b, 0);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const stop = () => {
    clearTimer();
    const v = videoRef.current;
    if (v) v.pause();
    setPlaying(false);
  };

  const goto = (i) => {
    if (i >= items.length) {
      stop();
      setIdx(items.length - 1);
      return;
    }
    idxRef.current = i;
    setIdx(i);
  };

  // Drive the current item whenever idx changes (and we're playing).
  useEffect(() => {
    if (!playing) return;
    clearTimer();
    const it = items[idx];
    if (!it) return;
    idxRef.current = idx;

    if (it.kind === "card") {
      setCard(it);
      const v = videoRef.current;
      if (v) v.pause();
      timerRef.current = setTimeout(
        () => goto(idx + 1),
        (Number(it.duration) || 0) * 1000
      );
      return;
    }

    setCard(null);
    const v = videoRef.current;
    if (!v) return;
    const url = fileUrl(it.clip_id);
    const seekPlay = () => {
      try {
        v.currentTime = it.start;
      } catch {
        /* metadata not ready yet; loadedmetadata will retry */
      }
      v.play().catch(() => {});
    };
    if (v.getAttribute("data-url") !== url) {
      v.setAttribute("data-url", url);
      v.src = url;
      v.onloadedmetadata = seekPlay;
    } else {
      seekPlay();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idx, playing]);

  useEffect(() => () => clearTimer(), []);

  const onTimeUpdate = () => {
    const it = items[idxRef.current];
    if (!it || it.kind !== "segment") return;
    if (videoRef.current.currentTime >= it.end - 0.03) {
      goto(idxRef.current + 1);
    }
  };

  const restart = () => {
    setPlaying(true);
    goto(0);
  };

  return (
    <div className="modal" onClick={onClose}>
      <div className="sheet preview" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose}>
          ×
        </button>
        <h3>Timeline preview · {total.toFixed(1)}s</h3>

        <div className="pv-stage">
          <video
            ref={videoRef}
            onTimeUpdate={onTimeUpdate}
            playsInline
            muted={false}
          />
          {card && (
            <div className="pv-card" style={{ background: card.bg || "black" }}>
              <span>{card.text}</span>
            </div>
          )}
        </div>

        {/* Proportional ruler — click a block to jump there. */}
        <div className="pv-ruler">
          {items.map((it, i) => (
            <button
              key={i}
              className={
                "pv-block " + (it.kind === "card" ? "card" : "seg") +
                (i === idx ? " on" : "")
              }
              style={{ flexGrow: Math.max(durations[i], 0.2) }}
              title={
                it.kind === "card"
                  ? `card: ${it.text}`
                  : `${it.label || "segment"} ${it.start.toFixed(1)}–${it.end.toFixed(1)}s`
              }
              onClick={() => {
                setPlaying(true);
                goto(i);
              }}
            >
              {it.kind === "card" ? "▤" : "▷"}
            </button>
          ))}
        </div>

        <div className="row pv-controls">
          {playing ? (
            <button onClick={stop}>⏸ pause</button>
          ) : (
            <button onClick={restart}>▶ play from start</button>
          )}
          <span className="pv-pos">
            item {idx + 1} / {items.length}
          </span>
        </div>
      </div>
    </div>
  );
}
