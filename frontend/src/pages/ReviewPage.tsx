/* The core screen: one feature, reviewed one claim at a time.
 *
 * ## What this is the second rewrite of
 *
 * The first build rendered the whole feature at once — every claim expanded,
 * every conflict banner drawn twice, provenance shown for anything unreviewed.
 * Since nothing is reviewed when you arrive, the landing state was the densest
 * state the app could produce, which is exactly backwards.
 *
 * The fix for that was three fixed vertical panes — queue | stage | evidence —
 * and it fixed the density while introducing three new problems, all of them
 * visible in a screenshot:
 *
 *   1. **Three panes, three headers, three different typographic treatments.**
 *      The queue's header was sans 13/550 in full-strength ink; the other two
 *      were 11px mono all-caps in the faintest grey on the palette. Three
 *      headings sitting at the same y-position, at the same level of the
 *      hierarchy, styled as though they belonged to different applications.
 *   2. **A tall thin claim in a wide empty column.** The claim was capped at
 *      36ch inside a ~950px pane, with the action row pinned to the bottom of
 *      the viewport. Between the two sat several hundred pixels of nothing, and
 *      the eye had to cross all of it to get from the sentence to the buttons.
 *   3. **Hard-coded widths.** The queue truncated every claim to two clipped
 *      lines at exactly 300px whether the display was 1280px or 3440px wide,
 *      and nobody could change it.
 *
 * ## The shape now
 *
 * One title bar across the top, then **two** panes: the queue, and a workspace.
 *
 *   bar        the feature — its name, where it was assembled from, how far in
 *              you are, and what is contested. The screen's only sans heading.
 *   queue      every claim as one line — resizable, collapsible
 *   workspace  a card stack that *reflows*: the claim and its evidence sit side
 *              by side when there is room for both, and stack when there isn't
 *
 * The workspace is the load-bearing change and the reason this isn't just the
 * old layout with nicer borders. Evidence stops being a fixed 360px column that
 * ran three-quarters empty and becomes a card next to the claim it belongs to —
 * so the two things a reviewer is comparing are finally adjacent, which is the
 * entire trust argument of the product. It is driven by a **container query** on
 * the pane rather than a viewport media query, because the pane's width is now
 * something the reviewer sets: drag the queue wider and the workspace stacks on
 * its own.
 *
 * Provenance is still never folded away (flow spec §4) — it is a card that is
 * always rendered, not a disclosure. And every card in the stack wears the same
 * head treatment, which is the structural version of the fix for (1): there is
 * one sans heading on the screen and one label style under it, so nothing has to
 * be styled consistently by hand.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type { FeatureScopeDetail, Node, NodeType, Role, SourceRef } from "../api";
import {
  QUEUE_VIEWS,
  SOURCE_BADGES,
  SOURCE_LABELS,
  TYPE_TAGS,
  conflictMap,
  conflictPairs,
  crossesSource,
  inView,
  neighboursOf,
  pipsFor,
  progressOf,
  sourceLabel,
  toOrderedNodes,
  toSections,
} from "../review";
import type { Neighbour, QueueView } from "../review";
import { AddComposer } from "../components/AddComposer";
import { IconExternal, IconPanel } from "../components/icons";
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

/* The queue's width is the reviewer's to set.
 *
 * It was `--queue-width: 300px`, a constant, which is a guess about a claim's
 * length made once for every display the product will ever run on. Claims are
 * whole sentences; some features want a 480px queue to read them at a glance and
 * some want the column gone entirely. Persisted, because a width you have to
 * re-drag on every navigation is a worse default than the constant was.
 */
const QUEUE_MIN = 220;
const QUEUE_MAX = 620;
const QUEUE_DEFAULT = 320;
const QUEUE_KEY = "atlas.review.queue-width";
const COLLAPSE_KEY = "atlas.review.queue-collapsed";

const clampQueue = (px: number) => Math.max(QUEUE_MIN, Math.min(QUEUE_MAX, Math.round(px)));

function storedNumber(key: string, fallback: number): number {
  try {
    const raw = Number(window.localStorage.getItem(key));
    return Number.isFinite(raw) && raw > 0 ? clampQueue(raw) : fallback;
  } catch {
    return fallback;
  }
}

