# 自然语言生成 PSM 的报销审批材料示例

这套材料展示如何把报销审批规则转成平台模型配置，并追溯每项配置的依据。建议按“原始需求 → 补齐的示例规则 → 平台元模型 → 参考配置 → 验收场景”阅读。

ExpenseFlow v1 是本示例定义的假设平台。业务规则和设计决定均为演示构造；参考配置尚未经用户或业务专家认可。这里的 PSM 采用自定义元模型及 JSON 序列化，没有声明符合 OMG MOF，也没有可部署的真实工作流引擎。材料中的“放行付款”仅表示生成放行记录，不执行银行支付。

| 材料 | 内容 |
|---|---|
| [本说明](README.md) | 原始需求、规则、平台语义、设计决定、使用方式 |
| [规则中间表示](rules.ir.json) | 需求抽取后的结构化语义，未绑定平台存储方式 |
| [PSM 结构模式](psm.schema.json) | 配置对象、字段类型、枚举与结构限制 |
| [参考 PSM 配置](reference.psm.json) | 绑定 ExpenseFlow v1 的配置实例 |
| [生成依据](traceability.json) | 需求、规则、配置路径和验收场景的对应关系 |
| [验收场景](acceptance-cases.json) | 输入、事件顺序和预期结果，尚未在平台运行 |

这些文件中，JSON Schema 只规定结构。完整的示例元模型由结构模式、下述平台语义和模型不变量共同组成。结构合法不等于业务规则正确。

**最初收到的自然语言需求**

> 金额超过人民币 10 万元的报销，必须得到至少两名不同经理同意后才可付款。申请人不得参与审批。

这两句话不能直接决定完整配置。至少有四项缺失：不超过 10 万元时怎样处理、经理的组织范围、拒绝如何处理、修改申请后是否需要重新审批。应输出澄清项，而不是把猜测写成原始需求。

| 缺项 | 为何影响配置 | 本示例采用的补全 |
|---|---|---|
| U01 低额申请 | 无法确定低额分支 | 至少一名经理同意 |
| U02 经理范围 | 无法确定办理人集合 | 与申请同租户，且不是申请人 |
| U03 拒绝与关闭 | 无法确定状态转换 | 待审时一票有效拒绝即驳回；达到同意人数立即关闭投票 |
| U04 修订与历史票 | 无法确定旧票有效性 | 修改金额产生新版本，全部重新审批 |

以上是为了形成完整例子而选择的答案，并非用户已经确认的政策。若实验输入只有最初两句话，正确输出应保留这些缺项；不得把下面的完整参考配置当作唯一正确答案。

**补齐后的示例需求集**

| 编号 | 自然语言规则 |
|---|---|
| R01 | 金额以人民币计，必须大于零，最多两位小数。 |
| R02 | 金额不超过 100000.00 元时，至少一名合格经理同意才可完成审批。 |
| R03 | 金额超过 100000.00 元时，至少两名不同的合格经理同意才可完成审批。 |
| R04 | 合格经理须与申请属于同一租户；申请人不得审批自己的申请，即使申请人具有经理或管理员身份。 |
| R05 | 每个申请版本中，每名审批人只能留下一个决定；待审时重复同一决定不增加人数，不得更改已经成功保存的决定。 |
| R06 | 仅待审版本接受新审批决定；一票有效拒绝立即驳回，达到同意人数立即通过。通过或驳回后关闭投票。 |
| R07 | 合格经理不足时不得降低要求或自动通过；未满足完成条件的申请保持待审。 |
| R08 | 仅当前且审批通过的版本可由同租户财务角色放行；每版本最多一条放行记录，放行后关闭该申请的业务变更。申请人兼任财务时可执行放行，但不因此获得审批权限。 |
| R09 | 待审、通过或驳回的当前版本允许修改金额；修改时创建下一版本并重新审批，不继承旧票。已放行申请不得修改。 |
| R10 | 申请人和租户在申请生命周期内不可修改；旧版本保留原结果和记录，但不再接受新审批、修订或付款放行。 |

“至少”表示达到门槛即可通过。选择立即关闭投票是 R06 给出的明确政策；因此通过之后的新拒绝不会推翻结果。

**平台与架构决定**

这些决定属于生成输入，不能假装从最初两句话推导得到。

