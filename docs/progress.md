# Implementation progress

Last updated: 2026-10-28.

## Current handoff

- Repository: https://github.com/tdpham2/watchkeeper
- Local checkout: `/Users/tpham2/work/projects/watchkeeper`.
- Implementation branch: `feature/campaign-config`, based on merged PR1 at
  `74b9bab` on `main`.
- [PR #1: package scaffold and CI](https://github.com/tdpham2/watchkeeper/pull/1)
  merged on 2026-10-28; all four Linux/macOS Python 3.11/3.13 CI jobs passed.
- [PR #2: campaign configuration](https://github.com/tdpham2/watchkeeper/pull/2)
  implements roadmap increment 2a and is open for review, not merged:
  strict campaign configuration and read-only `watchkeeper validate`.
- The [design](design.md) documents the supported schema; the
  [roadmap](implementation-plan.md) splits configuration into 2a/2b.
- No campaign execution behavior is implemented. Available commands are
  help/version and campaign configuration validation only.

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
environment is `.venv`; `.venv-313`, `.venv-wheel`, and `.venv-wheel-config` are
local verification environments, all ignored by Git.

Review and merge increment 2a before branching from current `main` for roadmap
2b: target/template/action contracts, `init`, and expanded `validate`, with
hermetic tests. Complete 2b before ledger increment 3. Stop-rule fields belong
to increment 11; wake-trigger fields belong to 12/16. Do not start submission or
adapter execution before their safety dependencies.

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
