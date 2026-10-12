# Scientific claim–evidence audit

Audit date: 2026-10-12. Read-only review of claim_evidence.md, outline.md, manuscript.audit.md, evidence/evidence_audit.json, literature/citation_audit.json, and relevant policy/runner/analyzer code. No new experiments, external manuscript upload, or git operations. This is an AI-assisted scientific-critical-thinking review, not human sign-off or an exhaustive independent literature verification.

The draft appropriately limits the 416/1392 completed subset to descriptive results, retains four infrastructure failures, separates 66 historical verifier probes from model experiments, and avoids novelty, superiority, equivalence, and cross-benchmark score claims. The checked totals and per-arm first-action/repair counts agree with the audit JSON. Citation descriptions remain within the supplied citation audit's claim scope; I did not independently reopen the papers.

## Actionable findings

1. **Medium — “offline replay” is not the implemented provenance.** C003, C023, C040 and T11 describe the four C/D disagreements as offline policy replay. `generation/public_benchmark/runner.py:181–193` computes both recommendations during the original run, before recording the chosen action, and saves them in `scheduler_audit`. `analyze.py:142–171` and `evidence/extract_evidence.py:144–157` subsequently aggregate those saved values; they do not reconstruct and rerun the policies offline. Replace the term with “运行时同状态双策略建议记录的事后汇总” or “同状态建议对照”. The count of four remains supported; a separate replay-verification claim is not.

2. **Low — specify the target-following proxy and all denominators.** C073 gives 114 auditable rounds, 112 followed, and one missing, without explicitly accounting for the other two false values. `runner.py:234–236` defines the measure solely by whether the selected declaration appears in the token-change list, not semantic adherence or editing it first. The two false records have no declaration token change and still verify successfully (DA0271/solve and DV0034/MajorityElement); the missing one is infrastructure failure DH0071/search. Suggested wording: “D 的 115 次动作中，114 次有可计算的目标声明 token 变化判据：112 次为真、2 次为假，另 1 次缺失。该代理指标不证明目标优先顺序、必要修复或因果遵循。” C040 should use this same proxy qualification.

3. **Low — total-token limit is also a stopping threshold, not a guaranteed consumption ceiling.** C027 qualifies the output cap as checked after generation, but still calls 240000 a total-session upper bound. `runner.py:175–176,198–220` checks cumulative tokens before and after each call; it cannot interrupt that call at the remaining session-token allowance. Revise to “总 token 停止阈值 240000；单次调用返回后的检查可能使实际消耗越过阈值”, while retaining the existing shared-budget/compute caveat. No new run is needed.

4. **Low — disambiguate parsed diagnostics from parsing errors.** C005/C044 and T15 use “解析诊断”. Here the Count/Copy observations are verification-failed postcondition/invariant diagnostics, not syntax/parser errors. Use “经适配器解析后的验证诊断（结构化诊断记录）”. Keep the explicit caveat that equal diagnostics do not mean equal full model inputs.

## Pairing clarification already being resolved

The parent audit establishes 104 completed task×replicate blocks, each containing all A/B/C/D arms. Only four families have all three planned repeats. Do not equate incomplete family repetition with absence of within-block pairing. The latest C003 already reflects this distinction; apply it consistently to T07–T09, the outline, and C036/C055. This does not justify population-effect or equivalence inference from the selected completed subset.

## Overall assessment

No additional unsupported superiority or causal-effect claim was identified in the checked draft. The central mechanism interpretation is acceptable as a bounded observation: few completed trajectory states offer competing targets. The manuscript should preserve its explicit distinction between that observation and demonstrated downstream outcome benefit. Historical verifier-version mismatch is already disclosed in C074 and is not a new blocker from this review.
