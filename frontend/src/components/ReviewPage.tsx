/* The core screen: one feature scope as a readable document, with a keyboard
 * review mode layered on top (flow spec §3–§5).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type { FeatureScopeDetail, Node, NodeType, Role } from "../api";
import {
  SOURCE_BADGES,
  TYPE_LABELS,
  conflictMap,
  progressOf,
  relationsOf,
  toOrderedNodes,
  toSections,
} from "../review";
import { AddComposer } from "./AddComposer";
import { NodeCard } from "./NodeCard";

type LastAction = { nodeId: string; status: Node["status"]; content: string };

const isTyping = (target: EventTarget | null) =>
  target instanceof HTMLElement && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);

export function ReviewPage({
  scopeId,
  actor,
  role,
}: {
  scopeId: string;
  actor: string;
  role: Role;
}) {
  const writable = canWrite(role);
  const [detail, setDetail] = useState<FeatureScopeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [focusIndex, setFocusIndex] = useState(0);
  const [editingId, setEditingId] = useState<string | null>(null);
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
    setFocusIndex(0);
    setEditingId(null);
    setAdding(false);
    void load();
  }, [load]);

  const sections = useMemo(() => toSections(detail?.nodes ?? []), [detail]);
  const ordered = useMemo(() => toOrderedNodes(sections), [sections]);
  const conflicts = useMemo(
    () => (detail ? conflictMap(detail) : new Map<string, Node[]>()),
    [detail],
  );
  const progress = progressOf(ordered);
  const focused = ordered[Math.min(focusIndex, ordered.length - 1)];

  /** Every write goes through here: call the API, swap the returned node into
   * place, and remember what it looked like so `u` has something to restore. */
  const act = useCallback(
    async (node: Node, call: () => Promise<Node>) => {
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
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : "That didn't save.");
      }
    },
    [],
  );

  const confirm = useCallback(
    (node: Node) => void act(node, () => api.confirm(node.id)),
    [act],
  );
  const reject = useCallback((node: Node) => void act(node, () => api.reject(node.id)), [act]);
  const saveEdit = useCallback(
    (node: Node, content: string) => {
      setEditingId(null);
      if (content && content !== node.content) void act(node, () => api.edit(node.id, content));
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
    if (lastAction.content !== node.content) {
      void act(node, () => api.edit(node.id, lastAction.content));
    } else if (lastAction.status === "confirmed") {
      void act(node, () => api.confirm(node.id));
    } else if (lastAction.status === "rejected") {
      void act(node, () => api.reject(node.id));
    } else {
      setNote(
        "Nothing to undo back to: a node can't return to “to review”. The log only moves " +
          "forward — confirm, edit or reject it instead.",
      );
      return;
    }
    setLastAction(null);
  }, [act, detail, lastAction]);

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
          setFocusIndex((index) => Math.min(index + 1, ordered.length - 1));
          break;
        case "k":
          event.preventDefault();
          setFocusIndex((index) => Math.max(index - 1, 0));
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
          setEditingId(focused.id);
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
  }, [confirm, focused, ordered.length, reject, undo, writable]);

  if (loading) {
    return (
      <main className="main">
        <div className="skeleton" />
        <div className="skeleton" />
        <div className="skeleton" />
      </main>
    );
  }

  if (error && !detail) {
    return (
      <main className="main">
        <div className="notice notice--error">
          <span>{error}</span>
          <button type="button" className="link-button" onClick={() => void load()}>
            Retry
          </button>
        </div>
      </main>
    );
  }

  const scope = detail?.feature_scope ?? null;
  const conflictCount = new Set(conflicts.keys()).size;
  const percent = progress.total ? (progress.reviewed / progress.total) * 100 : 0;

  return (
    <main className="main">
      <header className="scope-header">
        <h1 className="scope-header__title">{scope?.title ?? "Untitled feature scope"}</h1>
        <div className="scope-header__meta">
          <span className="meter">
            <span className="meter__track">
              <span className="meter__fill" style={{ width: `${percent}%` }} />
            </span>
            {progress.reviewed === progress.total && progress.total > 0
              ? `All ${progress.total} reviewed`
              : `${progress.reviewed} of ${progress.total} reviewed`}
          </span>
          {conflictCount > 0 && (
            <span className="meter__conflicts">
              ⚠ {conflictCount} conflict{conflictCount === 1 ? "" : "s"}
            </span>
          )}
        </div>
        {scope && scope.runs.length > 0 && (
          <div className="assembled">
            Assembled from
            {scope.runs.map((run) => (
              <span className="badge" key={run.url} title={run.url}>
                {SOURCE_BADGES[run.source_type]} {run.external_id}
              </span>
            ))}
          </div>
        )}
      </header>

      {error && (
        <div className="notice notice--error" style={{ marginBottom: "var(--space-4)" }}>
          <span>{error}</span>
          <button type="button" className="link-button" onClick={() => void load()}>
            Reload
          </button>
        </div>
      )}
      {note && <div className="notice">{note}</div>}

      {adding && writable && (
        <AddComposer actor={actor} onAdd={(type, text) => void addNode(type, text)} onCancel={() => setAdding(false)} />
      )}

      {ordered.length === 0 && !adding && (
        <div className="notice">
          No elements were extracted for this feature yet. Re-run ingestion from the CLI
          (<code>atlas ingest</code>){writable && (
            <>
              , or press <kbd>a</kbd> to add a claim yourself
            </>
          )}.
        </div>
      )}

      {sections.map((section) => {
        const toReview = section.nodes.filter((node) => node.status === "unconfirmed").length;
        return (
          <section className="section" key={section.type}>
            <h2 className="section__header">
              {TYPE_LABELS[section.type]}
              <span className="section__count">
                {section.nodes.length} · {toReview} to review
              </span>
            </h2>
            <div className="section__list">
              {section.nodes.map((node) => (
                <NodeCard
                  key={node.id}
                  node={node}
                  focused={focused?.id === node.id}
                  editing={editingId === node.id}
                  writable={writable}
                  conflicts={conflicts.get(node.id) ?? []}
                  relations={relationsOf(node, detail?.edges ?? [], detail?.nodes ?? [])}
                  onFocus={() => setFocusIndex(ordered.findIndex((n) => n.id === node.id))}
                  onConfirm={() => confirm(node)}
                  onReject={() => reject(node)}
                  onStartEdit={() => setEditingId(node.id)}
                  onSaveEdit={(content) => saveEdit(node, content)}
                  onCancelEdit={() => setEditingId(null)}
                />
              ))}
            </div>
          </section>
        );
      })}

      {/* Only the keys this role can actually use. Advertising `c confirm` to a
          viewer teaches a shortcut that silently does nothing. */}
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
    </main>
  );
}
