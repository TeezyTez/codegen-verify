# Refactor guide implementation map

This document maps the supplied *Spec-Guided Coding Agent Project Refactor Guide* to the current
vertical slice. The implementation deliberately keeps one orchestration interface and a small
number of deep modules instead of copying the guide's illustrative directory tree.

## Implemented

| Guide capability | Current implementation |
|---|---|
| Requirement analysis | `RequirementAnalyzer` produces stable `REQ-*` records, ambiguity, edge cases, and public verification cases. |
| Shared structured specification | `SpecArtifact.structured` holds requirements and atomic `SPEC-PRE/POST/INV-*` clauses beside the Dafny contract. |
| Three spec levels | Semantic clauses and cases are stored explicitly; the formal level is Dafny. Spec-blind executable probes remain inside the independent Critic. |
| Spec validation/refinement | Resolve, cross-level mapping, adequacy, executable probes, mutation, independent Critic, bounded regeneration. |
| Spec-guided planning | `SpecGuidedPlanner` maps every clause to algorithm/state/invariant/verification strategy. |
| Spec-guided generation | `CandidateSynthesizer` receives task, structured spec, frozen formal spec, and program plan. |
| Unified verification evidence | `VerificationEvidence` records stage, structured diagnostics, violated clause IDs, policy failures, and formal results. |
| Failure attribution | `FailureDiagnoser` uses the guide's six categories and localizes code around verifier diagnostics. |
| Targeted repair | Repair prompts contain violated clauses, related requirements, plan, localized code, and preserve all unrelated clauses. |
| Spec drift protection | Versioned fingerprints and drift reports record removed/added/changed clauses, affected requirements, reason, and evidence. |
| Traceability graph | Requirement, clause, test, plan, strategy, code, VC, failure, and patch nodes are linked and serialized. |
| Replay artifacts | Each task stores requirements, all spec versions, plan, all candidate versions, final verification, diagnoses, graph, metrics, and result. |
| Research observability | Manifest schema 3 records role-specific models and ablations; LLM usage is aggregated per role and per task. |

## Safety decisions

- A normal Dafny failure cannot authorize a spec change. It is evidence about code/proof, not user
  intent. A spec revision requires independent development evidence and then reruns every spec gate.
- Official HumanEval tests remain outside the Agent loop and never authorize repair.
- Raw Dafny spec output remains supported for historical replay, but new structured model output
  must explicitly map requirements to clauses.
- Reference/helper collapse remains disabled by default.

## Deliberately deferred

- A language-independent unit/property/metamorphic test harness for generated candidate code.
- Repository-level symbol/range localization; the current target is one generated Dafny program.
- Additional formal backends such as Verus or Lean.
- A dedicated direct-generation baseline runner and automatic equal-budget scheduler. Current runs
  record role-level calls, tokens, and latency so these experiments can be added without changing
  the shared IR.

These are separate research increments, not prerequisites for the current end-to-end architecture.
