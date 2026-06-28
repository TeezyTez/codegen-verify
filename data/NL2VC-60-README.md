# NL2VC-60 数据集集成说明

## 简介

**NL2VC-60** (Natural Language to Verified Code - 60 problems) 是一个包含 60 道算法问题的 Dafny 验证数据集。
论文: [arXiv:2604.22601](https://arxiv.org/abs/2604.22601)

作者: Md Erfan, Md Kamal Hossain Chowdhury, Ahmed Ryan, Md Rayhanur Rahman (University of Alabama)

## 数据格式

`NL2VC-60.jsonl` 每行一个 JSON 对象：

```json
{
  "id": "uva_11934",                // UVa 问题编号
  "title": "Magic Formula",         // 问题标题
  "description": "完整的自然语言问题描述（详细）",
  "short_desc": "简短的函数级描述（喂给 Spec Agent）",
  "problem_type": "math",
  "ground_truth_spec": "Dafny 方法签名 + requires/ensures 规约",
  "ground_truth_code": "完整的 Dafny 实现代码（已验证通过）",
  "ground_truth_entry": "MagicFormula",
  "udebug_tests": [
    {"input": [1, 2, 3, 4, 5], "expected": 3},
    {"input": [0, 0, 0, 1, 10], "expected": 11}
  ],
  "difficulty": "easy",
  "tags": ["math", "counting"]
}
```

## 下载

数据集尚未公开。请联系作者获取:
- Md Erfan: merfan@crimson.ua.edu
- arXiv: https://arxiv.org/abs/2604.22601

## 评测指标

### 规约正确性（核心贡献）
| 指标 | 说明 |
|------|------|
| exact_match | 生成的规约和 ground-truth 完全一致 |
| method_match | 方法签名匹配 |
| has_requires/ensures | 规约结构完整性 |
| llm_judge_score | LLM 评判的语义相似度 (0-1) |
| missing_conditions | LLM 分析出的缺失约束 |
| extra_unnecessary | LLM 分析出的多余约束 |

### 代码质量
| 指标 | 说明 |
|------|------|
| exact_match | 完全匹配 |
| structural_match | 忽略空白/注释后匹配 |
| num_loops / num_invariants | 循环/不变量数量对比 |
| has_entry_method | 入口方法是否存在 |

### 功能正确性
- uDebug 测试用例通过率

## 相关论文

```
@misc{erfan2026nl2vc,
  title={From Natural Language to Verified Code: Toward AI Assisted Problem-to-Code Generation with Dafny-Based Formal Verification},
  author={Md Erfan and Md Kamal Hossain Chowdhury and Ahmed Ryan and Md Rayhanur Rahman},
  year={2026},
  eprint={2604.22601},
  archivePrefix={arXiv},
}
```
