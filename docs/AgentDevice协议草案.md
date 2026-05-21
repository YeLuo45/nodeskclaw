# Agent Device 协议草案

> 文档状态：内部讨论稿
> 当前版本：v0.32
> 目标：定义通用 Agent Device 协议，说明外部生产资源如何在 Device Context 中被治理、操作、交接和审计
> 参考结构：RFC（请求评议文档）/ W3C（万维网联盟）技术规范 / Kubernetes KEP（增强提案）

## 摘要

Agent Device 协议定义外部生产资源如何在 Device Context 中被 Agent（AI 执行体）操作，并如何被 Operator（操作者）观察、接手、交接和审计。

Agent Device 不是“Agent 的设备”，而是 Agent 可以操作的、受 Device Context 治理的外部生产资源。

它不是 Tool（工具）协议，也不是 Skill 协议。它解决的是：当 Agent 使用外部系统对外部世界产生真实影响时（业务、账号、客户、文件、网页、终端、电话、消息通道等），Device 协议如何让这个过程变得可见、可控、可交接、可审计。

v1 分为两个合规级别：Level 1 `Device Governance`（设备治理）验证设备准入、租约、操作、释放和审计；Level 2 `Control Transfer`（控制权转移）在 Level 1 基础上验证介入上下文、可观察现场、授权接手、归还或结束控制权。BrowsePilot（浏览器设备提供方）只是当前候选验证样例，不是协议默认设备。Human（人类操作者）只是 Operator 的一种可能实现，不是协议前提。

协议内容按四层组织：Core Protocol（核心协议）、Governance Profile（治理剖面）、Control Transfer Profile（控制权转移剖面）和 Device Profile（设备剖面）。Core Protocol 是最小互操作内核，其他 Profile 在其上约束真实外部副作用、控制权转移和具体设备能力。

## 状态

| 项目 | 内容 |
|------|------|
| `status`（状态） | internal_draft（内部草案） |
| `version`（版本） | v0.32 |
| `audience`（读者） | 协议设计、Device Provider 适配、Agent Runtime（Agent 运行时）、Context Controller（上下文控制器）、协议评审 |
| `normative_level`（规范强度） | 草案阶段，MUST（必须）/ SHOULD（应该）/ MAY（可以）用于表达内部约束强度 |
| `promotion_rule`（升级规则） | 进入正式协议前，所有开放问题必须被关闭、删除，或转化为明确规范要求 |

## 目录

