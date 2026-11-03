# Memory and cache audit of the ANTS codebase

Date 2026-11-01, branch `synthesizer`, hackathon deadline 2026-11-04. Scope: which parts of System 1, System 2, the orchestrator, policy development (offline hardening) and deployment (running a saved policy on a cell) can become **memory** (durable knowledge that changes future decisions) or **cache** (memoised, content-addressed results that save cost or time and change no decision). Nothing was edited or run in the repo except read-only analysis of `data/runs`.

**Tags.** `[code]` read in `src/`, `tools/`, `tests/`, or ASPIRE source. `[doc]` read in `docs/`. `[data]` measured by a read-only script over `data/` (git-ignored local runs). `[inferred]` my reasoning, not verified. Line numbers refer to the working tree on 2026-11-01 (it has uncommitted edits, see `git status`).

## 0. Findings in one page

1. **Only one real cache exists: the Muse call cache** (`src/ants/synthesizer/llm.py:67-82`). Everything else called "resume", "record", "evidence" is a run-directory convention keyed by path name, not by content.
2. **The LLM key is content-addressed but not sample-aware.** Key = `sha256([model, messages, temperature])[:24]` (`llm.py:68-70`). Two "samples" at equal temperature are the same sample. The ledger proves it: `demo/s0/a0` (key `5e2809…`) was served from cache 3 times after its single paid call, across exp01, exp01b and exp02 (`data/llm_ledger.jsonl`, 0-based line indices 3, 16, 45, 70) [data]. So the first program of exp02's samples at T 0.2 and 0.7 is the exp01 program; only the repairs differ. This matters for the "not reproduced" statement in `experiment-02-scaled-scene.md`.
3. **There is no rollout cache and no rollout key**, yet rollouts are the expensive, deterministic part. Measured determinism [data]: 65 groups of repeated runs with the same program sha, seed, suite, task and `scene.json` hash (136 runs); 63 groups have a **byte-identical `episode/steps.jsonl`**. The 2 exceptions are scaled-scene re-scores 1 h 46 min apart, across the launcher on-top-tolerance fix, so the launcher source must be in any key.
4. **`CapHarness.run` can return a stale result** (`src/ants/adversary/rollout.py:80-88`): it picks the newest `outcome.json` under `output_root`, ignores `proc.returncode`, and does not catch `subprocess.TimeoutExpired`. `--eval-only` re-scores reuse `eval_<scene>_seed<N>` directories (`demo_vs_nodemo.py:151`), so a crashed re-run silently returns the previous run's outcome.
5. **`CaseSpec` cannot identify a rollout.** It omits the harness `scene` (`rollout.py:30`, e.g. the scaled scene), `max_steps`, camera size, `init_mode`, the launcher version and the policy bytes. `EpisodeTrace.policy_id` is a free-form tag such as `demo-s0-final` (`demo_vs_nodemo.py:118`), not a code hash. `Policy.prompt_hash` exists (`types.py:82`) but no code sets it [code].
6. **Memory is specified but not built.** `Skill.help_count`/`last_used` exist (`types.py:163-164`) and nothing reads or writes them; no retrieval, decay or admission code exists. `Constraint` is the only System 2 to System 1 object and `harden` hands the generator **all** constraints every cycle (`system2.py:133`), with no retrieval, pruning or credit assignment.
7. **A "correction behavior library" is mostly a join of things the loop already produces in one place**: the `Constraint` (`diagnoser.py:56`), the triggering `CaseSpec`, the failing feedback, the unified diff (`runlog.unified_diff`), the `GateDecision` (`gate.py:13`) and run ids. `harden` has all of them in scope at `system2.py:141-159`, and writes them to `system2.jsonl` unlinked. Section 3 gives the record and dataclass diff.
8. **Held-out separation is enforced only by seed ranges** (`system2.py:51-52,72,82`) and a `split` label on `CaseSpec` (`types.py:115`) that no store keys on. ASPIRE's own doc warns that seeded-mode seeds are "not a guarantee of distinct layouts" (`ASPIRE/docs/libero-pro.md:77-79`), and the `saved` mode wraps seeds at 50 so seed 51 equals seed 1 (`:73-74`). Any cache or memory must key on a layout fingerprint, keep separate namespaces per split, and be unreadable from decision code for held-out.
9. **No deployment code exists** (P9). The hooks are `Policy.kind="monitored_program"`, `Constraint.check_code`, `Skill.precondition`/`envelope`, and the program-declared `params`/`attack_ranges` dict literals added to the prompt rules in the uncommitted `generator.py:20`. Those literals are a ready-made, machine-readable validated envelope.
10. **`harden` was never run against a real simulator or Muse** (only `tools/system2_mock.py` and `tests/orchestrator/test_system2.py` call it) [code]. Hackathon memory/cache work must therefore ride the day the loop goes live, not precede it.

## 1. What is persisted or cached today (a)

