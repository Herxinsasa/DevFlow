# DevFlow 1.2.0 — shared

本目录基于 DevFlow `1.2.0` 的现有流程，使用 Codex 与 DeepSeek Harness（DSH）共同支持的项目入口：根目录 `AGENTS.md` 和 `.agents/skills/`。需求、设计、TDD、Bug 批次、审查与验证门禁沿用原版。安装脚本尚未适配；Git 提交前 hook 已提供手动启用方式。

## 使用范围

将本目录放在项目根使用。两种 Harness 都读取项目根 `AGENTS.md` 并发现 `.agents/skills/`；独立评审和 T2/T3 独立实现由主 Agent 派发全新子 Agent，由子 Agent 加载对应角色 Skill；T0/简单 T1 按 `dev-builder` 执行策略可由主 Agent 直接编码。合并到现有项目时，先合并已有 `AGENTS.md` 与同名 Skill，保留已有项目状态和约束，避免覆盖用户规则。

全局安装 DSH 后可直接运行 `dsh web`。在 DSH Web 中，需要把该项目根目录登记并选为当前工作区；若仍处于“默认工作区”，DSH 的原生 `skill` 工具不会发现项目内 `.agents/skills/`，会报告 Skill 不存在。

`.devflow/` 仅是 DevFlow 自有的约束、脚本和状态目录，并非任何 Harness 的官方目录。当前需手动维护 `.devflow/progress.json`，并执行提交前审查、构建和验证门禁；Git hook 仅在手动配置后对提交时的审查与构建提供兜底。

### DSH 运行前提

- 选择项目根为工作区，并启用原生 `skill` 与 `subagent` 工具。DSH 没有 `subagent_type`，角色只能由 `subagent` 的 prompt 指定；prompt 第一句必须要求子 Agent 先 `skill` 加载角色 Skill，主 Agent 不得直接加载角色 Skill。
- 三个角色 Skill（`reviewer`、`doc-reviewer`、`implementer`）的 `user-invocable: false` 只隐藏用户 `/name` 调用，不阻止模型加载；角色隔离仍靠本条约定和独立评审流程，不能把它当成硬隔离。
- 子 Agent 看不到父会话；派发时把用户原始输入、范围、基线、允许/禁止范围和输出要求写入 prompt。`subagent` 异步返回，主 Agent 必须等待完成通知并核对；同一子 Agent 用 `send_message` 续用。默认委派深度为 1，角色子 Agent 不再嵌套。
- 会话权限需允许工作区写入、`pwsh`、`git` 和项目构建命令；构建需要网络时同时放行。DSH 的权限在会话/profile 权限预设中配置，没有项目级 `permissions.allow` 文件。
- `AGENTS.md` 受 DSH 指令预算限制；base profile 默认 65,536 字节，实际以当前 profile 为准。合并项目自有 `AGENTS.md` 后需复核，避免末尾门禁被截断。
- Git 项目需手动执行 `git config --local core.hooksPath .devflow/hooks` 才会触发提交门禁。

角色派发 prompt 的最小结构：

```text
你是独立 <角色>。第一步：调用 `skill` 工具加载 `<角色>`，再按该 Skill 执行。
任务与范围：...；基线/变更集：...；事实与路径：...；允许/禁止范围：...；输出要求：...
```

DSH 用 `subagent` 启动，等待完成通知后由主 Agent 核对；不要让主 Agent 直接加载角色 Skill。

---

## 一句话定位

```text
按需求规格确认事实、按影响面锁定范围；用 T0-T3 分级控制流程深度，用开发计划逐任务执行，用独立子 Agent 控制审查和 T2/T3 编码，提交前核对指纹凭据。
```

## 工作流特点

- **质量优先**：开发前确认需求和影响范围，开发后执行独立审查与验证，减少理解偏差和遗漏。
- **轻重适配**：按 T0-T3 调整流程深度，小改动保持轻量，复杂需求补足影响面和详细设计。
- **尊重项目事实**：优先使用项目文档、现有架构和源码证据，不让 AI 自行推断业务与模块边界。
- **可持续执行**：任务、阻塞和验证状态文件化，跨会话或中途切换后可以继续推进。
- **人工控制关键方向**：需要业务判断的阶段由用户确认，编码、审查和测试尽量自动完成。
- **保护现有项目**：保留用户已有修改和项目定制，升级、审查及提交均有明确保护边界。

