/* What this product *is* — the page that was missing.
 *
 * Every other screen in Atlas answers "what is mine to do": the worklist, the
 * rail badges, the conflicts queue. None of them answers "what am I looking
 * at", which is the first question anyone opening a product has and the only
 * one a newcomer can ask. That gap is a strange one for a tool whose entire
 * thesis is that people and coding agents are starved of correct context —
 * Atlas ingested the context and rendered a queue over it, and never rendered
 * the context itself (`docs/architecture/product-info-and-spec-export-v1.md`).
 *
 * Two halves, and the split is the design:
 *
 *   - the **authored spine** — what the PM says the product is. Prose, not a
 *     claim: no provenance, no confirmation, and it never reaches an export as
 *     a fact. Reuses `Orientation`, the same control as the Overview.
 *   - the **derived body** — the confirmed claims, assembled by the server. It
 *     updates itself as claims get confirmed, which is what stops this page
 *     being a document that rots.
 *
 * Nothing here filters by status. The server decides what "confirmed" means,
 * once, in `src/atlas/assembly.py`, because the Markdown export reads the same
 * assembly — and a rule implemented twice in two languages is a rule that will
 * eventually be implemented differently in two languages.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError, api, canWrite, specUrl } from "../api";
import type {
  DocumentClaim,
  DocumentSection,
  Disagreement,
  ProductDocument,
  Readiness,
  Role,
  SpecChanges,
} from "../api";
import { Orientation } from "../components/Orientation";
import { Loading } from "../components/Loading";
import { SOURCE_BADGES, TYPE_TAGS } from "../review";
import { linkProps } from "../router";
import type { Route } from "../router";

/** The order sections are printed in, mirroring `DOCUMENT_ORDER` in
 * `src/atlas/assembly.py`. The server already sorts the claims; this only maps
 * a type to the heading it sits under, and a type absent here would render
 * under its own raw name rather than vanishing. */
const HEADINGS: Record<string, string> = {
  goal: "Goals",
  problem: "Problems",
  evidence: "Evidence",
  requirement: "Requirements",
  constraint: "Constraints",
  decision: "Decisions",
  architecture_note: "Architecture notes",
  rejected_alternative: "Rejected alternatives",
  open_question: "Open questions",
};

function groupByType(claims: DocumentClaim[]): [string, DocumentClaim[]][] {
  /* The server has already put the claims in document order, so walking them in
     order and starting a new group on each change of type preserves it — no
     second sort here that could disagree with the first. */
  const groups: [string, DocumentClaim[]][] = [];
  for (const claim of claims) {
    const last = groups[groups.length - 1];
    if (last && last[0] === claim.type) last[1].push(claim);
    else groups.push([claim.type, [claim]]);
  }
  return groups;
}

function Provenance({ claim }: { claim: DocumentClaim }) {
  return (
    <>
      {claim.sources.map((source, index) => (
        <figure className="about__src" key={source.id ?? index}>
          <blockquote className="about__ex">{source.excerpt}</blockquote>
          <figcaption className="about__cite">
            <span className="tag">{SOURCE_BADGES[source.source_type] ?? source.source_type}</span>
            {/* `external_id` fully qualifies the artifact within its source
                (`plausible/analytics#1364`, not `1364`), which is exactly the
                label a reader needs to know *which* PR this came from. */}
            <a href={source.url} target="_blank" rel="noreferrer" className="about__link">
              {source.external_id} ↗
            </a>
          </figcaption>
        </figure>
      ))}
    </>
  );
}

function Claim({ claim }: { claim: DocumentClaim }) {
  return (
    <li className="about__claim">
      <p className="about__claim-text">
        {claim.content}
        {/* An edited claim reads as the product's own words, which it now is —
            but somebody rewrote it, and the page should not quietly present a
            human revision as the extractor's output or the reverse. */}
        {claim.status === "edited" && <span className="about__edited">edited</span>}
      </p>
      {/* Evidence density, said only when there is corroboration — "1 source"
          on every line is noise that teaches the reader to skip the line. */}
      {claim.source_count > 1 && (
        <p className="about__density">
          {claim.source_count} sources across {claim.systems.length} system
          {claim.systems.length === 1 ? "" : "s"}
        </p>
      )}
      <Provenance claim={claim} />
    </li>
  );
}