| # | Artifact | Where (writer) | Key / identity | What invalidates it | Gaps | Split leakage |
|---|---|---|---|---|---|---|
| A1 | **Muse call cache** | `data/llm_cache/<24 hex>.json`, 67 files (`llm.py:67-82`) | `sha256(json([model, messages, temperature], sort_keys))[:24]` | Any change to prompt text, model string or temperature (natural miss). Nothing else | See §4.1: no sample index, no `base_url`/params/model snapshot, request not stored (key unverifiable), non-atomic write (`:80`), no schema version, no corrupt-entry handling (`json.loads` on read, `:73`), entries never expire | None by construction (prompt only), but a prompt containing held-out evidence would be cached forever; no code does this |
| A2 | **Token ledger** | `data/llm_ledger.jsonl`, 88 rows, 21 cache hits (`llm.py:84-101`) | append-only; `cache_key`, `tag`, tokens, seconds | Never | Older rows lack `reasoning_tokens` (schema drift: `KeyError` in my own reader). `spent()` reads the file once per process (`:57-65`), so two concurrent processes (exp04 E and G ran as separate logs) each see the same base; the hard cap is per process [inferred]. Hit rows are logged like calls. No prompt hash or response `model` field | None |
| A3 | **Run directory per experiment** | `data/runs/<name>/` 8.7 GB (`runlog.py`) | path: `<arm>/sample<N>/attempt<K>` | Manual | `config.json` is **overwritten** on every start (`demo_vs_nodemo.py:256`), so a resumed run loses its first config (exp02 resumed with a different budget). Not content-addressed | Mixed: acceptance seeds only so far |
| A4 | **Per-run artefacts** (messages, reply, api_response, program, diff, feedback, `events.jsonl`) | `RunLog` (`runlog.py:38-57`), `demo_vs_nodemo.py:68-76,103` | file names | Manual | They are the audit trail and complete enough to rebuild A1 entries (`api_response_attempt*.json`), but there is no import path back into A1 | None |
| A5 | **Sample-level resume** | `record.json` exists and not `stopped` -> reuse (`demo_vs_nodemo.py:272-275`, `scene_context_exp.py:265-267`) | `<arm>/sample<N>` path only | Delete the file | Config-blind: changing `--demospec`, `--task`, `--repairs`, `--debug-scene`, prompt rules or the launcher reuses the old record silently | None |
| A6 | **ASPIRE run dir** (per rollout) | `<output_root>/libero-pro/<suite>/<task>/<seed>/run-<ts>-<id>/` | `run.json` (seed, suite, task, `init_mode`, providers, `environment_sha256` is `null` in our runs), `source/provenance.json` (program `sha256`, `dependency_lock_sha256`, `harness_git.commit` + `dirty:true`), `manifest.json` (sha256 of every file) [code `artifacts.py:370-411,770-780`, data] | New dir per run | It already carries most of a rollout key. Missing: launcher/`scene.json` hash (written by ANTS one level up, `rollout.py:49-50`, overwritten per call), `harness_git.dirty` means the commit does not pin the code | Seeds in `run.json`; split is not recorded |
| A7 | **`scene.json`** (perturbation spec) | `<output_root>/scene.json` (`rollout.py:49-50`) | none | overwritten per call | Located outside the run dir; the run dir does not point to it | none |
| A8 | **Contact log and scene dumps** | `contacts.jsonl`, `*_scene.json`, `*_scene_reset.json` via `tools/aspire_launch.py` `contacts` key; `data/evidence/` 143 MB, `data/scenes/` 91 MB | by directory | manual | `_scene_reset.json` is a pure function of (suite, task, seed, scene spec): a program-independent layout fingerprint. Not exploited | none |
| A9 | **System 2 cycle log** | `<run>/system2.jsonl` (`system2.py:105-168`) | one row per cycle | n/a | Holds tests, new constraints, gate decision and per-case results, but nothing links a constraint to the diff that fixed it or to run ids of the failing/passing rollouts (the `run_dir` is in `tests[]` only) | acceptance only (enforced `system2.py:82`) |
| A10 | **DemoSpec JSON** | `data/demospecs/*.json` by `tools/hurobo_demospec.py:94-121`, `tools/libero_demospec.py:143` | file name = clip id | Manual | No content hash, no extraction parameters (marker size 6.0 cm was used; 5.75 cm measured, `HANDOFF.md` §2), no tool version. The generator reads the extra `summary` block directly (`demo_vs_nodemo.py:255`); `DemoSpec` has no `summary` field and `from_json` drops unknown keys silently (`types.py:186`). `quality` is `{}` for hurobo (`hurobo_demospec.py:119`), so the "low quality escalates" rule has no signal | n/a |
| A11 | **Viewer output** | `<run>/report.html`, built by `evalkit/report.py` from A3/A4/A6 | n/a | rebuilt on demand | Derived, safe to regenerate; not a source of truth | n/a |
| A12 | **In-memory only (lost on exit)** | `harden` locals: `specs`, `results`, `constraints`, `stalls` (`system2.py:74-78`); `TestPlanner.failures/passes` (`planner.py:26-27`) | none | process end | The accepted candidate's per-case results become the next incumbent results (`:147-148`), a correct in-memory rollout cache that is lost on crash. Planner beliefs are deliberately dropped on acceptance (`:149`) | n/a |

**Reading of the gaps.** The system is reproducible by *replaying logs* (A3, A4, A6) but not by *hashing inputs*: nothing answers "have I already run exactly this?" except A1.

## 2. Phase by module table (b)

Rows P0-P10. Kinds: cache | experience memory | skill library | correction library | failure corpus | test-case corpus | demo store | posterior store. "Value" is `[inferred]` unless a number is cited. Reference costs [data/doc]: one Muse call about 20-25k tokens (`HANDOFF.md` §6), about $0.27-0.34 at the logged $13.5 per M tokens; one rollout about 30 s wall (`outcome.json` timing 30.6 s attributed, 24.3 s sim); 50 seeds about 18 min in ASPIRE's batch mode (`aspire-deep-read.md` §6).

### 2.1 What, key, and what exists

