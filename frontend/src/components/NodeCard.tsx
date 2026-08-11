/* The unit of review (design baseline §6.1, flow spec §4).
 *
 * The focus model: only the focused card expands to show its provenance and
 * actions; reviewed cards that aren't focused recede to a quiet one-line row, so
 * the layout itself shows what still needs the reader.
 */

import { useEffect, useRef, useState } from "react";
import type { Node, NodeType, SourceRef } from "../api";
import { SOURCE_BADGES, TYPE_TAGS, crossesSource, pipsFor, sourceLabel } from "../review";

const STATUS_MARKS: Record<Node["status"], { mark: string; label: string }> = {
  unconfirmed: { mark: "○", label: "to review" },
  confirmed: { mark: "✓", label: "confirmed" },
  edited: { mark: "✎", label: "edited" },
  rejected: { mark: "✕", label: "rejected" },
};

function Provenance({ refs }: { refs: SourceRef[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="provenance">
      {refs.map((ref) => (
        <div key={ref.id}>
          <div className="provenance__row">
            <span className="badge">{SOURCE_BADGES[ref.source_type]}</span>
            <button
              type="button"
              className="provenance__toggle"
              aria-expanded={expanded}
              onClick={() => setExpanded((open) => !open)}
            >
              {expanded ? "▾" : "▸"} “{ref.excerpt}”
            </button>
            {ref.source_type === "human_assertion" ? (
              <span className="provenance__asserted">asserted by {ref.external_id}</span>
            ) : (
              <a
                className="provenance__link"
                href={ref.url}
                target="_blank"
                rel="noreferrer"
                onClick={(event) => event.stopPropagation()}
              >
                ↗ source
              </a>
            )}
          </div>
          {expanded && <div className="provenance__well">{ref.excerpt}</div>}
        </div>
      ))}
    </div>
  );
}

function InlineEditor({
  initial,
  onSave,
  onCancel,
}: {
  initial: string;
  onSave: (content: string) => void;
  onCancel: () => void;
}) {
  const [draft, setDraft] = useState(initial);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="composer">
      <textarea
        ref={ref}
        rows={3}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel();
          if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onSave(draft.trim());
        }}
      />
      <div className="composer__row">
        <button
          type="button"
          className="action action--primary"
          onClick={() => onSave(draft.trim())}
          disabled={!draft.trim()}
        >
          Save
        </button>
        <button type="button" className="action" onClick={onCancel}>
          Cancel
        </button>
        <span className="composer__hint">
          The source excerpt below is a snapshot and stays as it was — editing changes the claim,
          never its provenance.
        </span>
      </div>
    </div>
  );
}

export function NodeCard({
  node,
  focused,
  editing,
  writable,
  conflicts,
  relations,
  onFocus,
  onConfirm,
  onReject,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
}: {
  node: Node;
  focused: boolean;
  editing: boolean;
  writable: boolean;
  conflicts: Node[];
  relations: string[];
  onFocus: () => void;
  onConfirm: () => void;
  onReject: () => void;
  onStartEdit: () => void;
  onSaveEdit: (content: string) => void;
  onCancelEdit: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const status = STATUS_MARKS[node.status];
  const reviewed = node.status !== "unconfirmed";

  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [focused]);

  const className = [
    "card",
    focused && "card--focused",
    reviewed && "card--reviewed",
    node.status === "rejected" && "card--rejected",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div
      ref={ref}
      className={className}
      onClick={onFocus}
      aria-current={focused ? "true" : undefined}
    >
      <div className="card__head">
        <span className="tag">{TYPE_TAGS[node.type as NodeType]}</span>
        <span className="card__spacer" />
        <span className="pips" title={node.confidence_score?.toFixed(2) ?? "not scored"}>
          {pipsFor(node)}
        </span>
        <span className={`status status--${node.status}`}>
          <span aria-hidden>{status.mark}</span> {status.label}
        </span>
      </div>

      {editing ? (
        <InlineEditor initial={node.content} onSave={onSaveEdit} onCancel={onCancelEdit} />
      ) : (
        <p className="card__claim">{node.content}</p>
      )}

      {conflicts.map((other) => (
        <div className="conflict" key={other.id}>
          <span className="conflict__mark" aria-hidden>
            ⚠
          </span>
          <span>
            Conflicts with a {TYPE_TAGS[other.type as NodeType]}
            {/* Naming the other side's source is the point: a requirement in a PR
                contradicting a decision in Jira is the thing no single tool could
                have shown you (design baseline §6.6). */}
            {crossesSource(node, other) && <> in {sourceLabel(other)}</>}{" "}
            <span className="conflict__target">— “{other.content}”</span>
          </span>
        </div>
      ))}

      {(focused || !reviewed) && !editing && <Provenance refs={node.source_refs} />}

      {relations.length > 0 && focused && (
        <div className="edges">
          {relations.map((relation) => (
            <span key={relation}>
              <span className="edges__relation">↳</span> {relation}
            </span>
          ))}
        </div>
      )}

      {focused && !editing && writable && (
        <div className="actions">
          <button type="button" className="action action--primary" onClick={onConfirm}>
            ✓ Confirm <span className="action__key">c</span>
          </button>
          <button type="button" className="action" onClick={onStartEdit}>
            ✎ Edit <span className="action__key">e</span>
          </button>
          <button type="button" className="action" onClick={onReject}>
            ✕ Reject <span className="action__key">x</span>
          </button>
        </div>
      )}
    </div>
  );
}
