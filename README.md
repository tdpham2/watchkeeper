# Watchkeeper

Watchkeeper is an experimental supervisor for budgeted, multi-day agent
campaigns on HPC. Agents propose work; code owns approvals, reservations,
submission, recovery, and result validation.

This is a standalone project originating in
[ChemGraph](https://github.com/argonne-lcf/ChemGraph). Its core must not import
ChemGraph or depend on a particular agent or scientific domain.

## Development status

The package provides help/version and read-only campaign configuration validation.
Campaign execution is not implemented. There is no supported PyPI release.
Linux and macOS are the initial execution targets; Windows headless process
recovery is deferred.

- [Design](docs/design.md): behavior, interfaces, and safety invariants.
- [Implementation plan](docs/implementation-plan.md): focused implementation increments.
- [Progress](docs/progress.md): completed work, verification, and the next step.
- [Agent guidance](AGENTS.md): instructions for working directly in this repo.

A developer-only [ChemGraph contract probe](docs/design.md#running-the-cg1-probe)
checks an explicitly selected CLI against fake local model/MCP services.
It is separate from campaign execution; ordinary tests require no ChemGraph.

## Execution boundary

The intended headless adapters expose only Watchkeeper MCP tools and use a
scrubbed environment. This is an application boundary, not an OS sandbox.
Interactive sessions retain their host tools and credentials: guarantees cover
only work routed through Watchkeeper. The planned hook guard is a tripwire.

## Validate campaign configuration

Create a directory with this minimal `campaign.toml`:

```toml
goal = "Explore a small campaign"

[budget]
node_hours = 1.25

[envelope]
templates = ["example"]
queues = ["debug"]
max_nodes = 1
max_walltime_s = 600
max_concurrent_jobs = 1
max_actions_per_wake = 4

[backend]
kind = "simulated"
```

Run `watchkeeper validate --campaign DIR`, or `watchkeeper validate` from that
directory. Success exits 0; configuration/read errors exit 2 with diagnostics
on stderr. The command reads only `campaign.toml` and creates no state. It does
not check templates, approval, credentials, installed adapters, or execution
readiness. No target or template files are needed for this validation step.

The [configuration contract](docs/design.md#implemented-campaign-configuration-roadmap-2a)
lists all supported fields, defaults, and billing restrictions. Unknown fields,
including `[wake]` and `[stop]`, are rejected. `init`, target/template/action
validation, and campaign execution remain future increments.

## Development

From this checkout, create an isolated environment and install the package:

```bash
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -e '.[test]'
.venv/bin/watchkeeper --help
.venv/bin/watchkeeper --version
```

`python -m watchkeeper` also displays help. Campaign commands such as `tick`
are intentionally unavailable until their implementation and recovery tests
land. The development install needs no ChemGraph installation or credentials.

Run the local checks:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest
.venv/bin/python -m build
uv pip check --python .venv/bin/python
```

CI runs these checks on Linux/macOS with Python 3.11 and 3.13, then installs
the wheel in a separate environment and checks the CLI and import boundary.

## Contributing

Start from current `main` and open one focused feature PR at a time. Later
PRs add the behaviors described in the roadmap, with hermetic tests alongside
each change. Keep live LLM, Globus, and HPC work out of ordinary tests.

## License and origin

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution.
