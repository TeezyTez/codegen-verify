# 公开文献核验台账

访问日期：2026-10-12。定向叙述性核验，不是系统综述。机器已检查元数据与所列窄范围支持位置；所有文献仍待具名人类复核。

| Evidence ID | Bibkey | 文献与年份 | 已打开版本 | 出版状态 |
|---|---|---|---|---|
| E101 | DafnyBench2024 | [DafnyBench: A Benchmark for Formal Software Verification](https://arxiv.org/abs/2406.08467), 2024 | v1 | Cited arXiv preprint (2024); potential TMLR 2025 version discovered but access-gated and not upgraded |
| E102 | Clover2024 | [Clover: Closed-Loop Verifiable Code Generation](https://arxiv.org/abs/2310.17807), 2024 | v4 | Published conference paper, SAIV 2024; Springer LNCS 14846, pp.134–155 |
| E103 | VeruSAGE2026 | [VeruSAGE: A Study of Agent-Based Verification for Rust Systems](https://arxiv.org/abs/2512.18436), 2026 | v2 | Cited arXiv preprint v2 (2026); first submitted 2025; no publisher version established |
| E104 | DafnyPro2026 | [DafnyPro: LLM-Assisted Automated Verification for Dafny Programs](https://arxiv.org/abs/2601.05385), 2026 | v1 | Cited arXiv preprint v1 (2026); formal publication not established |
| E105 | P32026 | [P$^{3}$: Joint Program-and-Proof Planning for Verified Code Generation](https://arxiv.org/abs/2608.09277), 2026 | v1 | Cited arXiv preprint v1 (2026); formal publication not established |
| E106 | SkillForge2026 | [SkillForge: Compositional Skill Synthesis with Verification-in-the-Loop for Generating Formally Verified Dafny Programs](https://arxiv.org/abs/2608.29841), 2026 | v1 | arXiv v1; authors report accepted by EMNLP 2026; publisher acceptance/proceedings record not independently confirmed |
| E107 | ExVerus2026 | [ExVerus: Verus Proof Repair via Counterexample Reasoning](https://arxiv.org/abs/2603.25810), 2026 | v2 | Cited arXiv preprint v2 (2026); formal publication not established |
| E108 | ScientificAgentSkills2026 | [Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents](https://arxiv.org/abs/2609.00065), 2026 | v2 | Cited arXiv preprint v2 (2026); software/procedural-workflow reference |
| E109 | AxDafny2026 | [AxDafny: Agentic Verified Code Generation in Dafny](https://arxiv.org/abs/2606.32007), 2026 | v1 | Cited arXiv preprint v1 (2026); formal publication not established |

## E101: DafnyBench: A Benchmark for Formal Software Verification

- 作者：Chloe Loughridge; Qinyi Sun; Seth Ahrenbach; Federico Cassano; Chuyue Sun; Ying Sheng; Anish Mudide; Md Rakib Hossain Misu; Nada Amin; Max Tegmark
- 支持命题：DafnyBench evaluates restoration of assert/invariant proof hints and retries with Dafny error feedback.
- 定位：https://arxiv.org/html/2406.08467v1 §3.2 Task Design: Fill Hints, lines 114–122; §4.1, lines 161–165 (saved locator_more_web.txt).
- 不可推出：Does not establish that declaration-level dependency scheduling is new or effective; its fill-hints result is not directly comparable to joint implementation/proof generation.
- 实际打开程度：arXiv abstract, BibTeX export, targeted HTML full-text sections; author repository README.
- 交叉核验：arXiv authors/title match author repository https://github.com/sun-wendy/DafnyBench. Search exposed OpenReview yBgTVWccIx TMLR 01/2025; direct record/PDF access showed browser verification challenge, API inaccessible.
- 限制：Use 2024 only for the cited arXiv version. TMLR version/year/metadata upgrade remains unresolved. No published-version numbers copied into this record.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E102: Clover: Closed-Loop Verifiable Code Generation

- 作者：Chuyue Sun; Ying Sheng; Oded Padon; Clark Barrett
- 支持命题：Clover checks consistency among program code, docstrings, and formal annotations.
- 定位：https://arxiv.org/pdf/2310.17807 §3.2 Clover Verification Phase, printed pp.5–6 (PDF indices 4–5), lines 195–205; Springer abstract.
- 不可推出：Does not prove this project's fixed-specification scheduler improves effectiveness; consistency among descriptions is a different decision variable from proved dependency status.
- 实际打开程度：arXiv abstract/BibTeX, targeted PDF extracted text, Springer chapter metadata, author BibTeX and Stanford blog; arXiv HTML and Weizmann PDF attempts failed.
- 交叉核验：Publisher https://link.springer.com/chapter/10.1007/978-3-031-65112-0_7 matches https://web.stanford.edu/~chuyues/files/clover.html and arXiv authors/title.
- 限制：Use the 2024 published reference. Earlier shorthand 'Code Verification via LLMs' was incorrect. Author BibTeX date/page mojibake normalized to -- using publisher-supported page range; abstract omitted. Crossref API inaccessible; no DOI metadata invented.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E103: VeruSAGE: A Study of Agent-Based Verification for Rust Systems

- 作者：Chenyuan Yang; Natalie Neamtu; Chris Hawblitzel; Jacob R. Lorch; Shan Lu
- 支持命题：VeruSAGE studies hands-off general coding agents and hands-on verification-specific guidance and control for Rust/Verus proof tasks.
- 定位：https://arxiv.org/html/2512.18436v2 §4 Agentic System Designs, §4.1 Hands-Off Approach, §4.2 Hands-On Approach, lines 160–175 and following; original abstract.
- 不可推出：No cross-benchmark comparison with this project's Dafny tasks; does not establish a universal advantage for more prescriptive control.
- 实际打开程度：arXiv abstract/BibTeX and selected HTML introduction/methods; not an exhaustive paper/implementation review.
- 交叉核验：arXiv version history and export agree on current citation year 2026; targeted USENIX search yielded no confirmed publisher record in this session.
- 限制：Record first-submission year 2025 separately from v2/export year 2026. Publication search was targeted, not exhaustive.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E104: DafnyPro: LLM-Assisted Automated Verification for Dafny Programs

- 作者：Debangshu Banerjee; Olivier Bouissou; Stefan Zetzsche
- 支持命题：DafnyPro combines a parser-based diff checker protecting base code with pruning and problem-independent proof-hint augmentation.
- 定位：https://arxiv.org/html/2601.05385v1 §3.1, especially lines 115–117; §3.2 Removing Unnecessary Clauses; §3.3 Incorporating Domain Knowledge; abstract confirms three components.
- 不可推出：Protecting a base implementation in annotation completion does not show the same task as generating implementation bodies under fixed specifications; reported gains cannot be transferred.
- 实际打开程度：arXiv abstract/BibTeX and selected HTML §§3.1–3.3 and appendix; not replication.
- 交叉核验：arXiv abstract and full text agree on method components. Publisher search found no primary published record.
- 限制：HTML contains placeholder DOI XXXXXXX.XXXXXXX and template year 2018; these were rejected as bibliographic facts. Citation uses arXiv record's 2026 and arXiv-issued DOI only.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E105: P$^{3}$: Joint Program-and-Proof Planning for Verified Code Generation

- 作者：Zenan Li; Ziran Yang; Peiyang Song; Zhaoyu Li; Kaiyu Yang
- 支持命题：P3 first makes a joint program-and-proof plan and then elaborates implementation and proof using that plan.
- 定位：https://arxiv.org/html/2608.09277v1 §3 Methodology, §3.1 Joint Program-and-Proof Planning, §3.2 Plan-Guided Elaboration; lines 103–107 and following. Appendix C (lines 310–315) limits transfer claims.
- 不可推出：Does not empirically establish the approach in Dafny or Verus; no implication that current dependency-status scheduling is new or better.
- 实际打开程度：arXiv abstract and targeted HTML methods/limitations; BibTeX endpoint returned cache miss, API inaccessible.
- 交叉核验：Original arXiv abstract metadata parsed programmatically and compared with full-text author/title block.
- 限制：Current empirical setting is Lean; transfer to Dafny/Verus is described as plausible but not empirically established. No publication outlet inferred.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E106: SkillForge: Compositional Skill Synthesis with Verification-in-the-Loop for Generating Formally Verified Dafny Programs

- 作者：Yanming Liu; Xinyue Peng; Jiannan Cao; Xinyi Wang; Jinbo Su
- 支持命题：SkillForge uses structured verification-error categories to deterministically route to reusable repair skills.
- 定位：https://arxiv.org/html/2608.29841v1 §3.2 (Table 1; SYNTHBODY and STRENGTHENSPEC), §3.3 Error-Conditioned Routing, lines 179–232; arXiv abstract/comments.
- 不可推出：Does not establish that fixed-specification declaration scheduling is new or effective; do not characterize all SkillForge steps as freely changing specifications.
- 实际打开程度：arXiv abstract and selected HTML §§3.2–3.3; BibTeX export cache miss; metadata fallback used original arXiv abstract.
- 交叉核验：Full-text title/authors match abstract; targeted ACL Anthology search did not establish a publisher record.
- 限制：SYNTHBODY anchors specifications, while STRENGTHENSPEC may add inferred domain constraints; scope differs from globally frozen specification. EMNLP acceptance is author-reported only.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E107: ExVerus: Verus Proof Repair via Counterexample Reasoning

- 作者：Jun Yang; Yuechun Sun; Yi Wu; Rodrigo Caridad; Yongwei Yuan; Jianan Yao; Shan Lu; Kexin Pei
- 支持命题：ExVerus uses generated and validated counterexamples to guide iterative proof repair.
- 定位：https://arxiv.org/html/2603.25810v2 §3 ExVerus Framework, §3.1 Counterexample Generation with Validation, §3.2 mutation-based repair; lines 169–176 and following.
- 不可推出：Behavioral counterexamples do not establish the efficacy or novelty of a ledger of proved declaration dependencies; no cross-benchmark success-rate comparison.
- 实际打开程度：arXiv abstract/BibTeX and selected HTML problem formulation/methods.
- 交叉核验：arXiv abstract and full-text author/title/method descriptions agree; no separate publisher metadata established.
- 限制：Counterexample validation has a stated special role for invariant-related failures. No claim that all generated examples are executable witnesses of original program bugs.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E108: Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents

- 作者：Timothy Kassis; Vinayak Agarwal; Yuhuan He; Darshil Patel; Aubrey M. Brueckner
- 支持命题：Scientific Agent Skills describes an on-demand procedural knowledge library; it does not report a task-level evaluation of scientific-work improvement.
- 定位：https://arxiv.org/html/2609.00065v2 §2 What an agent skill is, lines 95–98; §6 Limitations, No task-level evaluation, lines 140–142; abstract.
- 不可推出：Does not validate this study's science, source truth, reproducibility, or effectiveness; library automation is not human scientific verification.
- 实际打开程度：arXiv abstract/BibTeX, selected HTML §2/§6, official repository README.
- 交叉核验：Official arXiv link points to https://github.com/K-Dense-AI/scientific-agent-skills; repository names the same paper.
- 限制：Added because scientific skills materially contributed and skill instructions request citation; this is software/procedural credit, not evidence for scheduler performance. Current citation URL and DOI are unversioned; opened version v2 retained only in audit.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。

## E109: AxDafny: Agentic Verified Code Generation in Dafny

- 作者：Benjamin Breen; Austin Letson; Borja Requena Pozo; Leopoldo Sarra
- 支持命题：AxDafny uses a proposer, review system, and memory module in a verification loop; its evaluation treats specifications as fixed.
- 定位：https://arxiv.org/html/2606.32007v1 §3.1 Agent Architecture, lines 111–128; Appendix A LCB-Pro-Dafny Construction, lines 219–224.
- 不可推出：Fixed specifications, memory and verifier-guided repair alone are not novel contributions of the current project; no direct effectiveness ranking without matched tasks/budgets.
- 实际打开程度：arXiv abstract/BibTeX and selected HTML §3.1/Appendix A.
- 交叉核验：Original arXiv metadata/export and full-text title/authors match.
- 限制：Direct near neighbour. Allows helper definitions/proof artifacts while protecting original signatures/definitions/specifications; model, dataset and acceptance protocol differ from current partial matrix.
- 机器状态：metadata_and_targeted_source_locators_checked；人类状态：pending，尚无具名复核人。
