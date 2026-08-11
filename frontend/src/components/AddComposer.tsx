/* Add a claim the extraction missed (PRD R10, flow spec §4.4).
 *
 * It asks for a claim and a type — and deliberately **not** for a citation.
 * Manual nodes carry `human_assertion` provenance: the evidence is the person
 * who typed it, recorded automatically by the server
 * (docs/decisions/2026-08-03-manual-node-provenance.md). Asking a PM to paste a
 * URL here is exactly how fabricated provenance gets into the store.
 */

import { useEffect, useRef, useState } from "react";
import type { NodeType } from "../api";
import { SECTION_ORDER, TYPE_TAGS } from "../review";

export function AddComposer({
  actor,
  onAdd,
  onCancel,
}: {
  actor: string;
  onAdd: (type: NodeType, content: string) => void;
  onCancel: () => void;
}) {
  const [type, setType] = useState<NodeType>("constraint");
  const [content, setContent] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), []);

  return (
    <div className="composer">
      <div className="composer__row">
        <select value={type} onChange={(event) => setType(event.target.value as NodeType)}>
          {SECTION_ORDER.map((option) => (
            <option key={option} value={option}>
              {TYPE_TAGS[option]}
            </option>
          ))}
        </select>
        <span className="composer__hint">Recorded as asserted by {actor}.</span>
      </div>
      <textarea
        ref={ref}
        rows={3}
        placeholder="A constraint mentioned in a meeting, a decision made in the hallway…"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onAdd(type, content.trim());
        }}
      />
      <div className="composer__row">
        <button
          type="button"
          className="action action--primary"
          onClick={() => onAdd(type, content.trim())}
          disabled={!content.trim()}
        >
          Add claim
        </button>
        <button type="button" className="action" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}
