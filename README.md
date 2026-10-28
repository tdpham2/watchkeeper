# Watchkeeper

Watchkeeper is an experimental supervisor for budgeted, multi-day agent
campaigns on HPC. Agents propose work; code owns approvals, reservations,
submission, recovery, and result validation.

This is a standalone project originating in
[ChemGraph](https://github.com/argonne-lcf/ChemGraph). Its core must not import
ChemGraph or depend on a particular agent or scientific domain.

## Development status

The repository currently contains the design and implementation roadmap.
Campaign execution is not implemented. There is no supported PyPI release.
Linux and macOS are the initial execution targets; Windows headless process
recovery is deferred.

- [Design](docs/design.md): behavior, interfaces, and safety invariants.
- [Implementation plan](docs/implementation-plan.md): 26 focused implementation PRs.
- [Progress](docs/progress.md): completed work, verification, and the next step.
- [Agent guidance](AGENTS.md): instructions for working directly in this repo.

## Execution boundary

The intended headless adapters expose only Watchkeeper MCP tools and use a
scrubbed environment. This is an application boundary, not an OS sandbox.
Interactive sessions retain their host tools and credentials: guarantees cover
only work routed through Watchkeeper. The planned hook guard is a tripwire.

## Contributing

Start from current `main` and open one focused feature PR at a time. The first
implementation PR establishes packaging, developer commands, and CI. Later
PRs add the behaviors described in the roadmap, with hermetic tests alongside
each change. Keep live LLM, Globus, and HPC work out of ordinary tests.

## License and origin

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for attribution.