| P | Phase and module (file) | Inputs -> outputs | Stored now | Candidate (kind) | Proposed key / schema |
|---|---|---|---|---|---|
| P0 | **Demo ingestion**: `tools/hurobo_demospec.py`, `tools/libero_demospec.py`, `types.DemoSpec` | clip `.npz` / LIBERO `.hdf5` + `measurements.yaml` -> DemoSpec JSON (+ `summary`) | A10 | **cache** of extraction (clip bytes + marker size + extractor version -> DemoSpec); **demo store** (DemoSpec with provenance, quality, and the cases/corrections it later explained) | `demo_key = sha256(input file bytes, marker_length_m, setup yaml, tool git sha)`; add `DemoSpec.content_sha`, `extractor`, `params` |
| P1 | **Policy synthesis**: `generator.build_messages/repair_message/extract_code`, `llm.ChatClient`, `demo_vs_nodemo.run_sample` | task, DemoSpec summary, scene context, constraints -> program text | A1, A2, A4, A5 | **cache** (exists); **experience memory** (accepted programs by task/scene features); **correction library** (retrieved rules + repair exemplars into the `constraints=` slot, `generator.py:41,56-58`); prompt-prefix ordering for provider caching | LLM: see §4.1. Memory: `PolicyRecord{policy_id=sha(code), task_text, demo_sha, scene_features, accepted_in_run, gate_row, help_count, epoch}` |
| P2 | **Plan gate and nominal replay**: not built (`discussion.md` §10.4 proposes `orchestrator/plan_gate.py`); nominal check in `harden` (`system2.py:89-94`) | program text -> AST verdict; nominal seeds 51-53 pass/fail | none | **cache** of AST verdicts (pure function of code bytes + allow-list version); **rollout cache** for nominal cases | `plan_key = sha(code, allowlist_version, demospec_ranges_sha)`; nominal rollouts use `rollout_key` (§4.2) |
| P3 | **System 2 test planning**: `adversary/planner.py`, `perturbations.py`, `scene_levels.py`, `collision_world.py` | category beliefs, bounds, seed -> `Perturbation` -> launcher spec | in memory only (A12); `system2.jsonl` tests | **test-case corpus** (every case ever run with outcome, for dedupe, replay and warm start); **failure corpus**; **posterior store** (Beta counts per category per policy lineage); **cache** of scene dumps/layout fingerprints | `case_key = sha(suite, task, seed, init_mode, canonical(scene spec))`; `posterior{lineage_id, category, fails, passes, epoch}` |
| P4 | **Rollout**: `rollout.CapHarness.run`, `tools/aspire_launch.py`, ASPIRE `cap-harness` | program, `CaseSpec`, harness config -> run dir, `EpisodeTrace` | A6, A7 | **cache** (rollout store, §4.2); layout fingerprint cache | `rollout_key` (§4.2) |
| P5 | **Diagnosis**: `diagnoser.diagnose/signature`, `rollout.feedback`, `evalkit/contacts.py`, `evalkit/phases.py` | feedback dict, contact log -> signature, rule | `system2.jsonl` `constraints_new` | **cache** of feedback/contacts summaries (pure functions of a run dir); **failure corpus** with structured signature features; hindsight "achieved outcome" record (`reuse-from-hurobo.md` §2.5) | `diag_key = sha(run manifest sha, diagnoser version)`; `FailureRecord{signature_features, run ids}` |
| P6 | **Constraint formation**: `diagnoser.RULES` (static text per category, `:13-45`), dedupe by signature (`system2.py:129`) | failures -> `Constraint` | in `system2.jsonl`, `HardenResult.constraints` | **correction library** (§3) | `correction_id = sha(signature_features, rule, repair_diff)` |
| P7 | **Regression gate**: `orchestrator/gate.py`, `system2.py:141-159` | incumbent/candidate per-case dicts -> `GateDecision` | `system2.jsonl` `gate`, `*_results` | **cache** (candidate per-case results reused); **correction credit** (help/hurt per constraint present in prompt); **test-case corpus** replay set | gate input rows are `(case_key -> RolloutRecord)`; gate refuses mixed harness fingerprints |
| P8 | **Stop / escalate**: `system2.py:160-170`, `stalls` dict, `confidently_robust` (`planner.py:57`) | stall counts, posterior -> stop/escalate | `escalation` in `system2.jsonl` | **experience memory** of escalations: signature -> which human demo resolved it; stall counters persisted across sessions | `EscalationRecord{signature_features, request, demo_sha, resolved_by_policy, tokens}` |
| P9 | **Deployment / run-time monitor / autonomous mode**: nothing built; `skills.md` §3, `aspire-assessment.md` C3, `Policy.kind` | live observations, saved policy + library -> actions, monitor flags, recovery | none | **skill library** retrieval at run time; **correction library** monitor-triggered recovery; **cache** of monitor answers by observation hash (C3); cell profile (calibration, measured sizes) | `monitor_key = sha(case/cell id, step, observation_hash, question)`; `CellProfile{marker_len, camera, object sizes}` |
| P10 | **Reporting**: `evalkit/report.py`, `system2_view.py`, `scene_view.py` | run dirs -> `report.html` | A11 | **cache** of derived report parts (not needed); **evidence export** with run ids (`discussion.md` §10.7) | export row cites `rollout_key` and `config_sha` |

### 2.2 When, validation, invalidation, value, effort

| P | Retrieval trigger | Write trigger | Validation on read | Invalidation / eviction | Value | Effort |
|---|---|---|---|---|---|---|
| P0 | Before P1 for a clip already extracted | After extraction | recompute `content_sha`; compare marker size and tool sha; re-extract when `quality` below floor | key change = new entry; never evict (small) | avoids stale 6.0 cm DemoSpecs being fed to Muse; enables escalation "quality" signal | S |
| P1 (LLM) | every `chat` | every uncached `chat` | parse OK, `choices[0].message.content` present, request echo hash equals key | Muse snapshot change (response `model` or API date) -> new namespace; keep for audit | 20-25k tokens per avoided call (about $0.3); makes n-sample claims honest | S |
| P1 (memory) | before writing a program: task text + DemoSpec + scene features (+ failure signature for repair) | when a policy is accepted by the gate and when it passes held-out only for *reporting*, never for tuning | `precondition` evaluates true on current scene; `harness_fingerprint` compatible; status >= `admitted` | decay per epoch, evict when `hurt_count > help_count` or unused N epochs; deprecate on failed re-verify | quality: the "skills are shared" claim; also fewer repair attempts | M |
| P2 | each candidate before any rollout | each candidate | code sha equals; allow-list version equal | allow-list/DemoSpec change | removes wasted rollouts on invalid code (cheap; `discussion.md` §10.4) | S |
| P3 | planner start of cycle; before proposing, dedupe against corpus | each case with its outcome | `case_key` match and harness fingerprint match | new incumbent resets *beliefs* (`planner.py:52`), not the corpus | skip duplicate proposals; warm start; "failures per rollout" metric needs the corpus | M |
| P4 | before every subprocess launch (`CapHarness.run`) | after each completed, non-error rollout | key match, `determinism_verified` for the fingerprint, run dir manifest sha intact, not `harness_error`/timeout | harness fingerprint change; canary mismatch quarantines the fingerprint | about 30 s per hit. Gate over `N` cases after `k` cycles costs `N` rollouts per candidate; a 4-cycle run reaches about 19 cases (3 nominal + 4 per cycle), about 50 candidate rollouts [code `system2.py:90,99,141`, inferred]. Re-runs, `--eval-only`, ablation arms sharing v0 and crash resume are free | M |
| P5 | at diagnosis | at diagnosis | run manifest sha equals; diagnoser version equal | diagnoser version | small; but gives the structured signature in P6 | S |
| P6 | at synthesis (P1) and at run time (P9) | in `harden` when the gate accepts a candidate whose prompt contained the constraint and that fixed the triggering case | §3.4 | §3.5 | the main novelty argument made persistent; enables the memory on/off ablation (N20, C11) | M |
| P7 | before each gate comparison | after each gate | all compared results share one harness fingerprint; a cache miss means rerun, never "missing = fail" (`gate.py:25`) | n/a | correctness | S |
| P8 | at stall detection | on resolution | the targeted demo's DemoSpec exists and parses | evict on a new signature schema version | closes "ask a human once, never twice" | M |
| P9 | on a monitor trigger | after a verified field recovery is replayed in sim | precondition + envelope check, then sim replay of evidence cases (SkillForge) | decay; failed re-verify -> deprecated | operations story: robot recovers from known failures with no model call | L |
| P10 | n/a | at export | n/a | n/a | traceability of README numbers (AGENTS.md rule) | S |

