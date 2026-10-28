# Watchkeeper implementation roadmap

Status: approved direction; PR1 is merged and configuration is split into 2a/2b.
ChemGraph contract testing (CG1) is the next implementation priority after 2a.
These are roadmap identifiers, not guaranteed GitHub PR numbers. This roadmap was
adapted for the standalone `tdpham2/watchkeeper` repository on 2026-10-28.
See [progress](progress.md) for the current handoff and [design](design.md) for
the behavior contracts.

## Goal and delivery

Build a chemistry-free, restartable campaign supervisor with conservative
node-hour accounting, proposal-only agents, validated results, and IRI/Polaris
execution. The first release supports Linux/macOS, interactive Claude Code and
Codex sessions, and headless Claude Code and ChemGraph decision workers.
Windows headless execution is deferred; the core remains portable.

Use `src/watchkeeper/`, `tests/`, and `pyproject.toml` at this repository's root.
There is no `packages/watchkeeper/` wrapper and no ChemGraph runtime dependency.
The documentation-only initialization commit establishes `main`; all
implementation follows through focused feature PRs. Merge dependencies before
branching the next dependent PR from current `main`.

### Early ChemGraph integration

Delivery order is **2a → CG1 → 2b → 3–18 → 20 → 19 → 21–26**.
Keep existing roadmap identifiers stable; row order indicates delivery priority.
CG1 is a separate focused PR after 2a merges, not an addition to configuration
implementation. The first real ChemGraph test should not wait for the runtime
adapter in 20 or for Claude integration in 19.

