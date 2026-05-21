# DeskClaw 官网与产品视觉风格参考

## 目标

这份文档用于让 DeskClaw 官网、用户门户和管理后台保持同一套产品气质。它不是一份完整设计系统，也不是具体页面线框图，而是后续写官网、Portal、Admin、产品文档和设计稿时必须先读取的风格上下文。

核心判断标准：用户看到官网后，再进入产品，不应该感觉进入了另一个品牌；但官网和产品也不需要使用完全相同的页面配色。官网负责解释品牌和产品心智，产品负责承载真实经营操作。

## 依据来源

- `README.md`、`README.zh-CN.md`：DeskClaw 的公开定位是人与 AI 共同经营组织的平台，核心概念包括 Cyber Workspace、共享黑板、任务委派、Gene System 和 Elastic Scale。
- `AGENTS.md`、`CLAUDE.md`：产品侧要求 UI 服务于“人和 AI 共同经营”，图标统一使用 `lucide-vue-next`，禁止 emoji，用户可见文案需要可解释、可操作。
- `nodeskclaw-portal/src/styles/globals.css`：Portal 当前使用暗色经营界面，基础 token 包括 `#0a0a0a` 背景、`#111111` 卡片、`#a78bfa` 主色、`#9ca3af` 弱文本。
- `ee/nodeskclaw-frontend/src/styles/globals.css`：Admin 当前同样是暗色控制台，半径约 6px，并有 success、warning、error、info 等状态色。
- `nodeskclaw-portal/src/views/WorkspaceView.vue`、`nodeskclaw-portal/src/components/hex2d/Workspace2D.vue`、`nodeskclaw-portal/src/components/blackboard/BlackboardOverlay.vue`：产品真实核心界面是 Cyber Workspace、六边形拓扑、共享黑板、任务与状态面板。
- `../nodeskclaw-site/src/styles.css`、`../nodeskclaw-site/src/main.ts`、`../nodeskclaw-site/src/content.ts`：官网当前风格是高对比、粗边框、纸面网格、黄色品牌面和运营看板式首屏。

## 设计北极星

DeskClaw 的视觉不应该像普通 AI 聊天工具，也不应该像泛 SaaS 模板。它要表达的是：

- 人类做判断，AI 做执行。
- 团队和 AI partners 在同一个 Cyber Workspace 中工作。
- 共享黑板、任务、成果、文件和审批是持续流转的经营对象。
- Gene System 是 AI operating capabilities 的扩展方式。
- 产品是工程化、可信赖、可运营的，不是玩具感的 AI 展示页。

## 风格定位

推荐关键词：

- operational
- engineering
- high-contrast
- data-dense
- shared workspace
- blackboard
- human judgment
- AI execution
- trustworthy

不要走的方向：

- 普通渐变 SaaS landing page
- 大面积紫蓝渐变和漂浮光球
- 只有聊天框的 AI 工具视觉
- 过度圆润、玩具化、卡通化
- 纯控制台工具感，完全看不出人和 AI 的关系
- 把官网做成产品登录页或实例管理入口

## 官网与产品的分工

官网是对外品牌表达层，应更强烈、更可记忆：

- 首屏必须让 `DeskClaw` 成为第一视觉信号。
- 可以使用浅色纸面、黄色品牌块、粗黑线和产品抽象场景。
- 要用真实产品概念构成视觉资产，例如 Cyber Workspace、黑板、任务卡、operator、成果卡。
- 不要把产品解释藏在后面，也不要做空泛 hero。

产品是高频工作层，应更克制、更密集：

- 保持暗色经营界面，优先服务长时间操作和信息密度。
- 使用 panel、drawer、toolbar、tabs、table、kanban、timeline 和拓扑画布组织信息。
- 页面结构要支持反复扫描、比较、审批和协作，而不是讲故事。
- 允许品牌色点亮关键状态，但不要让大面积品牌黄色干扰真实操作。

两者的统一点不是“同一张皮肤”，而是同一套产品语言：黑板、拓扑、任务、成果、状态、AI partner、人类确认、Gene 能力扩展。

## 色彩原则

### 官网公开表达

| 用途 | 建议值 | 使用方式 |
| --- | --- | --- |
| Paper | `#f7f5ee` | 官网背景、纸面网格底色 |
| Surface | `#ffffff` / `#fafafa` | 卡片、工具面板、内容容器 |
| Ink | `#1a1a1a` / `#000e1a` | 主文字、粗边框、按钮底 |
| Brand Yellow | `#ffcb00` | 首屏品牌面、重点 CTA、成果卡 |
| Blue | `#2f6fed` | AI / 流动 / 系统动作 |
| Green | `#168f55` | 已连接、成功、运行中 |
| Red | `#d93f32` | 等待确认、风险、阻塞 |

官网可以大胆使用黄色和黑色粗边框，但要控制信息层级，避免满屏高饱和导致疲劳。

### 产品经营界面

| 用途 | 当前值 | 使用方式 |
| --- | --- | --- |
| Background | `#0a0a0a` | 应用背景 |
| Card / Panel | `#111111` | 面板、卡片、侧栏 |
| Popover | `#1a1a1a` | 弹窗、浮层 |
| Primary | `#a78bfa` | 主操作、选中态、焦点态 |
| Muted Text | `#9ca3af` | 次级文本 |
| Success | `#4ade80` | 运行中、成功 |
| Info | `#22d3ee` / `#60a5fa` | 信息流、连接、蓝色强调 |
| Warning | `#fbbf24` | 等待、注意、需要处理 |
| Error | `#f87171` | 失败、阻塞、危险 |