## 3. The correction behavior library (design)

### 3.1 What a correction is in ANTS terms

A **correction** is a persisted, gate-verified *behavioral repair* for one failure signature. It is the join of: the `Constraint` that names the rule, the **repair diff** between the failing incumbent and the accepted candidate, the **failure signature**, the **perturbation case** that exposed it, the **evidence run ids** (failing and passing), the **gate verdict**, and an **absorption status** (kept as a prompt rule, folded into a `Skill`, or turned into a runnable monitor/recovery). A constraint without an accepted repair is only a hypothesis; a correction exists only after the gate accepted a candidate that fixed the case with the constraint in its prompt.

All inputs already exist in `harden` at `system2.py:126-159` [code]: `p`, `res.feedback`, `sig`, `c`, `candidate`, `gate`, `cand_results`, `res.run_dir`. The diff is `runlog.unified_diff(old, new, ...)` (`runlog.py:19`). The WHY text exists when `--explain` is on (`generator.repair_message(explain=True)`, `generator.py:62-75`).

### 3.2 Relation to the existing dataclasses

| Existing | Covers | Missing for a correction |
|---|---|---|
| `Constraint` (`types.py:86-95`: `constraint_id, failure_signature, when_to_apply, rule, check_code, evidence`) | rule text, scope text, optional check | structured signature features (the string `size:move_to_pose:timeout` collapses different root causes: the exp03 wine-rack stall and a plain plate stall share one signature); trigger case; repair diff; gate verdict; status; usage counters; schema/version; typed evidence (it is `list[str]` of prose, `diagnoser.py:60-70`); `check_code` has no execution contract; `constraint_id` is `c%03d` per run (`diagnoser.py:57`), so ids collide across runs |
| `Skill` (`:146-164`: `skill_id, name, signature, success_predicate, precondition, code, envelope, evidence, constraints, version, parent_id, status, help_count, last_used`) | the absorbed, reusable form; `constraints` links ids; `envelope`; `status` | `kind` (skill vs correction), retrieval text/embedding ref, `verifier_report`, `reverify_after`, `source_policy_id`, harness fingerprint, hurt counter; `last_used` is a wall-clock string (non-reproducible decay: use an epoch counter) |
| `Policy` (`:65-83`: `constraints_used, skills_used, model, prompt_hash, tokens`) | which constraints were in the prompt (needed for credit) | `code_sha`, `llm_cache_keys` of the generating calls, `demo_sha`, `memory_sha` (hash of the memory snapshot consulted), `harness_fingerprint`; `prompt_hash` is never filled |
| `CaseSpec` / `Perturbation` (`:98-116`) | the trigger case | `case_key`, `scene` (harness-level scene spec), `init_mode`, `max_steps` |
| `GateDecision` (`orchestrator/gate.py:13`, not in contracts) | verdict | not importable by System 1 or the store (contracts only); needs a contract twin |

### 3.3 Proposed dataclass diff (proposal only, not applied)

All new fields have defaults so `from_json` stays backward compatible (it ignores unknown keys, `types.py:186`). `types.py` is the shared contract file: per `docs/adversary/spec.md` build step 1 it needs agreement with the System 2 owner before editing.