function Contested({ disagreement, number }: { disagreement: Disagreement; number: number }) {
  return (
    <div className="about__vs">
      {/* The explanation lives once under the section heading, not on every
          pair: one claim can be in several disagreements at once (it really can
          contradict two different things), and repeating the banner six times
          buries the claims it is meant to frame. What is left is a number, so
          the pairs can be counted and referred to. */}
      <p className="about__vs-head">
        <span className="about__vs-mark">▲</span> Disagreement {number}
      </p>
      <div className="about__vs-pair">
        {[disagreement.left, disagreement.right].map((side) => (
          <div className="about__vs-side" key={side.node_id}>
            <p className="about__claim-text">{side.content}</p>
            <p className="about__vs-meta">
              <span className={`status status--${side.status}`}>{side.status}</span>
              <span className="tag">{TYPE_TAGS[side.type] ?? side.type}</span>
            </p>
            <Provenance claim={side} />
          </div>
        ))}
      </div>
    </div>
  );
}

function Section({
  section,
  writable,
  productId,
  navigate,
  onChanged,
}: {
  section: DocumentSection;
  writable: boolean;
  productId: string;
  navigate: (route: Route, replace?: boolean) => void;
  onChanged: () => void;
}) {
  const empty = section.claims.length === 0 && section.disagreements.length === 0;
  return (
    <section className="about__feature">
      <h2 className="about__feature-name">
        <a
          {...linkProps(
            { name: "feature", productId, featureId: section.feature_scope_id },
            navigate,
          )}
        >
          {section.title}
        </a>
        {section.unreviewed > 0 && (
          <span className="about__pending">{section.unreviewed} awaiting review</span>
        )}
      </h2>

      <Orientation
        description={section.description ?? null}
        writable={writable}
        what="feature"
        placeholder="What is this feature for? One or two sentences."
        onSave={async (description) => {
          await api.describeFeature(section.feature_scope_id, description);
          onChanged();
        }}
      />

      {/* An empty feature is shown rather than hidden. Omitting it would hide
          work from the person whose job it is to do it, and make the page claim
          a completeness it does not have. */}
      {empty && (
        <p className="about__nothing">
          Nothing confirmed here yet.{" "}
          {section.unreviewed > 0 ? (
            <a
              {...linkProps(
                { name: "feature", productId, featureId: section.feature_scope_id },
                navigate,
              )}
            >
              Review {section.unreviewed} claim{section.unreviewed === 1 ? "" : "s"} →
            </a>
          ) : (
            "Nothing has been extracted into it."
          )}
        </p>
      )}

      {groupByType(section.claims).map(([type, claims]) => (
        <div className="about__group" key={type}>
          <h3 className="about__heading">{HEADINGS[type] ?? type}</h3>
          <ul className="about__claims">
            {claims.map((claim) => (
              <Claim claim={claim} key={claim.node_id} />
            ))}
          </ul>
        </div>
      ))}

      {section.disagreements.length > 0 && (
        <div className="about__group">
          <h3 className="about__heading about__heading--conflict">Unresolved disagreements</h3>
          {/* Said once, and said plainly: confirming one side does not settle a
              conflict (TRD §5.2), so these claims sit here rather than in the
              sections above — nothing still in dispute should read as settled. */}
          <p className="about__vs-why">
            The sources disagree and nothing here is settled. Confirming one side does not
            resolve a disagreement; ruling the other side out does.{" "}
            <a {...linkProps({ name: "conflicts", productId }, navigate)}>Rule on these →</a>
          </p>
          {section.disagreements.map((disagreement, index) => (
            <Contested disagreement={disagreement} number={index + 1} key={disagreement.edge_id} />
          ))}
        </div>
      )}
    </section>
  );
}

/** How ready this spec is to hand to a coding agent, and exactly why not.
 *
 * The score is computed server-side in `assembly.py` (four equally weighted
 * checks per feature) and the export carries the same one at its head; this
 * only renders it. Every gap links to where it can be fixed, because a number
 * with nothing to click is a grade, not a to-do list. */
