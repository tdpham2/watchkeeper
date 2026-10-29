"""Opt-in installed-ChemGraph probe with fake services, never a campaign runner."""

import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import shlex
import signal
from socketserver import TCPServer
import subprocess
import sys
import tempfile
from threading import Thread
import time
from uuid import uuid4

from chemgraph_fixture import PROPOSAL
from watchkeeper.actions import ProposalRequest


TOOLS = {"get_brief", "propose_actions"}
SCENARIOS = ("success", "loop", "provider_error", "malformed", "failed_mcp")
FLAGS = ("--workflow", "--model", "--config", "--base-url", "--recursion-limit",
         "--mcp-command", "--query")


def run_process(argv, directory, env, timeout, label):
    """Bound foreground work and clean the POSIX group even after leader exit."""
    with (directory / f"{label}.log").open("w+", encoding="utf-8", errors="replace") as output:
        try:
            process = subprocess.Popen(argv, cwd=directory, env=env,
                                       stdin=subprocess.DEVNULL, stdout=output,
                                       stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            return {"outcome": "launch_error", "exit": None, "error": str(exc)}
        try:
            process.wait(timeout=timeout)
            outcome = "exited"
        except subprocess.TimeoutExpired:
            outcome = "timeout"
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        output.seek(0)
        return {"outcome": outcome, "exit": process.returncode,
                "output": output.read(65536)}


@contextmanager
def model_endpoint(scenario, requests):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.connection.settimeout(2)
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1_000_000:
                self.send_error(413)
                return
            body = json.loads(self.rfile.read(size))
            requests.append({"path": self.path, "body": body})
            step = len(requests)
            status = 500 if scenario == "provider_error" else 200
            message = {"role": "assistant", "content": "Diagnostic complete."}
            name = None
            if scenario == "loop" or (scenario == "success" and step == 1):
                name, arguments = "get_brief", {}
            elif scenario == "success" and step == 2:
                name, arguments = "propose_actions", PROPOSAL
            elif scenario == "malformed" and step == 1:
                name, arguments = "propose_actions", {"actions": "invalid"}
            if name:
                message.update(content=None, tool_calls=[{
                    "id": f"call_{step}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }])
            payload = {"id": f"cg1-{step}", "object": "chat.completion",
                       "created": 0, "model": "watchkeeper-cg1",
                       "choices": [{"index": 0, "message": message,
                                    "finish_reason": "tool_calls" if name else "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                 "total_tokens": 2}}
            if status == 500:
                payload = {"error": {"message": "CG1 injected provider failure",
                                     "type": "server_error", "code": "cg1"}}
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    class LoopbackServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer's default bind does a reverse DNS lookup. The fixture
            # already knows its address; startup must not depend on a resolver.
            TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address

    server = LoopbackServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def proposal_schema_matches(schema):
    """Compare validation rules despite inlined refs and omitted annotations."""
    def normalize(node, root):
        if isinstance(node, list):
            return [normalize(item, root) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            prefix, name = node["$ref"].rsplit("/", 1)
            if prefix != "#/$defs":
                raise ValueError("Unexpected schema reference")
            node = root["$defs"][name] | {k: v for k, v in node.items() if k != "$ref"}
        return {k: normalize(v, root) for k, v in node.items()
                if k not in {"$defs", "title", "description"}}

    expected = ProposalRequest.model_json_schema()
    try:
        return normalize(schema, schema) == normalize(expected, expected)
    except (KeyError, TypeError, ValueError, RecursionError):
        return False


def inspect_case(scenario, result, requests, events, probe_id, limit):
    schemas = [[t.get("function", {}) for t in r["body"].get("tools", [])]
               for r in requests]
    names = [sorted(t.get("name", "") for t in tools) for tools in schemas]
    checks = {"foreground_completed": result["outcome"] == "exited"}
    if scenario == "failed_mcp":
        checks["startup_refused"] = (result["exit"] not in (None, 0) and not requests
                                     and any(e["event"] == "start" for e in events))
    else:
        checks["observable_requests"] = bool(requests)
        checks["request_bound"] = 0 < len(requests) <= limit
        checks["tool_isolation"] = bool(names) and all(set(n) == TOOLS for n in names)
        proposals = [[t.get("parameters") for t in tools if t.get("name") == "propose_actions"]
                     for tools in schemas]
        checks["proposal_schema"] = bool(proposals) and all(
            len(p) == 1 and proposal_schema_matches(p[0]) for p in proposals)
        checks["protocol"] = all(r["path"] == "/v1/chat/completions" and
                                 not r["body"].get("stream") for r in requests)
    if scenario == "success":
        checks["exit_zero"] = result["exit"] == 0
        checks["brief"] = any(e["event"] == "get_brief" for e in events)
        checks["proposal"] = any(e["event"] == "propose_actions" and
                                 e["arguments"] == PROPOSAL for e in events)
        discovery = {e["pid"] for e in events if e["event"] == "discovery"}
        calls = {e["pid"] for e in events if e["event"] in TOOLS}
        ended = {e["pid"] for e in events if e["event"] == "eof"}
        checks["reconnect_identity"] = (len(discovery) >= 2 and len(calls) >= 2
                                        and calls <= discovery and discovery <= ended and
                                        all(e["probe_id"] == probe_id for e in events))
    if scenario in {"loop", "provider_error"}:
        # A zero exit after an injected failure is ambiguous for a future adapter.
        checks["failure_exit"] = result["exit"] not in (None, 0)
    if scenario == "malformed":
        checks["malformed_refused"] = (any(e["event"] == "rejected" for e in events)
                                        and not any(e["event"] == "propose_actions"
                                                    for e in events))
    return {"scenario": scenario, "recursion_limit": limit,
            "process": result, "request_count": len(requests),
            "tool_names": names, "checks": checks,
            "blockers": [name for name, passed in checks.items() if not passed]}


def probe(executable: Path, output: Path, *, limit=6, timeout=30,
          scenarios=SCENARIOS, evidence="harness-only", provenance="unspecified"):
    if sys.platform not in {"linux", "darwin"}:
        raise ValueError("CG1 process containment requires Linux/macOS")
    if limit < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("limit and timeout must be positive")
    if not set(scenarios) <= set(SCENARIOS):
        raise ValueError("Unknown probe scenario")
    executable = executable.absolute()
    output = output.absolute()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {"evidence": evidence, "executable": str(executable),
              "provenance_supplied": provenance, "recursion_limit": limit, "cases": [],
              "blockers": []}
    with tempfile.TemporaryDirectory(prefix="cg1-") as scratch:
        root = Path(scratch)
        env = {"HOME": str(root), "TMPDIR": str(root), "LANG": "C",
               "PATH": os.pathsep.join((str(executable.parent),
                                        str(Path(sys.executable).parent), os.defpath)),
               "VLLM_API_KEY": "cg1-dummy", "PYTHONNOUSERSITE": "1",
               "PYTHON_DOTENV_DISABLED": "1"}
        version = run_process([str(executable), "--version"], root, env, timeout, "version")
        help_result = run_process([str(executable), "run", "--help"], root,
                                  env, timeout, "help")
        report.update(version=version, help=help_result)
        missing = [flag for flag in FLAGS if flag not in help_result.get("output", "")]
        if help_result["outcome"] != "exited" or help_result["exit"] or missing:
            report["blockers"].append("CLI preflight failed; missing flags: " + str(missing))
        else:
            cases = [(s, n) for s in scenarios for n in
                     (sorted({1, limit}) if s in {"loop", "provider_error"} else [limit])]
            for scenario, case_limit in cases:
                label = f"{scenario}-{case_limit}"
                directory = root / label
                directory.mkdir()
                config = directory / "probe.toml"
                config.write_text('[general]\nstructured = false\nreport = false\n'
                                  'human_supervised = false\n')
                observations = directory / "observations.jsonl"
                probe_id = str(uuid4())
                mcp = [sys.executable, str(Path(__file__).with_name("chemgraph_fixture.py")),
                       "--observations", str(observations), "--probe-id", probe_id]
                if scenario == "failed_mcp":
                    mcp.append("--fail-startup")
                requests = []
                with model_endpoint(scenario, requests) as url:
                    mcp.extend(["--deadline", str(time.monotonic() + timeout)])
                    argv = [str(executable), "run", "--workflow", "single_agent",
                            "--config", str(config), "--model", "watchkeeper-cg1",
                            "--base-url", url, "--recursion-limit", str(case_limit),
                            "--mcp-command", shlex.join(mcp), "--query",
                            "Read the diagnostic brief, propose a diagnostic batch of "
                            "run, note, ask_human and stop actions, then finish."]
                    result = run_process(argv, directory, env, timeout, "cli")
                events = ([json.loads(line) for line in observations.read_text().splitlines()]
                          if observations.exists() else [])
                case = inspect_case(scenario, result, requests, events, probe_id, case_limit)
                case.update(argv=argv, probe_id=probe_id, events=events)
                report["cases"].append(case)
                report["blockers"].extend(f"{label}: {b}" for b in case["blockers"])
                (output / f"{label}-requests.json").write_text(json.dumps(requests, indent=2))
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chemgraph", type=Path, required=True,
                        help="Explicit opt-in: path to an already installed real CLI")
    parser.add_argument("--output", type=Path, required=True, help="New local artifact directory")
    parser.add_argument("--provenance", required=True, help="Installed version/commit or unknown")
    parser.add_argument("--recursion-limit", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    result = probe(args.chemgraph, args.output, limit=args.recursion_limit,
                   timeout=args.timeout, evidence="real-cli/fake-model",
                   provenance=args.provenance)
    print(json.dumps({"result": str(args.output / "result.json"),
                      "blockers": result["blockers"]}, indent=2))
    return int(bool(result["blockers"]))


if __name__ == "__main__":
    raise SystemExit(main())
