import React from "react";
import { useDraggable } from "@dnd-kit/core";

// A small drag handle shown on each library card. Dragging it onto the timeline
// drop zone adds that reel as a segment (and auto-downloads it if needed).
// It's a separate element so normal card clicks (open, select) still work.
export default function Grip({ clip }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `clip-${clip.id}`,
    data: { type: "clip", clip },
  });
  return (
    <button
      ref={setNodeRef}
      className={"grip" + (isDragging ? " dragging" : "")}
      title="drag into the timeline"
      onClick={(e) => e.stopPropagation()}
      {...listeners}
      {...attributes}
    >
      ⠿
    </button>
  );
}