## 适用场景

适合由 AI 参与日常迭代的 C/C++、Qt、Web、服务端或混合技术栈项目，尤其适合：

- 需求涉及多个模块、接口、数据、UI 或持久化。
- 开发任务可能跨会话执行或中途切换。
- 希望按风险确认关键文档，后续开发尽量自动推进。
- 需要保留独立代码审查、人工验收和提交门禁。

以下工作不会启动需求迭代：

- 代码解释、方案讨论、只读排查、文档评审和状态查询。
- 不改变既有预期的普通 Bug 修复。
- 纯格式、注释或不改变产品行为的短时维护。

DevFlow 不替代项目管理平台、产品决策和人工验收。一次性脚本、纯探索原型或无须留存状态的极短任务通常无需使用。

## 组成

| 组成 | 用途 |
|---|---|
| `AGENTS.md` | 调度入口、等级判断、阶段流转和恢复规则 |
| `.agents/skills/` | 需求、影响面、UI、设计、计划、编码、审查、测试和提交流程 |
| `.devflow/constraints/` | 默认编码、日志、文档和目录规范；可增加项目约束 |
| `.devflow/progress.json` | 当前迭代、任务、阻塞和待办输入 |
| `.devflow/scripts/` | 项目模板/约束解析与修改文件的编码检查 |
| `releaseNote.txt` | 版本修订记录 |
| `tests/` | DSH 适配与入口一致性回归测试 |

需求、设计、计划和测试文档生成在目标项目的 `docs/` 中；更新本适配版时应保留这些项目产物。

各类事实分别维护：需求规格保存业务预期，影响面保存真实范围，详细设计保存技术契约，开发计划保存任务与验证当前状态，审查和构建凭据证明最终代码质量，`progress.json` 只负责恢复导航。UI 原型按需写入 `docs/05-UI/原型/<迭代ID>/`。

## 流程分级

等级按业务影响、技术契约风险和失败后果判断，不按文件或函数数量判断。

| 等级 | 典型场景 | 默认流程 |
|---|---|---|
| T0 | 极小修改或不接入既有业务的独立新增 | 需求确认、简要影响、编码、独立审查、最小验证；可省略计划 |
| T1 | 同模块局部行为变化，模式清楚 | 需求确认、简要影响、计划、编码、独立审查、验证 |
| T2 | 跨模块、接口/数据、持久化、复杂 UI 或线程 | 需求、独立影响面、按需 UI、需求设计、计划、编码、独立审查、验证 |
| T3 | 跨工程协议、迁移、安全或不可逆变更 | T2 主链，默认增加独立概要设计并加深兼容、回退和验证 |

T0/T1 默认不生成详细设计，只有需求规格一次开发前硬确认；简要影响写回现有产物并建议查阅。T2/T3 分别确认需求、影响面和设计；按需 UI 产物在原有 UI 确认门处理。等级由影响和风险决定，不因文件多、函数多或需求项多自动升档。

## 工作入口

| 输入意图 | 进入的流程 | 首先确认的事实 |
|---|---|---|
| 新增或改变行为、接口、数据、UI、配置规则 | 需求开发主链 | 目标、现有行为、验收与影响范围 |
| 保持已确认预期，改进实现、性能、依赖或构建方式 | 技术改造（复用分级开发链） | 技术目标、不变边界和验证基线 |
| 当前行为偏离已确认预期 | Bug 修复子流程 | 既有预期、失败信号、根因证据 |
| 解释、评估或只读排查 | 只读处理 | 所需信息和证据范围 |

入口根据目标与已确认预期判断，不凭“Bug”“优化”“重构”等词触发。预期不明时先查需求、契约、测试和项目事实；仍不明再问用户。一次输入混有新功能和 Bug 时拆为关联工作项，不把新功能塞进修复批次。

## 主流程