```diff
--- a/src/ants/contracts/types.py
+++ b/src/ants/contracts/types.py
@@
 SkillStatus = Literal["candidate", "verified", "deprecated"]
+CorrectionStatus = Literal["proposed", "admitted", "verified", "absorbed", "deprecated"]
+RepairKind = Literal["prompt_rule", "code_diff", "param_change", "monitor_check", "recovery_branch"]
@@ class Policy:
     model: str = ""
     prompt_hash: str = ""
     tokens: int = 0
+    code_sha: str = ""                                  # sha256 of the program bytes (what the harness hashes)
+    llm_cache_keys: list[str] = field(default_factory=list)   # ChatClient keys of the generating calls
+    demo_sha: str = ""                                  # DemoSpec content hash
+    memory_sha: str = ""                                # hash of the memory snapshot retrieved from
+    harness_fingerprint: str = ""                       # see rollout key, memory-audit §4.2
@@ class Constraint:
     check_code: str | None = None
     evidence: list[str] = field(default_factory=list)
+    signature_features: dict[str, str] = field(default_factory=dict)
+        # category, phase (evalkit.phases stage label), tool, status, blocker_part, blocker_object, blocker_region
+    signature_version: int = 1
+    scope: dict[str, str] = field(default_factory=dict)  # task_text, suite, object roles, embodiment
+    # constraint_id must become globally unique: sha256(signature_features + rule)[:12]
+
+@dataclass
+class Evidence:
+    kind: Literal["failing_run", "passing_run", "gate_row", "llm_call", "demo", "contact_log"]
+    ref: str            # run dir relative to data/, "system2.jsonl:<cycle>", llm cache key, ...
+    sha256: str = ""    # manifest sha for run dirs
+    split: Literal["acceptance", "held_out"] = "acceptance"   # writers must reject held_out
+
+@dataclass
+class GateVerdict:      # contract twin of orchestrator.gate.GateDecision
+    accepted: bool
+    reason: str
+    fixed_cases: list[str] = field(default_factory=list)
+    regressions: list[str] = field(default_factory=list)
+    cases: int = 0
+    incumbent_passes: int = 0
+    candidate_passes: int = 0
+
+@dataclass
+class Correction:
+    """A gate-verified repair for one failure signature (memory-audit-codebase.md section 3)."""
+    correction_id: str
+    constraint: Constraint
+    kind: RepairKind
+    trigger_case: CaseSpec                  # acceptance split only
+    trigger_case_key: str                   # rollout key of the failing rollout
+    parent_policy_id: str                   # failing incumbent (code_sha based)
+    repaired_policy_id: str                 # accepted candidate
+    repair_diff: str = ""                   # unified diff parent -> repaired
+    why: str = ""                           # model rationale (generator --explain), may be empty
+    recovery_code: str | None = None        # sandbox-allowlisted snippet, run-time use only
+    envelope_tested: dict[str, list[float]] = field(default_factory=dict)  # param -> [min,max] seen passing
+    evidence: list[Evidence] = field(default_factory=list)
+    gate: GateVerdict | None = None
+    status: CorrectionStatus = "proposed"
+    absorbed_into: str | None = None        # Skill.skill_id (+ version in Skill.version)
+    help_count: int = 0                     # gate accepted a candidate that had it in the prompt AND fixed a case
+    hurt_count: int = 0                     # a candidate with it regressed, or a re-verify failed
+    retrieved_count: int = 0
+    created_epoch: int = 0                  # logical clock (orchestrator cycle counter), not wall time
+    last_helped_epoch: int | None = None
+    harness_fingerprint: str = ""
+    model: str = ""
+    schema_version: int = 1
@@ class Skill:
     help_count: int = 0
     last_used: str | None = None
+    hurt_count: int = 0
+    last_helped_epoch: int | None = None
+    source_policy_id: str | None = None
+    absorbs: list[str] = field(default_factory=list)   # correction_ids folded into `code`
+    verifier_report: str | None = None                 # ASPIRE-style: fresh agent reproduced the fix from text, >=4/5 seeds
+    harness_fingerprint: str = ""
+    reverify_after_epoch: int | None = None
```

### 3.4 Lifecycle and admission

`proposed` (diagnoser output, in prompt) -> `admitted` (gate accepted a candidate whose prompt held this constraint and that fixed `trigger_case`; written by `harden`) -> `verified` (replayed on its evidence cases plus a fresh acceptance seed set; for the hackathon this is the ASPIRE verifier idea reduced to a replay: `aspire-deep-read.md:159` needs at least 4/5 seeds in 2 attempts) -> `absorbed` (the repair became part of a `Skill`, `absorbed_into` set) -> `deprecated`.

Credit assignment is the weak point [inferred]: `harden` passes all constraints at once (`system2.py:133`), so "this constraint helped" cannot be separated from the others. Cheap options in order: (i) credit all constraints in the accepted prompt whose `trigger_case` flipped from fail to pass (the gate already lists `improvements`, `gate.py:31`); (ii) add one leave-one-out regeneration only for ablation runs; (iii) ASPIRE's per-use grade `useful|misleading|wrong|not-applicable` (`campaign.py:177`) as the model's own report, never as the success authority.

Decay uses a logical clock: `pheromone = helped_weight * rho^(epoch - last_helped_epoch)`, with the epoch the orchestrator cycle counter, so a replay of a logged run reproduces the ranking (N13 in `docs/dev/paper-vs-docs.md`).

### 3.5 Retrieval

**At synthesis time (offline hardening and first-program writing).**
- Query: `task_text`, `DemoSpec` object roles, scene features (from the program-independent `_scene_reset.json` fingerprint, A8), and for a repair the live `signature_features` of the current failure.
- Filter (hard): `status >= admitted`; `scope` matches; `precondition`/`envelope` check against the current case; `harness_fingerprint` compatible; **`evidence.split == "acceptance"`**; not `deprecated`.
- Score: `sim(query, signature_features, task) * (1 + help_count - hurt_count) * rho^(epoch - last_helped_epoch)`; keep top `K` (default 3-5) to bound prompt growth (the dynamic-skills survey reports flat retrieval degrading above about 64-128 entries [doc, `module-radar.md` block 9]).
- Render into the existing slot `build_messages(constraints=...)` (`generator.py:55-58`): the `rule` lines; for code-level repairs add the short `repair_diff` hunk and `why` as an exemplar. Put them **last** in the user message so the 5-6k-token stable prefix stays identical (the provider already reports `cached_tokens`, e.g. 5,492 of 7,511 in `smoke-2026-10-31.md` attempt 1) [doc].
- Record on the `Policy`: `constraints_used`, `memory_sha`, and bump `retrieved_count`. Credit is applied after the gate decision.

**At run time (deployment, monitor-triggered recovery).**
- ANTS policies are programs with no model in the loop (`discussion.md` §2, Q3), so run-time recovery must be deterministic code. Two shapes: (a) *absorbed* corrections are already inside the saved program (the common, cheap case: nothing to retrieve at run time); (b) *situational* corrections stay as `check_code` (monitor predicate over typed call results: tool, `status`, `final_errors`, gripper width) plus `recovery_code` (allow-listed snippet), executed by a `MonitoredProgramRunner` wrapper (`aspire-assessment.md` C3).
- Trigger: a typed call failure or a program `result` flag matches `signature_features` of an `admitted`/`verified` correction whose `precondition` holds now; cap attempts at `K` (C3 suggests 3) and log each as an event with the correction id.
- Miss: no correction matches or the cap is hit -> stop safely and either escalate or enter autonomous mode with an operator-approved budget (`skills.md` §3).
- Write-back: a field recovery creates a `proposed` correction only. It becomes `admitted` after the saved case is **replayed in simulation** and the gate (or the Skill-V no-regression rule) accepts it. A deployment self-report must never raise `help_count`.
- Programs already declare an envelope: `params` and `attack_ranges` dict literals (uncommitted `generator.py:20`) can be parsed with `ast.literal_eval` to fill `Skill.envelope` and `Correction.envelope_tested` at no model cost [code, inferred].

### 3.6 Worked example from the logs