| 编号 | 已为本示例选择的决定 |
|---|---|
| A01 | 金额使用有符号 int64 的“分”保存；1 元 = 100 分。入口精确解析十进制文本，拒绝超过两位小数、零、负数和超出 int64 正数范围的金额，不静默四舍五入。 |
| A02 | 操作人、租户及角色来自服务端认证上下文。请求不能自行指定操作人或覆盖身份属性；客户端不能直接写入票、状态或放行记录。 |
| A03 | 经理资格在投票时校验。成功保存的历史票按当时资格有效；之后角色变化不撤销该票。申请人和租户不变，避免历史票跨主体复用。 |
| A04 | 对同一 expenseId 的操作原子串行化，范围覆盖全部版本、修订和放行。去重、资格判断、记票、状态改变和放行记录写入处于同一原子操作。 |
| A05 | 每个操作指定 expenseId、version、requestId。成功请求按键、原认证主体、操作类型及全部业务参数回放；相同键的主体、操作类型或业务参数不一致时报错。回放只返回历史结果，不产生新票或放行记录。 |
| A06 | 提交及修订来自已授权的内部申请服务。本文仅建模其业务状态约束，不定义该服务的完整授权流程。付款放行是内部记录，不承诺外部支付成功。 |

**PSM 元模型及执行语义**

PSM 顶层名为 ExpenseApprovalModel，包含平台绑定、金额表示、金额分段、审批策略、状态策略、修订策略、放行策略及执行约束。结构定义见 [psm.schema.json](psm.schema.json)。

| 模型元素 | 关键字段 | 含义 |
|---|---|---|
| platform | name、version | 绑定 ExpenseFlow 的目标版本 |
| money | currency、unit、storage、minimum、maximum | 金额在目标平台上的类型、单位及支持范围 |
| bands | lowerExclusive、upperInclusive、requiredApprovals | 分段区间为 `(下界, 上界]`；上界 null 表示平台支持范围内无额外上限 |
| approval | role、sameTenant、excludeApplicant、countBy | 谁可以投票，以及如何计数 |
| approval | eligibilityAt、duplicateDecision、changeDecision、insufficientApprovers | 资格时间点、重复、改票及人数不足行为 |
| workflow | rejectPolicy、closeOnThreshold | 拒绝和达到人数时的状态变化 |
| revision | allowedFrom、editableFields、resetVotes、closePrevious | 创建版本时保留或失效哪些内容 |
| release | role、sameTenant、requiredState、oncePerVersion | 放行权限及状态门槛 |
| execution | actorSource、atomicScope、requestReplay、clientStateWritable | 身份来源、原子边界、回放和写入约束 |

ExpenseFlow v1 的运行时对象如下。它们是平台数据模型，不是都由模型生成器填写的配置项。

| 运行时对象 | 主键及主要内容 |
|---|---|
| Expense | expenseId、applicantSubject、tenantId、currentVersion |
| ExpenseVersion | (expenseId, version)、amountFen、state、closedByRevision |
| Vote | (expenseId, version, actorSubject)、decision、投票时资格快照 |
| ReleaseRecord | (expenseId, version)、actorSubject、requestId |
| SuccessfulRequest | (expenseId, version, requestId)、原主体、操作类型、全部业务参数、原结果 |

状态为 PENDING、APPROVED、REJECTED、RELEASED。`closedByRevision` 与审批状态分开保存：旧版本被新版本替代时，仍保留 APPROVED 或 REJECTED 等历史状态，不把原结果覆盖成一个通用的“已替代”。

| 事件 | 前置条件 | 原子结果 |
|---|---|---|
| create | 已授权内部服务；身份字段与金额合法 | 版本 1，PENDING，无票 |
| approve | 当前未关闭版本为 PENDING；操作人合格；无相反历史决定 | 保存该主体的同意；不同主体同意数达到所属分段门槛则 APPROVED，否则 PENDING |
| reject | 当前未关闭版本为 PENDING；操作人合格；无相反历史决定 | 保存拒绝，变为 REJECTED |
| revise | 当前版本处于 revision.allowedFrom；只改 amountFen | 旧版本 closedByRevision=true；创建版本号加一的新版本，PENDING、无票；身份字段不变 |
| releasePayment | 当前未关闭版本符合 release 的状态、角色、租户要求 | 保存唯一放行记录并变为 RELEASED；不触发银行支付 |

新请求按顺序检查版本、状态、身份资格和已存决定。旧版本新请求返回 E_STALE_VERSION，当前已关闭投票返回 E_VOTING_CLOSED。PENDING 下，同主体重复同意返回 NOOP，相反决定返回 E_DECISION_IMMUTABLE。无资格的拒绝不得触发驳回。所有错误均不改变状态。

成功请求回放先于上述业务状态判断，但仍要求同一认证主体、同一键、同一操作类型和相同的全部业务参数；下文简称“同一载荷”。比较按解析后的字段和值进行，不依赖 JSON 字段顺序。回放结果标记 REPLAY，附原处理版本。它可以在修订或关闭后读回旧结果，绝不能重新对当前版本执行。相同键不同内容返回 E_IDEMPOTENCY_CONFLICT；例如 approve 与 releasePayment 即使请求正文同为空，也不是同一操作。