产品侧不要直接照搬官网的大面积浅色和品牌黄。更合理的做法是：产品保持暗色密集操作底盘，黄色只用于提示、重要成果、等待确认或品牌化空状态。

## 几何与组件语言

### 半径

- 产品主界面半径控制在 6-8px。
- 官网内容卡片和工作区抽象面板使用 6-8px。
- pill 形状只用于状态、筛选、badge、operator 标签和轻量工具开关。
- 不要把所有容器都做成大圆角，也不要卡片套卡片。

### 边框与阴影

- 官网可以使用 2-3px 深色边框和硬阴影，形成“工程纸面 + 经营白板”的记忆点。
- 产品内使用低透明度边框，例如 `border-border`、`border-white/8`，避免长时间使用疲劳。
- 产品的 hover、focus、selected 状态要清楚，但不应该靠过强阴影堆叠。

### 图标

- 产品统一使用 `lucide-vue-next`。
- 官网当前使用 `lucide`，保持线性图标体系即可。
- 不使用 emoji、HTML 符号或装饰字符充当图标。
- 工具按钮优先使用图标；不熟悉的图标需要有 tooltip 或 title。

### 卡片和面板

- 卡片只用于独立对象：任务、成果、实例、成员、指标、事件。
- 页面级分区不要都包成卡片，产品页面优先用 toolbar + content area + panel/drawer。
- 产品核心工作区不要像 landing page；官网核心视觉不要像表格后台。

## 布局原则

### 官网

- 首屏应该直接出现 `DeskClaw`，并露出 Cyber Workspace / blackboard / task delegation 的视觉线索。
- 页面需要有下一屏内容露出，避免首屏像封面海报。
- 适合使用一块强品牌区域 + 一块产品抽象场景，而不是左右均分的普通 SaaS hero。
- 信息块要围绕问题、工作流、能力、治理、开源社区，不要扩展到产品控制台功能。

### 产品

- Workspace 是产品心智核心，画布、黑板和任务状态应是主角。
- Header、toolbar、side panel 和 drawer 要紧凑，不占用核心操作空间。
- 数据密集区域优先考虑扫描效率：表格、分组、状态点、短标签、固定操作位。
- 空状态、加载态、错误态必须可操作，告诉用户下一步做什么。

## 动效原则

动效应该服务于“协作流动”和“状态变化”，而不是装饰。

可以使用：

- 拓扑节点选中 ring。
- AI partner 思考 / 运行状态的轻量脉冲。
- 消息流、任务流、协作流的路径动画。
- drawer、panel、tabs 的短过渡。

避免使用：

- 大面积背景漂浮光球。
- 只为炫技的长动画。
- 影响读取表格和任务状态的持续运动。
- 没有 `prefers-reduced-motion` 兜底的动画。

## 文案语气

中文建议使用：

- DeskClaw
- 人与 AI 共同经营
- 赛博办公室（Cyber Workspace）
- 共享黑板 / 共享经营看板
- AI 经营伙伴 / AI partners
- 任务委派
- 成果卡
- Trust 与审批
- Gene System / 基因系统

英文建议使用：

- DeskClaw
- Co-operate with AI.
- Human-AI co-operation
- Cyber Workspace
- shared blackboard
- AI partners
- task delegation
- deliverable card
- Gene System
- elastic scale

避免：

- 把 DeskClaw 简化成普通 AI chat。
- 官网主品牌使用 `NoDeskClaw`。
- 使用 `Portal` 描述官网。
- 写入未被产品或代码支撑的能力。
- 在公开文案泄露私有 EE 实现细节。

## 落地检查清单

做官网或产品 UI 前，先逐项检查：

- 这个页面是否服务于“人和 AI 共同经营”？
- 用户是否能看出人类判断、AI 执行、共享黑板或任务流转之间的关系？
- 官网首屏是否让 `DeskClaw` 成为第一视觉信号？
- 产品页面是否保持高频操作所需的信息密度？
- 图标是否来自 lucide，而不是 emoji 或装饰符号？
- 半径是否控制在 6-8px，pill 是否只用于状态或轻量标签？
- 卡片是否只承载独立对象，而不是页面分区套页面分区？
- 状态色是否有明确语义：成功、信息、等待、错误？
- 加载、空状态、错误和权限不足是否给出下一步？
- 文案是否与 README 中的公开产品事实一致？
- 是否避免把 EE 私有实现写进公开页面？

## 当前建议

官网可以保留更强烈的浅色纸面和黄色品牌识别，用来建立第一印象；产品侧不建议整体改成官网浅色风格。更稳妥的统一路径是：

1. 保留产品暗色经营底盘。
2. 把官网的粗边框、低圆角、黑板/任务/成果对象语言逐步带入产品关键界面。
3. 把产品里的 Cyber Workspace、hex topology、blackboard 和 task 状态作为官网视觉资产来源。
4. 在产品空状态、引导页、成果卡、审批等待等低频但关键位置使用品牌黄色。
5. 后续如果要重做产品视觉，先抽出共享 token，而不是逐页手动改色。
