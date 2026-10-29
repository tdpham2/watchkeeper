"""CG1 tests use fake executables, loopback HTTP and real stdio MCP only."""

import asyncio
import importlib
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import pytest

from watchkeeper.actions import ProposalRequest


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="POSIX probe")


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "tools"))
    return importlib.import_module("chemgraph_contract")


@pytest.fixture
def executable(tmp_path):
    def create(mode="normal"):
        path = tmp_path / (mode + " CLI with spaces")
        path.write_text(f"#!{sys.executable}\nMODE = {mode!r}\n" +
                        (ROOT / "tests/fixtures/chemgraph_cli.py").read_text())
        path.chmod(0o700)
        return path
    return create


def test_fake_cli_full_contract(harness, executable, tmp_path, monkeypatch):
    def no_dns(*args):
        pytest.fail("Loopback fixture startup must not perform DNS lookups")
    monkeypatch.setattr(socket, "getfqdn", no_dns)
    scratch = tmp_path / "scratch 'with spaces"
    scratch.mkdir()
    monkeypatch.setattr(harness.tempfile, "tempdir", str(scratch))
    for key in ("CG1_SECRET", "OPENAI_API_KEY", "HTTP_PROXY", "PYTHONPATH"):
        monkeypatch.setenv(key, "must-not-reach-child")
    report = harness.probe(executable(), tmp_path / "evidence")
    assert report["evidence"] == "harness-only"
    assert report["blockers"] == [], json.dumps(report, indent=2)
    assert len(report["cases"]) == 7
    success = report["cases"][0]
    assert success["request_count"] == 3
    assert success["tool_names"] == [["get_brief", "propose_actions"]] * 3
    assert json.loads((tmp_path / "evidence/result.json").read_text()) == report
    requests = json.loads((tmp_path / "evidence/success-6-requests.json").read_text())
    proposal = requests[0]["body"]["tools"][1]["function"]["parameters"]
    assert set(proposal["required"]) == {"request_id", "actions"}
    assert proposal["additionalProperties"] is False
    assert proposal == ProposalRequest.model_json_schema()
    proposal["properties"]["actions"]["items"]["discriminator"]["propertyName"] = "type"
    mismatch = harness.inspect_case("success", success["process"], requests,
                                    success["events"], success["probe_id"], 6)
    assert "proposal_schema" in mismatch["blockers"]
    delivered = next(e["arguments"] for e in success["events"]
                     if e["event"] == "propose_actions")
    assert [a["kind"] for a in delivered["actions"]] == ["run", "note", "ask_human", "stop"]
    events = [dict(e) for e in success["events"]]
    events[-1]["probe_id"] = "wrong-identity"
    mismatch = harness.inspect_case("success", success["process"], requests, events,
                                    success["probe_id"], 6)
    assert "reconnect_identity" in mismatch["blockers"]
    assert not list(tmp_path.rglob("*.db"))
    with pytest.raises(FileExistsError):
        harness.probe(executable(), tmp_path / "evidence")


@pytest.mark.parametrize(("mode", "scenario", "blocker"), [
    ("leak_tool", "success", "tool_isolation"),
    ("silent_error", "provider_error", "failure_exit"),
    ("retry_excess", "provider_error", "request_bound"),
])
def test_incompatibilities_are_blockers(harness, executable, tmp_path, mode, scenario, blocker):
    report = harness.probe(executable(mode), tmp_path / "evidence", scenarios=[scenario])
    assert any(b.endswith(blocker) for b in report["blockers"])


@pytest.mark.parametrize("mode", ["missing", "unsupported"])
def test_preflight_stops_before_model(harness, executable, tmp_path, mode, monkeypatch):
    def unexpected(*args):
        pytest.fail("Preflight failure must prevent model startup")
    monkeypatch.setattr(harness, "model_endpoint", unexpected)
    cli = tmp_path / "absent" if mode == "missing" else executable(mode)
    report = harness.probe(cli, tmp_path / "evidence")
    assert report["blockers"] and report["cases"] == []


def test_missing_version_is_observed_not_invented(harness, executable, tmp_path):
    report = harness.probe(executable("versionless"), tmp_path / "evidence", scenarios=[])
    assert report["version"]["exit"] == 2
    assert report["provenance_supplied"] == "unspecified"
    assert report["blockers"] == []