- [摘要](#摘要)
- [状态](#状态)
- [1. 引言](#1-引言)
- [2. 范围](#2-范围)
- [3. 术语和规范性语言](#3-术语和规范性语言)
- [4. 一致性模型](#4-一致性模型)
- [5. Agent Device 和 Skill / MCP 的边界](#5-agent-device-和-skill--mcp-的边界)
- [6. 核心对象](#6-核心对象)
- [7. 状态机](#7-状态机)
- [8. 暂停语义](#8-暂停语义)
- [9. Audit（审计）和 Artifact（产出物）](#9-audit审计和-artifact产出物)
- [10. 安全、隐私和风险](#10-安全隐私和风险)
- [11. 兼容性和扩展](#11-兼容性和扩展)
- [12. 验收标准](#12-验收标准)
- [13. v1 MUST / SHOULD / MAY](#13-v1-must--should--may)
- [14. v1 决议和 v2 待讨论](#14-v1-决议和-v2-待讨论)
- [15. 参考资料](#15-参考资料)
- [16. 修订记录](#16-修订记录)

## 1. 引言

### 1.1 背景

Agent Device 协议属于 foundation / protocol（基础抽象 / 交互协议）型规范：它既要定义 Device Context 中的设备抽象，也要定义 Operator、Agent、Context Controller 和 Device Provider（设备提供方）之间如何协作。

本草案不描述某个具体设备实现的全部 API（应用程序接口），而是规定外部生产资源进入某个设备上下文后必须满足的治理边界。

Device Context 是管理设备实例、策略、租约、状态、可见性、控制权转移和审计责任的治理边界。它可以是 single-agent runtime（单 Agent 运行时）、多 Agent 协作空间、个人任务环境、自动化流水线、服务账号环境或其他受治理的执行上下文。

### 1.2 命名结论

本草案采用 `Agent Device` 作为协议名。

这里的 Agent Device 不是 Agent 私有设备，也不是 Agent 内部工具。它的准确含义是：

> Agent Device 是登记在某个 Device Context 下、受该上下文的策略、租约、状态机和审计约束，并允许 Agent 操作的外部生产资源。

Agent Device 强调的是“Agent 可以操作”，不是“Agent 拥有”。设备通过 `context_id`（上下文 ID）纳入具体上下文的治理边界，必须对当前 Operator、监督方和审计方可见、可控、可交接、可审计。

### 1.3 第一性原理

Agent Device 协议不是为了解决“怎么让 Agent 多一个工具”。

它要解决的是：

> 当 Agent 使用外部系统对外部世界产生真实影响时，Device 协议如何让这个过程变得可见、可控、可交接、可审计？

如果一个外部系统只是能被 Agent 调用，但上下文内的监督方看不见它、不能接手或回收它、不知道谁在用它、无法审计它对外部世界做了什么，那么它只是 Tool 或 Skill，不是 Agent Device。

### 1.4 协议判断标准

后续所有协议字段都先过这个判断：

> 这个字段是否帮助外部系统在具体 Device Context（设备上下文）中成为可见、可控、可分配、可交接、可审计的受治理生产资源？

如果不能回答这个问题，它可能是实现建议、运行时适配、UI（用户界面）方案或部署检查，但不应该进入 Agent Device 协议核心。

## 2. 范围

### 2.1 协议分层

Agent Device 协议不是一个完整控制面产品说明，而是可互操作的设备会话契约。v1 按以下四层组织：

| 层 | 定位 | 放入内容 | 不放入内容 |
|----|------|----------|------------|
| Core Protocol | 所有实现必须理解的最小互操作内核 | 设备类型、设备实例、租约、通用状态、基础动作、结构化可见性 | 具体设备私有动作、产品 UI、部署方式 |
| Governance Profile | 约束真实外部副作用的治理层 | 设备准入、授权、租约回收、审计边界、证据引用、风险约束 | 具体业务审批流、组织制度、审计存储产品形态 |
| Control Transfer Profile | Level 2 控制权转移层 | 介入请求、接手授权、可观察现场、接手、归还或结束控制权 | 不需要交接的单 Agent 最小场景 |
| Device Profile | 具体设备类型的适配层 | browser、terminal、phone 等设备的能力声明、私有动作和 adapter 约束 | 可以跨所有设备复用的核心状态和租约语义 |

判断一个字段属于哪一层，先看它是否跨所有设备类型都必须存在。跨设备必需的字段进入 Core Protocol；用于约束外部副作用的字段进入 Governance Profile；只有控制权转移需要的字段进入 Control Transfer Profile；只对某类设备有意义的能力进入 Device Profile。

Core Protocol 不强制定义统一 request/response schema，也不要求目标平台为了接入 Agent Device 迁移到固定 wire protocol（传输协议）。Core Protocol 定义的是 Agent-readable semantic contract（Agent 可理解语义契约）：目标平台可以通过 CLI、Tool、Skill、MCP、HTTP API、SDK 或其他入口实现这些语义，不要求按固定请求/响应结构做协议转换。

### 2.2 Agent-readable semantic contract

Agent-readable semantic contract 不是固定字段名、错误码或返回包格式，而是每次设备动作返回或关键状态变化时必须让 Agent Runtime 和 Context Controller 能稳定理解的语义事实。

设备动作包括 Core Protocol 的基础动作、Control Transfer Profile 的接手动作，以及 Device Profile 中可能产生外部副作用的私有动作。无论目标平台通过自然语言、CLI 输出、Tool 结果、MCP 返回、HTTP API 响应还是 SDK 返回实现，都按以下规范强度表达语义：

| 语义 | 规范强度 | v1 要求 |
|------|----------|---------|
| 操作意图 | MUST | 说明本次动作试图对哪个 `device_instance_id`、`lease_id`、会话或外部对象做什么 |
| 动作执行状态 | MUST | 说明本次动作执行本身是成功、失败、被拒绝、等待中、部分完成、不支持，还是需要介入 |
| 状态变化 | MUST | 说明设备状态、租约、`current_operator`、现场引用或其他关键状态是否发生变化 |
| 失败原因 | MUST | 失败或拒绝时，说明失败原因、拒绝原因或无法分类状态，见 2.3 |
| 外部副作用 | MUST | 说明是否没有副作用、已经产生副作用、只产生部分副作用，或副作用状态未知 |
| 审计证据 | MUST | 说明相关 Audit（审计）事件、`evidence_refs` 或 `observable_surface_ref` 是否存在；产生外部副作用时不得只返回空泛成功 |
| 下一步建议 | SHOULD | 在可判断时说明 Agent 应继续、停止、重试、刷新状态、释放设备、续租、请求介入或等待 Operator |
| 能力发现 | MUST | 声明影响 Agent 决策的关键能力边界；能力不可用时说明原因或降级语义 |

协议不要求这些语义必须以相同字段名出现，也不要求返回 `code`（状态码）或 `message`（消息）这类固定结构。但返回内容不能只是“成功”“失败”或原始日志；它必须足够让 Agent 判断下一步动作，并足够让 Context Controller 更新状态、审计和租约。

Provider 返回中的成功、失败、完成、拒绝或等待等判断，MUST 绑定到明确语义维度，例如动作执行状态、外部副作用状态、设备状态变化、租约状态或审计证据状态。没有维度归属的泛化 `success` / `failure` 不能被视为合规的 Agent-readable semantic contract。

#### 2.2.1 能力发现与拒绝语义

v1 不定义通用 version negotiation（版本协商）协议，也不要求 Device Provider 实现统一握手、兼容矩阵或协议转换层。Device Provider MUST 声明其 `Device Type`、所实现的 `Device Profile` / 合规级别，以及会影响 Agent 决策的关键能力边界。

能力不可用时，结果语义 MUST 让 Agent 理解原因，例如不支持、条件不满足、需要授权、需要更高 Profile 或只能降级执行。这些是 Agent-readable semantic category（Agent 可理解语义类别），不是固定 error enum（错误枚举）、返回字段或状态码。

### 2.3 最小失败语义

Agent Device 协议不定义统一 error code（错误码）、error enum（错误枚举）或错误返回结构，也不把统一错误模型作为后续版本目标。失败语义的目的不是让目标平台重写自己的错误体系，而是让 Agent 和 Context Controller 能判断下一步是否安全。

最小失败语义中的 MUST 维度不是要求设备给出确定结论；它要求设备不能静默省略关键不确定性。无法判断时，设备可以明确表达 unknown（未知）、unconfirmed（未确认）或 unclassified（无法分类）。

当设备动作不是完全成功时，实现按以下规范强度表达最小决策维度：

| 决策维度 | 规范强度 | 协议要求 |
|----------|----------|---------|
| 执行状态 | MUST | 说明动作未执行、已执行、部分执行、等待中，还是执行状态未知 |
| 副作用状态 | MUST | 说明外部副作用未发生、已发生、部分发生，还是无法确认 |
| 重试安全性 | MUST | 说明重试是否可安全执行、不可安全执行，还是无法判断；无法判断不能被解释为可安全重试 |
| 失败类别 | MUST | 说明粗粒度失败类别；无法分类时必须明确 unknown / unclassified，不要求映射为统一错误码 |
| 审计可靠性 | MUST | 说明是否已有可引用的 Audit（审计）事件或证据；如果审计不可确认，不能当作普通失败处理 |
| 下一步动作 | SHOULD | 在可判断时说明 Agent 应停止、重试、刷新状态、释放设备、续租、重新申请租约、请求授权或请求 Operator 介入 |

这些类别不是固定字段名，也不是必须逐字返回的枚举值。目标平台可以继续使用自己的异常、日志、trace id（链路追踪 ID）或原始错误；但它不能只把原始错误抛给 Agent，也不能只返回“失败”。尤其当副作用状态未知时，协议必须把它表达出来，因为盲目重试可能重复发消息、重复提交、重复拨号、重复删除或重复触发外部业务。

下一步动作是 SHOULD，不是 MUST。设备或平台能从自身状态可靠判断时应该提供建议；如果无法可靠判断，就不应该编造建议，可以明确表示无建议、需要 Agent 自行判断，或需要上层策略 / Operator 介入。

Agent Device 协议不要求设备动作或控制面动作具备统一幂等能力。实现如果能确认某次失败可安全重试，应在重试安全性中表达；如果无法确认，必须表达未知。治理类动作 SHOULD 尽量具备重复调用安全性，但业务副作用动作不得被默认视为可重试。

Device Profile MAY 为某类设备补充更细失败语义，例如 terminal（终端）的命令退出状态、phone（电话）的呼叫失败原因、browser（浏览器）的页面导航失败原因；这些补充不能反向进入 Core Protocol 成为所有设备的负担。

### 2.4 v1 合规级别

v1 定义两个合规级别，避免单 Agent 场景和完整控制权转移场景混在一起：

| 级别 | 名称 | 包含 | 适用场景 |
|------|------|------|----------|
| Level 1 | `Device Governance` | 设备准入、占用、操作、释放、审计 | 单 Agent 环境、自动化流水线、服务账号环境 |
| Level 2 | `Control Transfer` | Level 1 + 控制权转移状态机、介入上下文、可观察现场、授权接手、归还或结束控制权 | 多 Operator 协作环境、多 Agent 接力、Human 接手场景 |

Level 1 等于 Core Protocol + Governance Profile，是受治理设备的最低合规级别。Level 2 等于 Level 1 + Control Transfer Profile，是 v1 的完整验证目标。Device Profile 用于说明某一类设备如何实现上述层级，不单独构成通用合规级别。

### 2.5 Level 2 Control Transfer Profile

Level 2 不绑定具体产品形态，至少验证以下链路：

1. Agent 申请使用一个外部设备。
2. Context Controller 创建有效 `DeviceLease`（设备租约）。
3. Agent 通过租约操作设备。
4. 设备进入需要介入或控制权转移的状态。
5. 另一个已授权 Operator 接手同一个设备现场。
6. Operator 完成处理并归还或结束控制权。
7. Agent 恢复执行，或设备进入可释放状态。
8. 设备释放，并留下审计记录和最小产出摘要。

如果 v1 跑不通这条链路，Agent Device 协议就只是“工具接入系统”的复杂版本，不是真正的设备治理协议。

Operator 不限定为 Human。它可以是 Human、另一个 Agent、系统控制器、上级执行体或其他被 Device Context 授权的操作者。协议关心的是控制权能否被转移、归还、回收和审计，不关心具体操作者形态。

### 2.6 v1 验证剖面

满足 v1 的实现 MUST 明确声明自己满足的合规级别：

| 剖面项 | 所属层 | 要求 | 适用级别 |
|--------|--------|------|----------|
| `context_governance` | Core Protocol | 设备必须登记在某个 Device Context 中 | Level 1 / Level 2 |
| `lease_control` | Core Protocol | 活跃设备必须有有效租约 | Level 1 / Level 2 |
| `visibility` | Core Protocol | 设备状态、租约和 `current_operator` 必须以结构化状态可见 | Level 1 / Level 2 |
| `release_or_reclaim` | Core Protocol | 设备必须能释放、超时回收或强制回收 | Level 1 / Level 2 |
| `admission_control` | Governance Profile | 设备实例必须由 Device Context 内的授权主体显式创建或纳管 | Level 1 / Level 2 |
| `audit_boundary` | Governance Profile | 外部副作用必须在 Device Context 可治理边界产生审计事件 | Level 1 / Level 2 |
| `control_transfer` | Control Transfer Profile | 控制权必须能从一个 Operator 转移给另一个 Operator | Level 2 |
| `operator_authorization` | Control Transfer Profile | 接手方必须满足租约或上下文策略中的授权要求 | Level 2 |
| `intervention_context` | Control Transfer Profile | 请求介入时必须携带可理解的上下文 | Level 2 |
| `observable_surface` | Control Transfer Profile | 请求介入时必须生成或刷新可观察现场引用 | Level 2 |

单 Agent 场景可以声明 Level 1 `Device Governance`；如果没有第二个可接手的 Operator，就不能声明 Level 2 `Control Transfer`。

### 2.7 v1 非目标

v1 不做以下协议层抽象：

- 完整多设备抽象。
- Agent-Agent 排队系统。
- 通用 Preflight（设备预检）规范。
- 通用 Artifact（产出物）存储系统。
- Push state stream（状态流推送）。
- 把具体设备的私有操作模型写进核心协议（例如浏览器 DOM/截图/点击/滚动、终端命令流、电话呼叫控制、消息通道事件）。
- 把 K8s（Kubernetes 集群）、Docker（容器运行时）、镜像拉取、网络出口等部署细节写进协议核心。

这些可以先由对应 device adapter（设备适配器）自己实现。BrowsePilot 只是 v1 候选验证适配器之一；等第二种设备出现后，再从真实差异里抽象通用协议。

## 3. 术语和规范性语言

| 术语 | 说明 |
|------|------|
| `MUST`（必须） | v1 必须满足，否则不能称为 Agent Device 实现 |
| `SHOULD`（应该） | 强烈建议满足；如果不满足，必须说明原因和替代机制 |
| `MAY`（可以） | v1 可以选择不做，不影响协议成立 |
| `Core Protocol` | 所有 Agent Device 实现必须理解的最小互操作内核 |
| `Agent-readable semantic contract` | 设备动作必须向 Agent Runtime 和 Context Controller 表达的可理解结果语义，不等同于固定返回结构或统一 wire format |
| `Governance Profile` | 约束设备准入、授权、租约回收、审计边界和外部副作用的治理剖面 |
| `Control Transfer Profile` | 约束介入请求、可观察现场、授权接手和控制权归还的控制权转移剖面 |
| `Device Profile` | 约束某一类具体设备能力和私有动作的设备剖面 |
| `Device Context`（设备上下文） | 管理设备实例、策略、租约、状态、可见性、控制权转移和审计责任的治理边界 |
| `Operator`（操作者） | 当前实际控制设备并可能产生外部副作用的一方，可以是 Agent、Human、系统控制器、上级执行体或其他被授权主体 |
| `Human`（人类操作者） | 可以观察、接手、审批和审计设备操作的人类操作者，是 Operator 的一种实现 |
| `Agent`（AI 执行体） | 可以申请并操作设备的自动化执行者 |
| `Context Controller`（上下文控制器） | 管理设备实例、租约、状态、权限和审计的控制面 |
| `Device Provider`（设备提供方） | 提供具体设备能力和设备现场状态的系统 |
| `Operator Client`（操作者客户端） | 展示设备状态并承接观察、接手、归还或回收操作的客户端或控制面 |
| `AgentDeviceType`（设备类型） | 设备的抽象类别，如 browser（浏览器）、terminal（终端）、phone（电话） |
| `AgentDeviceInstance`（设备实例） | Device Context 中一个可见、可管理、可占用的具体设备 |
| `DeviceLease`（设备租约） | 设备被占用时的归属、操作者和有效期 |
| `DeviceArtifact`（设备产出） | 设备操作产生的业务产出，不等同于审计 |
| `Audit`（审计） | 对设备操作及外部副作用的强制留痕 |

## 4. 一致性模型

协议必须明确“谁需要符合协议”。v1 至少涉及以下实现方：

| 实现方 | 一致性要求 |
|--------|------------|
| `Context Controller`（上下文控制器） | MUST 维护设备实例、租约、状态、权限、可见性和审计边界 |
| `Agent Runtime`（Agent 运行时） | MUST 通过租约操作设备，不能绕过设备状态机直接产生外部副作用 |
| `Device Provider`（设备提供方） | MUST 暴露设备能力、设备现场状态和必要的接管入口 |
| `Operator Client`（操作者客户端） | SHOULD 能展示设备状态，并支持授权 Operator 接手和归还；如果实现提供 Human 介入能力，则必须支持 Human 接手和归还 |
| `Audit Store`（审计存储） | MUST 记录外部副作用相关操作和证据引用 |

这些实现方是 v1 的 conformance classes（一致性类别）。后续如果引入新的设备类型，必须先说明新增实现方是否属于这些类别，还是需要新增一致性类别。

外部副作用的审计事件必须产生在 Device Context 可治理的边界上。Agent Runtime 可以提供操作意图，Device Provider 可以提供执行结果和证据，但审计不能只依赖被治理主体或外部提供方的单方面声明。

## 5. Agent Device 和 Skill / MCP 的边界

| 概念 | 解决的问题 | 是否是 Agent Device |
|------|------------|---------------------|
| `Skill` | Agent 是否知道如何使用某种能力 | 否 |
| `MCP` / Tool Schema | Agent 是否能调用某个接口 | 否 |
| `Agent Device` | 外部设备是否作为 Device Context 中的受治理生产资源 | 是 |

一个 Agent 可以拥有某类设备的 Skill，也可以通过 MCP 调用对应工具，但这不等于它正在操作一个受治理的、有连续状态的设备现场。

这条边界需要同时从 Agent 和目标平台两侧理解：

- 对 Agent：MCP / Tool / Skill 解决“Agent 如何调用能力”；Agent Device 解决“一个会产生真实外部影响的连续设备会话，如何在 Device Context 中被占用、观察、交接、回收和审计”。
- 对目标平台：如果它希望作为 Agent Device 被 Agent 使用，就不能只暴露零散 CLI / Tool / Skill；它必须按本协议把这些能力纳入设备实例、状态、租约、权限、交接和审计模型。CLI / Tool / Skill 可以是 Device Provider 的实现入口，但不是协议本身。

Agent 操作 Agent Device 必须同时满足三层前置条件：

| 层 | v1 要求 |
|----|---------|
| 操作知识 | Agent MUST 具备对应 `device_type`（设备类型）的操作知识，来源可以是 Skill 或 Tool Schema，获取方式不由本协议规定 |
| 上下文可达 | 设备 MUST 在当前 Device Context 中对该 Agent 可达，可达性判断由 Context Controller 决定 |
| 实例权限 | Agent MUST 持有该设备实例的有效 `DeviceLease` |

## 6. 核心对象

本章属于 Core Protocol。它只定义跨设备类型都必须理解的对象骨架；字段中的治理策略由 Governance Profile 约束，具体设备能力由 Device Profile 约束。

### 6.1 AgentDeviceType（设备类型）

设备类型定义设备的通用语义，不定义具体操作细节。

| 字段 | 说明 |
|------|------|
| `device_type` | 设备类型，如 browser（浏览器）、terminal（终端）、phone（电话） |
| `capability_schema` | 该设备类型自己的能力结构 |
| `concurrency_model` | 并发模型。v1 只允许 `exclusive`；`shared` 和 `pooled` 保留给后续版本或 Device Profile 扩展 |
| `pause_capability` | 暂停能力：硬暂停、软暂停或不支持暂停 |
| `side_effect_profile` | 副作用画像：无、内部影响、外部影响、不可逆影响 |

具体设备的私有操作字段属于对应 adapter（适配器），不进入通用 Agent Device 协议核心。

### 6.2 AgentDeviceInstance（设备实例）

设备实例表示 Device Context 中一个可见、可管理、可占用的具体设备。

AgentDeviceInstance MUST 由 Device Context 内的授权主体显式创建或纳管。设备提供方可以提交注册请求或能力声明，但不能绕过 Device Context 策略自行创建活跃设备实例。

| 字段 | 说明 |
|------|------|
| `device_instance_id` | 设备实例 ID |
| `device_type` | 设备类型 |
| `provider` | 设备提供方 |
| `context_id` | 登记所在的 Device Context（设备上下文） |
| `display_name` | 可见名称 |
| `state` | 当前状态 |
| `lease` | 当前租约，没有占用时为空 |
| `policy` | 权限、接手授权与风险策略 |
| `visibility` | Operator、监督方和审计方如何看到设备状态，见 6.4 |
| `admitted_by` | 纳管该设备实例的授权主体 |
| `admitted_at` | 设备实例纳管时间 |

### 6.3 DeviceLease（设备租约）

活跃设备不能无主。即使没有明确 Task（任务），也必须有 Session（会话）。

| 字段 | 说明 |
|------|------|
| `lease_id` | 租约 ID |
| `device_instance_id` | 被占用设备 |
| `lease_mode` | `task_bound`（绑定任务）或 `session_bound`（绑定会话） |
| `task_id` | 任务 ID，可为空 |
| `session_id` | 会话 ID，必须存在 |
| `current_operator` | 当前可产生外部副作用的操作者 |
| `requested_by` | 申请者 |
| `authorized_operators` | 允许接手该租约的 Operator 范围 |
| `expires_at` | 租约过期时间 |

`authorized_operators` 可以是显式主体列表、角色、策略表达式或 `context_members`（当前 Device Context 内成员）。v1 不允许使用不受 Device Context 限制的全局 `any` 作为默认授权范围。

`current_operator` 表示当前被授权通过该租约产生设备外部副作用的控制者；在 `exclusive` 模式下必须唯一。观察、监督、审批和审计权限不由 `current_operator` 表达，可以由 Device Context 策略分别授权，且可以同时存在多个主体。

DeviceLease 不只是记录字段，而是设备动作的当前授权边界。租约过期、释放、撤销或回收后，旧 lease 不得继续授权新的外部副作用。实现如果无法在 Device Provider 或 adapter 边界强制阻断旧 lease，MUST 在失败语义、DeviceVisibility 或 Audit 中暴露这个治理缺口，不能把旧 lease 后续操作表达为安全成功。

协议不要求 Agent 在操作前单独发起 lease 校验，也不定义统一 token（令牌）或凭证格式。

### 6.4 DeviceVisibility（设备可见性）

可见性是 Agent Device 区别于 Tool 和 Skill 的核心特征。v1 不要求所有设备都提供完整现场快照，但 MUST 提供结构化状态对象。

结构化状态对象至少包含：

| 字段 | 说明 |
|------|------|
| `device_instance_id` | 设备实例 ID |
| `device_type` | 设备类型 |
| `state` | 当前状态 |
| `lease_id` | 当前租约 ID，没有占用时为空 |
| `current_operator` | 当前可产生外部副作用的操作者 |
| `task_id` | 关联任务，可为空 |
| `session_id` | 关联会话 |
| `pause_capability` | 当前设备声明的暂停能力 |
| `needs_intervention` | 是否等待介入 |
| `observable_surface_ref` | 当前可观察现场引用，在等待介入或介入中状态必须存在 |
| `last_action_summary` | 最近一次关键操作摘要 |
| `updated_at` | 状态更新时间 |

Device Context 内被授权的 Operator、监督方和审计方 MUST 能查询该结构化状态。状态变更时主动通知或推送属于 MAY，v1 不要求实现。`observable_surface_ref` 可以指向截图、终端 buffer（缓冲区）、状态树、通话转写、文件预览、视频流或其他由 `device_type` 声明的现场呈现。

`observable_surface_ref` 必须是受 Device Context 策略治理的引用，而不是不受控的原始数据直出。

## 7. 状态机

本章同时包含 Core Protocol 和 Control Transfer Profile。`IDLE`、`OCCUPIED`、`RELEASING`、`ERROR`、`QUARANTINED` 和基础占用/释放动作属于 Core Protocol；`PAUSED_FOR_INTERVENTION`、`OPERATOR_INTERVENING` 以及介入相关动作属于 Control Transfer Profile。

### 7.1 状态

| 状态 | 说明 |
|------|------|
| `IDLE` | 空闲，可申请使用 |
| `OCCUPIED` | 已被占用 |
| `PAUSED_FOR_INTERVENTION` | Agent 暂停，等待其他 Operator 介入 |
| `OPERATOR_INTERVENING` | Operator 正在接手处理 |
| `RELEASING` | 正在释放 |
| `ERROR` | 设备异常 |
| `QUARANTINED` | 被隔离，不允许继续使用 |

### 7.2 动作

| 动作 | 说明 |
|------|------|
| `reserve_device` | 申请占用设备 |
| `attach_device` | 连接到已有设备会话 |
| `request_intervention` | Agent 请求其他 Operator 介入 |
| `acquire_intervention` | Operator 开始接手 |
| `commit_intervention` | Operator 完成处理并提交结果 |
| `abandon_intervention` | Operator 放弃处理，设备回到等待介入状态 |
| `release_device` | 释放设备 |
| `force_reclaim` | 管理员或策略强制回收 |

`request_intervention` MUST 携带 `intervention_context`，否则接手方无法理解设备现场。

`request_intervention` MUST 在状态切换时生成或刷新 `observable_surface_ref`，并将该引用纳入 `intervention_context`。该引用必须代表本次介入发生时的设备现场，不得指向更早状态的过期缓存。

`intervention_context` 至少包含：

| 字段 | 说明 |
|------|------|
| `reason` | 请求介入的原因 |
| `blocking_condition` | 当前阻塞点或风险点 |
| `last_safe_state` | 最后一个可恢复或可说明的安全状态 |
| `expected_operator_action` | 期望接手方完成的动作 |
| `resume_hint` | 归还控制权后 Agent 如何继续 |
| `observable_surface_ref` | 本次介入发生时的可观察现场引用 |
| `evidence_refs` | 支撑判断的证据引用 |

### 7.3 状态约束

- `OCCUPIED`（已占用）、`PAUSED_FOR_INTERVENTION`（等待介入）和 `OPERATOR_INTERVENING`（操作者介入中）状态 MUST 有有效 `DeviceLease`（设备租约）。
- `current_operator`（当前可产生外部副作用的操作者）在 `exclusive` 模式下任意时刻 MUST 唯一。
- `acquire_intervention`（开始接手）MUST 校验接手方是否匹配 `authorized_operators` 或 Device Context 策略。
- `exclusive`（排他）模式下，设备已被占用时新的 `reserve_device` MUST 直接返回 occupied/rejected（已占用 / 已拒绝），不得进入协议层 queue（队列）。
- 租约过期、释放、撤销或回收后，旧 Operator 后续操作 MUST 被视为 lease invalid（租约无效）、state conflict（状态冲突）或副作用状态未知，不得默认继续产生外部副作用。
- `force_reclaim`（强制回收）MUST 写入 Audit（审计）。
- `ERROR`（异常）状态下 MAY 允许只读观察，但 MUST 禁止继续产生外部副作用。

## 8. 暂停语义

本章属于 Device Profile 与 Control Transfer Profile 的交界。Core Protocol 只要求设备声明暂停能力；具体如何暂停由 Device Profile 定义，控制权转移时如何使用暂停能力由 Control Transfer Profile 约束。

`PAUSED_FOR_INTERVENTION` 不代表所有设备都能真正冻结。

协议必须声明设备的暂停能力：

| 暂停能力 | 说明 |
|----------|------|
| `hard_pause` | 设备状态可以基本冻结 |
| `soft_pause` | 设备停止接受新指令，但内部状态可能继续变化 |
| `no_pause` | 设备不能暂停，只能释放或转人工流程 |

v1 验证设备可以按 `soft_pause` 或部分场景 `hard_pause` 处理，但不能把某个具体设备的暂停语义写死到通用协议里。

## 9. Audit（审计）和 Artifact（产出物）

本章的 Audit 属于 Governance Profile。DeviceArtifact 不是 v1 Core Protocol 的必需对象，当前只保留语义，具体存储和路由可以由 Device Profile 或后续扩展定义。

### 9.1 Audit（审计）

只要设备动作产生 external side effect（外部副作用），必须强审计。

审计事件必须在 Device Context 可治理的边界产生。Agent Runtime 可以提供操作意图，Device Provider 可以提供执行结果和证据，但最终审计不能只依赖 Agent Runtime 或不受 Device Context 治理的外部 Provider 自报。

审计至少记录：

| 字段 | 说明 |
|------|------|
| `actor` | 操作者 |
| `device_instance_id` | 设备实例 |
| `lease_id` | 租约 |
| `task_id` | 任务 ID，可为空 |
| `session_id` | 会话 ID |
| `action` | 操作 |
| `side_effect_level` | 副作用级别 |
| `audit_boundary` | 产生审计事件的治理边界 |
| `summary` | 操作摘要 |
| `evidence_refs` | 截图、日志、转写、文件等证据引用 |

审计是协议底线，不是适配器自行决定是否存在的实现细节。具体设备动作的证据格式可以留在 adapter（适配器）层，但是否必须产生审计事件由协议约束。

动作执行状态可以表达为成功；但如果审计事件或证据不可确认，审计证据状态必须独立表达为不可确认，不能被动作执行成功覆盖。

`evidence_refs` 必须是受 Device Context 策略治理的引用，而不是不受控的原始证据直出。

### 9.2 DeviceArtifact（设备产出）

DeviceArtifact 表示设备操作产生的业务产出，不等同于审计。

v1 可以先不建立完整 DeviceArtifact 模型，但协议上必须保留这个语义。

| 字段 | 说明 |
|------|------|
| `artifact_id` | 产出 ID |
| `device_instance_id` | 来源设备 |
| `lease_id` | 来源租约 |
| `task_id` | 关联任务，可为空 |
| `session_id` | 关联会话 |
| `summary` | 产出摘要 |
| `artifact_type` | 截图、转写、命令结果、文件、消息记录等 |
| `routing_target` | 黑板、任务、文件、审计或讨论 |

v1 可以用 audit details（审计详情）临时承接，等第二种设备出现后再抽象独立模型。

## 10. 安全、隐私和风险

本章属于 Governance Profile。它约束所有会产生真实外部影响的 Agent Device 实现，不描述某个具体安全产品或审计存储的实现形态。

Agent Device 协议直接触达外部系统和真实业务，因此安全和隐私不是实现附录，而是协议核心。

| 风险 | v1 约束 |
|------|---------|
| 未授权设备进入治理边界 | AgentDeviceInstance MUST 由 Device Context 内授权主体显式创建或纳管 |
| Agent 绕过设备租约直接调用工具 | Agent Runtime MUST 只能通过有效 `DeviceLease` 操作设备 |
| 旧 lease 失效后继续操作 | 租约过期、释放、撤销或回收后，旧 lease 不得继续授权新的外部副作用 |
| 活跃设备无主 | Context Controller MUST 禁止 ownerless（无主）活跃设备 |
| 未授权主体接手设备 | `acquire_intervention` MUST 校验 `authorized_operators` 或 Device Context 策略 |
| Operator 接手后外部副作用责任不清 | `current_operator` MUST 在 Operator 接手和归还时更新 |
| 设备状态不可见 | 必须提供结构化 `DeviceVisibility` 状态对象 |
| 接手方看到过期现场 | `request_intervention` MUST 生成或刷新 `observable_surface_ref` |
| 外部副作用不可追溯 | 所有外部副作用 MUST 在 Device Context 可治理边界产生 Audit |
| 截图、日志、转写或现场引用包含敏感信息 | `observable_surface_ref` 和 `evidence_refs` MUST 受 Device Context 策略治理；访问控制、保留策略、脱敏和隔离规则由 Device Context 策略或 Device Profile 决定 |
| 设备异常后继续操作 | `ERROR` 和 `QUARANTINED` 状态 MUST 禁止产生新的外部副作用 |

## 11. 兼容性和扩展

本章约束 Core Protocol 与 Device Profile 的演进关系。新增设备类型优先进入 Device Profile；只有跨设备复用、且影响互操作的字段才进入 Core Protocol。

v1 的扩展原则：

- 新设备类型 MUST 先声明 `AgentDeviceType`（设备类型）。
- 设备特有字段 SHOULD 留在 adapter（适配器）层，不进入核心协议。
- 协议核心字段新增 SHOULD 向后兼容。
- 状态机新增状态 MUST 定义可进入条件、可退出动作和审计要求。
- 第二种设备出现前，不抽象通用 Preflight（设备预检）和通用 Artifact（产出物）存储。

## 12. 验收标准

本章按合规级别验收。Level 1 验收 Core Protocol + Governance Profile；Level 2 在 Level 1 基础上验收 Control Transfer Profile。具体设备的端到端验证属于对应 Device Profile。

合规判断基于实现对 Agent 暴露的 contract surface（契约表面）：API、CLI、Skill、Tool、MCP 返回或文档说明是否表达了对应 Level 要求的设备实例、租约、可见性、语义返回、审计引用、失败语义和控制权转移能力。协议不定义统一测试框架，也不试图证明实现内部是否真实执行；Agent Device 是约定优先的互操作协议，合规声明以暴露给 Agent 的契约是否满足本规范为基础。

### 12.1 Level 1 Device Governance

Level 1 至少用以下标准判断：

1. 设备实例只能由 Device Context 内授权主体显式创建或纳管。
2. Agent 可以通过协议申请并占用一个外部设备；v1 可以用 BrowsePilot browser（浏览器）作为验证样例，但验证目标不绑定浏览器。
3. 设备占用后能看到明确 `DeviceLease`（设备租约）。
4. 设备状态能以结构化 `DeviceVisibility` 形式被授权方查询。
5. 设备动作结果能表达操作意图、结果语义、状态变化、失败原因、外部副作用和审计证据，并在可判断时表达下一步建议；失败、拒绝、部分完成或状态未知时能表达最小失败语义。
6. 设备可以释放，并回到 `IDLE` 状态，或被超时/策略回收。
7. 全流程能在 Audit（审计）中还原关键操作者、设备、租约、会话、动作和证据。

### 12.2 Level 2 Control Transfer

Level 2 必须先满足 Level 1，并额外满足以下标准：

1. Agent 可以请求其他 Operator 介入，并进入 `PAUSED_FOR_INTERVENTION` 状态。
2. `request_intervention` 携带足够接手方理解的 `intervention_context`。
3. `request_intervention` 生成或刷新代表当前现场的 `observable_surface_ref`。
4. Operator 可以通过查询 `DeviceVisibility` 发现设备进入等待介入状态。
5. Operator 可以在授权策略允许时接手同一设备现场。
6. Operator 可以提交处理结果并归还或结束控制权。
7. Agent 可以恢复执行，或设备可以进入可释放状态。

## 13. v1 MUST / SHOULD / MAY

本章按合规级别列出规范要求。Level 1 MUST 对应 Core Protocol + Governance Profile；Level 2 MUST 对应 Control Transfer Profile 的新增要求。

### Level 1 MUST（必须）

- 必须有 AgentDeviceInstance（设备实例）。
- 必须由 Device Context 内授权主体显式创建或纳管 AgentDeviceInstance。
- 必须有排他租约。
- 必须支持 `task_bound`（绑定任务）和 `session_bound`（绑定会话）两种归属。
- 租约失效后，旧 Operator 后续操作不得继续被视为合法外部副作用。
- 必须禁止 ownerless（无主）活跃设备。
- 必须提供结构化 `DeviceVisibility`。
- 必须提供 Agent-readable semantic contract，不得只返回空泛成功、失败或原始日志。
- 失败、拒绝、部分完成或状态未知时，必须表达最小失败语义中的 MUST 维度，不要求统一错误码；下一步动作按 SHOULD 处理。
- 必须对 Agent 外部副作用强审计，并在 Device Context 可治理边界产生审计事件。
- 必须把具体设备的私有动作留在对应 adapter（适配器）。
- 排他租约竞争必须直接 reject，不进入协议层 queue。

### Level 2 MUST（必须）

- 必须满足 Level 1 MUST。
- 必须支持 `PAUSED_FOR_INTERVENTION`。
- 必须支持控制权转移语义；如果实现提供 Human 介入能力，则 Human 必须作为授权 Operator 参与同一接手和归还机制。
- 必须要求 `request_intervention` 携带 `intervention_context`。
- 必须要求 `request_intervention` 生成或刷新 `observable_surface_ref`。
- 必须在 `acquire_intervention` 时校验接手方授权。

### SHOULD（应该）

- 应该支持 `abandon_intervention`。
- 应该支持 lease timeout（租约超时）。
- 应该支持 force reclaim（强制回收）。
- 应该生成最小 artifact summary（产出摘要）。
- 应该把 `pause_capability` 作为设备类型能力声明。
- 治理类动作应该尽量具备重复调用安全性，避免 Agent 或网络重试造成重复租约、重复介入或重复归还。

### MAY（可以）

- 可以先不做通用 Preflight（设备预检）。
- 可以先不做完整 DeviceArtifact（设备产出）模型。
- 可以先不做 Push state stream（状态流推送）。
- 可以先不做通用事件协议。

## 14. v1 决议和 v2 待讨论

### 14.1 v1 决议

| 主题 | v1 决议 |
|------|---------|
| 协议边界和命名 | v1 按 Core Protocol、Governance Profile、Control Transfer Profile、Device Profile 分层；Core Protocol 只保留最小互操作内核。`Device Context` 作为治理边界足够，v1 不进一步拆分 `context_id` 和 `owner_scope`。保留 `Agent Device` 命名，并在摘要中明确它不是“Agent 的设备” |
| 互操作契约 | 不定义统一 request/response schema，也不定义通用版本协商协议。v1 定义 Agent-readable semantic contract，允许目标平台通过 CLI、Tool、Skill、MCP、HTTP API、SDK 或其他入口表达同一组语义 |
| 失败、幂等和重试 | 不定义统一错误码或错误返回结构，也不作为后续版本方向；不定义统一幂等模型，也不要求所有动作可重试。通用协议层只要求最小失败语义，确保 Agent 能判断执行状态、副作用状态、重试安全性、失败类别和审计可靠性；这些维度允许表达未知、未确认或无法分类，下一步动作只在可判断时 SHOULD 提供。治理类动作 SHOULD 尽量具备重复调用安全性；业务副作用动作必须通过重试安全性表达是否可重试或未知 |
| 租约和并发 | 不定义统一 fencing token、heartbeat、renew API 或凭证格式，也不要求 Agent 操作前单独校验 lease。v1 只定义租约有效性边界：旧 lease 失效后不得继续授权新的外部副作用；具体阻断机制由平台或 Device Profile 实现。v1 并发模型只支持 `exclusive`，Agent-Agent 竞争直接 reject，不进入 queue |
| 状态和发现 | v1 规定核心状态、动作和状态约束；具体状态转移路径与失败落点由实现或 Device Profile 约束，并通过 Agent-readable semantic contract 表达状态变化和失败语义。v1 采用 query-first（查询优先）模型，要求 `DeviceVisibility` 可查询；不要求通用事件协议、Push state stream、webhook、SSE、WebSocket 或 queue |
| 能力和准入 | 设备实例必须由 Device Context 内授权主体显式创建或纳管，设备提供方不能自注册为活跃实例。Device Provider 必须声明 `Device Type`、`Device Profile` / 合规级别和关键能力边界；能力不可用时通过 Agent-readable semantic contract 表达不可用原因或降级语义。`pause_capability` 由设备声明；Preflight 留给 adapter，不进入核心协议字段 |
| 控制权转移 | v1 分为 Level 1 `Device Governance` 和 Level 2 `Control Transfer`；Level 2 是完整验证目标。`current_operator` 只表示当前可产生外部副作用的控制者；观察、监督、审批和审计权限由 Device Context 策略分别授权，不进入 v1 角色模型。`acquire_intervention` 必须校验 `authorized_operators` 或 Device Context 策略；默认授权范围不能是不受上下文约束的全局 `any` |
| 现场、证据和产出 | `request_intervention` 必须生成或刷新 `observable_surface_ref`，不能使用过期现场引用。`observable_surface_ref` 和 `evidence_refs` 必须是受治理引用；若引用因权限、保留或脱敏策略不可访问，返回语义必须表达受限、已过期、已脱敏或不可用。DeviceArtifact 保留语义，v1 暂不要求完整模型 |

### 14.2 v2 待讨论

- 共享或池化设备并发模型。
- 协议层 queue、优先级、抢占和等待超时。
- Core Protocol 语义契约的机器可测试化。
- 通用 Preflight 字段。
- 完整 DeviceArtifact 模型和跨设备产出路由。
- Level 1 / Level 2 之外是否需要更细的合规剖面。
- 多 Device Context 之间的设备迁移、托管和审计继承。

## 15. 参考资料

- RFC 7322（RFC 风格指南）：https://www.rfc-editor.org/rfc/rfc7322.html
- W3C Variability in Specifications（规范可变性）：https://www.w3.org/TR/spec-variability/
- Kubernetes KEP Template（Kubernetes 增强提案模板）：https://github.com/kubernetes/enhancements/blob/master/keps/NNNN-kep-template/README.md

## 16. 修订记录

| 版本 | 变更 |
|------|------|
| v0.1-v0.3 | 建立内部草案、参考规范结构、目录、状态、范围、术语、一致性模型和修订记录 |
| v0.4-v0.10 | 去除 Office、浏览器和产品化默认假设，收敛外部影响表述，并降低 MCP、Skill、Tool Schema、Agent Device 等术语重复解释 |
| v0.11-v0.13 | 补充 Control Transfer Profile、DeviceVisibility、intervention_context、审计边界、Level 1 / Level 2 合规级别，并按 Core Protocol、Governance Profile、Control Transfer Profile、Device Profile 重组协议边界 |
| v0.14-v0.19 | 建立 Agent-readable semantic contract、最小失败语义、非统一错误模型、下一步动作 SHOULD、未知状态表达，以及幂等和重试的失败语义边界 |
| v0.20-v0.23 | 明确租约有效性边界、不定义统一 fencing token / heartbeat / renew API、不定义完整状态转换表，并采用 query-first 状态发现模型 |
| v0.24-v0.26 | 补充能力发现与拒绝语义、不定义通用版本协商和统一 token / 凭证格式，并明确成功 / 失败判断必须绑定语义维度 |
| v0.27-v0.30 | 明确 current_operator 边界、证据和现场引用治理、contract surface 合规判断，以及 v1 concurrency_model 只允许 exclusive |
| v0.31 | 合并修订记录，保留阶段性演进脉络 |
| v0.32 | 合并 v1 决议，改为主题化记录 |
