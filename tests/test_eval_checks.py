"""Unit tests for the inline `check:` judges in eval/eval.yaml.

These run the check source straight out of the config, so they fail if the YAML
drifts from what they assert.
"""
import json
import os

import pytest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EVAL_YAML = os.path.join(PROJECT_ROOT, "eval", "eval.yaml")

SESSION = "11111111-2222-3333-4444-555555555555"
OTHER_SESSION = "99999999-8888-7777-6666-555555555555"

# Long enough to clear MIN_RESULT_CHARS — stands in for a real architecture doc.
DOC = "RHOAI platform architecture. " * 20
# What an empty context directory actually returned in the 2026-08-11 run.
EMPTY_LISTING = "No files found"


def _load_check(name):
    with open(EVAL_YAML) as f:
        config = yaml.safe_load(f)
    judge = next(j for j in config["judges"] if j["name"] == name)
    body = "".join("    " + ln + "\n" for ln in judge["check"].splitlines())
    namespace = {}
    exec("def _check(outputs):\n" + body, namespace)
    return namespace["_check"]


def _write_case(tmp_path, results, session=SESSION, tool="Read"):
    """Build a case dir whose refine subagent made one read per entry in results.

    Each entry is (content, is_error).
    """
    case_dir = tmp_path / "case"
    step_dir = case_dir / "steps" / "refine"
    step_dir.mkdir(parents=True)
    (step_dir / "stdout.log").write_text(
        json.dumps({"type": "system", "session_id": session}) + "\n")

    events = [{"sessionId": session, "type": "user", "message": {"content": []}}]
    for index, (content, is_error) in enumerate(results):
        call_id = "toolu_{}".format(index)
        events.append({
            "sessionId": session,
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use",
                "id": call_id,
                "name": tool,
                "input": {"file_path": ".context/architecture-context/PLATFORM.md"},
            }]},
        })
        block = {"type": "tool_result", "tool_use_id": call_id, "content": content}
        if is_error:
            block["is_error"] = True
        events.append({
            "sessionId": session,
            "type": "user",
            "message": {"content": [block]},
        })

    subagents = case_dir / "subagents"
    subagents.mkdir()
    with open(subagents / "refine.jsonl", "w") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return case_dir


@pytest.fixture
def check():
    return _load_check("architecture_context_used")


def test_passes_when_a_read_returns_real_documentation(check, tmp_path):
    case_dir = _write_case(tmp_path, [(DOC, False)])

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is True
    assert "1 of 1" in rationale


def test_fails_when_every_read_comes_back_empty(check, tmp_path):
    """The 2026-08-11 failure: six reads, all attempted, none returned anything.

    Counting tool_use blocks scored this 100%. Counting results scores it 0.
    """
    case_dir = _write_case(tmp_path, [(EMPTY_LISTING, False)] * 6)

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is False
    assert "0 of 6" in rationale


def test_errored_reads_do_not_count(check, tmp_path):
    case_dir = _write_case(tmp_path, [(DOC, True)])

    value, _ = check({"case_dir": str(case_dir)})

    assert value is False


def test_mixed_results_pass_on_the_substantive_one(check, tmp_path):
    case_dir = _write_case(
        tmp_path, [(EMPTY_LISTING, False), (DOC, False), (DOC, True)])

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is True
    assert "1 of 3" in rationale


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Bash"])
def test_every_read_tool_counts(check, tmp_path, tool):
    case_dir = _write_case(tmp_path, [(DOC, False)], tool=tool)

    value, _ = check({"case_dir": str(case_dir)})

    assert value is True


def test_reads_from_another_session_are_not_credited(check, tmp_path):
    """Reviewer transcripts land in the same directory; only refine's count."""
    case_dir = _write_case(tmp_path, [(DOC, False)], session=OTHER_SESSION)
    step_log = case_dir / "steps" / "refine" / "stdout.log"
    step_log.write_text(json.dumps({"type": "system", "session_id": SESSION}) + "\n")

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is False
    assert "no subagent transcript belongs to the refine session" in rationale


def test_fails_closed_without_a_step_log(check, tmp_path):
    case_dir = tmp_path / "case"
    case_dir.mkdir()

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is False
    assert "stdout.log" in rationale


def test_fails_closed_without_subagent_transcripts(check, tmp_path):
    case_dir = _write_case(tmp_path, [(DOC, False)])
    os.remove(case_dir / "subagents" / "refine.jsonl")

    value, rationale = check({"case_dir": str(case_dir)})

    assert value is False
    assert "no subagent transcripts" in rationale