def test_request_count_and_identity_cannot_pass_without_evidence(harness):
    result = {"outcome": "exited", "exit": 0}
    case = harness.inspect_case("success", result, [], [], "identity", 6)
    assert {"observable_requests", "request_bound", "tool_isolation", "proposal_schema", "brief",
            "proposal", "reconnect_identity"} <= set(case["blockers"])


def test_transmitted_schema_may_omit_annotations_but_not_constraints(harness):
    schema = ProposalRequest.model_json_schema()
    del schema["description"]  # ChemGraph moves the model description out of parameters.
    del schema["title"]
    assert harness.proposal_schema_matches(schema)
    schema["properties"]["actions"]["minItems"] = 0
    assert not harness.proposal_schema_matches(schema)


def test_mcp_rejects_malformed_and_preserves_literal_data(harness, tmp_path):
    observations = tmp_path / "events.jsonl"
    identity = "probe 'with spaces; $(touch NEVER)'"

    async def exercise():
        params = StdioServerParameters(command=sys.executable, args=[
            str(ROOT / "tools/chemgraph_fixture.py"), "--observations", str(observations),
            "--probe-id", identity, "--deadline", str(time.monotonic() + 10)])
        async with stdio_client(params) as io:
            async with ClientSession(*io) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert next(t.inputSchema for t in tools if t.name == "propose_actions") == (
                    ProposalRequest.model_json_schema())
                for args in ({}, {"request_id": "", "actions": []},
                             {"request_id": "r", "actions": [{"type": "run", "text": "x"}]},
                             {"request_id": "r", "actions": [{"kind": "run", "template": "t"}]},
                             {"request_id": "r", "actions": [], "extra": True}):
                    assert (await session.call_tool("propose_actions", args)).isError
                payload = json.loads(json.dumps(harness.PROPOSAL))
                payload["actions"][1]["text"] = identity
                malformed = json.loads(json.dumps(payload))
                malformed["actions"][0]["resources"]["nodes"] = True
                assert (await session.call_tool("propose_actions", malformed)).isError
                for _ in range(2):
                    reply = await session.call_tool("propose_actions", payload)
                    assert not reply.isError
                    assert reply.structuredContent == {"diagnostic_only": True, "probe_id": identity}
        return payload

    payload = asyncio.run(exercise())
    events = [json.loads(line) for line in observations.read_text().splitlines()]
    assert all(e["probe_id"] == identity for e in events)
    assert [e["arguments"] for e in events if e["event"] == "propose_actions"] == [payload] * 2
    assert events[-1]["event"] == "eof"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["events.jsonl"]


@pytest.mark.parametrize("leader_exits", [False, True])
def test_process_cleanup_includes_descendants(harness, tmp_path, leader_exits):
    # Child holds a TCP listener; successful rebinding proves it stopped serving.
    child = """import socket, pathlib, time
s = socket.socket()
s.bind(('127.0.0.1', 0))
s.listen()
pathlib.Path('port').write_text(str(s.getsockname()[1]))
time.sleep(60)
"""
    parent = ("import subprocess, sys, time\nfrom pathlib import Path\n"
              f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
              "while not Path('port').exists(): time.sleep(0.01)\n" +
              ("" if leader_exits else "time.sleep(60)\n"))
    result = harness.run_process([sys.executable, "-c", parent], tmp_path, {}, 2, "process")
    assert result["outcome"] == ("exited" if leader_exits else "timeout")
    port = int((tmp_path / "port").read_text())
    deadline = time.monotonic() + 2
    while True:
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", port))
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)  # SIGKILL delivery/reclamation is asynchronous.


def test_fixture_deadline_with_open_stdin(tmp_path):
    path = tmp_path / "events"
    process = subprocess.Popen([sys.executable, str(ROOT / "tools/chemgraph_fixture.py"),
                                "--observations", str(path), "--probe-id", "deadline",
                                "--deadline", str(time.monotonic() + 2)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        assert process.wait(timeout=5) == -signal.SIGALRM
        assert json.loads(path.read_text().splitlines()[0])["event"] == "start"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdin.close()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_invalid_timeout_refused(harness, tmp_path, timeout):
    with pytest.raises(ValueError):
        harness.probe(tmp_path / "unused", tmp_path / "output", timeout=timeout)
    assert not (tmp_path / "output").exists()


def test_unsupported_platform_refused(harness, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(ValueError, match="Linux/macOS"):
        harness.probe(tmp_path / "unused", tmp_path / "output")