function store(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* a browser with storage disabled still gets a working, non-persisted pane */
  }
}

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
  /* Triage is the default posture, not reading: arriving at a feature that is
     mostly reviewed should show what is left, not bury it under what is done. */
  const [view, setView] = useState<QueueView>("ruling");

  const [queueWidth, setQueueWidth] = useState(() => storedNumber(QUEUE_KEY, QUEUE_DEFAULT));
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const widthRef = useRef(queueWidth);

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

  const conflicts = useMemo(
    () => (detail ? conflictMap(detail) : new Map<string, Node[]>()),
    [detail],
  );
  const allNodes = detail?.nodes ?? [];
  const sections = useMemo(
    () =>
      toSections(
        allNodes.filter((node) => inView(node, view, conflicts)),
        conflicts,
      ),
    [allNodes, view, conflicts],
  );
  const ordered = useMemo(() => toOrderedNodes(sections), [sections]);
  /* What the current view is hiding, so the queue can say so rather than
     leaving a reader to wonder where twenty-five claims went. */
  const hidden = allNodes.length - ordered.length;

  /* Focus is held by node id, not by index. An index silently points at a
   * different claim the moment the list reorders — which it does on every
   * confirm, since unconfirmed claims sort first. */
  const focused = ordered.find((node) => node.id === focusId) ?? ordered[0] ?? null;
  useEffect(() => {
    const first = ordered.find((node) => node.status === "unconfirmed") ?? ordered[0];
    if (!focusId && first) setFocusId(first.id);
  }, [focusId, ordered]);

  /* Progress is a fact about the *feature*, not about the current view. Basing
     it on `ordered` would have made the meter read "0 of 2" the moment a
     reader switched to Needs ruling — a filter silently rewriting the number
     the rail is also showing. */
  const progress = progressOf(allNodes);

  /** Which tools this feature was assembled out of.
   *
   * The design baseline calls for an "assembled from" strip on the feature
   * header (§6.6a) and it was never built, so the one screen whose whole pitch
   * is cross-source assembly never said what it had been assembled from. Read
   * off the provenance already in hand, deduplicated by badge so a feature
   * built from four PRs and two issues reads `gh`, not `gh gh gh gh gh gh`. */
  const assembledFrom = useMemo(() => {
    const seen = new Map<string, string>();
    for (const node of allNodes)
      for (const ref of node.source_refs)
        seen.set(SOURCE_BADGES[ref.source_type], SOURCE_LABELS[ref.source_type]);
    return [...seen].map(([badge, label]) => ({ badge, label }));
  }, [allNodes]);

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
      if (content && content !== node.content)
        void act(node, () => api.edit(node.id, content), true);
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

  const toggleQueue = useCallback(() => {
    setCollapsed((current) => {
      store(COLLAPSE_KEY, current ? "0" : "1");
      return !current;
    });
  }, []);

  /* Drag to resize. Listeners go on the window rather than the handle so the
     drag survives the pointer outracing the element — the classic resizer bug
     where letting go outside the 6px strip leaves the pane stuck to the mouse. */
  const startResize = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const body = event.currentTarget.parentElement;
    if (!body) return;
    event.preventDefault();
    const left = body.getBoundingClientRect().left;
    document.body.classList.add("is-resizing");
    const move = (moved: PointerEvent) => {
      widthRef.current = clampQueue(moved.clientX - left);
      setQueueWidth(widthRef.current);
    };
    const stop = () => {
      document.body.classList.remove("is-resizing");
      store(QUEUE_KEY, String(widthRef.current));
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      window.removeEventListener("pointercancel", stop);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
    window.addEventListener("pointercancel", stop);
  }, []);

  /* The same resize from the keyboard, because a mouse-only control on a
     keyboard-first screen (design baseline §1.4, §7) is a control half the
     product's own users can't reach. */
  const resizeByKey = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const delta =
      event.key === "ArrowLeft" ? -24 : event.key === "ArrowRight" ? 24 : 0;
    if (!delta) return;
    event.preventDefault();
    widthRef.current = clampQueue(widthRef.current + delta);
    setQueueWidth(widthRef.current);
    store(QUEUE_KEY, String(widthRef.current));
  }, []);

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
      // Hide the queue and read the claim on its own — the reviewer's version of
      // full screen, on the pane that is otherwise always in the way of it.
      if (event.key === "[") {
        event.preventDefault();
        toggleQueue();
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
  }, [confirm, focused, reject, step, toggleQueue, undo, writable]);

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
  // rail badge counts the latter, so the bar names both rather than showing one
  // number that silently contradicts the other.
  const conflictCount = conflicts.size;
  const conflictPairCount = detail ? conflictPairs(detail).length : 0;
  const percent = progress.total ? (progress.reviewed / progress.total) * 100 : 0;

  const jumpTo = (id: string) => {
    // Jumping to a neighbour that the current view hides would look like a dead
    // click, so widen the view rather than fail quietly.
    const target = allNodes.find((node) => node.id === id);
    if (target && !inView(target, view, conflicts)) setView("all");
    setFocusId(id);
    setEditing(false);
  };

  return (
    <div className="rv">
      {/* The screen's one heading, and the only sans heading on it. Everything
          below is a card wearing the same label treatment, which is what stops
          three panes from looking like three applications. */}
      <header className="rv__bar">
        <button
          type="button"
          className={`rv__collapse${collapsed ? " is-collapsed" : ""}`}
          onClick={toggleQueue}
          aria-pressed={!collapsed}
          title={collapsed ? "Show the claim list ([)" : "Hide the claim list ([)"}
          aria-label={collapsed ? "Show the claim list" : "Hide the claim list"}
        >
          <IconPanel />
        </button>

        <div className="rv__id">
          <h1 className="rv__title" title={scope?.title ?? undefined}>
            {scope?.title ?? "Untitled feature"}
          </h1>
          {/* Speced in the design baseline §6.6a and never built: the screen
              whose argument is cross-source assembly never said what it was
              assembled from. */}
          {assembledFrom.length > 0 && (
            <span className="rv__from">
              <span className="rv__from-label">assembled from</span>
              {assembledFrom.map(({ badge, label }) => (
                <span className="badge" key={badge} title={label}>
                  {badge}
                </span>
              ))}
            </span>
          )}
        </div>

        {/* The 20-minute exit criterion, made visible (design baseline §6.9).
            It sits in the bar rather than in the queue's foot because it is a
            fact about the feature, not about the list's current filter. */}
        {progress.total > 0 && (
          <div className="rv__prog" title={`${progress.reviewed} of ${progress.total} reviewed`}>
            <span className="rv__prog-n">
              <b>{progress.reviewed}</b>
              <span className="rv__prog-of">/{progress.total}</span> reviewed
            </span>
            <span className="meter__track">
              <span className="meter__fill" style={{ width: `${percent}%` }} />
            </span>
          </div>
        )}

        {conflictCount > 0 && (
          <a
            className="queue__conflicts"
            {...linkProps({ name: "conflicts", productId }, navigate)}
          >
            {/* Both figures, because they are different things and showing only
                the claim count made this disagree with the badge in the rail,
                which counts disagreements. */}
            <span aria-hidden>⚠</span> {conflictCount} {conflictCount === 1 ? "claim" : "claims"} in{" "}
            {conflictPairCount} {conflictPairCount === 1 ? "conflict" : "conflicts"}
          </a>
        )}
      </header>

      <div
        className={`rv__body${collapsed ? " is-collapsed" : ""}`}
        style={{ "--queue-w": `${queueWidth}px` } as React.CSSProperties}
      >
        {!collapsed && (
          <section className="rv__queue" aria-label="Claims">
            {/* Three views, not a filter menu. A menu hides its own state; a
                segmented control shows at a glance which slice of the feature
                you are looking at, which matters when the slice is "not
                everything" — and "Needs ruling" is the default. */}
            <div className="qviews" role="tablist" aria-label="Which claims to show">
              {QUEUE_VIEWS.map(({ key, label }) => {
                const n =
                  key === "all"
                    ? allNodes.length
                    : allNodes.filter((node) => inView(node, key, conflicts)).length;
                return (
                  <button
                    key={key}
                    type="button"
                    role="tab"
                    aria-selected={view === key}
                    className={`qview${view === key ? " is-active" : ""}`}
                    onClick={() => setView(key)}
                  >
                    {label}
                    <span className="qview__n">{n}</span>
                  </button>
                );
              })}
            </div>

            <div className="queue__scroll">
              {ordered.length === 0 && allNodes.length === 0 && (
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
                /* A confirmed claim sitting in an unresolved conflict is not
                   done — confirming one side settles nothing (TRD §5.2).
                   Counting only `unconfirmed` made a group of contested claims
                   label itself DONE while displaying them. */
                const left = section.nodes.filter(
                  (node) => node.status === "unconfirmed" || conflicts.has(node.id),
                ).length;
                return (
                  <div className="qsection" key={section.key}>
                    <div className="qgroup">
                      <span className="qgroup__label">{section.label}</span>
                      {/* Was rendered as bare text directly after the label,
                          which ran the two together — "HOW IT WAS DECIDED DONE"
                          reads as a typo, not as a status. */}
                      <span className={`qgroup__n${left ? " is-open" : ""}`}>
                        {left ? `${left} left` : "done"}
                      </span>
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

              {hidden > 0 && (
                <button type="button" className="qdone" onClick={() => setView("all")}>
                  <span aria-hidden>▸</span> {hidden} settled{" "}
                  {hidden === 1 ? "claim" : "claims"} hidden
                  <span className="qdone__show">show all</span>
                </button>
              )}

              {ordered.length === 0 && allNodes.length > 0 && (
                <p className="qempty">
                  {view === "conflicts"
                    ? "No unresolved conflicts in this feature."
                    : "Nothing here needs a ruling. Every claim has been confirmed, edited or rejected."}
                </p>
              )}
            </div>
          </section>
        )}

        {/* A real separator, not a decorative border: `aria-valuenow` and the
            arrow keys make the width reachable without a pointer. */}
        {!collapsed && (
          <div
            className="rv__grip"
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the claim list"
            aria-valuenow={queueWidth}
            aria-valuemin={QUEUE_MIN}
            aria-valuemax={QUEUE_MAX}
            tabIndex={0}
            onPointerDown={startResize}
            onKeyDown={resizeByKey}
            onDoubleClick={() => {
              widthRef.current = QUEUE_DEFAULT;
              setQueueWidth(QUEUE_DEFAULT);
              store(QUEUE_KEY, String(QUEUE_DEFAULT));
            }}
          />
        )}

        <div className="rv__work">
          <div className="rv__scroll">
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
                Nothing to review here yet. Ingest a source for this feature, or add a claim
                yourself.
              </p>
            )}

            {focused && (
              /* The reflow. Claim and evidence are siblings in one grid, not two
                 fixed panes, so on a wide workspace they sit abreast — the
                 comparison the product is *for* — and on a narrow one they stack
                 rather than both being squeezed into unreadable columns. Driven
                 by a container query on the pane, because the pane's width is
                 something the reviewer sets by dragging. */
              <div className="rv__stack">
                <div className="rv__col">
                  <ClaimCard
                    node={focused}
                    editing={editing}
                    writable={writable}
                    onConfirm={() => confirm(focused)}
                    onReject={() => reject(focused)}
                    onStartEdit={() => setEditing(true)}
                    onSaveEdit={(content) => saveEdit(focused, content)}
                    onCancelEdit={() => setEditing(false)}
                  />

                  {(conflicts.get(focused.id) ?? []).length > 0 && (
                    <Versus
                      node={focused}
                      others={conflicts.get(focused.id) ?? []}
                      onFocusNode={jumpTo}
                      conflictsHref={linkProps({ name: "conflicts", productId }, navigate)}
                    />
                  )}

                  {/* Edges sit with the claim rather than with the receipts:
                      what this claim rests on is a fact *about the claim*, where
                      the excerpt is the evidence *behind* it. Left column is the
                      claim and its neighbourhood; right column is the paper
                      trail. It also stops the left column from being one short
                      card beside a tall stack on the features that have no
                      disagreement to show. */}
                  <Related
                    neighbours={neighboursOf(focused, detail?.edges ?? [], allNodes)}
                    onFocusNode={jumpTo}
                  />
                </div>

                <div className="rv__col">
                  <Evidence node={focused} />
                  <Siblings siblings={siblingsOf(focused, allNodes)} onFocusNode={jumpTo} />
                </div>
              </div>
            )}
          </div>

          {/* Only the keys this role can actually use. Advertising `c confirm`
              to a viewer teaches a shortcut that silently does nothing. */}
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
            <span className="hints__end">
              {/* Says what the key will do, not what it did last time. A hint
                  reading "hide list" beside an already-hidden list is a hint
                  that has stopped describing the screen it is on. */}
              <kbd>[</kbd> {collapsed ? "show list" : "hide list"}
            </span>
          </footer>
        </div>
      </div>
    </div>
  );
}

/** One card head, used by all four cards.
 *
 * The whole of the fix for the mismatched pane headers: a heading is not
 * something each component styles for itself, it is something it asks for. Every
 * label on this screen therefore renders at one size, one weight, one colour and
 * one letter-spacing, because there is exactly one place that decides. */
function CardHead({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children?: React.ReactNode;
}) {
  return (
    <div className="card__head">
      <span className="card__title">{title}</span>
      {count !== undefined && <span className="card__n">{count}</span>}
      {children && <span className="card__head-end">{children}</span>}
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

/** The claim, at reading size, with the three rulings directly under it.
 *
 * The actions used to be a sticky bar pinned to the bottom of the pane, with a
 * gradient fading whatever it covered. On a tall display that put several
 * hundred pixels of empty column between the sentence and the buttons that rule
 * on it — a hole in the middle of the screen's one job. They are part of the
 * card now, so they sit where the reading ends however long the claim is.
 */
function ClaimCard({
  node,
  editing,
  writable,
  onConfirm,
  onReject,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
}: {
  node: Node;
  editing: boolean;
  writable: boolean;
  onConfirm: () => void;
  onReject: () => void;
  onStartEdit: () => void;
  onSaveEdit: (content: string) => void;
  onCancelEdit: () => void;
}) {
  const status = STATUS_MARKS[node.status];
  return (
    <article className="card card--claim">
      <CardHead title="The claim">
        <span className="tag">{TYPE_TAGS[node.type as NodeType]}</span>
        <span className="pips" title={node.confidence_score?.toFixed(2) ?? "not scored"}>
          {pipsFor(node)}
        </span>
        <span className={`status status--${node.status}`}>
          <span aria-hidden>{status.mark}</span> {status.label}
        </span>
      </CardHead>

      <div className="card__body">
        {editing ? (
          <InlineEditor initial={node.content} onSave={onSaveEdit} onCancel={onCancelEdit} />
        ) : (
          <p className="claim">{node.content}</p>
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
      </div>
    </article>
  );
}

/* A disagreement, as two sides.
 *
 * A conflict never disappears — confirming one side does not resolve it (TRD
 * §5.2), and the pair is ruled on together on the conflicts screen. One block,
 * not one per edge: rendering a card per conflicting edge repeated *this* claim
 * once per disagreement, directly under the copy of it already set at reading
 * size above. A claim in several disagreements is one claim against several
 * others, and that is the shape drawn here.
 */
function Versus({
  node,
  others,
  onFocusNode,
  conflictsHref,
}: {
  node: Node;
  others: Node[];
  onFocusNode: (id: string) => void;
  conflictsHref: { href: string; onClick: (event: React.MouseEvent) => void };
}) {
  return (
    <div className="versus">
      <div className="versus__head">
        <span className="versus__mark" aria-hidden>
          ⚠
        </span>
        {others.length === 1 ? (
          crossesSource(node, others[0]!) ? (
            <>
              {sourceLabel(node)} and {sourceLabel(others[0]!)} disagree
              <span className="versus__why">— no single tool could have told you</span>
            </>
          ) : (
            <>Two claims in {sourceLabel(node)} disagree</>
          )
        ) : (
          <>
            {others.length} claims contradict this one
            {others.some((other) => crossesSource(node, other)) && (
              <span className="versus__why">— across tools</span>
            )}
          </>
        )}
      </div>

      <div className="versus__pair">
        <article className="versus__side is-this">
          <header>
            <span className="tag">{TYPE_TAGS[node.type as NodeType]}</span>
            <span className="versus__from">{sourceLabel(node)}</span>
            <span className="versus__here">on screen</span>
          </header>
          <p>{node.content}</p>
        </article>
        <span className="versus__vs" aria-hidden>
          vs
        </span>
        <div className="versus__others">
          {others.map((other) => (
            <article className="versus__side" key={other.id}>
              <header>
                <span className="tag">{TYPE_TAGS[other.type as NodeType]}</span>
                <span className="versus__from">{sourceLabel(other)}</span>
              </header>
              <p>{other.content}</p>
              <button type="button" className="link-button" onClick={() => onFocusNode(other.id)}>
                Read this one
              </button>
            </article>
          ))}
        </div>
      </div>

      <a className="versus__both" {...conflictsHref}>
        Rule on {others.length === 1 ? "both sides" : "these"} →
      </a>
    </div>
  );
}

/** Provenance, never folded away.
 *
 * It was a fixed 360px column running roughly three-quarters empty, which is
 * how the signature component of the product ended up looking like a margin
 * note. As a card it sits *beside the claim* whenever the workspace is wide
 * enough — the claim and the words it came from, adjacent, which is the
 * comparison the whole trust model rests on. It is still never a disclosure:
 * always rendered, never behind a toggle. */
function Evidence({ node }: { node: Node }) {
  return (
    <article className="card card--paper ev">
      <CardHead
        title="Where it came from"
        count={node.source_refs.length > 1 ? node.source_refs.length : undefined}
      />
      <div className="card__body ev__body">
        {node.source_refs.map((ref) => (
          <Doc key={ref.id} ref_={ref} />
        ))}
        <p className="ev__note">
          Every excerpt is literal text from the source, never a paraphrase — that is what makes a
          claim checkable rather than merely plausible.
        </p>
      </div>
    </article>
  );
}

function Doc({ ref_ }: { ref_: SourceRef }) {
  return (
    <div className="doc">
      <div className="doc__head">
        <span className="badge">{SOURCE_BADGES[ref_.source_type]}</span>
        <span className="doc__key" title={ref_.external_id}>
          {ref_.external_id}
        </span>
        {ref_.source_type === "human_assertion" ? (
          <span className="doc__open">asserted here</span>
        ) : (
          <a className="doc__open" href={ref_.url} target="_blank" rel="noreferrer">
            <IconExternal />
            open
          </a>
        )}
      </div>
      <p className="doc__excerpt">“{ref_.excerpt}”</p>
    </div>
  );
}

/** Local edges, as a short clickable list.
 *
 * Deliberately not a graph canvas: that is an explicit non-goal in three
 * documents, on the grounds that a node-link view reintroduces exactly the
 * overwhelm this screen exists to remove. What a reader actually needs is what
 * *this* claim touches — and to be able to go there. */
function Related({
  neighbours,
  onFocusNode,
}: {
  neighbours: Neighbour[];
  onFocusNode: (id: string) => void;
}) {
  if (neighbours.length === 0) return null;
  return (
    <article className="card">
      <CardHead title="Related" count={neighbours.length} />
      <div className="card__body edges">
        <ul>
          {neighbours.map(({ node: other, relation }) => (
            <li key={`${relation}-${other.id}`}>
              <button type="button" className="edge" onClick={() => onFocusNode(other.id)}>
                <span className="edge__rel">{relation}</span>
                <span className="edge__what">{other.content}</span>
                <span className="edge__tag">{TYPE_TAGS[other.type as NodeType]}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

/** The other claims Atlas drew from the same source document.
 *
 * The question a reader has standing right there — "what else did that PR say?"
 * — answered without leaving the screen, from provenance data already on hand
 * rather than a new fetch. */
function siblingsOf(node: Node, nodes: Node[]): Node[] {
  const mine = new Set(node.source_refs.map((ref) => `${ref.source_type}:${ref.external_id}`));
  return nodes.filter(
    (other) =>
      other.id !== node.id &&
      other.source_refs.some((ref) => mine.has(`${ref.source_type}:${ref.external_id}`)),
  );
}

function Siblings({
  siblings,
  onFocusNode,
}: {
  siblings: Node[];
  onFocusNode: (id: string) => void;
}) {
  if (siblings.length === 0) return null;
  return (
    <article className="card">
      <CardHead title="Also from this source" count={siblings.length} />
      <div className="card__body ev__also">
        <ul>
          {siblings.map((other) => (
            <li key={other.id}>
              <button type="button" className="ev__sib" onClick={() => onFocusNode(other.id)}>
                <span className={`ev__sib-mark is-${other.status}`} aria-hidden>
                  {STATUS_MARKS[other.status].mark}
                </span>
                <span className="ev__sib-text">{other.content}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </article>
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