CG1 supplies a developer-only subprocess harness and diagnostic MCP fixture.
Ordinary tests use a fake ChemGraph executable. An explicit opt-in runs an
already-installed real ChemGraph CLI against a loopback fake model endpoint,
allowing actual tool schemas and model requests to be inspected without a live
LLM, HPC credentials, model downloads, or a ChemGraph checkout. See the
[contract probe design](design.md#early-chemgraph-contract-probe-cg1) for the
boundary, scenarios, and evidence required. This harness is not implemented yet.

Keep the store, reservation, manifest, request journal, dispatcher, wake fencing,
and process-recovery dependencies intact. CG1 records protocol observations only;
it cannot approve, stage, submit, or establish campaign guarantees. Its findings
inform 2b, 14–17, and 20. Record incompatibilities explicitly and resolve them
before enabling the production adapter; core work can continue independently.

## Design amendments incorporated into the design

- Persist request ID, payload hash, per-item identity, and dispositions before
  adding dispatch or MCP. Request replay never creates another attempt.
- A one-operation resource exception cannot bypass schema, budget, uncertainty,
  or approved-byte checks. An unlisted template requires a manifest change and
  `approve-plan` before an operation can be approved.
- Computation identity includes the backend, resolved IRI endpoint, and every
  execution-affecting target setting, including `filesystems`. Exclude only
  validator bytes/configuration from the template execution digest.
- Publish verified immutable snapshots before committing approval and the
  reservation together. Unreferenced snapshots do not imply approval. Separate
  inputs/validators from outputs and recheck input hashes before stage/submit.
- Support one supervisor host and a local SQLite database. A stale heartbeat
  alone does not permit taking ownership from a live process. Keep network
  calls outside short database transactions.
- A headless MCP connection attaches to an existing wake and its token. EOF
  closes that server, not the wake; the supervisor/bootstrap owns the outcome.
- Claude uses `--max-turns`; stream output when inspecting init/usage events.
  ChemGraph uses unstructured `single_agent` without report generation and a
  conservative `--recursion-limit` mapping, verified to bound model calls.
- IRI filesystem calls return asynchronous tasks; persist IDs and poll across
  ticks. Wrapper timestamps are diagnostic. Retain full reservations unless
  authoritative allocation usage is available.

## Focused PR sequence

Each row is one independently reviewable PR, including tests and relevant
documentation. Aim for approximately 400 changed lines where practical;
necessary recovery tests take precedence over that target. Split an oversized
row further by behavior rather than omitting verification.

| PR | Focus | Acceptance |
| --- | --- | --- |
| 1 | Package and CI: setuptools, console entry point, README, local tests/lint. | Install without ChemGraph; wheel/import/CLI smoke checks; compatible dependency ranges; Linux/macOS Python 3.11/3.13 CI. |
| 2a | Campaign configuration and static adapter capabilities; read-only `validate`. | Strict settings/resources; explicit backend kind; billing constraints; required wake limits; forbidden credential names; reject deferred wake/stop sections; no state or external calls. |
| CG1 | Early ChemGraph CLI/MCP contract probe, after 2a and before 2b. | Hermetic fake-CLI tests; opt-in real CLI with a loopback fake model and diagnostic MCP; inspect exact tool set, proposal payloads, reconnect identity, and model-request counts; no campaign execution or core ChemGraph imports. |
| 2b | Target, template and action contracts; `init` and expanded `validate`. | Compatible IRI target format; strict parameter/resource contracts; scaffolded configuration validates; no approval, rendering or execution. Complete before PR3. |
| 3 | Transactional store and ledger: schema version, WAL, revisions, campaign revision, reserve/settle. | Concurrent approval cannot overspend; settlement is idempotent; unknown usage retains its charge; integer node-seconds internally. |
| 4 | Manifests and rendering: `approve-plan`, execution identity, immutable snapshots, JSON data mapping. | Target/template changes invalidate approval; validator-only edits preserve computation identity; traversal/symlinks/tampering/injection tested. |
| 5 | Operation journal and operator evidence: transitions, `approve`, `reject`, `confirm-nonexecution`, `abandon`. | Interrupted submission becomes uncertain; confirmation requires evidence and renewed review; abandonment retains charges and blocks replacement work. |
| 6 | Request/proposal journal: replay, item identities, saved dispositions and resumable dispatch bookkeeping. | Same ID/payload replays after failure and across sessions; changed payload is refused; each proposal creates its effect once. |
| 7 | Run dispatcher: envelope, dedup, human-review disposition, atomic reserve/approve. | Equivalent concurrent proposals share an operation; uncertain/abandoned keys block; resource exceptions cannot bypass budget/manifest checks. |
| 8 | Simulated execution: backend protocol, durable fake jobs, clock, supervisor lease, minimal `tick`/`run`. | Intent commits before submit; restart against the same remote simulator never duplicates a job; polling/staging resume. |
| 9 | Collection and built-in validation: status file, required outputs, exit codes, result persistence and usage. | Partial collection retries; missing/malformed output has explicit outcomes; scheduler failure never implies zero usage. |
| 10 | Custom validators: approved snapshot, isolated process, timeout/backoff, `revalidate`. | Execution failure stays collected; scientific rejection is invalid; revalidation changes provenance without a new job. |
| 11 | Campaign lifecycle and stop-rule configuration: separate gates, pause/resume/stop, deadline, draining and completion. | Funded work survives wake/budget exhaustion; drain releases only provably unused reservations; unresolved work prevents completion. |
| 12 | Decision events and wake-trigger configuration: notebook, questions/answers, durable triggers, log/command notifications. | An answer creates one consumable trigger; batch/threshold events survive restart; notifier failure cannot roll back progress. |
| 13 | Report/sign-off: consistent snapshot, revision/digest checks, reviewer record. | Completion required; changed data/report rejects sign-off; historical approval becomes stale. |
| 14 | Read-only MCP/briefs: status, brief, results, notebook, bounded responses and printed MCP config. | Real stdio client reads work; stdout is protocol-only; reads do not create a wake. |
| 15 | Interactive proposals: session admission, synchronous dispatch, read-only fallback, fencing, EOF recovery, `end-session`, detached tick. | Calls across ticks retain session; one decision-maker; stop completes with connection open; request replay stays idempotent. |
| 16 | Headless scheduling and remaining wake-trigger settings: wake journal, counts, trigger consumption, billing and backoff. | Crashes/rate limits consume allowance; daily limits defer; terminal wake limits do not stop funded jobs. |
| 17 | POSIX process recovery: bootstrap acknowledgement, identity/group checks, timeout, `confirm-wake-ended`. | No adapter before ack; reused PIDs never signalled; ambiguous groups become unverified; late writers fenced; Windows refuses headless launch. |
| 18 | Scripted autonomous campaign and integrated fault injection. | About 20 jobs over three simulated days finish quickly; hard kills preserve reservations, proposals, wake limits and unique submission. |
| 20 | Production ChemGraph adapter, after CG1 and 18, before 19: CLI, MCP wake attachment, graph-step bound, provider environment and unmetered cost. | Reuse verified CG1 contracts; real CLI drives the persistent simulated campaign through the actual supervisor; reconnects share one wake; no built-in chemistry tools; model-call bound and production recovery tested; no ChemGraph import. |
| 19 | Claude Code adapter: restricted launch, billing-specific environment, transcript/usage and rate-limit parsing. | Fake CLI checks argv/env; subscription strips API credentials; unknown cost is conservative; missing capabilities fail closed. |
| 21 | Globus staging: saved request/submission ID, replay, polling, cancellation. | Crash after acceptance reuses ID; never restage after submission starts; draining does not submit staged work. |
| 22 | IRI submission: JobSpec, lazy tokens, no redirects, outcome classification. | Injected HTTP distinguishes accepted/rejected/uncertain; no second POST; shared endpoint resolver matches guard. |
| 23 | IRI lifecycle: status, async collection, credential pause, cancellation, authoritative usage when available. | Expiry pauses; collection resumes; missing usage retains reservation; cancellation never releases charges early. |
| 24 | Interactive guard: separate Claude/Codex hook adapters and printed config. | Deny known operator/direct-submission commands; allow reads; cover endpoint overrides; describe the tripwire limit. |
| 25 | User workflow: tool-neutral skill, scheduling, recovery walkthrough, adapter setup. | Manual simulated interactive Claude/Codex and headless Claude work; record tested versions and hook behavior. |
| 26 | Polaris example: copied SMILES fixture, deterministic coordinates, calculation template and domain validator. | Hermetic preparation tests; chemistry outside core; documented small, capped live pilot. |

Expose executable features only after their safety dependencies land. Earlier
PRs may test internal services and isolated external CLI contracts directly, but
must not expose placeholder submission paths or claim campaign guarantees before
integration is complete. CG1 has no installed Watchkeeper command or runtime
adapter entry point.

## Verification and milestones

- Every implementation PR: `ruff check .`, `python -m pytest`, a distribution
  build and dependency check. Use an editable install of this checkout and a
  separate wheel-install smoke test. ChemGraph's root suite is not a dependency
  or required gate for this standalone repository.
- CI installs Watchkeeper without ChemGraph. Check imports and package
  dependencies; trigger CI for package, tests, workflow, configuration, and
  example changes. Ordinary tests never use real models, tokens or services.
- Fault injection covers both sides of submission, transfer acceptance,
  snapshot publication, reservation, dispatch and wake registration. Simulated
  remote state must outlive the supervisor process.
- Ledger assertions include known settled usage plus conservative charges and
  reservations for unknown outcomes. Do not discard unknown charges to make a
  test reconcile.
- Milestones: CG1 first actual ChemGraph CLI/MCP test with a fake model;
  PR11 restartable simulated execution; PR15 interactive campaigns;
  PR18 hermetic autonomy; PR20 ChemGraph-driven simulated campaign (before PR19);
  PR23 complete IRI backend. The first live HPC pilot remains PR26.
- CG1 verification: fake executables and local fixtures in ordinary CI; the real
  ChemGraph CLI is an explicit opt-in outside the default suite. Record its
  version/commit, invocation, observed tools, proposal/reconnect evidence, request
  counts, exit/timeout behavior, and unresolved incompatibilities. A fake-CLI pass
  alone is not a real ChemGraph integration pass. No live-provider call is needed.
- PR20 manual smoke: after all runtime safety dependencies land, an actual
  ChemGraph CLI proposes work through the real MCP/supervisor against persistent
  simulation. Check one wake across reconnects, bounded calls, conservative
  unmetered cost, and restart behavior. A real Argo/API provider smoke is separate,
  explicit, and user-run; ordinary tests remain hermetic.
- PR19 manual smoke: real Claude subscription wake against simulation; verify
  restricted tools and notional cost. Optional API mode checks reported cost.
  Record actual CLI usage-limit responses and supported auth-source reporting.
- PR25 manual smoke: interactive Claude and Codex sessions with skill/MCP/guard;
  close/reopen, continue from brief, and verify headless triggers wait for the
  session to close. Record whether Claude `!` commands invoke the hook.
- PR26 live acceptance is user-run: approximately three Polaris debug jobs,
  node-hour cap near one, supervisor restart, single submission, honest usage
  display and credential pause. Expand to the 20-molecule example only after
  this pilot passes.

## Deferred work

Windows headless recovery; PyPI publishing; dashboard; Codex headless adapter;
Globus Compute backend; scientific optimization/BO policies; dedicated chat
notifiers; LiteLLM spend retrieval; ChemGraph headless main-agent MCP/usage work;
and consolidation with ChemGraph's journal remain separate follow-ups.
