# Phase 1 exit measurement: session script

**Status:** ready to run on 2026-10-03, apart from the two items marked **NEEDS YOU**.
**Measures:** the Phase 1 exit criterion. *A PM outside the build team can, unassisted, connect two sources, review extracted elements, and confirm or reject them in under 20 minutes.*
**For:** whoever runs the session. Fill in §5 **before** the session starts and don't change it afterwards. That's the same rule as the Phase 2 pre-registration, and for the same reason.

## 1. Before the day

| Done | Step | Command / note |
|---|---|---|
| ✅ | A clean workspace exists, so nothing from the demo data leaks into the measurement | `PM measurement`, id `1a01e303-f230-4504-96ea-92e4d8ad272b`. Created 2026-10-03, empty. |
| ☐ **NEEDS YOU** | Get the PM's name **exactly as they will type it** (case, spaces, accents) | Sign-in matches it character for character. |
| ☐ | Seat them as **admin** (only an admin can connect sources) | `set -a && source .env && set +a && uv run atlas member-seat 1a01e303-f230-4504-96ea-92e4d8ad272b "<exact name>" --role admin`. It refuses a name with stray spaces, or one already seated in another workspace. |
| ☐ **NEEDS YOU** | Give the PM access to the Jira site with the `PA` project, so they can mint their own API token during the session | Minting a token is part of "connect a source", so it happens inside the 20 minutes. If the PM can't be invited, give them a read-only token on the task card instead, and record that in §5. |
| ☐ | Confirm the PM has a GitHub account (any account can read the public repo) | No account means a token goes on the card. Record that too. |
| ☐ | Check the Jira ticket key: the PA issue titled **"Change the graph's time detail"** | It was PA-3 when seeded on 2026-08-21. Use whatever key Jira shows now. |

## 2. On the day, 30 minutes before

1. **Wake the database.** The free tier pauses after 7 idle days. Sign in to the demo workspace once and load a page.
2. **Restart the API** so it runs today's code. A stale process has caused a wrong demo before.
   - `ATLAS_DEV_CORS=1 uv run uvicorn atlas.api.app:app --port 8000`
   - `cd frontend && npm run dev` (port 5173)
3. **Check that extraction can run.** Pull any PR into a scratch product in the demo workspace, *not* the PM's. A broken model login is better found now than at minute 6 of the session.
4. Have the passphrase ready to hand over. Open a stopwatch and the record sheet (§6).

## 3. The task card (give the PM exactly this, printed or pasted)

> You're a PM on **Plausible Analytics**, an open-source web analytics product. Your team is reworking the dashboard graph, and decisions are spread between Jira and GitHub.
>
> 1. Sign in at **http://localhost:5173** with the passphrase you were given and your name.
> 2. Create a product called **Plausible Analytics**.
> 3. Connect **GitHub** and pull pull request **plausible/analytics#1574**.
> 4. Connect **Jira** (site: *<the site URL>*) and pull issue **<the key from §1>**.
> 5. Review what Atlas extracted. Confirm what's right and reject what's wrong. Rule on at least **10** items.
> 6. Find where the two sources **disagree**, and tell us what the disagreement is.
>
> Think aloud if you can. We won't answer questions during the task. That's what we're measuring, not you.

**Why these two artifacts:** PR #1574 has 22 human comments, and pulled in about 4 minutes on 2026-08-21. The single Jira issue pulls in roughly a minute and a half. A whole epic took about 7 minutes, which would use too much of the 20 on waiting. The issue and the PR contain a real, planted disagreement: the ticket wants a shared link to carry the interval, while the PR deliberately keeps the interval at graph level. So step 6 has an answer.

## 4. Rules for whoever runs it

- **Say nothing about the product once the clock starts.** No hints, no "try the left rail", no nods. A question gets "do whatever you'd do if we weren't here".
- **Stop the clock** when the PM says they're done, or at **20:00**, whichever comes first. Don't extend.
- **If the PM is stuck for 3 minutes on one step** and asks to stop, mark the step failed, then help them so the rest can be observed. **Any help means the run fails the criterion**, whatever happens after.
- **Infrastructure faults are not the PM's failure, but they still count.** If a pull fails because of the database, model or network, record it and pause the clock. If the pause lasts more than 5 minutes, the run is void and gets rescheduled, not passed.
- **The in-product tour is allowed.** It's the product explaining itself. Record whether the PM took it, and the 20 minutes include it (`docs/decisions/2026-08-21-guided-tour-and-demo-readiness.md`).
- **Reading the task card isn't timed.** The clock starts when they first load the sign-in page.

## 5. Pre-registration: fill in before the session, then don't edit

- **PM** (role, how familiar with Jira and GitHub, ever seen Atlas: must be *no*):
- **Facilitator:**
- **Date and time:**
- **Credentials on the card instead of minted by the PM** (Jira / GitHub / none):
- **Pass** = all of the following, with no help:
  - signed in;
  - connected **both** sources;
  - pulled both artifacts;
  - ruled on **≥ 10** items;
  - all of it in **≤ 20:00** on the clock.
- **Secondary, reported but not part of pass/fail:**
  - Did they find the disagreement (step 6)?
  - How long was the wait on ingestion?
  - Did they take the tour?
  - How many rulings did they make, and what share were rejections?
- **One session is one data point.** A pass shows the criterion *can* be met. It doesn't show that it usually is. A fail shows exactly where the product loses people, which is worth as much.

## 6. Record sheet (fill in during the session)

| Time | Step / event | Note (what they said, where they hesitated) |
|---|---|---|
| 00:00 | Loads sign-in | |
| | Signed in | |
| | Product created | |
| | GitHub connected | |
| | PR pulled (ingestion started → finished) | |
| | Jira connected | |
| | Issue pulled (started → finished) | |
| | First ruling | |
| | 10th ruling | |
| | Found the disagreement? | |
| | Says done / 20:00 | |

Tour taken: Y / N · Help given: Y / N (at ___ , for ___ ) · Infrastructure pauses: ___

## 7. Afterwards

1. **Data the product records by itself:**
   - The PM's rulings are human events in the `PM measurement` workspace.
   - The Quality page shows acceptance at first human read, the first real number for that metric.
   - The admin Activity page shows the session's runs and rulings.
   - Screenshot both before anyone else signs into that workspace.
2. **Ask three questions, after the clock stops:**
   - What was the hardest moment?
   - What did you expect to happen that didn't?
   - Would you use this on your own team's work, and on what?
3. **Write it up** in `docs/research/phase1-pm-measurement-v1.md`:
   - the pre-registration (§5) unchanged;
   - the record sheet;
   - pass or fail;
   - the three answers.
   - Then update `docs/tracker.md`. A fail is a result too. It names the next piece of Phase 1 work.