同一申请的并发操作按提交到原子边界后的某个顺序执行。若达到门槛的同意先关闭投票，后续拒绝失败；若有效拒绝先关闭，后续同意失败。修订先完成则旧版本放行失败，放行先完成则修订失败。材料只要求符合一种合法串行顺序，不承诺某个请求总能先执行。

必须额外检查以下模型不变量；JSON Schema 不会自动完成这些跨字段检查。

| 编号 | 不变量 |
|---|---|
| I01 | 分段 id 唯一，区间互不重叠，完整覆盖 money.minimum 至 money.maximum；下界小于上界。 |
| I02 | bands 的数值单位与 money.unit 相同；原文元转成分时必须精确换算。 |
| I03 | 每条业务规则都必须有映射或明确缺项；有配置路径不代表语义已得到证明。 |
| I04 | 本例需要排除申请人、限制租户、按主体去重、修订清票及放行门槛；必须逐项核对对应值。 |
| I05 | execution 的原子范围必须覆盖单个申请的所有版本，避免“修订与放行各自成功”。 |

Schema 中某些布尔字段允许 true 或 false，表示平台可以配置两种行为；本例的需求只允许其中一种。把 excludeApplicant 改成 false 仍可能结构合法，但违反 R04。

**从一条规则到配置**

R03 的原文是“超过 100000.00 元，至少两名不同合格经理同意”。中间表示 [IR03](rules.ir.json) 保留严格大于、100000.00 元和不同主体人数 2。结合 A01，阈值换算为 10000000 分；结合 R04 再配置经理角色、租户和申请人排除条件。

参考配置中的关键片段如下；完整字段见 [reference.psm.json](reference.psm.json)。

```json
{
  "bands": [
    {"id": "standard", "lowerExclusive": 0, "upperInclusive": 10000000, "requiredApprovals": 1},
    {"id": "high", "lowerExclusive": 10000000, "upperInclusive": null, "requiredApprovals": 2}
  ],
  "approval": {
    "role": "manager",
    "sameTenant": true,
    "excludeApplicant": true,
    "countBy": "distinctSubject",
    "eligibilityAt": "voteTime",
    "duplicateDecision": "sameDecisionNoop",
    "changeDecision": "reject",
    "insufficientApprovers": "remainPending"
  }
}
```

这个片段不是独立可部署模型，不能省略完整配置中的状态、版本和执行约束。阈值从 100000.00 元变为 10000000 分属于平台映射；低额一票属于 R02 的补充业务政策，两者来源不同。

**验收与错误配置示例**

[acceptance-cases.json](acceptance-cases.json) 给出可供人工审阅或未来执行器使用的事件脚本。预期结果是规则导出的验收依据，目前没有真实平台执行结果。

| 错误改动 | 为什么格式检查可能通过 | 应发现问题的场景 |
|---|---|---|
| 将分段阈值两处同时改成 10000001 分 | 数值及分段仍合法 | C03：100000.01 元应要求两人 |
| 将高额 requiredApprovals 改成 1 | 类型和值范围合法 | C03、C04：一票不能通过 |
| 将 excludeApplicant 改成 false | 合法布尔值 | C05：经理身份的申请人不能自批 |
| 将 revision.resetVotes 改成 false | 合法布尔值 | C12：新版本不能继承旧票 |
| 将 release.requiredState 改成 PENDING | 合法状态枚举 | C13：未通过不得放行 |

这些是候选变异用例，不是已经被实际工作流测试捕获的缺陷报告。

**可直接用于后续生成试验的任务说明**

> 输入：本说明中的 R01—R10、A01—A06、平台执行语义，以及 psm.schema.json。请先输出需求缺项和冲突；若信息充分，生成 ExpenseFlow v1 的 PSM 实例，并输出逐条需求到配置 JSON Pointer 的映射。所有额外设计选择须单列，不得把不支持的规则替换成较弱规则。若输入只有最初两句话，应列出 U01—U04 等缺项，完整性状态为 needs_clarification；允许输出已确定的部分模型，但不能宣称可部署。

评估时，参考配置、验收预期和 traceability.json 留在评估端；不要把参考答案同时作为被测生成器的输入。可以比较语义等价的不同配置，不要求 JSON 文本逐字相同。这是一个教学实例，不能据此统计总体生成能力或宣称方法有效。

材料检查结果：5 份 JSON 均可解析，参考配置通过 JSON Schema 校验，34 处溯源指针均可解析，全部配置叶字段均有来源，分段覆盖和边界检查通过。另已检查：未知顶层字段被模式拒绝，而把 excludeApplicant 改成 false 的业务弱化仍可通过结构校验。业务正确性仍需结合实际平台语义审阅；16 组验收场景尚未运行，参考答案尚未经独立业务专家裁决。