需求开发沿用一条 T0–T3 主链。下图只画默认执行链；按需增强和 Bug 修复分别见后续图示。图中的执行节点以 Skill 命名，菱形表示原有确认门或分级判断。T0/T1 只有需求确认这一道默认的开发前硬确认；T2/T3 再分别确认独立影响面和设计。`doc-reviewer` 在原需求、设计确认门前检查，不增加确认次数。失败只回到真正失效的阶段，不重走仍有效的前置结论。

```mermaid
flowchart TB
    START(["新增或改变行为"]) --> SPEC["spec-analyzer<br/>需求规格"]
    SPEC --> DR1["doc-reviewer<br/>需求评审"]
    DR1 --> SC{"用户确认需求？"}
    SC -->|需修改| SPEC
    SC -->|是| IMP["impact-analyzer<br/>影响分析"]
    IMP --> TIER{"风险等级？"}
    TIER -->|T0| BUILD["dev-builder<br/>编码"]
    TIER -->|T1| PLAN["dev-planner<br/>开发计划"]
    TIER -->|T2/T3| IC{"用户确认影响面？"}
    IC -->|需修改| IMP
    IC -->|是| DESIGN["design-writer<br/>需求设计"]
    DESIGN --> DR2["doc-reviewer<br/>设计评审"]
    DR2 --> DC{"用户确认设计？"}
    DC -->|需修改| DESIGN
    DC -->|是| PLAN
    PLAN --> BUILD
    BUILD --> RV["code-reviewer<br/>最终差异审查"]
    RV --> TV["code-tester<br/>构建与验证"]
    TV --> UV{"用户验收或风险接受？"}
    UV --> DONE(["迭代完成"])
    DONE -.->|用户明确要求| CC["code-committer<br/>提交或发布"]
```

需求有影响行为或验收的歧义时，`spec-analyzer` 逐题澄清并保留关键假设；输入明确时跳过访谈。复杂迭代按“目标 → 按需需求组 → 可验收的 `REQ`”组织。T0/T1 的简要影响写回需求规格，T2/T3 的独立影响面获确认后才进入设计和计划。开发计划将编码列为 `TASK`，将构建、测试、审查和用户验收列为 `VERIFY`。所有代码交付都要独立审查及与风险匹配的验证；提交和发布不属于迭代完成条件，只在用户明确要求时执行。

## 补充流程（按需增强）

增强节点按风险和用户选择插入主链，跳过时不增加产物或确认门。T0/T1 需要直观 UI 确认时，也在 UI 编码前插入 `ui-designer`；T2/T3 在影响面确认后、设计前插入。概要设计和接口契约由 `design-writer` 在同一设计阶段按需补充，测试设计在设计评审前接入。公开声明先审属于首个编码任务中的条件节点。

```mermaid
flowchart TB
    UISTART(["主链：影响分析后、UI 编码前"]) --> UIQ{"需要直观 UI 确认？"}
    UIQ -->|是| UI["ui-designer<br/>UI 产物"]
    UI --> UIC{"用户确认 UI？"}
    UIC -->|需修改| UI
    UIC -->|是| UIEND(["返回主链：设计或编码"])
    UIQ -->|否| UIEND

    DSTART(["主链：T2/T3 需求设计阶段"]) --> OVQ{"需要概要设计？"}
    OVQ -->|是| OV["design-writer<br/>概要设计"]
    OV --> CQ{"需要独立接口契约？"}
    OVQ -->|否| CQ
    CQ -->|是| CONTRACT["design-writer<br/>接口契约"]
    CONTRACT --> TQ{"需要测试设计？"}
    CQ -->|否| TQ
    TQ -->|是| TD["test-designer<br/>可观察用例"]
    TD --> DEND(["返回主链：设计评审与确认"])
    TQ -->|否| DEND

    PSTART(["主链：首个编码任务"]) --> PQ{"需要公开声明先审？"}
    PQ -->|是| DECL["dev-builder<br/>公开声明草案"]
    DECL --> PC{"用户评审声明？"}
    PC -->|需修改| DECL
    PC -->|通过| PEND(["返回主链：后续编码"])
    PQ -->|否| PEND
```

图中的三个入口分别表示插入主链的时机，不要求所有增强节点依次执行。T3 默认产出概要设计；T2 仅在多对象或跨边界协作需要时产出。

### 增强节点启用条件

