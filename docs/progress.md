# Implementation progress

Last updated: 2026-10-28.

## Current handoff

- Repository: https://github.com/tdpham2/watchkeeper
- Local checkout: `/Users/tpham2/work/projects/watchkeeper`.
- Implementation branch: `feature/package-scaffold`.
- [PR #1: package scaffold and CI](https://github.com/tdpham2/watchkeeper/pull/1)
  is implemented and open for review; it has not been merged.
- `main` contains the documentation-only bootstrap (`2000c2f`). The complete
  [design](design.md) and [26-PR roadmap](implementation-plan.md) are saved here.
- No campaign execution behavior is implemented yet. Only CLI help/version
  and the independent package/development infrastructure are available.

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

The [PR checks](https://github.com/tdpham2/watchkeeper/pull/1/checks) exercise
Linux/macOS with Python 3.11 and 3.13. Consult that page for the current remote
results; the local results above do not claim Linux execution.

## Continue here next time

Open this repository directly and read `AGENTS.md`. The editable development
environment is `.venv`; `.venv-313` and `.venv-wheel` are local verification
environments, all ignored by Git.

Review PR1 and resolve any CI/review findings. After PR1 is merged, branch from
current `main` for roadmap PR2: campaign, target, template, action, and adapter
capability contracts, with `init`/`validate` and hermetic validation tests.
Do not start submission or adapter execution before their safety dependencies.

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
