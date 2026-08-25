/* Rebuild the fixture workspace before the suite runs.
 *
 * Two of these tests confirm a claim, and a confirmation is an irreversible
 * event in an append-only log. Running them repeatedly against one workspace
 * therefore drifts it: every run leaves fewer claims to stage, until the tests
 * that need something unruled start failing for reasons that have nothing to do
 * with the code. The fix is not to exclude those two tests — it is to make the
 * ground they stand on identical at the start of every run.
 *
 * `scripts/seed_test_workspace.py` touches exactly one workspace id and refuses
 * to delete anything a human actor wrote. It needs the owner credential to
 * clear the log, because `atlas_app` holds `SELECT, INSERT` on `event_log` and
 * nothing else — the application role structurally cannot do this, which is a
 * property worth keeping rather than working around.
 *
 * `ATLAS_SKIP_SEED=1` skips it, for the case the seed cannot serve: a suite run
 * against a deployed environment whose database this machine cannot reach.
 */
import { execFileSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");

export default function seedFixtureWorkspace(): void {
  if (process.env.ATLAS_SKIP_SEED === "1") {
    console.log("[fixture] ATLAS_SKIP_SEED=1 — running against whatever is already there");
    return;
  }
  if (!process.env.SUPABASE_DB_ADMIN_URL || !process.env.SUPABASE_DB_URL) {
    // Loud, not silent: a suite that quietly ran against a stale fixture is how
    // twelve tests once passed against an API that did not have the endpoints
    // they called.
    throw new Error(
      "SUPABASE_DB_ADMIN_URL and SUPABASE_DB_URL must be set to seed the fixture " +
        "workspace (`set -a && source .env && set +a`), or set ATLAS_SKIP_SEED=1 to " +
        "run against a database this machine did not seed.",
    );
  }
  const output = execFileSync("uv", ["run", "python", "scripts/seed_test_workspace.py"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  });
  for (const line of output.trimEnd().split("\n")) console.log(`[fixture] ${line}`);
}
