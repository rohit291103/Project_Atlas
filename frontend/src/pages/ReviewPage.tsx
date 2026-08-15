/* The core screen: one feature, reviewed one claim at a time.
 *
 * The old build rendered the whole feature at once — every claim expanded, every
 * conflict banner drawn twice, provenance shown for anything unreviewed. Since
 * nothing is reviewed when you arrive, the landing state was the densest state
 * the app could produce, which is exactly backwards.
 *
 * Three zones instead (the rail is the fourth, in App):
 *
 *   queue      every claim as one line — this *is* the progress display
 *   stage      the focused claim, alone, at reading size
 *   evidence   its source excerpts, always visible, never folded away
 *
 * Moving provenance out of the card is the load-bearing change: density falls
 * and trust rises at the same time, because the excerpt stops being the thing
 * you have to go looking for.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type { FeatureScopeDetail, Node, NodeType, Role } from "../api";
import {
  SOURCE_BADGES,
  TYPE_TAGS,
  conflictMap,
  conflictPairs,
  crossesSource,
  pipsFor,
  progressOf,
  relationsOf,
  sourceLabel,
  toOrderedNodes,
  toSections,
} from "../review";
import { AddComposer } from "../components/AddComposer";
import { linkProps } from "../router";
import type { Route } from "../router";

type LastAction = { nodeId: string; status: Node["status"]; content: string };

const STATUS_MARKS: Record<Node["status"], { mark: string; label: string }> = {
  unconfirmed: { mark: "○", label: "to review" },
  confirmed: { mark: "✓", label: "confirmed" },
  edited: { mark: "✎", label: "edited" },
  rejected: { mark: "✕", label: "rejected" },
};

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);

export function ReviewPage({
  scopeId,
  productId,
  actor,
  role,
  navigate,
}: {
  scopeId: string;
  productId: string;
  actor: string;
  role: Role;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const writable = canWrite(role);
  const [detail, setDetail] = useState<FeatureScopeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [adding, setAdding] = useState(false);
  const [lastAction, setLastAction] = useState<LastAction | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDetail(await api.featureScope(scopeId));
      setError(null);
    } catch (caught) {
      // Never present stale state as current (flow spec §6).
      setDetail(null);
      setError(caught instanceof ApiError ? caught.message : "Couldn't load this feature.");
    } finally {
      setLoading(false);
    }
  }, [scopeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const sections = useMemo(() => toSections(detail?.nodes ?? []), [detail]);
  const ordered = useMemo(() => toOrderedNodes(sections), [sections]);
  const conflicts = useMemo(
    () => (detail ? conflictMap(detail) : new Map<string, Node[]>()),
    [detail],
  );

  /* Focus is held by node id, not by index. An index silently points at a
   * different claim the moment the list reorders — which it does on every
   * confirm, since unconfirmed claims sort first. */
  const focused = ordered.find((node) => node.id === focusId) ?? ordered[0] ?? null;
  useEffect(() => {
    const first = ordered.find((node) => node.status === "unconfirmed") ?? ordered[0];
    if (!focusId && first) setFocusId(first.id);
  }, [focusId, ordered]);

  const progress = progressOf(ordered);

  /** Advance to the next claim still needing a ruling.
   *
   * Speced in flow spec §5 and never built, which left the old screen with a
   * progress meter that reported but nothing that carried you forward. Wrapping
   * to the start matters: after confirming the last item you should land on
   * whatever you skipped, not on a dead end. */
  const advanceFrom = useCallback(
    (current: Node) => {
      const at = ordered.findIndex((node) => node.id === current.id);
      const rotated = [...ordered.slice(at + 1), ...ordered.slice(0, at)];
      const next = rotated.find((node) => node.status === "unconfirmed");
      if (next) setFocusId(next.id);
    },
    [ordered],
  );

  const act = useCallback(
    async (node: Node, call: () => Promise<Node>, advance: boolean) => {
      const before: LastAction = { nodeId: node.id, status: node.status, content: node.content };
      try {
        const updated = await call();
        setDetail((current) =>
          current
            ? { ...current, nodes: current.nodes.map((n) => (n.id === updated.id ? updated : n)) }
            : current,
        );
        setLastAction(before);
        setNote(null);
        if (advance) advanceFrom(node);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "That didn't save.");
      }
    },
    [advanceFrom],
  );

  const confirm = useCallback(
    (node: Node) => void act(node, () => api.confirm(node.id), true),
    [act],
  );
  const reject = useCallback(
    (node: Node) => void act(node, () => api.reject(node.id), true),
    [act],
  );
  const saveEdit = useCallback(
    (node: Node, content: string) => {
      setEditing(false);
      if (content && content !== node.content) void act(node, () => api.edit(node.id, content), true);
    },
    [act],
  );

  const addNode = useCallback(
    async (type: NodeType, content: string) => {
      setAdding(false);
      if (!content) return;
      try {
        const created = await api.addNode(scopeId, type, content);
        setDetail((current) =>
          current ? { ...current, nodes: [...current.nodes, created] } : current,
        );
        setFocusId(created.id);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "Couldn't add that claim.");
      }
    },
    [scopeId],
  );

  /** Undo, honestly. Replay is last-write-wins, so reversing a ruling is just
   * another event — except there is no `node_unconfirmed` event type, by
   * design: the log moves forward and nothing returns to "never reviewed". */
  const undo = useCallback(() => {
    if (!lastAction) return;
    const node = detail?.nodes.find((n) => n.id === lastAction.nodeId);
    if (!node) return;
    setFocusId(node.id);
    if (lastAction.content !== node.content) {
      void act(node, () => api.edit(node.id, lastAction.content), false);
    } else if (lastAction.status === "confirmed") {
      void act(node, () => api.confirm(node.id), false);
    } else if (lastAction.status === "rejected") {
      void act(node, () => api.reject(node.id), false);
    } else {
      setNote(
        "Nothing to undo back to: a claim can't return to “to review”. The log only moves " +
          "forward — confirm, edit or reject it instead.",
      );
      return;
    }
    setLastAction(null);
  }, [act, detail, lastAction]);

  const step = useCallback(
    (delta: number) => {
      if (!focused) return;
      const at = ordered.findIndex((node) => node.id === focused.id);
      const next = ordered[Math.min(Math.max(at + delta, 0), ordered.length - 1)];
      if (next) setFocusId(next.id);
    },
    [focused, ordered],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (isTyping(event.target) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "a" && writable) {
        event.preventDefault();
        setAdding(true);
        return;
      }
      if (event.key === "u" && writable) {
        event.preventDefault();
        undo();
        return;
      }
      if (!focused) return;
      switch (event.key) {
        case "j":
          event.preventDefault();
          step(1);
          break;
        case "k":
          event.preventDefault();
          step(-1);
          break;
        case "c":
          if (!writable) break;
          event.preventDefault();
          confirm(focused);
          break;
        case "x":
          if (!writable) break;
          event.preventDefault();
          reject(focused);
          break;
        case "e":
          if (!writable) break;
          event.preventDefault();
          setEditing(true);
          break;
        case "o": {
          event.preventDefault();
          const ref = focused.source_refs[0];
          if (ref && ref.source_type !== "human_assertion")
            window.open(ref.url, "_blank", "noreferrer");
          break;
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirm, focused, reject, step, undo, writable]);

  if (loading) {
    return (
      <div className="pad">
        <div className="skeleton" />
        <div className="skeleton" />
        <div className="skeleton" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="pad">
        <div className="notice notice--error">
          <span>{error}</span>
          <button type="button" className="link-button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  const scope = detail?.feature_scope ?? null;
  // Claims caught in a disagreement, and the disagreements themselves. The
  // rail badge counts the latter, so the footer names both rather than
  // showing one number that silently contradicts the other.
  const conflictCount = conflicts.size;
  const conflictPairCount = detail ? conflictPairs(detail).length : 0;
  const percent = progress.total ? (progress.reviewed / progress.total) * 100 : 0;

  return (
    <div className="zones">
      <section className="zone queue" aria-label="Claims">
        <div className="zone__head">
          <span className="zone__head-title">{scope?.title ?? "Untitled feature"}</span>
        </div>

        <div className="queue__scroll">
          {ordered.length === 0 && (
            <div className="notice" style={{ margin: "var(--space-3)" }}>
              Nothing extracted for this feature yet.
              {writable && (
                <>
                  {" "}
                  Press <kbd>a</kbd> to add a claim yourself.
                </>
              )}
            </div>
          )}

          {sections.map((section) => {
            const left = section.nodes.filter((node) => node.status === "unconfirmed").length;
            return (
              <div key={section.key}>
                <div className="qgroup">
                  {section.label}
                  <span className="qgroup__n">{left ? `${left} left` : "done"}</span>
                </div>
                {section.nodes.map((node) => (
                  <QueueItem
                    key={node.id}
                    node={node}
                    focused={focused?.id === node.id}
                    conflicted={conflicts.has(node.id)}
                    onSelect={() => {
                      setFocusId(node.id);
                      setEditing(false);
                    }}
                  />
                ))}
              </div>
            );
          })}
        </div>

        <div className="queue__foot">
          <span className="meter__track">
            <span className="meter__fill" style={{ width: `${percent}%` }} />
          </span>
          <div className="queue__foot-line">
            <span>
              {progress.reviewed} of {progress.total} reviewed
            </span>
            {conflictCount > 0 && (
              <a
                className="queue__conflicts"
                {...linkProps({ name: "conflicts", productId }, navigate)}
              >
                {/* Both figures, because they are different things and showing
                    only the claim count made this disagree with the badge in
                    the rail, which counts disagreements. */}
                ⚠ {conflictCount} {conflictCount === 1 ? "claim" : "claims"} in {conflictPairCount}{" "}
                {conflictPairCount === 1 ? "conflict" : "conflicts"}
              </a>
            )}
          </div>
        </div>
      </section>

      <section className="zone stage" aria-label="The claim">
        <div className="zone__head">The claim</div>
        <div className="stage__body">
          {error && (
            <div className="notice notice--error" style={{ marginBottom: "var(--space-4)" }}>
              <span>{error}</span>
              <button type="button" className="link-button" onClick={() => void load()}>
                Reload
              </button>
            </div>
          )}
          {note && (
            <div className="notice" style={{ marginBottom: "var(--space-4)" }}>
              {note}
            </div>
          )}

          {adding && writable && (
            <AddComposer
              actor={actor}
              onAdd={(type, text) => void addNode(type, text)}
              onCancel={() => setAdding(false)}
            />
          )}

          {!focused && !adding && (
            <p className="stage__empty">
              Nothing to review here yet. Ingest a source for this feature, or add a claim yourself.
            </p>
          )}

          {focused && (
            <Stage
              node={focused}
              editing={editing}
              writable={writable}
              conflicts={conflicts.get(focused.id) ?? []}
              relations={relationsOf(focused, detail?.edges ?? [], detail?.nodes ?? [])}
              conflictsHref={linkProps({ name: "conflicts", productId }, navigate)}
              onConfirm={() => confirm(focused)}
              onReject={() => reject(focused)}
              onStartEdit={() => setEditing(true)}
              onSaveEdit={(content) => saveEdit(focused, content)}
              onCancelEdit={() => setEditing(false)}
            />
          )}
        </div>

        {/* Only the keys this role can actually use. Advertising `c confirm` to
            a viewer teaches a shortcut that silently does nothing. */}
        <footer className="hints">
          <span>
            <kbd>j</kbd>/<kbd>k</kbd> move
          </span>
          <span>
            <kbd>o</kbd> open source
          </span>
          {writable ? (
            <>
              <span>
                <kbd>c</kbd> confirm
              </span>
              <span>
                <kbd>e</kbd> edit
              </span>
              <span>
                <kbd>x</kbd> reject
              </span>
              <span>
                <kbd>a</kbd> add
              </span>
              <span>
                <kbd>u</kbd> undo
              </span>
            </>
          ) : (
            <span>read-only — your role is {role}</span>
          )}
        </footer>
      </section>

      <aside className="zone ev" aria-label="Where it came from">
        <div className="zone__head">Where it came from</div>
        <div className="ev__body">
          {focused ? <Evidence node={focused} /> : null}
        </div>
      </aside>
    </div>
  );
}

function QueueItem({
  node,
  focused,
  conflicted,
  onSelect,
}: {
  node: Node;
  focused: boolean;
  conflicted: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (focused) ref.current?.scrollIntoView({ block: "nearest" });
  }, [focused]);

  const className = [
    "qitem",
    `qitem--${node.status}`,
    focused && "qitem--focused",
    node.status !== "unconfirmed" && "qitem--reviewed",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      ref={ref}
      type="button"
      className={className}
      aria-current={focused ? "true" : undefined}
      onClick={onSelect}
    >
      <span className="qitem__mark" aria-hidden>
        {STATUS_MARKS[node.status].mark}
      </span>
      <span className="qitem__text">
        {node.content}
        {conflicted && (
          <span className="qitem__flag" aria-label="in conflict">
            {" "}
            ⚠
          </span>
        )}
      </span>
    </button>
  );
}

function Stage({
  node,
  editing,
  writable,
  conflicts,
  relations,
  conflictsHref,
  onConfirm,
  onReject,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
}: {
  node: Node;
  editing: boolean;
  writable: boolean;
  conflicts: Node[];
  relations: string[];
  conflictsHref: { href: string; onClick: (event: React.MouseEvent) => void };
  onConfirm: () => void;
  onReject: () => void;
  onStartEdit: () => void;
  onSaveEdit: (content: string) => void;
  onCancelEdit: () => void;
}) {
  const status = STATUS_MARKS[node.status];
  return (
    <>
      <div className="stage__meta">
        <span className="tag">{TYPE_TAGS[node.type as NodeType]}</span>
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
        <p className="claim">{node.content}</p>
      )}

      {/* A conflict never disappears — confirming one side does not resolve it
          (TRD §5.2), and the pair is ruled on together on the conflicts screen. */}
      {conflicts.map((other) => (
        <div className="flagbox" key={other.id}>
          <span className="flagbox__mark" aria-hidden>
            ⚠
          </span>
          <span>
            Conflicts with a {TYPE_TAGS[other.type as NodeType].toLowerCase()}
            {crossesSource(node, other) && <> in {sourceLabel(other)}</>}
            <span className="flagbox__quote"> — “{other.content}”</span>{" "}
            <a {...conflictsHref}>See both sides</a>
          </span>
        </div>
      ))}

      {relations.length > 0 && (
        <div className="edges">
          {relations.map((relation) => (
            <span key={relation}>
              <span className="edges__relation">↳</span> {relation}
            </span>
          ))}
        </div>
      )}

      {!editing && writable && (
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
    </>
  );
}

/** Provenance, in its own column and never folded away.
 *
 * In the old build this was a disclosure inside the card, so the trust moment —
 * the literal words the claim came from — was the one thing you had to go
 * looking for. Here it is simply always on screen for whatever you are reading. */
function Evidence({ node }: { node: Node }) {
  return (
    <>
      {node.source_refs.map((ref) => (
        <div className="doc" key={ref.id}>
          <div className="doc__head">
            <span className="badge">{SOURCE_BADGES[ref.source_type]}</span>
            <span className="doc__key">{ref.external_id}</span>
            {ref.source_type === "human_assertion" ? (
              <span className="doc__open">asserted here</span>
            ) : (
              <a className="doc__open" href={ref.url} target="_blank" rel="noreferrer">
                ↗ open
              </a>
            )}
          </div>
          <p className="doc__excerpt">“{ref.excerpt}”</p>
        </div>
      ))}
      <p className="ev__note">
        Every excerpt is literal text from the source, never a paraphrase — that is what makes a
        claim checkable rather than merely plausible.
      </p>
    </>
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
          The source excerpt stays as it was — editing changes the claim, never its provenance.
        </span>
      </div>
    </div>
  );
}
