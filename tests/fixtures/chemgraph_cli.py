"""Fake executable exercising the real HTTP/MCP fixtures without ChemGraph."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
import sys
import tomllib
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# Tests prepend MODE as data and an interpreter shebang to this file.
MODE = globals().get("MODE", "normal")
if "--version" in sys.argv:
    print("fake-chemgraph 0")
    raise SystemExit(2 if MODE == "versionless" else 0)
if MODE == "unsupported":
    print("--workflow-only")
    raise SystemExit(0)

parser = argparse.ArgumentParser()
parser.add_argument("command", choices=["run"])
for name in ("workflow", "model", "config", "base-url", "recursion-limit",
             "mcp-command", "query"):
    parser.add_argument("--" + name, required=True)
args = parser.parse_args()
assert args.workflow == "single_agent" and args.model == "watchkeeper-cg1"
assert tomllib.loads(Path(args.config).read_text())["general"] == {
    "structured": False, "report": False, "human_supervised": False,
}
assert not {"CG1_SECRET", "OPENAI_API_KEY", "HTTP_PROXY", "PYTHONPATH"} & os.environ.keys()
assert Path.cwd().is_relative_to(Path(os.environ["HOME"]).resolve())
assert os.environ["VLLM_API_KEY"] == "cg1-dummy"
command = shlex.split(args.mcp_command)


async def mcp_call(call=None):
    # Separate connections reproduce discovery -> EOF -> calls after reconnect.
    async with stdio_client(StdioServerParameters(command=command[0], args=command[1:])) as io:
        async with ClientSession(*io) as session:
            await session.initialize()
            if call is None:
                return (await session.list_tools()).tools
            return await session.call_tool(call["name"], json.loads(call["arguments"]))


async def run():
    try:
        tools = await mcp_call()
    except Exception:
        return 1
    schemas = [{"type": "function", "function": {"name": t.name,
                "description": t.description, "parameters": t.inputSchema}} for t in tools]
    if MODE == "leak_tool":
        schemas.append({"type": "function", "function": {"name": "submit"}})
    messages = [{"role": "user", "content": args.query}]
    limit = int(args.recursion_limit)
    for step in range(limit + (2 if MODE == "retry_excess" else 0)):
        request = Request(args.base_url + "/chat/completions", headers={
            "Content-Type": "application/json"}, data=json.dumps({
                "model": args.model, "tools": schemas, "messages": messages,
            }).encode())
        try:
            with urlopen(request, timeout=2) as response:
                message = json.load(response)["choices"][0]["message"]
        except HTTPError:
            if MODE == "retry_excess":
                continue
            return 0 if MODE == "silent_error" else 1
        messages.append(message)
        if "tool_calls" not in message:
            return 0
        for call in message["tool_calls"]:
            result = await mcp_call(call["function"])
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": json.dumps(result.model_dump(mode="json"))})
    return 1


raise SystemExit(asyncio.run(run()))