exp03 clip 233859 attempt 2 [doc `proposal-collision-context.md` §2]: `move_to_pose` timeout, hand blocked on the wine rack top (steps 322-823), `evalkit/contacts.analyse` yields `blocking: [{part:"hand", object:"wine rack", ...}]`. Today's `signature()` gives `<category>:move_to_pose:timeout`. Proposed `signature_features = {category:"clutter-ish/scene", phase:"closed at the bowl", tool:"move_to_pose", status:"timeout", blocker_part:"hand", blocker_object:"wine rack"}` and a rule template (deterministic, no VLM, as `proposal-collision-context.md` §175 suggests): "approach from a side where the nearest non-target object is farther than 6 cm from the finger". The record stores the failing run dir, the program diff of the attempt that cleared it, and the gate row.

## 4. Cache-key audit

### 4.1 `src/ants/synthesizer/llm.py`

| Question | Finding [code] | Fix |
|---|---|---|
| Is `(model, messages, temperature)` enough? | Enough to **replay** (reproducibility), not enough for **sampling**. Hosted models are non-deterministic even at temperature 0 (`aspire-assessment.md:118`), so replay is the only reproducibility mechanism, and it works only because the first reply is frozen | Add `sample_index: int = 0` to the key and to `chat()`. "n samples at one temperature" then means indices 0..n-1. Without it, `demo_vs_nodemo --temperatures` is the only way to get diversity (`demo_vs_nodemo.py:193,267-268`) and experiments share `a0` (finding 2) |
| Parameters that change the response but are absent | `base_url` (`:50`), `max_tokens`, `top_p`, reasoning-effort or any future param, `n`, the Muse alias target. `_post` sends only `model, messages, temperature` (`:105-107`) so today nothing else varies, but a future param would silently reuse old entries | Key a canonical `request` dict (everything sent) plus `key_schema: 2` plus `endpoint host` |
| Model snapshot | `model` is the alias `muse-wonder-1.0`; the response `model` field is stored in the entry but not compared or logged | Log response `model` and `created` in the ledger; add an optional `--cache-epoch` string folded into the key to cut a namespace when Meta re-points the alias |
| Request stored? | **No**: the entry holds only the response (`:79-80`), so the key cannot be audited or recomputed, and a hash collision (24 hex = 96 bits, negligible) would go unnoticed | Store `{"key_schema", "request", "response", "created", "client_version"}` and verify `sha(request) == filename` on read |
| Atomicity | `path.write_text` is not atomic; a crash leaves a truncated file and every later run raises on `json.loads` (`:73`) | write to `*.tmp` then `os.replace`; treat unreadable entries as a miss and quarantine them |
| Budget semantics | `spent()` is computed once from the ledger (`:57-65`); parallel processes race; cache hits do not count (correct) | re-read the ledger tail before each uncached call, or take a file lock |
| Prompt provenance | `Policy.prompt_hash` never set; the system prompt changed in the working tree (`generator.py:20`) so every pre-change entry will miss (correct invalidation, but invisible) | write `sha(system message)` and `sha(user message)` to the ledger row; log `prompt_version` |
| Secrets | API key is read from env and used only in the header (`:112`), never written to cache, ledger or run dir [code]; `api_response_attempt*.json` stores the raw response which holds no key | keep; add a test that cache files contain no `Bearer` |
| Leakage across splits | Prompts are built from DemoSpec, scene text, constraints, feedback of **acceptance** seeds only today. A cache hit cannot leak because the prompt is the key | forbid held-out feedback in any prompt (assert on `CaseSpec.split` in the code that builds `repair_message`) |

### 4.2 Rollout cache key (proposed)

Rollouts are the dominant time cost and are deterministic per fingerprint [data]: byte-identical `episode/steps.jsonl` in 63 of 65 repeat groups (136 runs); 21 of 21 stock-scene groups identical; the 2 mismatches are scaled-scene runs 1 h 46 min apart straddling the launcher tolerance fix (exp01 doc, "Decision (2026-10-31)") [inferred cause]. Same machine and GPU throughout, so cross-machine equality is **unverified**.

```
rollout_key = sha256(canonical_json({
  "schema": 1,
  "policy":   sha256(program bytes),                       # == ASPIRE provenance.json sha256
  "case": {"benchmark": "libero-pro", "suite", "task_id", "seed",
           "init_mode": "seeded",                          # 'saved' wraps seeds at 50 -> also store layout_id
           "layout_fp": sha(_scene_reset.json bodies)},    # catches equal layouts under different seeds
  "scene":    canonical(CapHarness.scene | to_launcher_spec(case.perturbations)),
                                                           # incl. actuation seed (perturbations.py:99), scale, ablate, contacts flag
  "run":      {"max_steps", "camera_width", "camera_height"},
  "harness":  {"aspire_git": commit + sha(git diff) if dirty,   # provenance 'dirty': true today
               "dependency_lock_sha256",                         # in provenance.json
               "launcher_sha256": sha(tools/aspire_launch.py),   # NOT in ASPIRE; proven necessary
               "providers": run.json providers (sam3, pyroki, curobo...),
               "sam3_ckpt_sha", "libero_assets_sha", "mujoco_version"},
  "ants":     {"perturbations_version": sha(adversary/perturbations.py FULL + to_launcher_spec)}
}))
```

Stored value `RolloutRecord`: `key`, `task_success`, `program_ok`, `termination_reason`, `steps_executed`, `calls` (the `CallRecord`s), the `feedback()` dict (so the diagnoser needs no run dir), `steps_sha256`, `run_dir` + `manifest_sha256`, `wall_s`, `fingerprint`, `split`, `created`. Not stored: videos (stay in the run dir).

**When the gate may reuse a rollout.**
1. `policy.deterministic is True` (`types.py:76`); `agent` or unmonitored LLM policies never. A `monitored_program` only if monitor answers are cached by observation hash (C3).
2. Full key match, and **both sides of every gate comparison share one `harness_fingerprint`**. Mixed fingerprints force a rerun of the incumbent side.
3. The record is a *completed* episode: not `harness_error`, subprocess timeout, OOM or EGL "invalid depth" contention (`HANDOFF.md` §6: contended EGL gives fake failures). Failures that look infrastructural are retried once and never cached.
4. A **determinism canary** has passed for the fingerprint: re-run one cached case per cycle (sentinel) and compare `steps_sha256`; a mismatch quarantines the fingerprint, invalidates its records and is logged as `cache_canary_fail`.
5. A cache **miss is a rerun, never "missing = fail"**: `gate.py:25` treats an absent candidate result as failure, which would turn a cold cache into rejections.
6. Final reporting runs (the accepted policy on acceptance and held-out) use `--no-cache` once, so the headline number is a fresh rollout; mismatches versus cache are reported.

