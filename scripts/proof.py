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

import asyncio
import hashlib
import json
import math
import random
import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from atlas.assembly import assemble, to_markdown
from atlas.models.schema import (
    Edge,
    IngestionRunPayload,
    Node,
    NodeStatus,
    SourceType,
)
from atlas.storage.projections import FeatureScope, Product, Projection

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


# --- curation: the automated stand-in for a human review (2026-09-30) -----------
#
# The product's spec is built from *human-confirmed* claims. For this run the
# user delegated that review, and recording an automated choice as a human
# ruling in Atlas's log is the one thing `actor_kind` exists to prevent -- so
# curation happens here, in memory, and the pre-registration states it: the
# treatment is "an Atlas spec curated by Claude". The curator sees exactly what
# the control agent sees (never the commits), so knowledge of what was built
# cannot leak into the spec.

CURATOR_PROMPT = """\
You are reviewing claims that were automatically extracted from a GitHub pull
request thread, as the reviewer of a product spec would. For each claim decide:
KEEP it if the source text below supports it and it would help an engineer
build this feature correctly; REJECT it if it is unsupported, speculative, a
duplicate of another claim, or irrelevant to building the feature (for example
release timing or thanks). Judge only from the source text given -- you are not
told how the feature was eventually built.

Reply with one JSON object and nothing else:
{"keep": ["<claim id>", ...], "reject": [{"id": "<claim id>", "reason": "<short>"}, ...]}
Every claim id must appear exactly once, in keep or in reject.
"""


class Curation(BaseModel):
    kept: tuple[uuid.UUID, ...]
    rejected: tuple[tuple[uuid.UUID, str], ...]


TextCall = Callable[[str], Awaitable[str]]


def _json_reply(text: str) -> Any:
    body = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
    return json.loads(fenced.group(1) if fenced else body)


async def curate(feature: ProofFeature, nodes: list[Node], call: TextCall) -> Curation:
    listing = "\n".join(f"- id {node.id} ({node.type.value}): {node.content}" for node in nodes)
    reply = _json_reply(
        await call(
            f"{CURATOR_PROMPT}\n# Source\n\n{_artifact_text(feature.raw)}\n# Claims\n\n{listing}\n"
        )
    )
    known = {node.id for node in nodes}
    kept = [uuid.UUID(str(value)) for value in reply.get("keep", [])]
    rejected = [
        (uuid.UUID(str(item["id"])), str(item.get("reason", "")))
        for item in reply.get("reject", [])
    ]
    named = kept + [node_id for node_id, _ in rejected]
    strangers = [node_id for node_id in named if node_id not in known]
    if strangers:
        raise ValueError(f"curation named {strangers[0]}, which is not a claim of {feature.name}")
    if len(named) != len(set(named)) or set(named) != known:
        raise ValueError(f"curation left claims unaccounted for or named twice in {feature.name}")
    return Curation(kept=tuple(kept), rejected=tuple(rejected))


def build_spec(
    name: str, title: str, nodes: list[Node], edges: list[Edge], curation: Curation
) -> str:
    """The treatment: the product's own assembly and Markdown export, run over
    the curated claims -- kept ones marked confirmed, rejected ones rejected --
    in memory only. Nothing is written to Atlas's log."""
    product_id, scope_id = uuid.uuid5(uuid.NAMESPACE_URL, name), uuid.uuid4()
    kept, rejected = set(curation.kept), {node_id for node_id, _ in curation.rejected}
    status = {
        **dict.fromkeys(kept, NodeStatus.CONFIRMED),
        **dict.fromkeys(rejected, NodeStatus.REJECTED),
    }
    ruled = [
        node.model_copy(
            update={
                "status": status.get(node.id, NodeStatus.UNCONFIRMED),
                "feature_scope_id": scope_id,
            }
        )
        for node in nodes
    ]
    first = nodes[0].source_refs[0] if nodes else None
    scope = FeatureScope(
        id=scope_id,
        title=title,
        runs=(
            IngestionRunPayload(
                feature_scope_id=scope_id,
                title=title,
                source_type=first.source_type if first else SourceType.GITHUB_PR,
                external_id=first.external_id if first else name,
                url=first.url if first else "https://github.com",
                product_id=product_id,
            ),
        ),
        product_id=product_id,
        description=None,
    )
    projection = Projection(
        nodes={node.id: node for node in ruled},
        edges={edge.id: edge for edge in edges},
        feature_scopes={scope_id: scope},
        products={product_id: Product(id=product_id, name=title, description=None)},
    )
    return to_markdown(assemble(projection, product_id))


