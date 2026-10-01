"""Tests for `scripts/proof.py` -- the Phase 2B measurement harness.

Roadmap v2 2B holds the proof to the standard `writing-evals` holds extraction
to: rubric pre-registered before any result, blind grading, N >= 5. These tests
pin the mechanics that make those words true rather than aspirational -- the
lock, the blinding, the control never seeing the answer, and the arithmetic.
They say nothing about whether the thesis holds; only the run does.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.proof import (
    Grade,
    LockError,
    Packet,
    ProofFeature,
    Rubric,
    blind,
    build_prompts,
    lock,
    score,
    sign_test,
    verify_lock,
)

RUBRIC = Rubric.model_validate(
    {
        "criteria": [
            {"id": "correct", "question": "Does it do what was built?", "min": 0, "max": 4},
            {"id": "scope", "question": "Does it avoid building what was not?", "min": 0, "max": 2},
        ],
        "min_mean_difference": 1.0,
        "alpha": 0.1,
    }
)

RAW = {
    "repo": "BurntSushi/ripgrep",
    "pr_number": 111,
    "pull_request": {
        "title": "Max depth option",
        "body": "Closes #109",
        "comments": [{"author": "burntsushi", "body": "Match GNU find semantics."}],
    },
    "linked_issues": [{"number": 109, "title": "Skip deep dirs", "body": "Add --maxdepth."}],
    "commits": [{"sha": "abc123", "message": "SECRET ANSWER: add max_depth to walker"}],
}


def _feature(name: str = "pr-111") -> ProofFeature:
    return ProofFeature(
        name=name, raw=RAW, spec="# ripgrep\n\n**Readiness: 75/100**\n- Add --maxdepth"
    )


# --- prompts: the control never sees the answer --------------------------------


def test_the_control_gets_the_artifact_but_never_its_commits() -> None:
    control = build_prompts(_feature()).control

    assert "Max depth option" in control
    assert "Match GNU find semantics." in control
    assert "Add --maxdepth." in control
    assert "SECRET ANSWER" not in control


def test_the_treatment_gets_the_spec_including_readiness_and_not_the_raw() -> None:
    """Pre-registration states the readiness score is part of the treatment."""
    treatment = build_prompts(_feature()).treatment

    assert "Readiness: 75/100" in treatment
    assert "Match GNU find semantics." not in treatment
    assert "SECRET ANSWER" not in treatment


def test_both_conditions_share_one_task_instruction() -> None:
    prompts = build_prompts(_feature())

    assert prompts.control.startswith(prompts.task)
    assert prompts.treatment.startswith(prompts.task)


# --- the lock: pre-registration before any result ------------------------------


def test_a_lock_verifies_while_the_preregistration_is_unchanged(tmp_path: Path) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("rubric v1")
    lock_file = lock(prereg, tmp_path / "lock.json")

    verify_lock(prereg, lock_file)


def test_editing_the_preregistration_after_locking_is_refused(tmp_path: Path) -> None:
    prereg = tmp_path / "prereg.md"
    prereg.write_text("rubric v1")
    lock_file = lock(prereg, tmp_path / "lock.json")
    prereg.write_text("rubric v1, adjusted after peeking")

    with pytest.raises(LockError):
        verify_lock(prereg, lock_file)


def test_locking_twice_is_refused(tmp_path: Path) -> None:
    """Re-locking is how a rubric gets quietly moved; it must be a deliberate
    act (delete the lock, and say so in the write-up), not a command."""
    prereg = tmp_path / "prereg.md"
    prereg.write_text("rubric v1")
    lock(prereg, tmp_path / "lock.json")

    with pytest.raises(LockError):
        lock(prereg, tmp_path / "lock.json")


# --- blinding ------------------------------------------------------------------


def _outputs() -> dict[tuple[str, str], str]:
    return {
        (f"f{i}", condition): f"diff for f{i} {condition}"
        for i in range(5)
        for condition in ("control", "treatment")
    }


def test_packets_do_not_reveal_their_condition() -> None:
    packets, _ = blind(_outputs(), seed=7)

    for packet in packets:
        assert "control" not in packet.id and "treatment" not in packet.id
        assert set(packet.model_dump()) == {"id", "feature", "output"}


def test_the_key_maps_every_packet_back_to_its_condition() -> None:
    packets, key = blind(_outputs(), seed=7)

    for packet in packets:
        assert _outputs()[(packet.feature, key[packet.id])] == packet.output


def test_blinding_is_reproducible_from_its_seed_and_varies_across_seeds() -> None:
    first, _ = blind(_outputs(), seed=7)
    again, _ = blind(_outputs(), seed=7)
    other, _ = blind(_outputs(), seed=8)

    assert [p.id for p in first] == [p.id for p in again]
    assert [p.output for p in first] != [p.output for p in other]


# --- scoring -------------------------------------------------------------------


def _grades(key: dict[str, str], treatment: int, control: int) -> list[Grade]:
    return [
        Grade(
            packet_id=packet_id,
            scores={"correct": treatment if cond == "treatment" else control, "scope": 1},
        )
        for packet_id, cond in key.items()
    ]


def test_a_consistent_win_on_five_features_is_reported_with_its_p_value() -> None:
    packets, key = blind(_outputs(), seed=7)

    result = score(RUBRIC, packets, key, _grades(key, treatment=4, control=2))

    assert result.n == 5
    assert (result.wins, result.losses, result.ties) == (5, 0, 0)
    assert result.mean_difference == 2.0
    assert result.p_value == pytest.approx(0.0625)
    assert result.meaningful


def test_a_null_result_is_reported_as_one_not_hidden() -> None:
    """A null result closes the phase legitimately (roadmap v2)."""
    packets, key = blind(_outputs(), seed=7)

    result = score(RUBRIC, packets, key, _grades(key, treatment=2, control=2))

    assert (result.wins, result.losses, result.ties) == (0, 0, 5)
    assert not result.meaningful
    assert "null" in result.verdict.lower()


def test_fewer_than_five_features_cannot_be_meaningful() -> None:
    outputs = {k: v for k, v in _outputs().items() if k[0] in {"f0", "f1", "f2"}}
    packets, key = blind(outputs, seed=7)

    result = score(RUBRIC, packets, key, _grades(key, treatment=4, control=0))

    assert not result.meaningful
    assert "n=3" in result.verdict


def test_a_missing_grade_is_refused() -> None:
    packets, key = blind(_outputs(), seed=7)

    with pytest.raises(ValueError, match="ungraded"):
        score(RUBRIC, packets, key, _grades(key, 4, 2)[1:])


def test_a_score_outside_the_rubric_scale_is_refused() -> None:
    packets, key = blind(_outputs(), seed=7)
    grades = _grades(key, treatment=9, control=2)

    with pytest.raises(ValueError, match="outside"):
        score(RUBRIC, packets, key, grades)


def test_sign_test_is_exact_and_two_sided() -> None:
    assert sign_test(5, 0) == pytest.approx(0.0625)
    assert sign_test(4, 1) == pytest.approx(0.375)
    assert sign_test(0, 0) == 1.0


def test_the_result_serializes_for_the_write_up() -> None:
    packets, key = blind(_outputs(), seed=7)
    result = score(RUBRIC, packets, key, _grades(key, 4, 2))

    assert json.loads(result.model_dump_json())["n"] == 5


# --- curation, spec building, judging, and the agent's file gate (2026-09-30) ----

import asyncio  # noqa: E402
import uuid  # noqa: E402

from atlas.models.schema import Node, NodeType, SourceRef, SourceType  # noqa: E402
from scripts.proof import (  # noqa: E402
    Curation,
    build_spec,
    curate,
    judge,
    workdir_gate,
)


def _claim(content: str, node_type: NodeType = NodeType.GOAL) -> Node:
    return Node(
        type=node_type,
        content=content,
        confidence_score=0.9,
        source_refs=[
            SourceRef(
                source_type=SourceType.GITHUB_PR,
                external_id="BurntSushi/ripgrep#2957",
                url="https://github.com/BurntSushi/ripgrep/pull/2957",
                excerpt=content.lower(),
                workspace_id=uuid.UUID(int=0),
            )
        ],
        workspace_id=uuid.UUID(int=0),
        feature_scope_id=uuid.uuid4(),
    )


def _reply(payload: object):  # type: ignore[no-untyped-def]
    seen: list[str] = []

    async def call(prompt: str) -> str:
        seen.append(prompt)
        return json.dumps(payload)

    return call, seen


def test_curation_must_account_for_every_claim_once() -> None:
    keep, drop = _claim("Support dynamic zsh sourcing"), _claim("Next release date unknown")
    call, seen = _reply(
        {"keep": [str(keep.id)], "reject": [{"id": str(drop.id), "reason": "off-topic"}]}
    )

    curation = asyncio.run(curate(_feature(), [keep, drop], call))

    assert curation.kept == (keep.id,)
    assert curation.rejected == ((drop.id, "off-topic"),)
    # The curator sees what the control sees -- never the commits.
    assert "SECRET ANSWER" not in seen[0]


def test_curation_that_invents_or_omits_a_claim_is_refused() -> None:
    real = _claim("Support dynamic zsh sourcing")
    invented, _ = _reply({"keep": [str(uuid.uuid4())], "reject": []})
    omitted, _ = _reply({"keep": [], "reject": []})

    with pytest.raises(ValueError, match="not a claim"):
        asyncio.run(curate(_feature(), [real], invented))
    with pytest.raises(ValueError, match="unaccounted"):
        asyncio.run(curate(_feature(), [real], omitted))


def test_the_spec_holds_only_kept_claims_and_its_readiness_block() -> None:
    keep = _claim("Support dynamic zsh sourcing")
    drop = _claim("Next release date unknown", NodeType.OPEN_QUESTION)

    spec = build_spec(
        "rg-2957",
        "zsh completion",
        [keep, drop],
        [],
        Curation(kept=(keep.id,), rejected=((drop.id, "x"),)),
    )

    assert "Support dynamic zsh sourcing" in spec
    assert "Next release date unknown" not in spec
    assert "Readiness:" in spec
    # Provenance travels into the spec exactly as in a real export.
    assert "https://github.com/BurntSushi/ripgrep/pull/2957" in spec


def test_the_judge_is_blind_and_its_scores_are_range_checked() -> None:
    packet = Packet(id="abc123", feature="rg-2957", output="diff --git a/x b/x")
    call, seen = _reply({"scores": {"correct": 3, "scope": 2}, "rationale": "close"})

    grade = asyncio.run(judge(packet, "diff --git merged", RUBRIC, call))

    assert grade.packet_id == "abc123"
    assert grade.scores == {"correct": 3, "scope": 2}
    assert "control" not in seen[0].lower() and "treatment" not in seen[0].lower()
    assert "diff --git merged" in seen[0] and "diff --git a/x b/x" in seen[0]

    bad, _ = _reply({"scores": {"correct": 9, "scope": 2}, "rationale": ""})
    with pytest.raises(ValueError, match="outside"):
        asyncio.run(judge(packet, "m", RUBRIC, bad))


def test_the_coding_agent_may_only_touch_files_inside_its_checkout(tmp_path: Path) -> None:
    gate = workdir_gate(tmp_path)

    async def decide(tool: str, args: dict[str, object]) -> str:
        return str((await gate(tool, args, None)).behavior)

    inside = str(tmp_path / "src" / "main.rs")
    assert asyncio.run(decide("Edit", {"file_path": inside})) == "allow"
    assert asyncio.run(decide("Grep", {"pattern": "x", "path": str(tmp_path)})) == "allow"
    assert asyncio.run(decide("Write", {"file_path": "/etc/passwd"})) == "deny"
    assert asyncio.run(decide("Read", {"file_path": str(tmp_path / ".." / "x")})) == "deny"
    assert asyncio.run(decide("Bash", {"command": "ls"})) == "deny"


def test_reaching_the_turn_cap_ends_the_run_rather_than_the_experiment() -> None:
    """The cap is the budget: at the cap the agent's answer is whatever it
    changed so far. Found live 2026-09-30 -- the SDK raises at the cap, which
    crashed the whole run before any diff was saved."""
    from scripts.proof import turn_cap_reached

    assert turn_cap_reached(
        Exception("Claude Code returned an error result: Reached maximum number of turns (40)")
    )
    assert not turn_cap_reached(Exception("rate limited"))


def test_the_prompt_stream_stays_open_until_the_session_ends() -> None:
    """Found live 2026-09-30: a stream that ends after its one message closes
    the SDK's input channel, and every permission request -- i.e. every Edit --
    then fails with "Stream closed". The agent could read but never write."""
    from scripts.proof import held_stream

    async def scenario() -> list[str]:
        done = asyncio.Event()
        stream = held_stream("do the task", done)
        events = [str((await stream.__anext__())["message"]["content"])]
        pending = asyncio.ensure_future(stream.__anext__())
        await asyncio.sleep(0.01)
        events.append("still open" if not pending.done() else "closed early")
        done.set()
        try:
            await pending
        except StopAsyncIteration:
            events.append("closed after done")
        return events

    assert asyncio.run(scenario()) == ["do the task", "still open", "closed after done"]


def test_an_infrastructure_error_is_retried_from_scratch_and_counted(tmp_path: Path) -> None:
    """Found live 2026-10-01: the CLI ended a session with an error result
    ("Claude Code returned an error result: success") and no answer. Such a
    session is rerun from a fresh checkout, at most twice, and every attempt is
    recorded -- the same rule for both conditions."""
    from scripts.proof import attempt_with_retries

    calls: list[int] = []

    async def flaky(attempt: int) -> str:
        calls.append(attempt)
        if attempt < 2:
            raise Exception("Claude Code returned an error result: success")
        return "diff --git a/x b/x"

    diff, attempts = asyncio.run(attempt_with_retries(flaky, retries=2))

    assert (diff, attempts, calls) == ("diff --git a/x b/x", 3, [0, 1, 2])


def test_retries_are_bounded() -> None:
    from scripts.proof import attempt_with_retries

    async def always(attempt: int) -> str:
        raise Exception("Claude Code returned an error result: success")

    with pytest.raises(Exception, match="error result"):
        asyncio.run(attempt_with_retries(always, retries=2))