Fixes needed regardless of caching: give every rollout a fresh `output_root` (or parse the `run_id` printed by the harness) and fail loudly on a nonzero return code or `TimeoutExpired` (`rollout.py:76-88`).

## 5. Must NOT be cached or remembered (c)

| Item | Why |
|---|---|
| **Held-out rollouts or held-out-derived text in any decision path** (planner, diagnoser, generator prompt, memory writer, gate set) | AGENTS.md rule: held-out is never used for tuning. They may be *stored* in a separate namespace for reporting; decision modules must not be able to import that reader |
| **Success predicates / the benchmark verdict from a policy report** | success comes only from `outcome.json` `task_success`; `Policy` `result` dicts are self-reports (FailBench-type judges are near chance, `proposal-collision-context.md` §1). Never put the predicate into a prompt or memory (ASPIRE forbids programs from reading it) |
| **Non-deterministic rollouts** (`deterministic=False`, per-step agents, live hardware, un-canaried fingerprints) | breaks gate monotonicity; use k seeds and Wilson bounds instead (`aspire-assessment.md:129`) |
| **Failures caused by infrastructure** (harness error, GPU contention, timeouts of the subprocess) | they are not properties of the policy |
| **Seed-specific numbers inside `rule` text** (absolute positions, measured offsets from one seed) | overfits the acceptance seeds and can leak the layout; evidence strings may hold them, rules may not (lint) |
| **Unverified field self-reports** as help counts | only sim-replayed, gate-accepted outcomes may change retrieval weights |
| **API keys, `.env`, bearer headers, raw hardware identifiers** | `ChatClient` already avoids it; keep under test |
| **Whole-trajectory video, 8.7 GB run dirs** in the key store | keep content-addressed *references* (manifest sha), not blobs; AGENTS.md forbids committing datasets |
| **Planner posteriors as a decision aid while the claim "adaptive beats uniform" is being measured** | warm starts confound that ablation; keep as a flagged option (§6, H5) |
| **LLM replies as a semantic cache** (similar prompt -> old reply) | changes decisions; not a cache. Only exact-key hits |
| **Perception outputs of SAM3/depth across different program prefixes** | valid only for the same simulator state; a prefix cache needs state snapshots (research tier) |

## 6. Leakage and integrity risks, and what to log (4)

| Risk | Mechanism | Guard |
|---|---|---|
| Acceptance/held-out contamination through equal layouts | `saved` mode wraps seeds (`libero-pro.md:73-74`); seeded mode does not guarantee distinct layouts (`:77-79`); a seed-keyed cache would equate them | include `layout_fp`; at planning time assert no acceptance `layout_fp` equals a held-out one; `RolloutStore(namespace=split)`; held-out reader only in `evalkit` |
| Memory writes from held-out failures | A correction/failure corpus fed by a held-out sweep turns the test set into tuning data | `Evidence.split` and `Correction.trigger_case.split` must be `acceptance`; the writer raises otherwise; unit test mirrors `system2.py:82` |
| Memory carries seed-specific facts | rule text with measured offsets; a retrieved policy with hard-coded positions | rule lint; `RULES` in the prompt already forbid absolute positions (`generator.py:16`) |
| Gate monotonicity broken by cache | stale incumbent results vs fresh candidate results; missing=fail; non-deterministic flips; warm-started case sets containing unwinnable cases (feasibility check is not built, `discussion.md` §10.4) | single fingerprint per comparison; rerun on miss; canary; feasibility filter before a case enters the persistent test-case corpus |
| Skill drift | a `Skill` modified after policies used it changes their behaviour (`skills.md` §2) | store `memory_sha` and skill `version` on each Policy; re-verify evidence cases on version bump; rerun policies whose `memory_sha` is older (ASPIRE records `skill_library_sha` per task: `campaign.py:115-136`, required field `:407-408`) |
| Reproducibility | decay on wall clock; ids that collide across runs (`c000`); `config.json` overwritten (`demo_vs_nodemo.py:256`); resume ignores config (`:272-275`) | logical epoch clock; content-hash ids; write `config.<n>.json` per start and a `config_sha` stored in each `record.json`; resume only if `config_sha` matches |
| Stale evidence | DemoSpec at the wrong marker size; scaled-scene results before the launcher fix | `demo_sha` and `launcher_sha256` in keys |
| Silent accounting errors | ledger schema drift; per-process budget | version field; re-read before spend |

**Log (append-only, one JSONL per concern, all carry `run_id`, `epoch`, `config_sha`, `harness_fingerprint`):** every cache lookup (`kind`, `key`, `hit|miss|bypass|quarantine`, `reason`); every canary result; every retrieval (query features, candidates with scores, chosen ids, `memory_sha`); every memory write (`correction_id`, `status` transition, evidence refs, `split`); every gate decision with the per-case rows and the fingerprint on both sides; every escalation request and its resolution; the held-out reads (who asked, which report). These extend `system2.jsonl` rather than replace it, which keeps `evalkit/system2_view.py` working.

## 7. Build order (5)

Context: today is 2026-11-01; deadline 2026-11-04. `harden` exists with callbacks but no real `run_case`/`generate` yet (A12, finding 10). The 3-day tier must therefore *wrap* the loop as it goes live, in small additive modules (`evalkit` is the right home for stores: `discussion.md` §10.5 says `evalkit/` holds the call cache and metrics with no system imports).

### 7.1 Hackathon tier (days 1-3)

