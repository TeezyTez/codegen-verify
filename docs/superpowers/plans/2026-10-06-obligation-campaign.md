# Obligation Campaign Implementation Plan

> Use superpowers:executing-plans for inline implementation. The user requested staged experimental execution; preserve current uncommitted work and do not commit or launch an unbounded live matrix.

**Goal:** Make the next experimental batch concrete and auditable before scaling.
**Architecture:** Add a separate campaign planner and paired task-level analysis over already-audited runs. Keep model execution unchanged until the isolated Codex transport passes a probe.
**Tech Stack:** Python standard library and existing pytest/Dafny setup.
**Spec:** research/OBLIGATION_EXPERIMENT_ROADMAP_2026_10_06.md

## Constraints

- Four strategies; no reference/fixture results claimed as model efficacy.
- Read task/config identities, freeze them, shuffle condition order inside task/replicate blocks deterministically.
- No automatic model calls in planning or statistics. Existing historical runs remain untouched.
- Keep unknown money unknown. User selected existing Codex access; no new API credentials or alternative paid provider.

## Review Focus

- Duplicate task or job identities rejected.
- Plans are deterministic for the same seed and cannot overwrite an existing directory.
- Missing, incomplete or unbalanced conditions rejected before paired inference.
- Bootstrap resamples independent clusters, not individual repeated trials.
- Tiny or mock results are explicitly exploratory, never promoted to confirmation.

## Tasks

1. [x] RED tests: deterministic block schedule, all combinations exactly once, no duplicate tasks, unknown cost remains null, no overwrite; paired known deltas, repeated runs not independent, missing pair rejected.
2. [x] Implement `generation/obligations/campaign.py`: `plan(tasks, config, schedule_seed=20261006) -> dict`, `paired(summary, clusters=None, draws=10000, seed=20261006) -> dict`, CLI `plan` and `analyze`. Freeze file hashes/config/source hashes and output the offline schedule.
3. [x] Verify tests; generate 96-run development plan, analyze complete 32-run stage-0 fixture matrix, record transport probe failures separately.
4. [x] Fresh read-only review and regression; update status documents and next gate.

## Validation

Fresh read-only review identified two P2 issues: explicit empty cluster mappings silently defaulted to singleton clusters, and absent expected-job manifests allowed omitted blocks to appear complete. Both were reproduced with failing tests, fixed, and independently re-reviewed. Full regression: `393 passed, 2 subtests passed in 106.73s`; log: `logs/obligation-full-tests-20261006.log`.

Latest offline artifacts: `logs/obligation-development-plan-20261006-r2/campaign.json` and `logs/obligation-stage0-paired-20261006-r2/paired.json`. The original artifacts remain preserved. The next gate is a successful isolated model transport followed by the separately labeled 8-run exploratory batch.

## Deferred live-execution requirements

Public initial-message hashes must be frozen after choosing the actual isolated model adapter and toolchain, before any experimental generation. The offline schedule does not claim to freeze live prompts. The durable schedule executor and live transport remain unimplemented/unverified; this plan's completion is not completion of the model experiment.
