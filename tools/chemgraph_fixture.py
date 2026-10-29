"""CG1 diagnostic MCP fixture; no campaign semantics or execution capability."""

import argparse
import asyncio
import faulthandler
import json
import os
from pathlib import Path
import signal
import time
from typing import Literal

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool
from pydantic import BaseModel, ConfigDict, Field


PROPOSAL = {
    "request_id": "cg1-note-1",
    "actions": [{"type": "note", "text": "CG1 diagnostic note."}],
}


class Note(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["note"]
    text: str


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    request_id: str = Field(min_length=1)
    actions: list[Note] = Field(min_length=1, max_length=1)


async def serve(path: Path, probe_id: str, fail_startup: bool = False) -> None:
    def record(event, **data):
        # One append per event; observations survive each stdio server's EOF.
        with path.open("a") as stream:
            stream.write(json.dumps(dict(event=event, probe_id=probe_id,
                                         pid=os.getpid(), **data)) + "\n")

    record("start")
    if fail_startup:
        raise SystemExit(2)
    server = Server("watchkeeper-cg1-diagnostic")

    @server.list_tools()
    async def list_tools():
        record("discovery")
        return [
            Tool(name="get_brief", description="Read a diagnostic brief.",
                 inputSchema={"type": "object", "properties": {},
                              "additionalProperties": False}),
            Tool(name="propose_actions", description="Record a diagnostic note only.",
                 inputSchema=Proposal.model_json_schema()),
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            if name == "propose_actions":
                Proposal.model_validate(arguments)
            elif name != "get_brief" or arguments:
                raise ValueError("Unknown tool or invalid brief arguments")
        except ValueError:
            record("rejected", name=name, arguments=arguments)
            raise ValueError("Invalid diagnostic arguments") from None
        record(name, arguments=arguments)
        return {"diagnostic_only": True, "probe_id": probe_id}

    try:
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())
    finally:
        record("eof")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--probe-id", required=True)
    parser.add_argument("--deadline", type=float, required=True)
    parser.add_argument("--fail-startup", action="store_true")
    args = parser.parse_args()
    # The SDK's blocking stdin reader can resist asyncio cancellation. Bound
    # this process even in a separate MCP process group with stdin still open.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    faulthandler.register(signal.SIGALRM, chain=True)
    signal.setitimer(signal.ITIMER_REAL, max(0.001, args.deadline - time.monotonic()))
    asyncio.run(serve(args.observations, args.probe_id, args.fail_startup))