| Order | Item | What | Effort | Why now |
|---|---|---|---|---|
| H1 | Harden `ChatClient` | `sample_index`, store request, atomic write, miss-on-corrupt, prompt hashes + response model in the ledger, test for no secrets | S (3-4 h) | protects every later token; fixes shared-`a0` ambiguity before new experiments are compared |
| H2 | `RolloutStore` + fixed `CapHarness.run` | key per §4.2 minus the heavy parts (policy sha, case, scene, run params, aspire git+dirty diff sha, launcher sha, dependency lock sha); fresh `output_root` per call; returncode/timeout handling; one-line canary; wrap `run_case` in the real `harden` | M (6-8 h) | ~30 s per hit; gate cost grows with every cycle; makes the ablation arms (uniform vs Thompson, gate on/off) affordable and crash-safe |
| H3 | `CorrectionRecord` JSONL (v0) | write at `system2.py:141-159` when a candidate is accepted: constraint, trigger case, diff, run ids, gate verdict; `status` admitted; `render_constraints()` into the `constraints=` slot; retrieval = exact `task_text` + `signature_features` match (Q9 default says start with exact task-text match, `discussion.md` Q9) | S-M (4-6 h) | gives the memory on/off ablation (N20) something to retrieve, resolving C11 cheaply: seed memory from run A, evaluate on a second suite/task or on fresh acceptance seeds |
| H4 | Structured signature features | extend `signature()` with phase stage (`evalkit/phases.py`) and blocker from `evalkit/contacts.py` | S (2-3 h) | stops different root causes merging into one constraint |
| H5 | Persist the test-case/failure corpus | JSONL of `(case_key, CaseSpec, outcome)`; gate set seeded from it for the same policy lineage; acceptance only | S (2 h) | re-gating after restart without rerunning discovery |
| H6 | DemoSpec hash + params | `content_sha`, marker size, tool sha; fill `quality` | S (1-2 h) | prevents stale-demo confusion; feeds the "quality triggers escalation" rule |
| H7 | Log fields | `config_sha`, fingerprint, `memory_sha` in events; per-start `config.<n>.json` | S (1-2 h) | traceable README numbers |

Do **not** build in this tier: embeddings/DINOv3 (large dependency, needs approval), skill extraction and verifier admission, planner warm start, run-time monitor, prefix/state caching.

### 7.2 Research tier

| Item | Effort | Note |
|---|---|---|
| Skill library: extract functions from accepted programs, ASPIRE-style Trigger/Code/Why/Limits entries with runnable `precondition`, verifier admission (fresh generation from text only, >=4/5 seeds) | L | `skills.md` §1-2; uses `params`/`attack_ranges` as envelope |
| Embedding retrieval (scene + task) with help-count and decay, evaluation of cross-task transfer | M-L | needs a DINOv3/SAM 3.1 feature dependency (ask first); flat retrieval degrades at about 64-128 entries |
| Leave-one-out credit assignment for constraints | M | regenerate without one constraint; costs tokens |
| Planner posterior store with discounted warm start across lineages | S-M | must be measured against the cold start before use |
| `MonitoredProgramRunner`, monitor cache by observation hash, `check_code`/`recovery_code` execution contract, caps | L | needs a safe envelope on hardware (`skills.md` §3) |
| Autonomous mode write-back: sim-replay then admission | L | budgets undecided (todo #4) |
| Escalation memory and human-demo store (including in-cell teleop, todo #11) | M | DemoSpec with source mode and its resolution links |
| Trajectory-prefix / perception caching across candidates sharing a program prefix | L | needs sim state snapshots; high risk, high payoff for gate cost |
| Cross-machine determinism study and a fingerprint registry | M | currently only same machine |
| Staleness detection with a conformal threshold at retrieval (`reuse-from-agentic-robot.md:67`) | M-L | ready-made experiment plan |
| Memory sharing across embodiments (tags, retargeting) | L | |

## 8. Open questions for the user (6)

1. **Hackathon memory content (C11).** Should the demo show memory with something to retrieve? Default: seed corrections from a first hardening run on T0 (bowl on plate) and retrieve them in a second run on a different seed set or task; otherwise mark the memory ablation "future".
2. **Contracts.** May `types.py` take the `Correction`/`Evidence`/`GateVerdict` additions (shared with the System 2 owner)? Default: yes, all fields defaulted.
3. **Determinism.** May I spend about 10 rollouts on a canary study (same program/seed/scene repeated, plus one cross-GPU-load run) before the gate relies on the cache? The 63/65 result is same-machine only.
4. **Where stores live.** `data/` is git-ignored, so memory cannot be shared by commit. Default: runtime stores in `data/`, and a small curated `memory/corrections.jsonl` committed for the demo. OK?
5. **Credit assignment.** Accept "all constraints in the accepted prompt that fixed the trigger case get credit" for the hackathon, with leave-one-out later?
6. **Rule source.** Keep the deterministic `RULES` templates (`diagnoser.py:13`) as the rule text for now, or let Muse Spark write rules? It changes dedupe, cost and the key.
7. **Provider prefix caching.** Is cached-token pricing known (todo #8)? It decides whether prompt ordering (memory last) matters for the budget.
8. **Embedding dependency.** Approve DINOv3 or SAM 3.1 features for retrieval in the research tier?
9. **Re-run of exp02 comparisons.** Because of the shared `a0` entries (finding 2), do you want exp01/exp02 claims re-stated as "same first program, different repairs" until independent samples (`sample_index`) are drawn?
10. **Teleop/VR demos (todo #11).** Affects the demo store schema (source mode, hardware).

## 9. Could not verify

- Cross-machine or cross-GPU determinism; whether the 2 mismatching scaled runs are fully explained by the launcher fix (the launcher source history was not diffed).
- Whether Muse bills cached prompt tokens at a discount; whether the API model alias is stable (no snapshot id in responses beyond `model`).
- Whether `EGL` contention failures can be recognised from `outcome.json` alone (the error text was not inspected).
- Whether `harden` works end to end with real rollouts (never run), so per-cycle rollout counts in §2.2 are derived from code, not from a run.
- Behaviour of `sam3`/`pyroki`/`curobo` providers regarding internal caches or nondeterminism (ASPIRE `docs/run-artifacts.md` only recommends measuring batch equivalence, `check_batch_equivalence.py`, which was not run).
- The hurobo and agentic-robot caches were only skimmed (`agentic-robot/sim/mp3/harness.py:91` has a cached VLM call keyed by backend/arm/video); not audited.