# --- judging --------------------------------------------------------------------

JUDGE_PROMPT = """\
You are grading a code change produced by a coding agent, against the change
that was actually merged for the same feature. You are not told how the agent
was instructed. Score each criterion on its integer scale, judging only the
candidate diff against the merged diff.

Reply with one JSON object and nothing else:
{"scores": {"<criterion id>": <int>, ...}, "rationale": "<two or three sentences>"}
"""


async def judge(packet: Packet, merged_diff: str, rubric: Rubric, call: TextCall) -> Grade:
    criteria = "\n".join(f"- {c.id} ({c.min}..{c.max}): {c.question}" for c in rubric.criteria)
    reply = _json_reply(
        await call(
            f"{JUDGE_PROMPT}\n# Criteria\n\n{criteria}\n\n# Merged diff\n\n{merged_diff}\n\n"
            f"# Candidate diff\n\n{packet.output or '(the agent changed nothing)'}\n"
        )
    )
    grade = Grade(packet_id=packet.id, scores={k: int(v) for k, v in reply["scores"].items()})
    _total(rubric, grade)  # raises on a missing criterion or an out-of-range score
    return grade


# --- the coding agent's file gate -------------------------------------------------

_FILE_TOOLS = {"Read": "file_path", "Edit": "file_path", "Write": "file_path"}
_SEARCH_TOOLS = {"Glob", "Grep"}


def workdir_gate(workdir: Path) -> Callable[[str, dict[str, Any], Any], Awaitable[Any]]:
    """`can_use_tool` for the coding agent: file tools only, and only inside its
    own scratch worktree. `acceptEdits` alone would let an edit land anywhere
    the process can write; this makes the checkout the whole world."""
    from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

    root = workdir.resolve()

    def inside(value: object) -> bool:
        if not isinstance(value, str) or not value:
            return False
        target = Path(value) if Path(value).is_absolute() else root / value
        return target.resolve().is_relative_to(root)

    async def gate(tool: str, args: dict[str, Any], context: Any) -> Any:
        if tool in _FILE_TOOLS and inside(args.get(_FILE_TOOLS[tool])):
            return PermissionResultAllow()
        if tool in _SEARCH_TOOLS and inside(args.get("path", str(root))):
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"{tool} is not allowed outside {root}")

    return gate


