# Obligation Agent Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an experimentally isolated obligation/evidence-guided generation protocol and share the existing trusted execution loop.

**Architecture:** A common generation engine owns execution, budgets and acceptance. Protocol adapters preserve legacy prompts and implement four new conditions; a pure state reducer owns candidate-versioned evidence and deterministic target selection.

**Tech Stack:** Python 3.12, pytest, existing Dafny 4.11 executable and model adapter; no new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-06-obligation-agent-design.md`

## Global Constraints

- Protocol `fixed_spec_obligation_v1`; retain historical protocols and result directories.
- Four conditions use the same frozen formal specification, body syntax, system prompt and budgets.
- Never infer proof from missing errors or accept model assertions as verifier evidence.
- No paid calls; no new dependencies; preserve unrelated working changes.

## Review Focus

- Changed candidate or verifier identity makes old proof stale: state tests.
- Method passes but individual diagnostics disappear: state tests prevent inferred VC proofs.
- Independent sampling accidentally gets old candidate/state: prompt and loop tests.
- Final verification fails or fixture pretends to verify: shared-engine tests.
- Summary mixes old protocol, duplicated jobs or altered state: artifact audit tests.

## Tasks

1. [x] State and policy: add `generation/obligations/{state,policy,config}.py` and tests. Interface `EvidenceState(task, toolchain).observe(source,evidence,label)`, `snapshot()`, `select_target()`; protocol exposes messages/begin_candidate/observe/reject/snapshot. Verify RED then GREEN for identity, state, ordering, disclosure and independent sampling.
2. [x] Shared engine: move trusted loop into `generation/engine.py`; retain `generation/representation/runner.py` compatibility entry and add representation policy. New obligation runner uses the same engine. Verify previous representation tests and new runner acceptance/budget/feedback-history tests.
3. [x] CLI and summaries: new run/matrix/preflight/validate/summarize entry, explicit paid gate, strict protocol-aware summaries and mock defaults. Reuse task admission without mislabeling the protocol. Verify artifact corruption, missing jobs and offline CLI paths.
4. [x] Documentation and verification: update root README, new protocol README/config examples. Run focused tests, complete existing suite, actual Dafny fixture smoke, and a fresh read-only review. Record concrete failures and limits.

## Execution record

- Authorized inline by the user's instruction to refactor according to the agreed experiment. Work in the current checkout; preserve untracked research notes. Leave changes uncommitted for inspection.
- Baseline test suite started before implementation. Local Python and Dafny are present in `.venv` and `.tools`.

- Initial test-only RED: six missing state-module failures; then eight missing policy/runner/config failures. Both groups passed after implementation.
- Baseline under UTF-8: 349 passed, 12 failed. Root causes: missing Windows profile variables in the restricted Dafny child environment, and two POSIX-only test doubles. Fixed the explicit environment allowlists and made the test doubles exercise either platform branch. File artifacts now use explicit UTF-8 on the new shared path.
- Shared-engine compatibility and real Dafny focused run: 150 passed. Full suite before review fixes: 380 passed, two subtests passed.
- A fresh read-only review found two P2 issues: mapped timeout diagnostics marked UNPROVED, and cross-run toolchain/task identities could be pooled. Both were reproduced with failing tests and fixed; 22 obligation tests pass.
- Reviewer exclusions accepted as outside this refactor: live provider behavior (no paid authorization), statistical efficacy and independent benchmark validity (no research trial), Windows descendant-process cleanup (existing platform limitation now documented).
- Real Dafny offline smoke: absolute and sequence_max, each across all four groups. Eight completed successful runs, each with two fixture calls and three full verification calls including final artifact verification. Admission independently checked reference success and mutant failure. All outcomes remain mock/reference-using diagnostics.

- Final verification after review fixes: `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q` — 383 passed, 2 subtests passed, exit 0 (115.23s). `git diff --check` passes. Logs: `logs/refactor-20261006/final-tests.log`. Both smoke matrices re-audited successfully by the final analyzer. No paid requests or new dependencies; six pre-existing research files remain untouched.
