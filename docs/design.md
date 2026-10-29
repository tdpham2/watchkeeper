# Watchkeeper design

Status: target behavior, not a claim of implemented functionality. Consult
[progress](progress.md) before using any command and the
[implementation roadmap](implementation-plan.md) for delivery order.

## Context

Watchkeeper is a standalone campaign layer for budgeted, multi-day agent work on
HPC. It owns durable records, a conservative ledger, at-most-once job submission,
a non-LLM supervisor, result validation, and approve-once-within-limits execution.

The design originated in ChemGraph on 2026-10-27 and was adapted for
https://github.com/tdpham2/watchkeeper on 2026-10-28. The local directory is
`watchkeeper`, beside the original ChemGraph checkout. The repository is
independent: core code must not import ChemGraph. Source links below are pinned
to the inspected ChemGraph commit, so that checkout is not required.

- Package/import/CLI name: `watchkeeper` (not published to PyPI by this series).
- Initial real backend: IRI on Polaris.
- First external integration target: ChemGraph, starting with an isolated contract
  probe; its production headless adapter precedes the separate Claude Code adapter.
- Initial platforms: Linux/macOS. Windows headless containment is deferred.
- Both interactive sessions and autonomous wakes are in the first release.

The first complete milestone is a single-agent campaign that survives restarts,
enforces reserved node-hours, never resubmits an uncertain job, and runs both
hermetically on persistent simulated HPC with fake time and live on Polaris
with Claude Code or ChemGraph as the decision worker.

## Design principles

1. **The supervisor owns the campaign; agents only propose.** Agents get read tools plus `propose_actions` and nothing that causes side effects. The dispatcher validates every proposal.
2. **Holding the credentials is what enforces the rules.** Only the watchkeeper process holds IRI and Globus credentials. Agents run with:
   - a restricted tool allowlist,
   - a scrubbed environment,
   - a working directory that contains only their brief.

   This is an application boundary, not an OS sandbox. State that plainly in the README, the same way [chemgraph/runtime/context.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/runtime/context.py) does.

   The boundary holds for **headless wakes only**. In an interactive session the agent also has the host's own tools (Bash, files), and `HOME` holds the user's IRI and Globus token caches. So interactively, watchkeeper's guarantees cover only the work that goes through watchkeeper. `watchkeeper guard` is a tripwire, not a boundary. Campaigns that need the hard boundary set `[agent] interactive = false`.
3. **Uncertainty is never relabelled.** A submission with an unknown outcome becomes `uncertain`. It keeps its budget reservation and needs operator evidence (`confirm-nonexecution`) or `abandon`. A best-effort status or listing never grants permission to resubmit.
4. **Budget is conservative.** Reserve the upper bound (nodes × walltime) before submitting. Settle against actual usage only when it is known; otherwise keep the reservation.
   - A reservation is released only when the job provably never ran: a definite pre-acceptance rejection, a failed stage-in (nothing was submitted), a `cancelled` operation that never reached `submitting`, or operator `confirm-nonexecution`.
   - `uncertain`, `abandon`, and finished-with-unknown-usage keep the full reservation as charged.
   - Node-hours are the hard budget.
   - LLM use by headless wakes is bounded by **wake count**, which watchkeeper enforces itself and which is hard: `max_wakes` (required for every adapter) and `max_turns` per wake.
   - Dollars are a separate matter:
     - With `billing = "api"`, `llm_usd` is an optional soft stopping threshold (see the Claude Code adapter).
     - Under a subscription, dollar figures are notional and never gate anything.
     - A hard dollar cap is enforced outside watchkeeper, by provider workspace limits or a user-run LiteLLM proxy. watchkeeper neither imports nor runs LiteLLM, because it makes no LLM calls itself. In-process LiteLLM budgeting would see no traffic, since the adapters are separate CLI processes.
   - Interactive sessions use the user's own login and bill, and aren't counted.
5. **The core stays chemistry-free.** Templates, exit-code meanings and validators belong to the campaign directory (the application), not to watchkeeper.
6. **Minimal dependencies.** Use the standard library (`sqlite3`, `tomllib`, `urllib`, `subprocess`) plus `pydantic` v2 and `mcp`. Pin ranges that are compatible with ChemGraph's pins (`mcp==1.28.1`). Optional extras are imported lazily.

## Who decides what

| Decision | Owner | Mechanism |
|---|---|---|
| Envelope, budget reservation, dedup, at-most-once submission, gates | Code (supervisor/dispatcher) | the rules below; there is no LLM or human in the path |
| Whether a run produced a usable result | Code | the status file + required outputs + optional template `validate` hook |
| What to run next, how to read results, when the goal is met (`stop`) | LLM (interactive or headless) | `propose_actions` only |
| The plan/manifest, out-of-envelope actions, `uncertain`/`unverified` resolution, logins, answers | Human | `approve-plan`, `approve`, `confirm-*`, `answer` |
| Whether the campaign's conclusions are scientifically trusted | Human, once, at the end | `report` + `sign-off` |

A human is not in the loop for each job. An LLM never certifies results.

## Concepts

**Campaign directory** (one campaign = one directory):

```
<campaign>/
  campaign.toml      # spec: goal, budget, envelope, target, adapter, templates, wake rules
  templates/<name>/  # template.toml (param schema, outputs, exit codes) + files rendered per run
  target.toml        # IRI target, same format as skills/iri-hpc/assets/target.example.toml
  watchkeeper.db     # SQLite (WAL): campaign, operations, ledger, results, events, wakes, questions, notebook
  runs/<op_id>/      # inputs/ (immutable), outputs/ (collected), validator/ (approved)
  wakes/<n>/         # brief.md + brief.json + adapter transcript and usage
```

`target.toml` deliberately reuses the iri-hpc skill format, so `iri_configure.py` output works unchanged.

