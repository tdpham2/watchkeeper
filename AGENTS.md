# Agent guidance

Watchkeeper is an independent Python package for durable, budgeted HPC
campaigns. Work directly in this repository; a ChemGraph checkout is not
required. Read `docs/progress.md` first, then the relevant design and roadmap
sections. Those documents distinguish implemented behavior from future work.

## Architecture

- Use a `src/watchkeeper/` layout and Python >=3.11.
- The core must never import `chemgraph`, LangChain, ASE, or RDKit. Port small
  patterns with attribution; adapters invoke external CLIs as subprocesses.
- Keep dependencies to the standard library, Pydantic v2, and MCP. Import
  optional dependencies lazily. Do not add plugin frameworks ahead of need.
- Agents propose; the dispatcher authorizes. Operator commands are separate.
- Commit submission intent before remote calls. An uncertain submission must
  never be retried automatically or relabelled as nonexecution.
- Reserve node-hours transactionally before approval. Unknown usage and
  abandonment retain the full charge. Request identity and computation identity
  are separate concepts.
- Use immutable approved snapshots and serialize agent parameters as data.
  Never substitute agent-controlled strings into shell scripts.
- Initially support headless execution on Linux/macOS. Defer Windows process
  containment; do not silently offer weaker recovery there.

## Development commands

The package-scaffold PR introduces the following commands:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m build
uv pip check --python .venv/bin/python
```

Use a clean environment to test the built wheel without ChemGraph installed.
The package version is single-sourced in `pyproject.toml`.

## Workflow

- Branch from current `main`; use `feature/`, `fix/`, `docs/`, or `chore/` names.
- Open PRs; do not push implementation directly to `main` or force-push shared
  branches. The documentation-only initial commit establishes the empty repo.
- Aim for one logical change and approximately 400 changed lines per PR where
  practical. Do not remove necessary recovery tests to meet a line count.
- Complete each PR's tests and documentation before starting dependent work.
  Merge dependencies before branching the next dependent PR from `main`.
- Run Ruff, package tests, a distribution build, and dependency checks before
  proposing an implementation PR. CI covers Linux/macOS on Python 3.11 and 3.13.
- Keep tests hermetic: fake time, persistent simulated backends, fake CLI
  executables, and injected HTTP transports. Never download models or call
  live LLM/HPC services in ordinary tests.
- Keep secrets and token caches out of source, tests, logs, and docs. Do not
  auto-run login commands or publish to PyPI.
- Update `docs/progress.md` with the PR, validation evidence, limitations, and
  next step so another session can continue without the original conversation.

## Sources and scope

`docs/design.md` links to the ChemGraph source patterns at a recorded commit.
Keep chemistry in examples and preserve attribution when copying source.
Do not pull unrelated ChemGraph work or dependencies into this repository.
No task requires editing the original ChemGraph checkout.
