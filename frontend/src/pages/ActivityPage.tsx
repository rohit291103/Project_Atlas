/* How the workspace is using Atlas, per week — the admin's view (Phase 4).
 *
 * Everything is counted server-side in `src/atlas/activity.py`, from the event
 * log alone. Workspace-wide rather than per product, so the title says so: the
 * page sits in a product's rail only because that is where an admin already is.
 * Automated rulings are shown in their own column and never added to a
 * person's, for the reason the Quality page's guard exists.
 */

import { useEffect, useState } from "react";
import { ApiError, api } from "../api";
import type { ActivityReport } from "../api";
import { Loading } from "../components/Loading";

export function ActivityPage() {
  const [report, setReport] = useState<ActivityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .activity()
      .then(setReport)
      .catch((caught) =>
        setError(caught instanceof ApiError ? caught.message : "Couldn't load activity."),
      );
  }, []);

  if (error) return <div className="pad"><div className="notice notice--error">{error}</div></div>;
  if (!report) return <Loading label="Counting the log…" />;

  const weeks = [...report.weeks].reverse(); // newest first on screen
  return (
    <div className="pad about activity">
      <div className="page-head">
        <h1>Workspace activity</h1>
      </div>
      <p className="about__provenance-note">
        Per week, across every product in this workspace, counted from the log. Rulings by
        automation are shown apart from people's. Spec exports and questions are not recorded, so
        they are not counted.
      </p>

      {weeks.length === 0 ? (
        <div className="notice">Nothing has happened in this workspace yet.</div>
      ) : (
        <div className="activity__scroll">
          <table className="quality__table">
            <thead>
              <tr>
                <th scope="col">Week</th>
                <th scope="col">Runs</th>
                <th scope="col">Failed</th>
                {report.people.map((person) => (
                  <th scope="col" key={person}>
                    {person}
                  </th>
                ))}
                <th scope="col">Automated</th>
                <th scope="col">Comments</th>
              </tr>
            </thead>
            <tbody>
              {weeks.map((week) => (
                <tr key={week.week}>
                  <th scope="row">{week.week}</th>
                  <td>{week.runs_started ?? 0}</td>
                  <td>{week.runs_failed ?? 0}</td>
                  {report.people.map((person) => (
                    <td key={person}>{week.rulings_by_person?.[person] ?? 0}</td>
                  ))}
                  <td>{week.automated_rulings ?? 0}</td>
                  <td>{week.comments ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