def text_call(system_prompt: str, model: str) -> TextCall:
    """One no-tool turn: the curator and the judge. Every tool is denied by a
    gate, with the prompt streamed so the gate is actually consulted."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    from atlas.qa import _deny_all, _stream

    options = ClaudeAgentOptions(
        model=model,
        system_prompt=system_prompt,
        can_use_tool=_deny_all,
        setting_sources=[],
        max_turns=1,
    )

    async def call(prompt: str) -> str:
        text = ""
        async for message in query(prompt=_stream(prompt), options=options):
            if isinstance(message, AssistantMessage):
                text = "".join(b.text for b in message.content if isinstance(b, TextBlock)) or text
        return text

    return call


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

    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "--detach", str(workdir), base_sha],
        check=True,
        capture_output=True,
    )
    try:
        options = ClaudeAgentOptions(
            model=model,
            cwd=str(workdir),
            # The gate is the authority: file tools only, only inside this
            # worktree. No `allowed_tools` -- pre-approval would bypass it.
            can_use_tool=workdir_gate(workdir),
            disallowed_tools=["Bash", "WebFetch", "WebSearch", "Task", "NotebookEdit"],
            setting_sources=[],
            max_turns=40,
        )
        done = asyncio.Event()
        try:
            async for message in query(prompt=held_stream(prompt, done), options=options):
                if isinstance(message, ResultMessage):
                    done.set()
        except Exception as stopped:  # noqa: BLE001 - only the turn cap is expected
            # The cap is the pre-registered budget, not a failure: the agent's
            # answer is whatever it has changed by then. Anything else re-raises.
            if not turn_cap_reached(stopped):
                raise
            (workdir.parent / "hit_turn_cap").write_text("1")
        finally:
            done.set()
        # Stage first: a plain `git diff` omits files the agent created, which
        # would silently drop part of its answer.
        subprocess.run(["git", "-C", str(workdir), "add", "-A"], check=True, capture_output=True)
        diff = subprocess.run(
            ["git", "-C", str(workdir), "diff", "--cached"],
            check=True,
            capture_output=True,
            text=True,
        )
        return diff.stdout
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(workdir)],
            capture_output=True,
        )


async def held_stream(prompt: str, done: asyncio.Event) -> AsyncIterator[dict[str, Any]]:
    """The prompt as streaming input, **held open until the session ends**.

    Required for the permission gate to work at all: the SDK closes its input
    channel when the prompt stream finishes, and Claude Code's permission
    requests travel back over that channel -- so a one-shot stream makes every
    gated tool (every Edit) fail with "Stream closed" (found live 2026-09-30;
    `proof/deviations.md` #3). Extraction never hit this because its in-process
    MCP server keeps the channel open.
    """
    yield {
        "type": "user",
        "session_id": "",
        "message": {"role": "user", "content": prompt},
        "parent_tool_use_id": None,
    }
    await done.wait()


def turn_cap_reached(error: BaseException) -> bool:
    """Whether the SDK stopped the agent because it used every turn."""
    return "maximum number of turns" in str(error)


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
                capped = (Path(scratch) / "hit_turn_cap").exists()
            target.write_text(diff)
            (out / f"{condition}.meta.json").write_text(
                json.dumps({"model": model, "hit_turn_cap": capped}, indent=2)
            )


def curate_all(root: Path, model: str) -> None:
    """Curate each feature's recorded claims and write its treatment spec.
    After `lock`: the curator prompt is part of what was pre-registered."""
    import asyncio

    verify_lock(root / "preregistration.md", root / "lock.json")
    call = text_call(CURATOR_PROMPT, model)
    (root / "curation").mkdir(exist_ok=True)
    (root / "specs").mkdir(exist_ok=True)
    for entry in _manifest(root):
        target = root / "specs" / f"{entry.name}.md"
        if target.exists():
            continue  # resumable
        raw = json.loads((GOLDEN / entry.fixture / "raw.json").read_text())
        extraction = json.loads((GOLDEN / entry.fixture / "extraction.json").read_text())
        nodes = [Node.model_validate(node) for node in extraction["nodes"]]
        edges = [Edge.model_validate(edge) for edge in extraction["edges"]]
        feature = ProofFeature(name=entry.name, raw=raw, spec="")
        curation = asyncio.run(curate(feature, nodes, call))
        (root / "curation" / f"{entry.name}.json").write_text(curation.model_dump_json(indent=2))
        title = str(raw.get("pull_request", {}).get("title") or entry.name)
        target.write_text(build_spec(entry.name, title, nodes, edges, curation))


def judge_runs(root: Path, repo: Path, rubric_path: Path, model: str) -> None:
    """Grade every packet blind against the merged diff. Needs the sealed key
    only to find the feature's merged diff -- never shown to the judge."""
    import asyncio
    import subprocess

    verify_lock(root / "preregistration.md", root / "lock.json")
    rubric = Rubric.model_validate_json(rubric_path.read_text())
    entries = {entry.name: entry for entry in _manifest(root)}
    packets = [Packet.model_validate(p) for p in json.loads((root / "packets.json").read_text())]
    call = text_call(JUDGE_PROMPT, model)
    grades: list[Grade] = []
    for packet in packets:
        entry = entries[packet.feature]
        merged = subprocess.run(
            ["git", "-C", str(repo), "diff", entry.base_sha, entry.merged_sha],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        grades.append(asyncio.run(judge(packet, merged, rubric, call)))
    (root / "grades.json").write_text(json.dumps([g.model_dump() for g in grades], indent=2))


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
    curate_cmd = commands.add_parser("curate", help="curate claims into treatment specs")
    curate_cmd.add_argument("--model", default="claude-opus-5")
    judge_cmd = commands.add_parser("judge", help="grade packets blind with a Claude judge")
    judge_cmd.add_argument("--repo", type=Path, required=True)
    judge_cmd.add_argument("--rubric", type=Path, required=True)
    judge_cmd.add_argument("--model", default="claude-opus-5")
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
    elif args.command == "curate":
        curate_all(args.root, args.model)
    elif args.command == "judge":
        judge_runs(args.root, args.repo, args.rubric, args.model)
    elif args.command == "blind":
        blind_runs(args.root, args.seed)
    else:
        print(score_runs(args.root, args.rubric).verdict)


if __name__ == "__main__":
    main()
