# Implementation progress

Last updated: 2026-10-28.

## Current handoff

- Repository: https://github.com/tdpham2/watchkeeper
- Implementation checkout: `/Users/tpham2/.codex/worktrees/71d0/watchkeeper`.
- Implementation branch: `feature/chemgraph-contract`, based on merged PR2 at
  `a369a97` on `main`.
- [PR #1: package scaffold and CI](https://github.com/tdpham2/watchkeeper/pull/1)
  merged on 2026-10-28; all four Linux/macOS Python 3.11/3.13 CI jobs passed.
- [PR #2: campaign configuration](https://github.com/tdpham2/watchkeeper/pull/2)
  implements roadmap increment 2a and merged on 2026-10-28:
  strict campaign configuration and read-only `watchkeeper validate`.
- The [design](design.md) documents the supported schema; the
  [roadmap](implementation-plan.md) splits configuration into 2a/2b.
- [PR #3: ChemGraph contract probe](https://github.com/tdpham2/watchkeeper/pull/3)
  implements CG1 and is open for review: a developer-only CLI/MCP probe, with
  hermetic fake-CLI tests and a separate opt-in installed-CLI run. See
  [probe usage](design.md#running-the-cg1-probe). No production adapter is enabled.
- No campaign execution behavior is implemented. Available commands are
  help/version and campaign configuration validation only.

## CG1 verification and compatibility findings

The probe exposes only diagnostic `get_brief` and `propose_actions` tools. It
records a note, request ID, and identity across server processes without any
campaign state or dispatcher. Ordinary tests use fake executables and real local
HTTP/MCP transports; actual ChemGraph is never a test-suite dependency.

Local verification on macOS:

- Ruff passed; Python 3.11.13 and 3.13.2 each passed all 136 tests.
- Source distribution and wheel built successfully. The source archive includes
  the developer tools and fake-CLI fixture; the wheel contains only the package.
- A clean `.venv-wheel-cg1` installed the wheel/test extras without ChemGraph.
  All 136 tests from the extracted source archive passed outside the checkout;
  wheel import/help/version and the absence of ChemGraph were verified there.
- Dependency checks passed for both editable environments and the clean wheel.
  Local documentation links, anchors, code fences, and `git diff --check` passed.
- Timeout tests cover a live CLI, a leader that exits leaving a child, and a
  diagnostic MCP process whose stdin remains open. The latter requires a POSIX
  timer: asyncio cancellation alone does not interrupt the SDK's stdin reader.
- CI exposed a startup-order issue: the MCP deadline preceded HTTP fixture
  setup. The loopback server now avoids HTTPServer's reverse DNS lookup, and
  the deadline starts immediately before CLI launch; the tests forbid DNS
  lookup during fixture startup. Deadline expiry retains a diagnostic stack.

These are local results; the [PR3 checks](https://github.com/tdpham2/watchkeeper/pull/3/checks)
provide Linux/macOS CI evidence.

Separate installed-CLI/fake-model evidence on macOS:

- Executable: `/opt/anaconda3/bin/chemgraph`, installed metadata version 0.7.0.
  The editable install points to commit
  `0c0a76cc76700f04621914e964a882855e5862b3` with clean tracked files (an unrelated
  untracked directory was present). This differs from the design's pinned source
  baseline. No ChemGraph files were changed. `--version` is unsupported; the
  report preserves that failure and records supplied provenance separately.
- Invocation: the documented command with this executable/provenance,
  `--recursion-limit 6 --timeout 30`, and a new local artifact directory.
  Fresh HOME/configuration, loopback services, and a dummy key were used.
  Final local artifacts: `/private/tmp/watchkeeper-cg1-release-evidence-r2/`.
- Success: 3 HTTP requests, exactly the two diagnostic tools, expected note
  payload, discovery/calls across three MCP processes with the same identity,
  EOF observations, and exit 0. Malformed arguments were rejected (2 requests).
  Failed MCP startup made no model requests and exited 1.
- Continued tool-loop requests: 1 at graph limit 1 and 2 at graph limit 6.
  Both exited 0, so exhaustion cannot be classified from the exit code alone.
- HTTP 500 injection: 3 requests at each graph limit (1 and 6), including
  retries. Both exited 0 despite provider failure. The limit-1 case exceeds the
  proposed model-request bound. The harness correctly exits 1 and reports these
  incompatibilities; this is **not** a full compatibility pass.

Production adapter 20 remains blocked on the request bound and reliable failure
classification. Resolve or explicitly verify those contracts before enabling
it; do not relax the bound. CG1 itself records findings, so independent core work
can continue. No provider authentication, live LLM/HPC services, campaign
durability, or production process recovery was tested.

## Configuration verification (2a)

Local verification on macOS completed successfully:

- Ruff passed; Python 3.11.13 and 3.13.2 each passed 119 tests.
- Source distribution and wheel built with `python -m build`. The shared test
  fixture is explicitly included in the source archive.
- A fresh `.venv-wheel-config` environment installed the wheel and test extras
  without ChemGraph. All 119 tests from the extracted source archive passed
  against that wheel outside the checkout.
- Wheel help/version and the README's `validate` example passed outside the
  checkout, creating no campaign state; `find_spec("chemgraph")` returned `None`.
- Dependency checks passed for both editable environments and the clean wheel
  environment. Local documentation links/code fences and `git diff --check`
  passed.

Validation reads only `campaign.toml`. It checks no target/template files,
credentials, installed adapters, approval, or execution readiness. Wake/stop
sections are rejected until their lifecycle/event/scheduling increments.
Credential checks cover documented variable names; environment construction and
runtime enforcement remain future work. No live LLM/HPC services were used.

Consult the [PR2 checks](https://github.com/tdpham2/watchkeeper/pull/2/checks) for
current remote Linux/macOS Python 3.11/3.13 results; the evidence above is local.

The earlier CG1 planning update inspected the pinned ChemGraph source only.
The separate installed-CLI findings above are new evidence from this increment.

## PR1 verification

Local verification on macOS completed successfully:

- `.venv/bin/ruff check .`.
- Python 3.11.13: 10 tests passed.
- Python 3.13.2: 10 tests passed.
- Source distribution and wheel built with `python -m build`.
- Dependency checks passed for both editable environments and a clean wheel
  environment, with no ChemGraph dependency.
- Wheel import, `watchkeeper --version`, and `python -m watchkeeper --help`
  worked outside the checkout; `find_spec("chemgraph")` returned `None`.
- Documentation links and code fences were checked, and `git diff --check`
  passed.

The [PR1 checks](https://github.com/tdpham2/watchkeeper/pull/1/checks) passed on
Linux/macOS with Python 3.11 and 3.13. The configuration results above are local
macOS results; they do not claim Linux execution of increment 2a.

## Continue here next time

Open this repository directly and read `AGENTS.md`. The editable development
environment is `.venv`; `.venv-313` and `.venv-wheel-cg1` are local verification
environments, all ignored by Git.

Review and merge CG1, then branch from current `main` for **2b**:
target/template/action contracts, `init`, and expanded `validate`. Complete 2b
before ledger increment 3. Keep core increments 3–18 intact; implement production
ChemGraph adapter 20 after 18 and before Claude adapter 19. Stop-rule fields
belong to 11; wake-trigger fields belong to 12/16. The first live HPC pilot stays
at 26. The early diagnostic probe grants no campaign execution or recovery
guarantees and cannot bypass the runtime safety dependencies.

## Decisions to preserve

- All Watchkeeper development belongs here; no ChemGraph edits or core imports.
- Linux/macOS first; Windows headless recovery is a separate follow-up.
- One focused implementation PR at a time, approximately 400 changed lines
  where practical. Experimental status remains until the simulated campaign
  and user-run Polaris pilot pass.
- No PyPI publication or live LLM/HPC tests as part of package scaffolding.
- ChemGraph source links are pinned to
  `855e3756856e49aa4326937e552840acd5ebdaf9`. External adapter/service assumptions
  still need the later contract and live checks specified in the roadmap.
