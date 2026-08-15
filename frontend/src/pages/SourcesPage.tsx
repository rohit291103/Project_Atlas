/* Sources: connect a repo or a Jira project, pull from it, watch it finish.
 *
 * This screen is what makes "connect two sources" in the Phase 1 exit criterion
 * literally true. Before it, ingestion was a terminal command — the product told
 * its target user to open a terminal.
 *
 * Three things here are deliberate rather than incidental:
 *
 * 1. **The credential field is write-only, visibly.** Nothing ever renders a
 *    stored secret because no response carries one; the list shows `••••1234`
 *    from a stored four-character hint. The form says where to mint the token
 *    and what Atlas will do with it, at the moment the question is being asked.
 * 2. **Connecting reports what the credential reaches** — "Private repository ·
 *    3 open issues". Least privilege is otherwise a claim the product makes
 *    about itself; this is the source system's own answer.
 * 3. **A run is polled, not awaited.** The POST returns 202 and this polls
 *    `/runs/:id`, so a five-minute extraction does not sit in a request. A run
 *    the server reports as `interrupted` says so plainly rather than spinning
 *    forever — the honest cost of running in-process with no queue.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, canWrite } from "../api";
import type {
  Connection,
  ConnectSource,
  FeatureScope,
  Role,
  Run,
  RunTargetKind,
  SourceType,
} from "../api";
import { linkProps } from "../router";
import type { Route } from "../router";

/** How often a running job is re-checked. Long enough not to hammer the API,
 * short enough that finishing feels immediate. */
const POLL_MS = 2500;

const SOURCE_LABEL: Record<string, string> = {
  github_pr: "GitHub",
  jira_ticket: "Jira",
};

const TARGET_HELP: Record<RunTargetKind, { label: string; placeholder: string; hint: string }> = {
  github_pr: {
    label: "Pull request",
    placeholder: "acme/web#42",
    hint: "One pull request, fully qualified — the repo and the number.",
  },
  jira_issue: {
    label: "One issue",
    placeholder: "SCRUM-6",
    hint: "A single Jira issue key.",
  },
  jira_epic: {
    label: "An epic's children",
    placeholder: "SCRUM-6",
    hint: "Every child of this epic, up to the limit below.",
  },
  jira_label: {
    label: "A label",
    placeholder: "checkout-rewrite",
    hint: "Every issue carrying this label, up to the limit below.",
  },
};

export function SourcesPage({
  productId,
  productName,
  scopes,
  role,
  navigate,
  onIngested,
}: {
  productId: string;
  productName: string;
  scopes: FeatureScope[];
  role: Role;
  navigate: (route: Route, replace?: boolean) => void;
  onIngested: () => void;
}) {
  const writable = canWrite(role);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [justConnected, setJustConnected] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [loadedConnections, loadedRuns] = await Promise.all([
        api.connections(productId),
        api.runs(productId),
      ]);
      setConnections(loadedConnections);
      setRuns(loadedRuns);
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't load your sources.");
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is actually running. An idle Sources screen makes
  // no requests at all, which is the difference between "live" and "chatty".
  const active = runs.some((run) => run.state === "running");
  const finishedCount = useRef(0);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, load]);

  useEffect(() => {
    const done = runs.filter((run) => run.state === "succeeded").length;
    if (done > finishedCount.current) onIngested();
    finishedCount.current = done;
  }, [runs, onIngested]);

  return (
    <div className="pad">
      <div className="page-head">
        <h1>Sources</h1>
        <a className="link-button" {...linkProps({ name: "product", productId }, navigate)}>
          Back to {productName}
        </a>
      </div>
      <p className="page-sub">
        Atlas reads. It never writes to GitHub or Jira, in this or any later version — and it sees
        exactly what the credential you give it already sees, nothing wider.
      </p>

      {error && <div className="notice notice--error">{error}</div>}

      <section className="sources">
        <div className="sources__head">
          <h2>Connected</h2>
          {writable && !connecting && (
            <button type="button" className="link-button" onClick={() => setConnecting(true)}>
              Connect a source
            </button>
          )}
        </div>

        {connections.length === 0 && !connecting && (
          <div className="notice">
            Nothing connected yet.{" "}
            {writable
              ? "Connect a GitHub repo or a Jira project to start pulling context."
              : "Ask an editor to connect one."}
          </div>
        )}

        {justConnected && <div className="notice notice--good">{justConnected}</div>}

        <div className="cards">
          {connections.map((connection) => (
            <ConnectionCard
              key={connection.id}
              connection={connection}
              writable={writable}
              onRevoked={() => {
                setJustConnected(null);
                void load();
              }}
            />
          ))}
        </div>

        {connecting && (
          <ConnectForm
            productId={productId}
            onCancel={() => setConnecting(false)}
            onConnected={(message) => {
              setConnecting(false);
              setJustConnected(message);
              void load();
            }}
          />
        )}
      </section>

      {writable && connections.length > 0 && (
        <RunForm
          productId={productId}
          connections={connections}
          scopes={scopes}
          onStarted={() => void load()}
        />
      )}

      <RunHistory runs={runs} productId={productId} navigate={navigate} scopes={scopes} />
    </div>
  );
}

