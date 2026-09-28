/* How well extraction is doing, read off the reviewers' own rulings.
 *
 * Every number is computed server-side in `src/atlas/feedback.py`, from the
 * event log, to roadmap v2's definitions. The page's one editorial job is the
 * guard: if any ruling was not made by a human, the numbers below are unsound
 * and the page says so *above* them, not in a footnote — a rate nobody may cite
 * must not look citable.
 */

import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { FeedbackReport, Tally } from "../api";
import { Loading } from "../components/Loading";
import { TYPE_TAGS, SOURCE_BADGES } from "../review";

const percent = (rate: number | null | undefined): string =>
  rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;

function Breakdown({
  title,
  rows,
  label,
}: {
  title: string;
  rows: Record<string, Tally>;
  label: (key: string) => string;
}) {
  const entries = Object.entries(rows).sort((a, b) => b[1].ruled - a[1].ruled);
  if (entries.length === 0) return null;
  return (
    <section className="quality__block">
      <h2 className="about__heading">{title}</h2>
      <table className="quality__table">
        <thead>
          <tr>
            <th scope="col" />
            <th scope="col">Kept</th>
            <th scope="col">Edited</th>
            <th scope="col">Rejected</th>
            <th scope="col">Acceptance</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, tally]) => (
            <tr key={key}>
              <th scope="row">{label(key)}</th>
              <td>{tally.kept}</td>
              <td>{tally.edited}</td>
              <td>{tally.rejected}</td>
              <td>{percent(tally.acceptance_rate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function QualityPage({ productId }: { productId: string }) {
  const [report, setReport] = useState<FeedbackReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .feedback(productId)
      .then(setReport)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "Couldn't load quality."),
      );
  }, [productId]);

  if (error) return <div className="pad"><div className="notice notice--error">{error}</div></div>;
  if (!report) return <Loading label="Reading the rulings…" />;

  const { overall } = report;
  return (
    <div className="pad about">
      <div className="page-head">
        <h1>Extraction quality</h1>
      </div>
      <p className="about__provenance-note">
        Of the claims Atlas extracted, how many a person kept <b>unedited at first read</b>.
        Only a claim's first ruling counts, and only when a person made it.
      </p>

      {/* Two cases, one message each. With no human first rulings at all there
          are no numbers below to warn about, so the guard's warning would
          contradict the empty state it sits on top of. */}
      {overall.ruled === 0 ? (
        <div className="notice">
          {report.guard_passes
            ? "Nothing has been ruled on yet."
            : "No claim has been ruled on by a person yet. Every ruling here was automated, so there is nothing to measure."}
        </div>
      ) : (
        <>
          {!report.guard_passes && (
            <div className="notice notice--error">
              {percent(report.human_share)} of rulings here were made by a person. Until that is
              100%, none of the numbers below should be quoted.
            </div>
          )}
          <section className="quality__headline">
            <span className="readiness__score">{percent(overall.acceptance_rate)}</span>
            <span className="readiness__label">
              Spec acceptance rate
              <span className="readiness__sub">
                {overall.kept} kept · {overall.edited} edited · {overall.rejected} rejected
              </span>
            </span>
          </section>

          {report.weekly.length > 0 && (
            <section className="quality__block">
              <h2 className="about__heading">By week</h2>
              <ol className="quality__weeks">
                {report.weekly.map((week) => (
                  <li key={week.week}>
                    <span className="quality__week">{week.week}</span>
                    <span
                      className="quality__bar"
                      style={{ width: `${Math.round((week.acceptance_rate ?? 0) * 100)}%` }}
                    />
                    <span>
                      {percent(week.acceptance_rate)} of {week.ruled}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <Breakdown
            title="By claim type"
            rows={report.by_type}
            label={(key) => (TYPE_TAGS as Record<string, string>)[key] ?? key}
          />
          <Breakdown
            title="By source"
            rows={report.by_source}
            label={(key) => (SOURCE_BADGES as Record<string, string>)[key] ?? key}
          />

          {report.edits.length > 0 && (
            <section className="quality__block">
              <h2 className="about__heading">Rewritten at first read</h2>
              <ul className="changes__list">
                {report.edits.map((edit) => (
                  <li key={edit.node_id}>
                    <span className="tag">{TYPE_TAGS[edit.type] ?? edit.type}</span>{" "}
                    <s>{edit.extracted}</s> → {edit.corrected}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {report.rejections.length > 0 && (
            <section className="quality__block">
              <h2 className="about__heading">Rejected at first read</h2>
              <ul className="changes__list">
                {report.rejections.map((rejection) => (
                  <li key={rejection.node_id}>
                    <span className="tag">{TYPE_TAGS[rejection.type] ?? rejection.type}</span>{" "}
                    {rejection.content}
                    <blockquote className="about__ex">{rejection.excerpt}</blockquote>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}