**`campaign.toml` sections:**
- `goal`: free text.
- `[budget]`: `node_hours` (hard), optional `llm_usd` (soft stopping threshold), `deadline`, and `soft = [0.5, 0.8]` notification thresholds.
- `[envelope]`: allowed `templates`, `max_nodes`, `max_walltime_s`, `queues`, `max_concurrent_jobs`, `max_actions_per_wake`.
- `[stop]`: stopping rules.
- `[agent]`:
  - `adapter` (optional; with no adapter, wake triggers only notify the human), model, `max_turns`, `timeout_s`;
  - `billing = "api" | "subscription" | "free"` and `max_wakes` (both required when an adapter is set);
  - optional `max_usd_per_wake` and `max_wakes_per_day` (the latter protects a subscription's interactive quota);
  - optional `env_passthrough`, a list of extra variable names copied into the adapter environment, e.g. `ANTHROPIC_BASE_URL` and `ANTHROPIC_CUSTOM_HEADERS` for a LiteLLM proxy;
  - `interactive = true | false` (default `true`).
  - `validate` rules:
    - `llm_usd` is allowed only with `billing = "api"` and an adapter that reports cost (not ChemGraph today);
    - `max_usd_per_wake` is required whenever `llm_usd` is set;
    - `env_passthrough` may not name any `ALCF_*`, `GLOBUS_*` or IRI token variable, nor an LLM credential reserved for the other billing mode.
- `[backend]`: required `kind = "simulated" | "iri"`; IRI alone accepts optional `iri_base_url`, default `https://api.alcf.anl.gov/api/v2` (the same default as `iri_submit.py` `BASE_URL` and `iri.sh` `BASE`). The future backend and `guard` will share one resolver, `backends/iri.py: resolve_base_url(spec)`, using this configuration value.
- `[wake]`: triggers.

### Implemented campaign configuration (roadmap 2a)

`load_campaign(path: Path) -> CampaignSpec` loads a single TOML file.
`watchkeeper validate --campaign DIR` reads `DIR/campaign.toml` (default directory:
the current working directory). It checks configuration only, without reading
target/templates, checking installed CLIs or credentials, approving work, or
creating a database. CLI errors omit input values and tracebacks. The API raises
`CampaignConfigError` with the same diagnostics for read, parse, or schema errors.

The following is the complete currently accepted schema. All models reject
unknown fields and implicit string/boolean-to-number conversions. Strings marked
nonblank retain their original contents. Numeric amounts are finite decimals;
TOML fractional amounts retain their precision. Ledger conversion is deferred.

| Section | Fields and constraints |
| --- | --- |
| Root | Required nonblank `goal`; required `budget`, `envelope`, `backend`; optional `agent`. |
| `budget` | Required nonnegative `node_hours`; optional nonnegative `llm_usd`; optional `deadline` as a native TOML offset datetime, e.g. `2030-01-01T00:00:00Z` without quotes. Deadlines are not compared with the clock. `soft` defaults to `[0.5, 0.8]`: increasing, unique fractions strictly between 0 and 1; `[]` disables these notifications. |
| `envelope` | Required nonempty lists of nonblank `templates` and `queues`; required positive integers `max_nodes`, `max_walltime_s`, `max_concurrent_jobs`, `max_actions_per_wake`. Template paths/content and actual queue availability are not checked yet. |
| `backend` | Required `kind` (`simulated` or `iri`). Only IRI accepts `iri_base_url`; omitted IRI URLs use the default above. URLs must be absolute HTTPS URLs without credentials, query, fragment, whitespace, control characters, or backslashes; explicit URLs are preserved. |
| `agent` | `interactive` defaults to `true`. Optional `adapter` is `claude_code` or `chemgraph`. With an adapter, require `billing`, positive integer `max_wakes`, `max_turns`, and `timeout_s`; optional nonblank `model`, positive integer `max_wakes_per_day`, positive decimal `max_usd_per_wake`, and `env_passthrough` (default `[]`). With no adapter, only `interactive` may be supplied. |

Adapter capabilities are a fixed, immutable configuration table, not runtime
capability detection: Claude Code supports `api`/`subscription` and reports cost;
ChemGraph supports `api`/`free` and does not report cost. `llm_usd` requires an
API-billed, cost-reporting adapter and `max_usd_per_wake`. Dollar settings only
gate future wakes when `llm_usd` is set; subscription figures never gate work.
Actual environment construction, cost reporting, and wake enforcement land with
their respective runtime increments.

`env_passthrough` contains names, never values, matching
`[A-Za-z_][A-Za-z0-9_]*`. Case-insensitive static exclusions reject `ALCF_*`,
`GLOBUS_*`, and `IRI_*` in every mode. Names ending in `_API_KEY`/`_AUTH_TOKEN`,
the names `API_KEY`/`AUTH_TOKEN`, and `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN` require API billing. `CLAUDE_CODE_OAUTH_TOKEN` requires Claude
subscription billing. Proxy settings `ANTHROPIC_BASE_URL` and
`ANTHROPIC_CUSTOM_HEADERS` remain allowed, as described in the adapter design.
These checks do not inspect environment values or establish runtime isolation.

`[stop]` and `[wake]` are currently rejected, including empty sections. Stop-rule
configuration belongs to lifecycle increment 11; wake-trigger configuration
belongs to decision-event/headless increments 12/16. Proposal shapes are
implemented in 2b1 below; target/template contracts and `init` belong to 2b2.

### Implemented proposal contracts (roadmap 2b1)

`watchkeeper.actions.ProposalRequest` validates proposal data with
`model_validate(data)` or `model_validate_json(text)` and exports its tool schema
with `model_json_schema()`. Validation raises Pydantic `ValidationError`. There
is no installed proposal command or production MCP server yet.

The envelope requires a nonblank `request_id` and a nonempty, ordered `actions`
list. Each action requires its `kind` discriminator and every field shown:

- `run`: `{kind:"run", template, params, resources:{nodes, walltime_s, queue}, rationale}`.
- `note`: `{kind:"note", text}`.
- `ask_human`: `{kind:"ask_human", question}`.
- `stop`: `{kind:"stop", reason}`.

The named text fields are nonblank strings preserved exactly as supplied. Resource
counts are positive integers; booleans and numeric strings are rejected. `params`
is a JSON object (possibly empty), with string keys and nested JSON values;
nonfinite numbers and non-JSON Python values are rejected. Envelope, action and
resource models reject unknown fields. The schema uses a `kind`-discriminated
union, shared by the diagnostic ChemGraph MCP fixture.

These checks establish shape only. Template existence/parameter contracts,
envelope limits (including `max_actions_per_wake`), request replay, approval and
execution remain later increments. Parameters are data and cannot override the
separate resource fields. Validation creates no state or action effects.

### Approval and execution contracts (future)

`watchkeeper approve-plan` records the digest of an **execution manifest**: `campaign.toml`, `target.toml`, and every file under each allowed `templates/<name>/` (including `template.toml`). `target.toml` holds executable settings (`environment_setup`, `python`, `account`), so it is part of what is approved.
- Every check below re-hashes the manifest. If it no longer matches, the campaign pauses until it is approved again:
  - before an approval,
  - before staging,
  - before submission,
  - before a wake.
- Prepare and atomically publish a verified immutable input snapshot under `runs/<op_id>/inputs/` before committing approval and reservation together. Record its manifest digest and file hashes on the operation. A crash may leave an unreferenced snapshot, but it never establishes approval or permission to submit. Staging and submission use and re-hash only that snapshot; they never re-render inputs.
- Store collected files under `runs/<op_id>/outputs/` and approved validators under `runs/<op_id>/validator/`. Output collection cannot overwrite inputs, validators, database files or other runs. Reject path traversal and symlink escapes.
- After a manifest change, reapproval alone does not rewrite pending operations. Before staging/submission, require the snapshot's execution-affecting configuration to match the current approved configuration; mismatches await operator review. Validator-only changes preserve computation identity and use the explicit revalidation path for existing results.

**Future effects of the [action contracts](#implemented-proposal-contracts-roadmap-2b1):**
`run` proposes computation, `note` writes the campaign notebook, and `stop`
requests draining. `ask_human` stores a question with an id; the operator answers
with `watchkeeper answer QID TEXT`. The answer is recorded transactionally,
creates one `human_answer` wake trigger (consumed once), and appears in the next
brief. None of these effects is implemented by proposal validation.

Cancelling a job is operator-only in v1.

**Templates and parameters** (agent-controlled values never reach a shell):
- `template.toml` declares a strict parameter schema: type, enum or range, pattern and max length for each param. Unknown params are rejected.
- Agent `params` are written only as data. Data files (e.g. `input.json`) are produced with `json.dumps` from a declared mapping, never by text substitution of agent values.
- `string.Template` substitution in scripts such as `launch.sh` is limited to dispatcher-owned fields (target settings, `op_id`, resources).
- Rendered paths must stay inside `runs/<op_id>/`. `resources` and target fields can't be set through `params`.

**Operation state machine (remote job):**

```
proposed → approved → staging → submitting → submitted → finished → collected → validated
off-path: blocked · rejected · failed(definite, with evidence) · invalid(validator said no) · cancelled(never submitted) · uncertain · abandoned
```

- Terminal states: `validated`, `invalid`, `rejected`, `failed`, `cancelled` and `abandoned`. `uncertain` is never terminal; it waits for the operator. A validator *execution* failure leaves the operation `collected` (see Validation).

- Every save is a compare-and-set on a revision number.
- Before calling the CLI, `staging` saves a Globus `submission_id` (from `globus task generate-submission-id`) together with the exact transfer request. Recovery replays with the same `--submission-id`, and Globus answers `Duplicate` with the original task id ([skills/globus-transfer/references/cli.md](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/globus-transfer/references/cli.md)). `tick` polls the task rather than blocking on it. A failed stage goes to `failed`; nothing was submitted, so the reservation is released. Once an operation reaches `submitting` it is never restaged. A backend with nothing to stage passes straight through.
- `submitting` is committed **before** the submission request is sent.
- At startup, `recover()` turns `submitting` into `uncertain`.
- `queued` and `running` are observed sub-states of `submitted`, recorded in the history.

**Concurrency:**
- One supervisor host per campaign, using a local SQLite database (not a shared/network filesystem). `tick` and `run` take a lease recording owner token, pid, process start time and heartbeat. A stale heartbeat alone never permits takeover from a live owner; ambiguous identity refuses takeover. Recovery runs only after ownership is established. Database transactions remain short, with network and subprocess work outside them.
- **Wakes are journalled like operations:** `starting → registered → running → exited → dispatched`, with off-path states `interrupted` and `unverified`.
  - The wake row (with a random wake token) is committed before anything is spawned.
  - On Linux/macOS the supervisor spawns a **bootstrap** (`watchkeeper _wake WAKE_ID`) in a new session; pgid = bootstrap pid. Windows headless launch is explicitly unsupported until a follow-up implements equivalent recovery.
  - The bootstrap records its own pid, pgid or job name, and process start time on the wake row (`starting → registered`). It then waits for the supervisor to acknowledge (`registered → running`). Only after that acknowledgement does it start the adapter inside the same group.
  - If no acknowledgement arrives within `ack_timeout_s`, or the bootstrap's parent changes, it exits without starting the adapter. A crash between spawn and registration therefore can't leave an adapter running.
  - `recover()` handles a wake by its state:
    - `starting`: wait `ack_timeout_s` plus a margin (any bootstrap has exited by then), then mark it `interrupted`.
    - `registered`/`running`: **verify identity before signalling, and verify containment-unit termination, never just the bootstrap pid.**
      - POSIX:
        - If a process with pid = pgid exists and its start time matches the record, it is ours: `killpg`.
        - If it exists with a *different* start time, the number was reused. Because the kernel doesn't reuse a pid while a group with that id still has members, our group was already empty when the id was reused, and an empty group can't regain members. Nothing is signalled, and this counts as verified termination. (Linux and BSD/macOS both refuse to allocate a pid that is still in use as a group id.)
        - If no such process exists but `killpg(pgid, 0)` succeeds, ownership is **not** established. Across downtime, our group may have emptied and its id been reused by an unrelated group whose leader then exited. Nothing is signalled, and the wake becomes `unverified` for the operator to resolve.
        - To make the leaderless case rare, the bootstrap stays the group leader for the adapter's whole life: it waits on the adapter, and on every exit path it can handle (normal exit, timeout, SIGTERM/SIGINT) it `killpg`s its own group before exiting. Only a hard kill of the bootstrap leaves a leaderless group.
        - Otherwise, termination is verified only when `killpg(pgid, 0)` reports no such group after our `killpg`.
      - Only after that verification is the wake marked `interrupted`.
    - If identity or termination can't be established, mark the wake `unverified`. No new wake starts until the operator runs `confirm-wake-ended`.
  - Residual limit, stated in the README: a descendant that deliberately leaves the POSIX session (`setsid`) escapes the group. The watchkeeper MCP server is still fenced by its wake token, and it exits on stdin EOF.
  - No new wake starts while any wake is `starting`, `registered`, `running` or `unverified`.
- A headless MCP server attaches to an existing wake using its ID and token; it never creates or closes that wake. Stdin EOF closes only that server, allowing CLI MCP clients to reconnect. The supervisor/bootstrap alone records the headless outcome. The MCP server is launched with the wake token. `propose_actions` inserts `proposed` rows tagged with that wake and is refused unless the wake is `running`, so late writers are fenced out. A headless-wake server never approves or dispatches. An interactive server dispatches synchronously (see **Two ways to drive a campaign**).
- **Every wake counts** toward `max_wakes` and `max_wakes_per_day`, `rate_limited` ones included. The count is taken when the wake row is committed, before anything is spawned, so a crash or restart can't lose it. Interactive sessions are not counted.
- **Request idempotency is kept separate from computation identity.** This works like the tool-call identity in [runtime/journal.py:161-170](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/runtime/journal.py), kept independent of operation state.
  - `propose_actions` takes a required `request_id`. The skill and the headless brief tell the agent to use a fresh id for each new intent, and to **reuse the same id when retrying a call whose result it didn't get**. Each action is identified by (`request_id`, item index).
  - A `requests` table maps (campaign, `request_id`) to the canonical payload hash and the per-item proposal ids. It is unique per campaign, not per wake, so a replay arriving in a later session is caught too.
  - **Replay** (same id, same payload): returns the original per-item dispositions. Nothing is inserted or dispatched again, even if the operation has since failed.
  - **Same id, different payload:** refused.
  - A **new id** goes through the normal action-key dedup. That is the intentional-retry path: it is allowed after a definite `rejected`/`failed`/`invalid`, and blocked on `uncertain` or `abandoned`.
  - Residual risk, stated in the README: an agent that loses a response and then issues a *new* id for the same intent looks the same as an intentional retry. It is allowed only after a definite failure, and the envelope and node-hour reservation still bound it. `get_status` shows recent requests and their outcomes, and the skill tells the agent to check it before retrying.
- **Dispatch is resumable:**
  - Each proposal row moves `proposed → dispatched` by compare-and-set, recording its outcome.
  - Every tick dispatches any `proposed` rows from `exited` or `interrupted` wakes. Every proposal still passes the full dispatcher checks, so partial wakes are safe.
  - A wake becomes `dispatched` once it is `exited` or `interrupted` and none of its proposals remain. A `running` interactive wake is never closed just because its queue is empty.
  - Dispatch side effects are keyed by proposal id: one operation, note, question or stop per proposal. A crash before or during dispatch therefore resumes without loss or duplication.
- Operator CLI commands (`approve`, `abandon`, `answer`, …) are compare-and-set transactions, so they are safe to run alongside the supervisor.

The patterns (compare-and-set revisions, `recover`, `confirm_nonexecution`, `abandon`, no automatic retry) are borrowed from [src/chemgraph/runtime/journal.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/runtime/journal.py). They are **reimplemented** without LangChain or ASE, not extracted from it. Bringing the two together later is a follow-up.

**Dispatcher** checks each proposed action in this order:
1. Schema.
2. Template is allowed by the envelope.
3. Resources are within the envelope.
4. Params validate against the template's schema.
5. Identity and dedup. Action key = sha256(template execution digest + backend identity + resolved IRI endpoint + all execution-affecting target settings (including `compute_resource_id`, `account`, `environment_setup`, `python`, and `filesystems`) + canonical params + resources).
   - The **execution digest** covers every template file except the declared validator file, with `template.toml` canonicalised without its `validate` entry. The manifest digest used for approval still covers everything. Changing only the validator therefore keeps the action key.
   - The key is a logical identity, independent of operation attempts. In the same transaction:
     - if a validated result exists for the key, return it (whatever validator version judged it);
     - if an operation with this key is `approved`, `staging`, `submitting`, `submitted`, `finished` or `collected`, return that operation instead of creating another;
     - if the latest attempt is `uncertain` or `abandoned`, block. Only operator `confirm-nonexecution` permits another attempt, and `abandon` never does;
     - a new attempt is allowed only after a definite `rejected`/`failed`/`invalid`.
6. Budget: an atomic reservation in the same SQLite transaction as the approval. Store node-seconds as integers, with conservative conversion at the node-hour interface; settlement is idempotent.

Within the envelope, a valid action is auto-approved. A resource-envelope exception goes to `awaiting_human`; operator `approve` authorizes only that operation. An unlisted template cannot execute under a one-off approval: first add it to the envelope and approve the changed manifest. Schema, parameters, hard budget, uncertainty, approved bytes and campaign gates cannot be overridden by operation approval.

**Validation (generic):**
- The rendered launch wrapper writes `watchkeeper_status.json` with the exit code and start/end timestamps.
- `template.toml` declares the required outputs and maps exit codes to outcomes, e.g. `{0="ok", 2="nonconverged", 1="failed"}` for ChemGraph's `calculate.py`.
- **Optional `validate` hook.** `template.toml` may declare `validate = "validate.py"`.
  - It is a single file in the template directory, so it is part of the approved manifest. It has no template-local imports, only the standard library and packages in the supervisor's interpreter.
  - After collection, the supervisor runs it:
    - as `sys.executable -I <snapshot copy>`. `-I` keeps the script directory, the cwd and user site-packages off `sys.path`, so collected outputs can't plant modules;
    - with `cwd = runs/<op_id>/outputs/`;
    - with a scrubbed environment (`PATH`, locale; no credential variables);
    - with a timeout (default 60 s).
  - It returns JSON `{"ok": bool, "checks": {...}}` on stdout. Typical checks: energy is finite, the `converged` flag is set, values fall in the expected range.
- **Only approved bytes ever run.**
  - At approval, the validator is copied into the operation's immutable snapshot as `runs/<op_id>/validator/<digest>.py`, and `validator_digest` is recorded on the operation.
  - Before each run, the snapshot copy is re-hashed. It runs only if the hash equals `validator_digest`; a mismatch is a validator execution failure.
  - The template file is never executed in place.
- **Outcomes:**
  - `ok: false` gives `invalid`, a definite scientific failure. It is terminal, the result is stored with its checks, and a new attempt is allowed.
  - Non-JSON output, a non-zero exit, a timeout or a hash mismatch is a **validator execution failure**, not a verdict on the result.
    - The operation stays `collected`, keeping its outputs and settled charge. Validation retries locally each tick with backoff.
    - The campaign is `waiting` and the operator is notified.
    - Dedup returns the collected operation, so there is no replacement run.
    - The operator fixes the validator, runs `approve-plan` and then `revalidate OP_ID`, or runs `abandon`. `abandon` keeps the outputs, blocks reruns of the key, and marks the result `unvalidated`.
- **`watchkeeper revalidate OP_ID`** (operator command):
  - re-hashes the execution manifest and refuses unless it is currently approved;
  - copies the approved validator into a new `runs/<op_id>/validator/<digest>.py`;
  - verifies that the **copy's** hash equals the approved digest (this also covers an edit racing the copy);
  - compare-and-sets `validator_digest`.
  Nothing about the job is re-rendered or resubmitted.
- Each result records the `validator_digest` that judged it. `status` and `report` show it.
- Domain validators added through entry points are deferred.

**Report and sign-off:**
- The store keeps one `campaign_rev` integer. It is incremented in the same transaction as every write to a report input: results, validation outcomes, ledger, operations, notebook, questions and answers, and the stop reason.
- `watchkeeper report` refuses unless the campaign is `complete`. It reads every input and `campaign_rev` in one read transaction, writes `report.md`, and records the revision and the file's digest. `report.md` contains:
  - the goal;
  - the results table, with validation outcomes and validator versions;
  - the notebook;
  - the agent's stop reason;
  - the ledger;
  - the header "agent-concluded, unreviewed".
- `watchkeeper sign-off --note TEXT` succeeds only if:
  - the campaign is `complete`;
  - the latest report's revision equals the current `campaign_rev`;
  - `report.md` on disk still matches its digest.

  It records the reviewer (OS user), the time, the note, the revision and the digest.
- `status` shows a sign-off as **stale** once `campaign_rev` moves past the signed revision. A stale sign-off approves a historical snapshot only.
- Sign-off doesn't gate `complete`, which remains a machine status.

**Supervisor** (`watchkeeper tick` = one idempotent step; `watchkeeper run` = loop with backoff):
1. `recover()` (operations and wakes).
2. Credential check. If credentials have expired, pause (not fail) and notify with the exact command the user should run.
3. Dispatch any undispatched proposals (see Concurrency).
4. Stage and submit approved operations, each passing the **submission gate**.
5. Poll submitted operations.
6. Collect, validate, settle the ledger, store the result.
7. Evaluate wake triggers.
8. Wake at most one adapter at a time, if the **wake gate** passes. After it exits, mark the wake `exited` and dispatch its proposals.

Three separate gates are re-checked before each individual action:
- **Submission gate** (staging and submitting an already-approved operation):
  - the manifest is approved;
  - the campaign isn't paused or stopped;
  - the deadline hasn't passed;
  - `max_concurrent_jobs` and credentials allow it.

  It does **not** re-check the budget, because the operation already holds its reservation.
- **Reservation gate** (approving a new `run` in the dispatcher): the same campaign checks, plus enough unreserved node-hours for this request.
- **Wake gate:**
  - the same campaign checks;
  - an adapter is configured;
  - `max_wakes` and `max_wakes_per_day` aren't reached;
  - the LLM threshold below allows it (only when `llm_usd` is set);
  - no LLM rate-limit backoff is active;
  - no wake (headless or interactive) is active or `unverified`.

The campaign enters **`draining`** on a stop rule, a `stop` action, the deadline, or the operator `stop` command. In the same transaction, a `running` interactive wake moves to `exited`, which fences its token. Its connection stays open read-only. Draining keeps polling, collection and settlement running, but nothing new is staged, submitted or woken. Running out of node-hours or wakes only closes the reservation gate or the wake gate; already-approved, funded work still runs.

**Draining disposition** (runs every tick while draining, so the campaign can finish):
- Undispatched `run` proposals and `awaiting_human` operations are recorded as `cancelled`. Notes and questions are still recorded.
- `approved` operations become `cancelled`, and their reservations are released, because nothing was sent.
- A `staging` operation's Globus task is cancelled (`globus task cancel`) or allowed to finish. Once the task is terminal, the operation becomes `cancelled` and its reservation is released. It is never submitted.
- `submitting`, `submitted` and `uncertain` keep their normal rules and charges.

**Campaign status** is derived each tick:
- **`waiting`** (resumable, never terminal):
  - the campaign is paused or the credential pause is active;
  - a wake is `unverified`;
  - an operation is `uncertain` or `awaiting_human`;
  - an operation is `collected` with a failing validator;
  - an LLM rate-limit backoff is active;
  - a question is unanswered while a wake could still consume the answer.
- **`complete`** only when all of these hold:
  - every proposal is dispatched;
  - every operation is in a terminal state with its result persisted and its ledger entry settled (collection, validation and settlement retry until done, or the operator gives an explicit terminal disposition);
  - no wake is `starting`, `registered`, `running`, `exited` or `unverified`;
  - and either the campaign is draining, or no further wake is possible for a terminal reason: `max_wakes` reached, or `llm_usd` reached when it is set.

  Being paused, an unverified wake, pending recovery or an active rate-limit backoff never counts as complete. With no adapter, "no further wake is possible" never holds, so an interactive-only campaign completes only by draining: an agent `stop`, the operator `stop`, or the deadline.

**Wake triggers:**
- campaign start,
- a batch finished (N results, or all in-flight jobs done),
- a failure that needs diagnosis,
- a soft budget threshold crossed,
- a human answer arrived,
- an idle timer.

**MCP server** (`watchkeeper mcp --campaign DIR`, stdio):
- `get_brief`
- `list_results`
- `get_result`
- `get_notebook`
- `get_status`: node-hours used, reserved and free; operations by state; pending approvals and questions; recent requests and their outcomes; the live wake or session; the backoff
- `propose_actions` (with a required `request_id`)

There is no submit tool.

**Adapters** run as subprocesses: `wake(brief, mcp_command, workdir, env, timeout) -> WakeResult(outcome, exit, usage, transcript, retry_after)`.
- `outcome` is one of `ok`, `error`, `timeout` or `rate_limited`. An adapter reports `rate_limited` when the CLI ends with a usage-limit or 429 error, and passes the reset time through as `retry_after` when the CLI gives one.
- On `rate_limited`:
  - the wake's proposals are dispatched as usual, and it still counts as a wake;
  - nothing is charged under `subscription` or `free`;
  - the supervisor sets a persisted backoff until `retry_after`, or exponential backoff (starting at 15 min, capped at 6 h) when no reset time is known, and notifies once per backoff.
  If rate limits use up `max_wakes`, that is terminal as usual. Raising `max_wakes` is a spec change and needs `approve-plan`.
- Unverified assumption: the exact form the CLI uses to signal a usage limit. PR19 confirms it live. Until then, an unrecognised error is `error`, which costs one wake.
- **The environment is built from scratch:** `PATH`, `HOME` and locale, plus the **billing-specific credential set**, plus `env_passthrough`. Nothing else is inherited.
- **Claude Code:**
  - `claude -p … --output-format stream-json --verbose --restricted --tools "" --mcp-config <file> --strict-mcp-config --allowedTools "mcp__watchkeeper__*" --permission-mode dontAsk --max-turns N`, plus `--max-budget-usd <max_usd_per_wake>` only when `billing = "api"` and `llm_usd` is set.
  - `--allowedTools` only pre-approves tools. Read-only built-ins (Read, Glob, Grep) would still run, and `HOME` is kept for login, so they could read token caches. `--tools ""` removes every built-in tool. `--restricted` ignores user, project and local settings files (and so their hooks), and `--strict-mcp-config` skips all MCP servers except the one in `--mcp-config`.
  - Not `--safe-mode`: in claude 2.1.312 it disables MCP servers, including the one in `--mcp-config`, which would leave the agent with no tools.
  - All of these flags exist in claude 2.1.312. Re-check them against `claude --help` at build time. The PR19 manual smoke test confirms the watchkeeper MCP tools are visible.
  - **Credentials follow the billing mode.**
    - `subscription`: `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` are **never** set. They are stripped even if the parent shell has them, because Claude Code prefers an environment API key over the subscription login. Login comes from `HOME`, and `--restricted` ignores any `apiKeyHelper` in the settings files.
    - `api`: `ANTHROPIC_API_KEY` is passed, or `ANTHROPIC_AUTH_TOKEN` if the spec names it.
    - A LiteLLM proxy (`ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS`) goes through `env_passthrough` in either mode. The README states that the proxy's virtual key reaches the agent process. That is acceptable because the agent has no tools other than the watchkeeper MCP server, and the key only grants LLM spend that the proxy caps.
    - Auth cross-check (best effort): if the CLI reports its auth source before inference (`--output-format stream-json --verbose`, the `apiKeySource` in the `system/init` event), the adapter kills the wake on a mismatch with the billing mode. The killed wake counts as an `error`. The env stripping is the actual guarantee.
  - **With `billing = "api"` and `llm_usd` set, LLM spend is a soft threshold, not a hard cap.** Under other billing modes, `--max-budget-usd` is not passed. `total_cost_usd` is recorded as `notional_usd` and gates nothing, and an unknown cost is recorded as `unmetered`.
    - `--max-budget-usd <max_usd_per_wake>` is checked against spend already incurred, so the final turn can overshoot it by an unbounded amount.
    - The wake gate admits a wake only if recorded spend + `max_usd_per_wake` ≤ `llm_usd`.
    - Spend is recorded from the reported `total_cost_usd`, including any overshoot. If the cost is unknown (an interrupted wake or unparseable output), the wake is recorded at `max_usd_per_wake` and flagged `cost_unknown`.
    - Overshoot and unknown costs are shown in `status` and notified. The README states that `llm_usd` can be exceeded by roughly one turn's cost.
- **ChemGraph:**
  - Verify the CLI/MCP contract early in CG1, below. Integrate the production
    adapter in roadmap 20 after the runtime/recovery milestone 18, before Claude
    Code in 19. The probe is not a production adapter.
  - `chemgraph run --workflow single_agent --recursion-limit N --mcp-command "watchkeeper mcp --campaign DIR <wake attachment arguments>" -q …`. Here `N = max_turns` is a conservative graph-step cap, not a claim that graph steps equal model turns. Use unstructured output without report generation, and test that model calls remain within the bound. The MCP command carries the existing wake identity/token explicitly; it must not rely on arbitrary environment forwarding by the ChemGraph MCP client.
  - `single_agent`, because headless `main_agent` rejects MCP tools (`HEADLESS_TOOLS_ERROR`, [src/chemgraph/cli/main.py:752-754](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/cli/main.py)). With MCP tools given, `single_agent` uses only those tools ([graphs/single_agent.py:504](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/graphs/single_agent.py)).
  - `billing = "free"` (Argo) passes the Argo variables the model loader reads. `billing = "api"` passes the named provider key.
  - LLM cost is recorded as `unmetered` until ChemGraph reports usage headlessly. That is a ChemGraph follow-up. Like every adapter, it is capped by `max_wakes`.
- **Scripted** (tests only): a deterministic policy that calls `propose_actions`.

### Early ChemGraph contract probe (CG1)

Implemented by `tools/chemgraph_contract.py` with diagnostic and test fixtures
outside the package runtime; see [usage and evidence](#running-the-cg1-probe).
It accepts an explicit installed ChemGraph executable; never import ChemGraph
in Watchkeeper, require its checkout, auto-install it, or expose a new installed
`watchkeeper` command. Ordinary CI exercises fake executables, the diagnostic
MCP server, and the local model fixture. Running the real CLI is a separate,
explicit opt-in on Linux/macOS.

**Real CLI, fake services.** Launch unstructured `single_agent`, without report
generation or human-supervised tools, using an explicit probe configuration,
model name, `--base-url`, `--recursion-limit`, and `--mcp-command`. Use a fresh
scratch directory and HOME, a minimal environment, and no real credentials.
Bind the fake OpenAI-compatible model endpoint to loopback on an ephemeral port;
use only a dummy key. Never fall back to a real provider or another workflow.
The pinned [custom endpoint implementation](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/models/endpoints/vllm.py)
supports an otherwise unknown model with an explicit base URL. Verify installed
CLI flags before the probe; record unsupported behavior as incompatibility.

**Diagnostic MCP only.** Expose fixture `get_brief` and `propose_actions` tools;
the scripted model reads the brief and proposes one batch containing `run`,
`note`, `ask_human` and `stop`, with a required request ID. Since 2b1 the fixture
uses `ProposalRequest` for both its advertised schema and validation, replacing
CG1's original diagnostic-only `{type:"note"}` shape. Record the exact payload
and return a diagnostic acknowledgement, never an approval/disposition or any
action effects. The fixture has no campaign path,
database, backend, dispatcher, token cache, or submission code. It records only
probe artifacts; duplicate calls are observations, not a substitute request
journal. Serialize launch arguments as data, use subprocess argv without a
shell, and quote the MCP command's argv for ChemGraph's `shlex.split` parsing.

**Reconnects.** Pass a unique probe identity explicitly in the MCP command and
retain diagnostic observations across server processes. Check discovery and
tool calls after EOF/reconnection all carry that identity. This checks the
[ChemGraph MCP client's](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/cli/mcp_utils.py)
transport behavior; it does not create or recover a real wake, consume wake
allowances, or demonstrate token fencing/request replay. Those remain runtime
tests in 6, 15–18, and 20.

**Acceptance scenarios.** The fake model captures every request and tool schema,
returns scripted tool calls, and supports success, continued tool-loop, and
provider-error responses. Assert that only the diagnostic MCP tools reach the
model, the shared proposal schema survives transport (allowing inlined references
and omitted title/description annotations), the entire mixed batch reaches the
fixture unchanged, and EOF/reconnects preserve probe identity. Inspect actual
provider-request counts, including retries and
error paths: passing `--recursion-limit N` alone does not prove a model-call
bound. Report any excess or unobservable count as an unresolved adapter blocker;
never weaken the production bound to make the probe pass. Include missing CLI,
unsupported flags, malformed tool arguments, failed MCP startup, nonzero exit,
and timeout/cleanup cases. Bound each case with a foreground timeout and POSIX
child-group cleanup; durable crash recovery still belongs to 17.

**Evidence and promotion.** Save a concise local result with executable/version
or commit provenance, flags, observed tool names, proposal/reconnect checks,
request counts, exit/timeout outcome, and compatibility failures. Keep artifacts
credential-free and out of source control; record a sanitized summary in
`docs/progress.md`. Distinguish harness-only, real-CLI/fake-model, and later
user-run live-provider results. A fake-CLI pass proves only the harness, and a
real-CLI/fake-model pass proves neither provider authentication nor campaign
durability. At 20, reuse the verified launch/transport contracts in the runtime
adapter and replace diagnostic fixtures with the real wake journal and MCP
server. Do not maintain the harness as an alternative campaign runner.

#### Running the CG1 probe

From a development checkout with the test dependencies installed:

```bash
.venv/bin/python tools/chemgraph_contract.py \
  --chemgraph /absolute/path/to/chemgraph \
  --provenance 'installed version/commit, or unknown' \
  --output .cg1-artifacts/run-1 --recursion-limit 6 --timeout 30
```

This invocation opts into running that executable; it never installs ChemGraph.
The output directory must be new. `.cg1-artifacts/` is ignored by Git. The tools
ship in the source distribution, not the installed wheel. Ordinary `pytest`
runs use fake CLIs only, including actual loopback HTTP and stdio MCP transports.

`result.json` records supplied provenance separately from the observed
`--version` response (unsupported version flags remain visible), CLI arguments,
bounded log excerpts, tool names, MCP events, counts, checks, and blockers.
Per-case request files retain the exact model bodies/tool schemas, without HTTP
headers. Scratch configuration, HOME, and CLI-created state are removed. These
are local diagnostic artifacts; only sanitized findings belong in the handoff.

The success, malformed-argument, and failed-startup cases use the requested graph
limit. Tool-loop and HTTP 500 cases each run at limit 1 and the requested limit,
counting retries individually. Exit 0 from the harness means its observed checks
passed; exit 1 reports compatibility blockers. A zero CLI exit after an injected
provider/recursion failure is a blocker, not successful completion. An absent
request count cannot establish a bound. These observations are not a proof for
untested providers or CLI versions.

Every foreground invocation has a timeout and POSIX group cleanup, including
help/version. The diagnostic MCP fixture also has an explicit absolute deadline
because MCP clients may launch it in another process group. This bounds the
cooperative fixture while stdin remains open; it is not durable crash recovery
or containment of arbitrary detached processes. Linux/macOS only. The probe adds
no installed command; the shared proposal models are the package API from 2b1.

**Notifier:** `log` plus a generic `command` notifier (runs a user script, e.g. a Discord webhook `curl`). Dedicated Discord or Slack adapters come later. Messages say what is needed: pending approvals with their exact commands, a batch summary, and, for interactive campaigns, "resume with: continue campaign <name>".

## Two ways to drive a campaign

Both are in v1. They share one store, one dispatcher and the same gates, and differ only in who the decision-maker is. A hook can't be the main interface: Claude Code has no hook that runs before each model call, and hooks die with the session.

**Interactive mode (the user's own Claude Code or Codex session).**
- **Setup.**
  - `watchkeeper print-mcp-config --campaign DIR` prints the MCP server entry for the user to add: `watchkeeper mcp --campaign DIR --interactive`.
  - A tool-neutral skill ships at `skill/SKILL.md`. The user symlinks it into `~/.claude/skills` or `~/.codex/skills`. The skill tells the agent to:
    - scaffold with `watchkeeper init` and draft `campaign.toml` and the templates together with the user;
    - run `validate`;
    - **ask the user** to run `approve-plan` themselves;
    - after that, act only through the watchkeeper MCP tools and never call IRI, Globus or the scheduler directly;
    - on "continue campaign X", start with `get_brief`.
- **A session is a wake of kind `interactive`.**
  - At startup the server registers a wake row (state `running`, a random token, its own pid and start time) in one transaction. It does so only if no other wake is `starting`, `registered`, `running` or `unverified`, the campaign is neither `draining` nor `complete`, and `[agent] interactive` is true. It then heartbeats every 30 s.
  - Otherwise it starts **read-only**: read tools work, and `propose_actions` returns the reason. Opening a connection just to inspect a finished campaign never creates a wake.
  - There is therefore at most one decision-maker at a time. Headless wakes wait while a session is live, and their triggers stay pending.
- **Lifetime.**
  - The wake stays `running` across any number of calls and ticks.
  - Stdin EOF (the session closed) marks it `exited`. Entering `draining` also marks it `exited` (see above).
  - The server spawns no children, so recovery only checks the pid and start time. If the process is gone, the wake becomes `interrupted`; it is never `unverified`.
  - `watchkeeper end-session` marks a live but abandoned session `interrupted`, for example a laptop that went to sleep. Token fencing makes the server harmless from then on, because its only side effects are writes to the database. No kill is needed.
- **Synchronous dispatch.** `propose_actions` inserts the proposals and runs the **same dispatcher** on them in the same call. Dispatch is keyed by proposal id, so it is idempotent with tick-time dispatch. It returns one disposition per item:
  - `approved` (reserved);
  - `awaiting_human`, with the exact `watchkeeper approve OP` command;
  - `duplicate` (the existing operation or result);
  - `blocked` (an `uncertain` or `abandoned` key);
  - `refused`, with the schema, envelope, budget or gate reason.

  It then spawns a detached `watchkeeper tick --campaign DIR` so staging and submission happen promptly. The tick lease makes that safe alongside cron, and cron remains the backstop. The interactive server never stages or submits.
- Sessions are **not counted** toward `max_wakes`, `max_wakes_per_day` or `llm_usd`, because they use the user's own LLM login. The envelope, node-hour reservation, dedup and every gate apply unchanged.
- **Guard (a tripwire, not a boundary; see Principle 2).** `watchkeeper guard` is a PreToolUse hook command for Claude Code (`.claude/settings.json`) and Codex (`pre_tool_use` in `.codex/hooks.json`; Codex 0.165 has stable hooks with hash-based trust).
  - It denies Bash commands that run watchkeeper operator commands: `approve`, `approve-plan`, `reject`, `confirm-nonexecution`, `abandon`, `confirm-wake-ended`, `answer`, `revalidate`, `sign-off`, `resume`, `end-session`.
  - It denies direct submission: `iri_submit.py`, `iri.sh` submit, `qsub`, `globus transfer`, and curl/wget to the IRI host from `resolve_base_url(spec)`.
  - `watchkeeper guard --print-config claude|codex` prints the snippet. It never edits settings.
  - The human runs operator commands in a separate terminal. Unverified: whether Claude Code's `!` prefix triggers PreToolUse. PR25 checks it.

**Autonomous mode** is the headless-wake design above. Wake triggers launch an adapter only if `[agent] adapter` is set and no session is live. With no adapter, triggers only notify.

**Background progress, the same for both modes.**
- `watchkeeper tick --campaign DIR` runs every 5 min from cron or launchd; the README has crontab and plist examples. Alternatively, `watchkeeper run` runs in tmux.
- It needs an always-on machine that can reach IRI. A sleeping laptop only delays progress, because ticks are idempotent.

**CLI:**
- `init`, `validate`, `approve-plan`
- `tick`, `run`, `status`
- `approve`, `reject`
- `confirm-nonexecution`, `abandon`, `confirm-wake-ended`, `end-session`
- `answer`, `revalidate`
- `report`, `sign-off`
- `pause`, `resume`, `stop`
- `mcp`, `print-mcp-config`, `guard`

## Planned package layout

```
watchkeeper/
  pyproject.toml            # setuptools, src layout, python>=3.11, deps: pydantic>=2,<3, mcp>=1.28.1,<2
                            # planned extra: iri = ["alcf-tokens"]; test = ["pytest", "ruff", "build"]; console script `watchkeeper`
  README.md
  src/watchkeeper/
    __init__.py  cli.py  spec.py  store.py  ledger.py  journal.py  dispatcher.py
    results.py  supervisor.py  brief.py  mcp_server.py  notify.py  report.py  guard.py
    backends/{base.py, simulated.py, iri.py, globus_cli.py}
    adapters/{base.py, scripted.py, claude_code.py, chemgraph.py}
  skill/SKILL.md            # tool-neutral; users symlink into ~/.claude/skills or ~/.codex/skills
  tests/
```

**Globus staging** shells out to the user's existing `globus` CLI login (the same path the globus-transfer skill uses). The `submission_id`, request, label and task id are recorded, and the `staging` state above defines replay. IRI upload and download return 501, so staging can't go through IRI. Small outputs are collected with IRI `view`. IRI filesystem requests (including `mkdir` and `view`) return asynchronous task IDs: persist the ID and poll across ticks. Never treat the initial task response as completed file content. Job usage is settled only from authoritative allocation data; launch-wrapper timestamps are diagnostic. If authoritative usage is unavailable, retain the full reservation.

## Implementation sequence

The authoritative [implementation roadmap](implementation-plan.md) replaces the original
ChemGraph monorepo sequence. Each increment lands independently in this repo;
there is no requirement to change or test ChemGraph itself.

## Reuse (read, port or copy; never import)

Sources are pinned to ChemGraph commit `855e3756856e49aa4326937e552840acd5ebdaf9`.
Preserve applicable notices and record changes when porting code.

| Source | Use |
| --- | --- |
| [src/chemgraph/runtime/journal.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/runtime/journal.py) | Compare-and-set, recovery, nonexecution and abandonment patterns |
| [src/chemgraph/skills/iri-hpc/scripts/iri_submit.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/iri-hpc/scripts/iri_submit.py) | Submission classification, no-redirect opener and lazy token access |
| [src/chemgraph/skills/iri-hpc/references/api-v2.md](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/iri-hpc/references/api-v2.md) | IRI v2 status and filesystem recipes |
| [src/chemgraph/skills/iri-hpc/assets/target.example.toml](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/iri-hpc/assets/target.example.toml) | Compatible target format |
| [src/chemgraph/skills/iri-hpc/assets/launch.sh.template](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/iri-hpc/assets/launch.sh.template) | Launch wrapper reference |
| [src/chemgraph/skills/iri-hpc/scripts/iri_configure.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/iri-hpc/scripts/iri_configure.py) | Target writer; output remains compatible |
| [src/chemgraph/skills/chemgraph/assets/calculate.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/chemgraph/assets/calculate.py) | Copy into the chemistry example, preserving notices |
| [src/chemgraph/skills/globus-transfer/references/cli.md](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/skills/globus-transfer/references/cli.md) | Submission-ID transfer replay recipe |
| [tests/test_iri_submit_guard.py](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/tests/test_iri_submit_guard.py) | Hermetic HTTP-test patterns |

## Chemistry example (PR26)

Keep chemistry under `examples/mace_screening/`, outside the package core.
Copy the [20-SMILES fixture](https://github.com/argonne-lcf/ChemGraph/blob/855e3756856e49aa4326937e552840acd5ebdaf9/src/chemgraph/academy/campaigns/example-002-mace-ensemble-screening/data/mace_screening_20_smiles.json)
so the example does not depend on the Academy folder remaining in ChemGraph.
The template accepts a pattern-restricted `smiles` parameter, serialized into
JSON as data. Its launch script first invokes an example-owned `prepare.py`
using `smiles_to_coordinate_file_core(smiles, "molecule.xyz", seed=2025)` from
the compute environment's installed ChemGraph. The calculation input specifies
`input_structure_file = "molecule.xyz"` before running the copied `calculate.py`.
Use exit mapping 0/2/1 for success/nonconvergence/failure and an application-owned
validator. Capture setup/preparation failures in the status wrapper as well as
calculation failures. Ordinary tests use mocks or EMT, never model downloads.
The user performs `alcf-tokens login iri` and `globus login`; Watchkeeper does
not initiate interactive authentication or install a compute environment.

## Out of scope (follow-ups)
- Globus Compute backend.
- Codex headless adapter and its billing detection. Codex is supported interactively in v1.
- Reading spend back from a LiteLLM proxy (`/key/info`) into the ledger.
- BO or active-learning baseline scorer and VOI.
- Dashboard.
- Discord or Slack notifiers.
- ChemGraph headless `main_agent` with MCP, plus usage reporting.
- Bringing watchkeeper's journal and `chemgraph.runtime` together.
- Academy and swarm (the roadmap's G3 revision: the campaign store lives in watchkeeper, not `academy/core`).
- Publishing to PyPI.
- Windows headless execution and Job Object recovery.

## Verification
- Each PR: `ruff check .`, `python -m pytest`, distribution build and dependency check, all in this standalone repository.
- PR18 hermetic end-to-end run: a simulated multi-day campaign completes. Assert:
  - ledger total equals known settled usage plus conservative charges/reservations for unknown outcomes;
  - zero duplicate submissions after a hard kill and restart;
  - an uncertain operation, and any re-proposal of its action key, stays blocked until the operator acts;
  - no wake overlaps another, and no proposal from a non-running wake is accepted.
- PR25 manual check, using a real Claude Code session with the MCP entry, the guard and the skill, against the simulated backend:
  1. Start a campaign through the skill. The user approves the plan in a separate terminal.
  2. The agent proposes runs, and the spawned tick submits them.
  3. Close the session. Cron ticks finish the batch and the notifier fires.
  4. Reopen and say "continue campaign X". The brief is picked up.
  5. With an adapter set, a headless wake fires only after the session has closed.

  Repeat steps 1–2 once in Codex. Record whether `!` commands trigger PreToolUse.
- PR19 manual smoke test: a real `claude -p` wake against the simulated backend with `billing = "subscription"` (the user's Max login). Check that the watchkeeper MCP tools are visible, that it proposes valid actions, that it can't reach Bash or file tools, and that `notional_usd` is recorded but gates nothing. An optional second run with `billing = "api"` and a small `llm_usd` checks that the recorded cost matches `total_cost_usd`. Also record live how the CLI reports a usage-limit failure, and the `apiKeySource` it reports in each mode.
- PR26 live run (user-run): Polaris debug queue, about 3 runs, `node_hours` cap of about 1. Check:
  - jobs submit once;
  - `watchkeeper status` honestly distinguishes known usage from full conservative charges;
  - stopping and restarting `watchkeeper run` mid-campaign resumes cleanly;
  - an expired IRI token pauses the campaign rather than failing it.