function ConnectionCard({
  connection,
  writable,
  onRevoked,
}: {
  connection: Connection;
  writable: boolean;
  onRevoked: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  return (
    <div className="card-link" style={{ cursor: "default" }}>
      <span className="card-link__name">
        {SOURCE_LABEL[connection.source_type] ?? connection.source_type} · {connection.scope}
      </span>
      <span className="card-link__meta">
        <span>{connection.host}</span>
        <span className="mono-hint">••••{connection.secret_hint}</span>
        <span>
          {connection.last_used_at
            ? `last used ${new Date(connection.last_used_at).toLocaleDateString()}`
            : "never used"}
        </span>
      </span>
      {writable && (
        <span className="card-link__meta">
          {confirming ? (
            <>
              <button
                type="button"
                className="action action--sm action--danger"
                onClick={() => {
                  void api.revokeConnection(connection.id).then(onRevoked);
                }}
              >
                Delete this credential
              </button>
              <button
                type="button"
                className="action action--sm"
                onClick={() => setConfirming(false)}
              >
                Keep it
              </button>
            </>
          ) : (
            <button
              type="button"
              className="link-button"
              onClick={() => setConfirming(true)}
              title="Removes the stored credential entirely"
            >
              Revoke
            </button>
          )}
        </span>
      )}
    </div>
  );
}

function ConnectForm({
  productId,
  onCancel,
  onConnected,
}: {
  productId: string;
  onCancel: () => void;
  onConnected: (message: string) => void;
}) {
  const [sourceType, setSourceType] = useState<SourceType>("github_pr");
  const [host, setHost] = useState("github.com");
  const [scope, setScope] = useState("");
  const [email, setEmail] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isJira = sourceType === "jira_ticket";

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    const body: ConnectSource = {
      source_type: sourceType,
      host: host.trim(),
      scope: scope.trim(),
      secret,
      ...(isJira ? { email: email.trim() } : {}),
    };
    try {
      const created = await api.connectSource(productId, body);
      // Clear the secret from component state the moment it is no longer
      // needed. It is never rendered and never stored here.
      setSecret("");
      onConnected(`Connected ${created.access_label} — ${created.access_detail}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't connect that source.");
    } finally {
      setBusy(false);
    }
  }, [email, host, isJira, onConnected, productId, scope, secret, sourceType]);

  return (
    <form
      className="connect"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <div className="connect__choice">
        {(["github_pr", "jira_ticket"] as SourceType[]).map((option) => (
          <button
            key={option}
            type="button"
            className={`action ${sourceType === option ? "action--primary" : ""}`}
            onClick={() => {
              setSourceType(option);
              setHost(option === "github_pr" ? "github.com" : "");
            }}
          >
            {SOURCE_LABEL[option]}
          </button>
        ))}
      </div>

      <label htmlFor="host">
        {isJira ? "Your Jira site" : "Host"}
        <input
          id="host"
          value={host}
          placeholder={isJira ? "acme.atlassian.net" : "github.com"}
          onChange={(event) => setHost(event.target.value)}
        />
      </label>

      <label htmlFor="scope">
        {isJira ? "Project key" : "Repository"}
        <input
          id="scope"
          value={scope}
          placeholder={isJira ? "SCRUM" : "acme/web"}
          onChange={(event) => setScope(event.target.value)}
        />
      </label>

      {isJira && (
        <label htmlFor="email">
          The email this token belongs to
          <input
            id="email"
            type="email"
            value={email}
            placeholder="you@acme.com"
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
      )}

      <label htmlFor="secret">
        {isJira ? "API token" : "Personal access token"}
        <input
          id="secret"
          type="password"
          value={secret}
          autoComplete="off"
          placeholder={isJira ? "ATATT…" : "ghp_…"}
          onChange={(event) => setSecret(event.target.value)}
        />
      </label>
      <p className="connect__note">
        Stored encrypted, and never shown again — you'll only ever see the last four characters.
        Atlas reads with it and never writes, so a read-only token is enough:{" "}
        {isJira ? (
          <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noreferrer">
            mint a Jira API token
          </a>
        ) : (
          <a href="https://github.com/settings/tokens" target="_blank" rel="noreferrer">
            mint a GitHub token
          </a>
        )}
        . Whatever you give it, Atlas sees exactly what you already see — no more.
      </p>

      {error && <div className="notice notice--error">{error}</div>}

      <div className="composer__row">
        <button
          type="submit"
          className="action action--primary"
          disabled={busy || !host.trim() || !scope.trim() || !secret || (isJira && !email.trim())}
        >
          {busy ? "Checking access…" : "Connect and check access"}
        </button>
        <button type="button" className="action" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function RunForm({
  productId,
  connections,
  scopes,
  onStarted,
}: {
  productId: string;
  connections: Connection[];
  scopes: FeatureScope[];
  onStarted: () => void;
}) {
  const [connectionId, setConnectionId] = useState(connections[0]?.id ?? "");
  const connection = connections.find((candidate) => candidate.id === connectionId);
  const isJira = connection?.source_type === "jira_ticket";
  // Memoised: it is a `useEffect` dependency below, and a fresh array every
  // render would re-run that effect forever.
  const kinds = useMemo<RunTargetKind[]>(
    () => (isJira ? ["jira_issue", "jira_epic", "jira_label"] : ["github_pr"]),
    [isJira],
  );
  const [kind, setKind] = useState<RunTargetKind>("github_pr");
  const [target, setTarget] = useState("");
  const [featureScopeId, setFeatureScopeId] = useState("");
  const [limit, setLimit] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Keep the target kind valid when the chosen connection changes source —
  // otherwise switching from a GitHub connection to a Jira one leaves "pull
  // request" selected and the run is rejected for a reason nobody can see.
  useEffect(() => {
    const first = kinds[0];
    if (first && !kinds.includes(kind)) setKind(first);
  }, [kind, kinds]);

  const help = TARGET_HELP[kind];
  const scoped = kind === "jira_epic" || kind === "jira_label";

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.startRun(productId, {
        connection_id: connectionId,
        target_kind: kind,
        target: target.trim(),
        ...(featureScopeId ? { feature_scope_id: featureScopeId } : {}),
        ...(scoped ? { limit } : {}),
      });
      setTarget("");
      onStarted();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't start that run.");
    } finally {
      setBusy(false);
    }
  }, [connectionId, featureScopeId, kind, limit, onStarted, productId, scoped, target]);

  return (
    <section className="sources">
      <div className="sources__head">
        <h2>Pull context</h2>
      </div>
      <p className="page-sub">
        Every pull is deliberate — one pull request, one issue, one epic, one label. Atlas never
        crawls a repo or a Jira site.
      </p>

      <form
        className="connect"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label htmlFor="connection">
          From
          <select
            id="connection"
            value={connectionId}
            onChange={(event) => setConnectionId(event.target.value)}
          >
            {connections.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {SOURCE_LABEL[candidate.source_type] ?? candidate.source_type} · {candidate.scope}
              </option>
            ))}
          </select>
        </label>

        {kinds.length > 1 && (
          <div className="connect__choice">
            {kinds.map((option) => (
              <button
                key={option}
                type="button"
                className={`action ${kind === option ? "action--primary" : ""}`}
                onClick={() => setKind(option)}
              >
                {TARGET_HELP[option].label}
              </button>
            ))}
          </div>
        )}

        <label htmlFor="target">
          {help.label}
          <input
            id="target"
            value={target}
            placeholder={help.placeholder}
            onChange={(event) => setTarget(event.target.value)}
          />
        </label>
        <p className="connect__note">{help.hint}</p>

        <label htmlFor="feature">
          Add to
          <select
            id="feature"
            value={featureScopeId}
            onChange={(event) => setFeatureScopeId(event.target.value)}
          >
            <option value="">A new feature</option>
            {scopes.map((scope) => (
              <option key={scope.id} value={scope.id}>
                {scope.title}
              </option>
            ))}
          </select>
        </label>
        <p className="connect__note">
          Adding to an existing feature is what makes it cross-source: the run is handed what the
          other source already said, so a contradiction between them becomes a conflict you can see
          rather than two halves that never meet.
        </p>

        {scoped && (
          <label htmlFor="limit">
            At most
            <input
              id="limit"
              type="number"
              min={1}
              max={50}
              value={limit}
              onChange={(event) => setLimit(Number(event.target.value))}
            />
          </label>
        )}

        {error && <div className="notice notice--error">{error}</div>}

        <div className="composer__row">
          <button
            type="submit"
            className="action action--primary"
            disabled={busy || !target.trim() || !connectionId}
          >
            {busy ? "Starting…" : "Pull it in"}
          </button>
        </div>
      </form>
    </section>
  );
}

function RunHistory({
  runs,
  productId,
  scopes,
  navigate,
}: {
  runs: Run[];
  productId: string;
  scopes: FeatureScope[];
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const titles = useMemo(
    () => new Map(scopes.map((scope) => [scope.id, scope.title])),
    [scopes],
  );
  if (runs.length === 0) return null;

  return (
    <section className="sources">
      <div className="sources__head">
        <h2>Runs</h2>
      </div>
      <ul className="runs">
        {[...runs].reverse().map((run) => (
          <li key={run.id} className={`run run--${run.state}`}>
            <span className="run__mark" aria-hidden />
            <div className="run__body">
              <div className="run__line">
                <span className="run__target">{run.target}</span>
                <span className="run__state">{stateLabel(run)}</span>
              </div>
              <div className="run__meta">
                <span>{new Date(run.started_at).toLocaleString()}</span>
                <span>started by {run.started_by}</span>
                {run.state === "succeeded" && (
                  <span>
                    {run.artifacts} artifact{run.artifacts === 1 ? "" : "s"} · {run.nodes} claim
                    {run.nodes === 1 ? "" : "s"}
                  </span>
                )}
                {/* Offered for any run that produced something, whether or not
                    the rail has finished loading the feature's title — the link
                    is the point of the row, and withholding it until a *label*
                    arrives makes the most useful thing here the last to appear. */}
                {run.state === "succeeded" && (
                  <a
                    {...linkProps(
                      { name: "feature", productId, featureId: run.feature_scope_id },
                      navigate,
                    )}
                  >
                    Review {titles.get(run.feature_scope_id) ?? "what it found"}
                  </a>
                )}
              </div>
              {run.error && <p className="run__error">{run.error}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** The wording matters for one of these. `interrupted` is not a synonym for
 * failed: the run started, nobody knows how far it got, and the honest thing is
 * to say that rather than to show a spinner that will never resolve. */
function stateLabel(run: Run): string {
  switch (run.state) {
    case "running":
      return "Working…";
    case "succeeded":
      return "Done";
    case "failed":
      return "Failed";
    case "interrupted":
      return "Interrupted — the server restarted mid-run";
  }
}
