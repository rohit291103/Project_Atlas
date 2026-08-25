/* Who the browser suite is, and where it works.
 *
 * The suite used to sign in as whoever `ATLAS_TEST_EDITOR` named, falling back
 * to a guess at the local seed's actors — so with the variable unset it signed
 * in as a person who might exist, into whatever workspace that person belonged
 * to, and its confirmations were real rulings in the workspace the demo is
 * given from. `X-Atlas-Automated` made those writes *honest*; it did not make
 * them stop happening.
 *
 * They now happen somewhere disposable. `scripts/seed_test_workspace.py` seats
 * these two actors in a workspace of their own and rebuilds its contents before
 * every run, and membership is what resolves a session to a workspace
 * (`src/atlas/api/deps.py::get_principal`) — so signing in as one of these names
 * cannot reach the demo's data even by accident.
 *
 * These strings are the join between the two halves and must match the seed
 * script exactly; `tests/test_seed_test_workspace.py` fails if they drift.
 */
export const EDITOR = "Suite Editor (automated)";
export const VIEWER = "Suite Viewer (automated)";

/** The fixture workspace's id — `uuid5`, so it is the same on every rebuild. */
export const WORKSPACE_ID = "7d7d0811-9fbb-5b17-9039-e48d8090bd88";

/* An override is still allowed, for the one case it is honest: pointing the
 * suite at a deployed environment that was seeded some other way. It is no
 * longer a *guess* — unset means the fixture, which is a fact this repo
 * guarantees rather than a hope about someone's database. */
export const actors = {
  editor: process.env.ATLAS_TEST_EDITOR ?? EDITOR,
  viewer: process.env.ATLAS_TEST_VIEWER ?? VIEWER,
};