| 节点 | 何时启用 | 写入何处或如何确认 |
|---|---|---|
| UI 设计 | 新页面，或布局、视觉层级、组件形态、交互路径需要直观确认 | UI 产物在原 UI 确认门处理；简单字段或文案变化可复用现有界面 |
| 概要设计 | T3 默认；T2 在多对象或跨边界协作需要时 | 独立概要设计，与需求设计及契约同次确认 |
| 接口契约 | 跨进程、跨工程、独立发布或不同维护方消费的通信边界变化 | 维护方与消费方在原设计确认门确认；REST 字段说明位置、单位、错误及无结果时的 `[]` / `null` |
| 公开声明先审 | 独立消费方需先依据头文件/IDL 开发，或公共类型语义风险高 | 先评审声明草案，再实现转换、后端和 UI；普通 REST 变化不触发 |
| 测试设计 | 关键逻辑、复杂映射、高回归风险或用户选择；T3 必须说明测试层级 | 可选 `test-designer` 在设计确认前补用例；单元测试不强制，未选用时写替代验证 |

### TDD（可选）

`test-designer` 在编码前设计可观察用例：T2/T3 写入设计草稿，无详设时写入开发计划；它不编写或运行测试代码。选用 TDD 后，`dev-planner` 将测试与实现放入同一行为 `TASK`，`dev-builder` 逐个行为执行红（失败测试）→ 绿（最小实现）→ 重构并复测，不预先批量编写测试。交付前仍由 `code-tester` 执行选定验证；未选 TDD 时按项目常规方式实现和验证。

每个编码任务重新核对同层同类实现、注册/转换机制、权威类型及文件编码；任务结束和交付前检查本次修改文件的编码、BOM、行尾和项目格式。审查与验证凭据必须覆盖最终待交付差异。

## Bug 修复子流程

用户主动报告异常时，无论是否使用“Bug”一词，都先核对**已确认预期 → 失败信号 → 根因证据 → 影响与复测范围**。无法可靠定位时先收集证据，不猜测性修改。若修复会改变原预期，该问题经用户确认后转入需求开发。

```mermaid
flowchart TB
    REPORT(["用户报告异常"]) --> DIAG["bug-fixer<br/>诊断与判险"]
    DIAG --> EVID{"根因证据充分？"}
    EVID -->|否| WAIT(["等待补充证据"])
    WAIT -.-> DIAG
    EVID -->|是| RISK{"需先确认方案？"}
    RISK -->|是| CONF{"用户确认修复方案？"}
    CONF -->|需调整| DIAG
    CONF -->|是| FIX["bug-fixer<br/>最小修复"]
    RISK -->|否| FIX
    FIX --> RETEST["bug-fixer<br/>针对性复测"]
    RETEST --> GATE{"准备下一版交付或提交？"}
    GATE -->|否| MORE(["等待同版后续反馈"])
    MORE -.-> DIAG
    GATE -->|是| REVIEW["code-reviewer<br/>累计最终差异审查"]
    REVIEW --> TEST["code-tester<br/>风险匹配构建与回归"]
    TEST --> ACCEPT{"用户验收或风险接受？"}
```

开发任务内自动发现的失败沿原任务修复，不增加确认门。用户报告的每个问题先诊断：根因清楚、范围局部且可验证的低风险修复可直接执行并报告；预期或根因不清、高风险，或用户要求先看方案时，先说明分析和拟改范围，获确认后再修改。根因或范围实质变化需重新判险。

初版交付后，同一测试版本的多轮反馈共用一个修复批次；优先复用现有问题清单，没有时使用 `docs/06-测试/<批次ID>-修复批次.md`。每个 `BUG-xxx` 只做针对性复测；公共声明、接口或构建配置变化在交给联调方前构建受影响目标。下一版交付或用户要求提交前，对累计最终差异统一审查、构建和回归。新功能进入待办，不混入本批次；提交或推送仍需用户明确要求。

## 其他入口

**技术改造**用于重构、依赖更新、构建调整等功能预期不变的工作。先明确技术目标、不变行为和验证基线，再按 T0–T3 风险等级复用影响分析、按需设计、编码、审查和验证；不生成需求规格或专用基线文档。若实际需要改变功能预期，转入需求开发。

