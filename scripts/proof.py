"""Phase 2B harness: does an Atlas spec improve what a coding agent builds?

Roadmap v2 2B, held to the standard `writing-evals` holds extraction to. The
mechanics here are what make "pre-registered, blind, N >= 5" true rather than
aspirational; none of them decides the answer.

    prepare  control + treatment prompts per feature        (build_prompts)
    lock     hash the pre-registration before any run       (lock / verify_lock)
    run      a coding agent per prompt -> one diff each      (run_agent; costs tokens)
    blind    shuffle outputs into opaque packets + a key     (blind)
    grade    a human scores packets against the rubric       (outside this file)
    score    unblind, pair, sign-test, verdict               (score)

**Control** is the artifact as a coding agent would otherwise get it: the PR's
title, body and comments and its linked issues. It **never** includes the
commits -- they are what was actually built, i.e. the answer being graded
against. **Treatment** is the Atlas spec Markdown for the same feature, readiness
block included: pre-registration must say the readiness score is part of the
treatment (roadmap v2 `[+2026-09-02]`), so provenance and gap-flagging are one
treatment and cannot be told apart afterwards.

Lives in `scripts/`, not `src/atlas/`: it is a measurement of the product, not
part of it, and nothing in the product imports it.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

CONDITIONS = ("control", "treatment")

#: Roadmap v2: "on >= 5 features". Below this a result is reported, never called
#: meaningful.
MIN_FEATURES = 5

TASK = (
    "You are working in the repository checked out in the current directory, at the "
    "commit before this feature was built. Implement the feature described below. "
    "Change only what the feature requires. When you are done, stop; your working "
    "tree diff is your answer.\n\n"
)


# --- rubric --------------------------------------------------------------------


class Criterion(BaseModel):
    id: str
    question: str
    min: int = 0
    max: int

    @model_validator(mode="after")
    def _scale(self) -> Criterion:
        if self.max <= self.min:
            raise ValueError(f"criterion {self.id}: max must exceed min")
        return self


class Rubric(BaseModel):
    """The pre-registered rubric. A packet's score is the sum of its criteria."""

    criteria: list[Criterion] = Field(min_length=1)
    #: Treatment must beat control by at least this much on average -- stated
    #: before any run, so "meaningfully higher" cannot be decided afterwards.
    min_mean_difference: float = Field(gt=0)
    #: Significance threshold for the exact two-sided sign test.
    alpha: float = Field(gt=0, lt=1)


# --- prompts -------------------------------------------------------------------


class ProofFeature(BaseModel):
    """One feature: the golden fixture's raw artifact and its Atlas spec."""

    name: str
    raw: dict[str, Any]
    spec: str


class Prompts(BaseModel):
    task: str
    control: str
    treatment: str


def build_prompts(feature: ProofFeature) -> Prompts:
    return Prompts(
        task=TASK,
        control=TASK + _artifact_text(feature.raw),
        treatment=TASK + feature.spec,
    )