function ReadinessPanel({
  readiness,
  productId,
  navigate,
}: {
  readiness: Readiness;
  productId: string;
  navigate: (route: Route, replace?: boolean) => void;
}) {
  const tone = readiness.score >= 80 ? "ok" : readiness.score >= 50 ? "mid" : "low";
  return (
    <section className={`readiness readiness--${tone}`} aria-label="Spec readiness">
      <div className="readiness__head">
        <span className="readiness__score">{readiness.score}</span>
        <span className="readiness__label">
          Spec readiness
          <span className="readiness__sub">
            {readiness.passed} of {readiness.checks} checks pass
          </span>
        </span>
      </div>
      {readiness.gaps.length > 0 && (
        <ul className="readiness__gaps">
          {readiness.gaps.map((gap, index) => {
            const target: Route =
              gap.kind === "disagreement"
                ? { name: "conflicts", productId }
                : gap.feature_scope_id
                  ? { name: "feature", productId, featureId: gap.feature_scope_id }
                  : { name: "sources", productId };
            return (
              <li className="readiness__gap" key={`${gap.kind}-${gap.feature_scope_id}-${index}`}>
                <span className="tag">{gap.kind.replace("_", " ")}</span>
                <a {...linkProps(target, navigate)}>
                  {gap.feature_title && <b>{gap.feature_title}: </b>}
                  {gap.detail}
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** How far back "what changed" looks. Fixed presets rather than a date
 * picker: the question a PM or an agent asks is "since last week", and every
 * preset is one replay of the log, so none costs more than another. */
const SINCE_PRESETS: [string, number][] = [
  ["24 hours", 1],
  ["7 days", 7],
  ["30 days", 30],
];

/** Spec versioning (Phase 3): what changed in the confirmed spec since a
 * moment. The server replays the log as of then and compares; this renders the
 * delta and copies it as Markdown for an agent already holding the old spec. */
function Changes({ productId }: { productId: string }) {
  const [days, setDays] = useState(7);
  const [changes, setChanges] = useState<SpecChanges | null>(null);
  const [copied, setCopied] = useState(false);
  const since = new Date(Date.now() - days * 86_400_000).toISOString();

  useEffect(() => {
    let live = true;
    api
      .changes(productId, since)
      .then((result) => live && setChanges(result))
      .catch(() => live && setChanges(null));
    return () => {
      live = false;
    };
    // `since` is derived from `days`; depending on it would refetch on every
    // render, since each render computes a new timestamp.
  }, [productId, days]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(await api.specChanges(productId, since));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* Clipboard denied: nothing useful to say beyond the button not changing. */
    }
  };

  const total = changes
    ? changes.added.length +
      changes.removed.length +
      changes.reworded.length +
      changes.disagreements_opened.length +
      changes.disagreements_resolved.length
    : 0;

  return (
    <section className="changes" aria-label="What changed">
      <div className="changes__head">
        <h2 className="about__heading changes__title">What changed in the last</h2>
        <div className="qviews" role="tablist" aria-label="How far back">
          {SINCE_PRESETS.map(([label, value]) => (
            <button
              type="button"
              key={value}
              role="tab"
              aria-selected={value === days}
              className={`qview${value === days ? " is-active" : ""}`}
              onClick={() => setDays(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {total > 0 && (
          <button type="button" className="action action--sm" onClick={() => void copy()}>
            {copied ? "Copied" : "Copy changes"}
          </button>
        )}
      </div>
      {changes && (
        <p className="changes__summary">
          {total === 0 ? (
            "Nothing in the spec changed."
          ) : (
            <>
              {changes.added.length > 0 && <span>+{changes.added.length} added</span>}
              {changes.reworded.length > 0 && <span>{changes.reworded.length} reworded</span>}
              {changes.removed.length > 0 && <span>−{changes.removed.length} removed</span>}
              {changes.disagreements_opened.length > 0 && (
                <span>{changes.disagreements_opened.length} newly disputed</span>
              )}
              {changes.disagreements_resolved.length > 0 && (
                <span>{changes.disagreements_resolved.length} settled</span>
              )}
            </>
          )}
          {changes.readiness_before !== changes.readiness_after && (
            <span>
              readiness {changes.readiness_before} → {changes.readiness_after}
            </span>
          )}
        </p>
      )}
      {changes && changes.added.length > 0 && (
        <ul className="changes__list">
          {changes.added.map((claim) => (
            <li key={claim.node_id}>
              <span className="tag">{TYPE_TAGS[claim.type] ?? claim.type}</span> {claim.content}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Hand the confirmed document to whatever comes next — a coding agent, a
 * teammate, a ticket. Copy and download rather than one or the other: pasting
 * into an agent's context is the case this exists for, and a file is what
 * anyone doing anything else will want. */
function Export({ productId }: { productId: string }) {
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(await api.spec(productId));
      setCopied(true);
      setFailed(false);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* A denied clipboard permission is not an error worth a banner — the
         download beside it does the same job. */
      setFailed(true);
    }
  }, [productId]);

  return (
    <span className="about__export">
      <button type="button" className="action action--sm" onClick={() => void copy()}>
        {copied ? "Copied" : "Copy as Markdown"}
      </button>
      <a className="action action--sm" href={specUrl(productId)} download>
        Download
      </a>
      {failed && <span className="about__export-note">Use Download instead</span>}
    </span>
  );
}

export function AboutPage({
  productId,
  role,
  navigate,
  onChanged,
}: {
  productId: string;
  role: Role;
  navigate: (route: Route, replace?: boolean) => void;
  onChanged: () => void;
}) {
  const writable = canWrite(role);
  const [doc, setDoc] = useState<ProductDocument | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setDoc(await api.document(productId));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't load this product.");
    } finally {
      setLoading(false);
    }
  }, [productId]);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = useCallback(() => {
    void load();
    onChanged();
  }, [load, onChanged]);

  if (loading && !doc) return <Loading label="Assembling what's confirmed…" />;
  if (error) return <div className="pad"><div className="notice notice--error">{error}</div></div>;
  if (!doc) return null;

  const pending = doc.features.reduce((total, section) => total + section.unreviewed, 0);
  const confirmed = doc.features.reduce((total, section) => total + section.claims.length, 0);

  return (
    <div className="pad about" data-tour="about">
      <div className="page-head">
        <h1>{doc.name}</h1>
        {/* The export is the same document this page is showing, rendered as
            Markdown by the same server-side assembly — not a second opinion
            about what "confirmed" means. That is why it lives here rather than
            on a screen of its own. */}
        {confirmed > 0 && <Export productId={productId} />}
      </div>

      <Orientation
        description={doc.description ?? null}
        writable={writable}
        what="product"
        placeholder="What is this product, and who is it for? One or two sentences."
        onSave={async (description) => {
          await api.describeProduct(productId, description);
          refresh();
        }}
      />

      {/* Say what is missing, on the page itself. A reader who does not know a
          third of the material was withheld reads the rest as complete. */}
      <p className="about__provenance-note">
        Assembled from <b>{confirmed}</b> confirmed claim{confirmed === 1 ? "" : "s"}, each shown
        with the source text it came from.
        {pending > 0 && (
          <>
            {" "}
            <b>{pending}</b> more {pending === 1 ? "is" : "are"} still awaiting review and{" "}
            {pending === 1 ? "is" : "are"} not included.
          </>
        )}
      </p>

      <ReadinessPanel readiness={doc.readiness} productId={productId} navigate={navigate} />
      {confirmed > 0 && <Changes productId={productId} />}

      {doc.features.length === 0 ? (
        <div className="notice">
          Nothing has been ingested into this product yet.{" "}
          {writable && (
            <a {...linkProps({ name: "sources", productId }, navigate)}>Connect a source</a>
          )}
        </div>
      ) : (
        doc.features.map((section) => (
          <Section
            section={section}
            writable={writable}
            productId={productId}
            navigate={navigate}
            onChanged={refresh}
            key={section.feature_scope_id}
          />
        ))
      )}
    </div>
  );
}
