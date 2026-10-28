# Implementation progress

Last updated: 2026-10-28.

## Repository bootstrap

- Repository: https://github.com/tdpham2/watchkeeper
- Local checkout requested by the maintainer: `../watchkeeper` beside ChemGraph.
- The documentation-only initial commit establishes `main`.
- The [design](design.md) and complete [implementation roadmap](implementation-plan.md)
  have been carried into this standalone repository.
- No campaign execution behavior is implemented yet.

## Next step

Implement roadmap PR1 on `feature/package-scaffold`: packaging, CLI help/version,
independent tests, distribution verification, and Linux/macOS CI. Do not expose
submission or campaign commands before their safety dependencies land.

## Decisions to preserve

- Keep all Watchkeeper development in this repository, with no required
  ChemGraph edits or runtime imports.
- Linux/macOS first; Windows headless recovery is a separate follow-up.
- Use small PRs into Watchkeeper `main`; experimental status remains until the
  end-to-end simulated campaign and user-run Polaris pilot pass.
- Do not publish to PyPI as part of this series.

## Verification

Bootstrap is documentation only. Runtime tests begin with PR1. Source references
were inspected against ChemGraph commit
`855e3756856e49aa4326937e552840acd5ebdaf9`; external service and adapter behavior
still requires the contract and live checks specified in the roadmap.