**只读处理**用于咨询、评估和排查，不启动迭代；用户要求实施后再选择相应入口。

## 目录与定制

| 路径 | 作用 |
|---|---|
| `AGENTS.md` | 两种 Harness 均支持的项目级调度入口 |
| `.agents/skills/` | 两种 Harness 均支持的项目技能目录，含流程 Skill、三个角色 Skill 及模板 |
| `.devflow/constraints/` | DevFlow 默认约束及用户新增约束 |
| `.devflow/progress.json` | DevFlow 当前迭代导航与恢复状态 |
| `.devflow/scripts/` | DevFlow 模板/约束解析和文件编码检查 |
| `.devflow/hooks/` | Git 提交前审查和构建检查 |
| `.devflow/document-policy.md` | 文档编写时按需加载的总控规则 |
| `tests/` | DSH 适配与入口一致性回归测试 |

跨 Codex 与 DSH 的项目推荐使用 `AGENTS.md` + `.agents/skills/<技能>/SKILL.md`。这是两边官方文档共同支持的交集：Codex 将 `.agents/skills/` 作为仓库 Skill 路径，DSH 同时扫描 `.dsh/skills/` 与 `.agents/skills/`。三个角色 Skill（`reviewer`、`doc-reviewer`、`implementer`）须由独立子 Agent 加载，它们不是 DSH Agent 预设；DSH 没有 `subagent_type`，具体启动工具按所用 Harness 选择。


官方依据：[Codex 项目自定义说明](https://learn.chatgpt.com/docs/customization/overview)、[Codex Skill 发现路径](https://learn.chatgpt.com/docs/build-skills)、[DSH Skill 发现顺序](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/skills.md)、[DSH 项目指令加载](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/README.md)。这里的“推荐”是依据两边官方支持路径得出的跨工具选择，并非 DSH 官方单独指定的首选路径。

替换默认模板时，直接修改 `.agents/skills/<技能>/references/` 下的对应文件；新增约束放入 `.devflow/constraints/`。若模板或约束放在这些目录之外，可在项目根配置 `devflow.project.json`，解析规则见 `AGENTS.md` 与 `.devflow/document-policy.md`。发生实质冲突时由用户确认。

## 安装与升级

本目录当前是手动安装/升级包，没有 DSH 版 `devflow.py`、managed-file manifest 或自动升级脚本。合并到项目根时，对以下受管路径做差异合并，不删除项目新增文件：`AGENTS.md`、`.agents/skills/`、`.devflow/constraints/`、`.devflow/scripts/`、`.devflow/hooks/`、`.devflow/document-policy.md` 和 `.devflow/devflow-version.json`；保留项目自己的 `docs/`、`.devflow/constraints/` 中新增的约束、`.devflow/progress.json` 和状态凭据。升级前先备份并 diff 受管路径，手动合并同名 Skill/约束；项目自有 `devflow.project.json` 和 `.agents` 之外的模板不改写。自动安装/升级脚本适配完成前，不要用脚本批量覆盖。

## Git 提交前门禁

本目录提供与 Codex、DSH 无关的 Git `pre-commit` hook。它在**提交时**检查暂存产品代码是否有覆盖该内容的独立审查凭据，并复用匹配当前暂存范围的构建凭据；缺失时按项目构建入口构建并记录。联调 Bug 批次中的每项修复只做针对性验证，下一版本交付或用户要求提交前才统一审查与构建。工作流本身仍负责验收状态、测试结果和用户提交授权；Git hook 不代替这些判断。

在普通 Git 工作树根目录使用，并确认没有需要保留的其他 `core.hooksPath` 后，手动启用：

```powershell
git config --local core.hooksPath .devflow/hooks
git config --local --get core.hooksPath
```

已有 hook 路径时先合并原有 hook，不要直接覆盖配置。Windows 使用 `powershell.exe`，其他系统需要 `pwsh`。未配置 Git hook、SVN 和无版本控制项目仍由 `code-committer` 按相同门禁检查。安装/升级脚本尚未适配，按“安装与升级”手动合并。当前已完成 DSH Web 启动、项目 Skill 原生加载和独立子 Agent 的只读运行验证；真实项目从编码到提交的完整写入交付链仍需在实际项目中验证。
