import React, { useState } from "react";
import { api } from "./api.js";

// The caption shown on a library card. Displays the user's title if set,
// otherwise the original Instagram caption. Click to add/edit a title inline
// (this writes to `title` and never overwrites the original IG caption).
export default function CardCaption({ clip, onChanged }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(clip.title || "");
  const [busy, setBusy] = useState(false);

  const display = clip.title || clip.caption || "";

  const save = async () => {
    setBusy(true);
    try {
      await api.updateMeta(clip.id, { title: value.trim() });
      await onChanged();
    } finally {
      setBusy(false);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <textarea
        className="card-caption-edit"
        autoFocus
        rows={2}
        placeholder="add a title…"
        value={value}
        disabled={busy}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            save();
          }
          if (e.key === "Escape") {
            setValue(clip.title || "");
            setEditing(false);
          }
        }}
      />
    );
  }

  return (
    <div
      className={"card-caption" + (display ? "" : " empty")}
      title={display ? "click to edit title" : "click to add a title"}
      onClick={() => {
        setValue(clip.title || "");
        setEditing(true);
      }}
    >
      {display || "+ add title"}
      {clip.title && clip.caption && clip.title !== clip.caption && (
        <span className="card-caption-sub">{clip.caption}</span>
      )}
    </div>
  );
}