def _artifact_text(raw: dict[str, Any]) -> str:
    """The artifact as a coding agent would otherwise see it -- deliberately
    without `commits`, which hold the answer."""
    pr = raw.get("pull_request", {})
    lines = [f"# {pr.get('title', '')}", "", pr.get("body", "") or "", ""]
    for comment in pr.get("comments", []) or []:
        lines += [f"**{comment.get('author', 'someone')}:** {comment.get('body', '')}", ""]
    for issue in raw.get("linked_issues", []) or []:
        lines += [
            f"## Linked issue #{issue.get('number')}: {issue.get('title', '')}",
            "",
            issue.get("body", "") or "",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


# --- lock ----------------------------------------------------------------------


class LockError(RuntimeError):
    """The pre-registration moved after it was locked, or was locked twice."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock(prereg: Path, lock_file: Path) -> Path:
    """Record the pre-registration's hash. Refuses to overwrite: re-locking is
    how a rubric gets quietly moved, so it must be a deliberate, recorded act."""
    if lock_file.exists():
        raise LockError(f"{lock_file} already exists; the pre-registration is locked")
    lock_file.write_text(
        json.dumps(
            {"sha256": _digest(prereg), "locked_at": datetime.now(UTC).isoformat()}, indent=2
        )
    )
    return lock_file


def verify_lock(prereg: Path, lock_file: Path) -> None:
    locked = json.loads(lock_file.read_text())["sha256"]
    if _digest(prereg) != locked:
        raise LockError(f"{prereg} changed after it was locked; results cannot be scored")


# --- blinding ------------------------------------------------------------------


class Packet(BaseModel):
    """What a grader sees: an opaque id, the feature, and the output. Nothing
    else -- in particular no condition, and no ordering that implies one."""

    id: str
    feature: str
    output: str


def blind(outputs: dict[tuple[str, str], str], *, seed: int) -> tuple[list[Packet], dict[str, str]]:
    """Shuffle outputs into packets and return them with the sealed key
    (packet id -> condition). Ids are random tokens from `seed`, so a run is
    reproducible by whoever holds the seed and opaque to whoever does not."""
    rng = random.Random(seed)
    items = list(outputs.items())
    rng.shuffle(items)
    packets: list[Packet] = []
    key: dict[str, str] = {}
    for (feature, condition), output in items:
        packet_id = f"{rng.getrandbits(48):012x}"
        packets.append(Packet(id=packet_id, feature=feature, output=output))
        key[packet_id] = condition
    return packets, key


# --- scoring -------------------------------------------------------------------


class Grade(BaseModel):
    packet_id: str
    scores: dict[str, int]


class FeatureResult(BaseModel):
    feature: str
    control: int
    treatment: int
    difference: int


class ProofResult(BaseModel):
    n: int
    features: list[FeatureResult]
    wins: int
    losses: int
    ties: int
    mean_difference: float
    p_value: float
    meaningful: bool
    verdict: str


def sign_test(wins: int, losses: int) -> float:
    """Exact two-sided sign test; ties are excluded before calling. Chosen for
    N >= 5 because it assumes nothing about the score distribution."""
    trials = wins + losses
    if trials == 0:
        return 1.0
    extreme = min(wins, losses)
    tail: float = sum(math.comb(trials, k) for k in range(extreme + 1)) / float(2**trials)
    return min(1.0, 2 * tail)


def score(
    rubric: Rubric,
    packets: list[Packet],
    key: dict[str, str],
    grades: list[Grade],
) -> ProofResult:
    by_packet = {grade.packet_id: grade for grade in grades}
    missing = [packet.id for packet in packets if packet.id not in by_packet]
    if missing:
        raise ValueError(f"{len(missing)} packet(s) ungraded: {missing[:3]}")

    totals: dict[str, dict[str, int]] = {}
    for packet in packets:
        total = _total(rubric, by_packet[packet.id])
        totals.setdefault(packet.feature, {})[key[packet.id]] = total

    features = [
        FeatureResult(
            feature=name,
            control=pair["control"],
            treatment=pair["treatment"],
            difference=pair["treatment"] - pair["control"],
        )
        for name, pair in sorted(totals.items())
    ]
    wins = sum(result.difference > 0 for result in features)
    losses = sum(result.difference < 0 for result in features)
    ties = len(features) - wins - losses
    mean = sum(result.difference for result in features) / len(features) if features else 0.0
    p_value = sign_test(wins, losses)
    enough = len(features) >= MIN_FEATURES
    meaningful = enough and mean >= rubric.min_mean_difference and p_value <= rubric.alpha

    if not enough:
        verdict = (
            f"Inconclusive: n={len(features)}, below the pre-registered minimum of {MIN_FEATURES}."
        )
    elif meaningful:
        verdict = (
            f"Treatment beat control by {mean:.2f} on average ({wins}-{losses}-{ties}, "
            f"p={p_value:.3f}), meeting the pre-registered margin."
        )
    else:
        verdict = (
            f"Null result: mean difference {mean:.2f} ({wins}-{losses}-{ties}, "
            f"p={p_value:.3f}) does not meet the pre-registered margin of "
            f"{rubric.min_mean_difference} at alpha={rubric.alpha}. Write it down and "
            f"revise the thesis."
        )
    return ProofResult(
        n=len(features),
        features=features,
        wins=wins,
        losses=losses,
        ties=ties,
        mean_difference=mean,
        p_value=p_value,
        meaningful=meaningful,
        verdict=verdict,
    )


def _total(rubric: Rubric, grade: Grade) -> int:
    total = 0
    for criterion in rubric.criteria:
        if criterion.id not in grade.scores:
            raise ValueError(f"packet {grade.packet_id} has no score for {criterion.id}")
        value = grade.scores[criterion.id]
        if not criterion.min <= value <= criterion.max:
            raise ValueError(
                f"packet {grade.packet_id}: {criterion.id}={value} is outside "
                f"{criterion.min}..{criterion.max}"
            )
        total += value
    return total


# --- running and the command line ----------------------------------------------
#
# Everything below touches the filesystem, git, or a model, and is exercised by
# running it rather than by unit tests. The layout it reads and writes:
#
#     proof/preregistration.md    the rubric + design, written by a person
#     proof/lock.json             written once by `lock`
#     proof/features.json         [{"name", "fixture", "base_sha", "merged_sha"}]
#     proof/specs/<name>.md       the Atlas spec export for that feature, taken
#                                 after a person confirmed its claims
#     proof/runs/<name>/          prompts and diffs per condition
#     proof/packets.json          what graders see
#     proof/key.json              sealed until grading is complete
#     proof/grades.json           [{"packet_id", "scores": {criterion: int}}]

GOLDEN = Path("tests/evals/golden_set")


class ManifestEntry(BaseModel):
    name: str
    fixture: str
    #: The commit the agent starts from -- the merged PR's parent.
    base_sha: str
    #: What was actually built; graders compare each packet against its diff.
    merged_sha: str


def _manifest(root: Path) -> list[ManifestEntry]:
    entries = [
        ManifestEntry.model_validate(e) for e in json.loads((root / "features.json").read_text())
    ]
    return entries


def prepare(root: Path) -> None:
    for entry in _manifest(root):
        feature = ProofFeature(
            name=entry.name,
            raw=json.loads((GOLDEN / entry.fixture / "raw.json").read_text()),
            spec=(root / "specs" / f"{entry.name}.md").read_text(),
        )
        prompts = build_prompts(feature)
        out = root / "runs" / entry.name
        out.mkdir(parents=True, exist_ok=True)
        (out / "control.prompt.md").write_text(prompts.control)
        (out / "treatment.prompt.md").write_text(prompts.treatment)


async def run_agent(prompt: str, repo: Path, base_sha: str, workdir: Path, model: str) -> str:
    """One coding-agent run in a fresh worktree at `base_sha`; returns its diff.

    Both conditions get the same model, tools, and budget -- the prompt is the
    only thing that differs, which is what makes the comparison a comparison.
    """
    import subprocess

    from claude_agent_sdk import ClaudeAgentOptions, query

    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(workdir), base_sha],
        check=True,
        capture_output=True,
    )
    try:
        options = ClaudeAgentOptions(
            model=model,
            cwd=str(workdir),
            permission_mode="acceptEdits",
            allowed_tools=["Read", "Glob", "Grep", "Edit", "Write"],
            max_turns=40,
        )
        async for _ in query(prompt=prompt, options=options):
            pass
        diff = subprocess.run(
            ["git", "-C", str(workdir), "diff"], check=True, capture_output=True, text=True
        )
        return diff.stdout
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(workdir)],
            capture_output=True,
        )


def run(root: Path, repo: Path, model: str) -> None:
    import asyncio
    import tempfile

    verify_lock(root / "preregistration.md", root / "lock.json")
    for entry in _manifest(root):
        out = root / "runs" / entry.name
        for condition in CONDITIONS:
            target = out / f"{condition}.diff"
            if target.exists():
                continue  # resumable: a finished run is never re-spent
            prompt = (out / f"{condition}.prompt.md").read_text()
            with tempfile.TemporaryDirectory() as scratch:
                diff = asyncio.run(
                    run_agent(prompt, repo, entry.base_sha, Path(scratch) / "wt", model)
                )
            target.write_text(diff)


def blind_runs(root: Path, seed: int) -> None:
    verify_lock(root / "preregistration.md", root / "lock.json")
    outputs = {
        (entry.name, condition): (root / "runs" / entry.name / f"{condition}.diff").read_text()
        for entry in _manifest(root)
        for condition in CONDITIONS
    }
    packets, key = blind(outputs, seed=seed)
    (root / "packets.json").write_text(json.dumps([p.model_dump() for p in packets], indent=2))
    (root / "key.json").write_text(json.dumps(key, indent=2))


def score_runs(root: Path, rubric: Path) -> ProofResult:
    verify_lock(root / "preregistration.md", root / "lock.json")
    packets = [Packet.model_validate(p) for p in json.loads((root / "packets.json").read_text())]
    key = json.loads((root / "key.json").read_text())
    grades = [Grade.model_validate(g) for g in json.loads((root / "grades.json").read_text())]
    result = score(Rubric.model_validate_json(rubric.read_text()), packets, key, grades)
    (root / "result.json").write_text(result.model_dump_json(indent=2))
    return result


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m scripts.proof", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("proof"))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="write control/treatment prompts per feature")
    commands.add_parser("lock", help="hash the pre-registration; refuses to re-lock")
    run_cmd = commands.add_parser("run", help="run the coding agent per prompt (costs tokens)")
    run_cmd.add_argument("--repo", type=Path, required=True, help="a local clone of the repo")
    run_cmd.add_argument("--model", default="claude-sonnet-5")
    blind_cmd = commands.add_parser("blind", help="shuffle diffs into packets + sealed key")
    blind_cmd.add_argument("--seed", type=int, required=True)
    score_cmd = commands.add_parser("score", help="unblind grades and compute the verdict")
    score_cmd.add_argument("--rubric", type=Path, required=True, help="rubric JSON")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        prepare(args.root)
    elif args.command == "lock":
        lock(args.root / "preregistration.md", args.root / "lock.json")
    elif args.command == "run":
        run(args.root, args.repo, args.model)
    elif args.command == "blind":
        blind_runs(args.root, args.seed)
    else:
        print(score_runs(args.root, args.rubric).verdict)


if __name__ == "__main__":
    main()
