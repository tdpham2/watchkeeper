# Watchkeeper

Watchkeeper is an experimental supervisor for budgeted, multi-day agent
campaigns on HPC. Agents propose work; code owns approvals, reservations,
submission, recovery, and result validation.

This is a standalone project originating in
[ChemGraph](https://github.com/argonne-lcf/ChemGraph). Its core must not import
ChemGraph or depend on a particular agent or scientific domain.

## Development status

The package provides help/version, campaign scaffolding, read-only campaign,
target and template configuration validation,
and [proposal data models](docs/design.md#implemented-proposal-contracts-roadmap-2b1).
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

## Create and validate campaign configuration

Create a simulated campaign in an absent or empty directory:

```bash
watchkeeper init --campaign my-campaign
watchkeeper validate --campaign my-campaign
```

Both commands default to the current directory. `init` writes `campaign.toml`
and `templates/example/template.toml`, with a 1.25 node-hour budget, a single-node
debug envelope, and no headless adapter. It refuses nonempty destinations and
never overwrites files. The example declares a string parameter `label` and a
future `result.json` output; it does not yet include a runnable calculation.

`validate` reads the campaign, every allowed template, and `target.toml` when
present (required for IRI). It checks scalar parameter declarations, file
references, and safe paths without executing scripts or creating state.
Success exits 0; configuration/read errors exit 2 with diagnostics on stderr.
Validation does not check approval, credentials, installed adapters, remote
resources, or execution readiness.

Existing campaign-only directories now need their declared templates before
the CLI will validate them. The Python `load_campaign(path)` API still reads
only one campaign file. See the [directory and template contracts](docs/design.md#implemented-directory-and-template-contracts-roadmap-2b2)
for the full schema and the separate parameter-validation API.

The [configuration contract](docs/design.md#implemented-campaign-configuration-roadmap-2a)
lists all supported fields, defaults, and billing restrictions. Unknown fields,
including `[wake]` and `[stop]`, are rejected. Proposal shapes can be validated
through the Python API and the developer ChemGraph probe. Campaign execution
remains a future increment.

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
