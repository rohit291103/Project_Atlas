/* The only place that talks to the API.
 *
 * Every type here comes from `api-types.ts`, which is generated from the
 * FastAPI OpenAPI schema (`npm run generate:types`) — never hand-written. A
 * hand-maintained mirror of Node/Edge is the same drift risk as a second model
 * layer on the server, one language further away
 * (docs/decisions/2026-08-11-api-frontend-module-boundary.md §6).
 */

import type { components } from "./api-types";

/* The domain models carry server-side defaults (`id`, `created_at`, `status`…),
 * so OpenAPI marks those fields optional — true of a *request*, never of a
 * *response*: the server has filled them in by the time we see one. Rather than
 * re-declare the models (the drift risk this whole file exists to avoid), the
 * response types are the generated ones with those fields narrowed to required. */
type Populated<T, K extends keyof T> = Omit<T, K> & Required<Pick<T, K>>;

export type SourceRef = Populated<components["schemas"]["SourceRef"], "id">;
export type Edge = Populated<components["schemas"]["Edge"], "id">;
/* `source_refs` is `Omit`-ed before being re-declared, not simply intersected
 * on: intersecting leaves the property as `RawSourceRef[] & SourceRef[]`, and
 * `.map` over that resolves to the *first* signature — so a ref read back off a
 * node arrived un-narrowed and every consumer had to re-assert `id`. Same shape
 * `FeatureScopeDetail` below already uses for `nodes`/`edges`. */
export type Node = Omit<
  Populated<components["schemas"]["Node"], "id" | "updated_at">,
  "source_refs"
> & {
  source_refs: SourceRef[];
};
/* The rail and the dashboard read rows, not bare identities: a row is the
   scope plus how much of it is still work. `FeatureScope` remains the identity
   shape returned inside a detail payload. */
export type FeatureScope = components["schemas"]["FeatureScopeRow"];
export type ScopeCounts = components["schemas"]["ScopeCounts"];
export type Product = components["schemas"]["Product"];
export type FeatureScopeDetail = Omit<
  components["schemas"]["FeatureScopeDetail"],
  "nodes" | "edges"
> & { nodes: Node[]; edges: Edge[] };
export type NodeType = components["schemas"]["NodeType"];
export type NodeStatus = components["schemas"]["NodeStatus"];
export type Role = components["schemas"]["Role"];
export type Session = components["schemas"]["SignInResponse"];
export type Connection = components["schemas"]["ConnectionView"];
export type ConnectionCreated = components["schemas"]["ConnectionCreated"];
export type Run = components["schemas"]["RunView"];
export type RunState = components["schemas"]["RunState"];
export type RunTargetKind = components["schemas"]["RunTargetKind"];
export type SourceType = components["schemas"]["SourceType"];

/** A viewer may read the extracted draft but not rule on it (TRD §9). The UI
 * hides what the API would refuse — an affordance that always 403s is worse
 * than no affordance. */
export const canWrite = (role: Role): boolean => role !== "viewer";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    // The session is a signed httpOnly cookie, so it has to ride along; no
    // token is ever held in JS, which is the point.
    credentials: "include",
    headers: init.body ? { "Content-Type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {
    /* a non-JSON error body is still an error; fall through to the status text */
  }
  return response.statusText || `request failed (${response.status})`;
}

const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** What the connect form collects. `secret` only ever travels *outbound* — no
 * response type in this file has a field it could come back in, which is the
 * client-side half of the rule `ConnectionView` enforces on the server. */
export type ConnectSource = {
  source_type: SourceType;
  host: string;
  scope: string;
  secret: string;
  email?: string;
};

export const api = {
  currentSession: () => request<Session>("/session"),
  signIn: (passphrase: string, name: string) =>
    post<Session>("/session", { passphrase, name }),
  signOut: () => request<void>("/session", { method: "DELETE" }),

  products: () => request<Product[]>("/products"),
  createProduct: (name: string) => post<Product>("/products", { name }),

  featureScopes: () => request<FeatureScope[]>("/feature-scopes"),
  featureScope: (id: string) => request<FeatureScopeDetail>(`/feature-scopes/${id}`),

  connections: (productId: string) => request<Connection[]>(`/products/${productId}/connections`),
  connectSource: (productId: string, body: ConnectSource) =>
    post<ConnectionCreated>(`/products/${productId}/connections`, body),
  revokeConnection: (connectionId: string) =>
    request<void>(`/connections/${connectionId}`, { method: "DELETE" }),

  runs: (productId: string) => request<Run[]>(`/products/${productId}/runs`),
  run: (runId: string) => request<Run>(`/runs/${runId}`),
  startRun: (
    productId: string,
    body: {
      connection_id: string;
      target_kind: RunTargetKind;
      target: string;
      feature_scope_id?: string;
      limit?: number;
    },
  ) => post<Run>(`/products/${productId}/runs`, body),

  confirm: (nodeId: string) => post<Node>(`/nodes/${nodeId}/confirm`),
  reject: (nodeId: string) => post<Node>(`/nodes/${nodeId}/reject`),
  edit: (nodeId: string, content: string) => post<Node>(`/nodes/${nodeId}/edit`, { content }),
  addNode: (scopeId: string, type: NodeType, content: string) =>
    post<Node>(`/feature-scopes/${scopeId}/nodes`, { type, content }),
};
