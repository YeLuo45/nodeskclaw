---
name: release-deploy
description: >-
  DeskClaw 发版与部署流程助手。当用户提到"发版"、"release"、"部署"、"deploy"、
  "promote"、"上线"、"发 beta"、"发 pre-release"时触发。根据用户意图生成完整的
  可执行命令，包含前置检查结果和操作确认清单。
---

# DeskClaw 发版与部署

## 触发后的工作流程

### 1. 解析用户意图

从用户消息中提取以下参数：

| 参数 | 如何判断 | 默认值 |
|---|---|---|
| 操作类型 | release / deploy / promote | 必须明确 |
| 版本号 | 用户指定（如 v0.9.8-beta.1） | release/promote 必须指定 |
| CE/EE | 用户说"EE"或"含 admin" → `--ee` | CE（不加 --ee） |
| 镜像源 | 用户说"国内源"/"mirrors"/"cn" → `--mirrors cn` | 不加 |
| 目标环境 | staging（默认）/ 生产（`--prod`） | staging |
| 部署目标 | all / backend / admin / portal / proxy | all |
| 仅发版 | 用户说"只发版不部署" → 只运行 `release.sh create` | 否 |
| 仅部署 | 用户说"不重新构建" → 只运行 `deploy.sh deploy --tag <version>` | 否 |
| 本地分支部署 | 用户说"当前分支/本地分支部署" → 使用分支用途镜像 tag，禁止创建 git tag/GitHub Release | 否 |

注意："部署当前分支"、"部署本地分支"只表示把当前工作树构建为镜像并部署，不等于发版授权。除非用户明确要求"发版"、"release"、"创建 tag"或"GitHub Release"，不得调用 `deploy/release.sh create`，不得创建或推送 git tag，不得创建 GitHub Release。

### 2. 前置检查（只读命令，直接执行）

```bash
git status --short                        # 未提交变更
git tag -l '<version>*'                   # tag 是否已存在
git log --oneline -1                      # 最新 commit
```

EE 模式额外检查：
```bash
ls -d ee/ 2>/dev/null                     # ee/ 目录存在
cd ee && git status --short               # EE 仓库状态
```

### 3. 输出操作确认清单

按以下格式输出。如果用户已经在同一请求中明确授权 AI 执行发版/部署，则可以直接执行；否则只给出可粘贴命令，等用户自己运行。

```
**发版目标**：<版本号> <CE/EE> <Pre-release/正式>

**当前状态**：
- CE 仓库：<干净/有未提交变更>
- EE 仓库：<干净/有未提交变更>（仅 EE 模式）
- 最新 commit：<hash> <message>
- tag <版本号>：<不存在/已存在>

**即将执行**：

| 步骤 | 命令 | 说明 |
|---|---|---|
| 1 | `./deploy/release.sh ...` | ... |
| 2 | `./deploy/deploy.sh ...` | ...（如有） |

**镜像分发**：
- backend/portal/proxy → <PUBLIC_REGISTRY 或 REGISTRY>
- admin → <REGISTRY>（仅 EE）

未授权 AI 执行时，请用户在终端运行以上命令。
```

**重要**：默认不得通过 Shell 工具运行 `deploy/release.sh`、`deploy/deploy.sh`、`deploy/init.sh`。只有用户在同一请求中明确授权 AI 执行发版/部署时，才允许运行；执行时必须显式带上 `--context` 和目标环境标志（`--staging` / `--prod`）。

## 常见场景速查

### 场景 A：EE Pre-release（如本次 v0.9.8-beta.1）

```bash
# 1. 发版（构建镜像 + git tag + GitHub Pre-release）
./deploy/release.sh create <version> --ee --mirrors cn

# 2. 部署到 staging（可选）
./deploy/deploy.sh deploy all --tag <version> --ee --staging --context <CTX>
```

### 场景 B：CE Pre-release

```bash
./deploy/release.sh create <version> --mirrors cn
```

### 场景 C：日常部署到 staging

```bash
./deploy/deploy.sh deploy all --tag <version> --staging --context <CTX>       # CE
./deploy/deploy.sh deploy all --tag <version> --ee --staging --context <CTX>  # EE
./deploy/deploy.sh deploy backend --tag <version> --staging --context <CTX>   # 只部署后端
```

### 场景 D：部署指定版本（不重新构建）

```bash
./deploy/deploy.sh deploy all --tag <version> --staging --context <CTX> # staging
./deploy/deploy.sh deploy all --tag <version> --prod --context <CTX>    # 生产
```

### 场景 E：正式发布（staging 转生产）

```bash
./deploy/deploy.sh deploy all --tag <version> --prod --context <CTX>
./deploy/release.sh finalize <version>
```

## CLI 参数速查

| 参数 | 作用 | 适用命令 |
|---|---|---|
| `--ee` | EE 模式（含 admin + ee/ 代码注入） | deploy, release |
| `--mirrors cn` | 国内镜像源加速构建 | deploy, release |
| `--prod` | 部署到生产环境 | deploy |
| `--tag <tag>` | 指定镜像标签 | deploy |
| `create` | 构建推送镜像、创建 git tag 和 GitHub Pre-release | release.sh |
| `finalize` | 将 GitHub Release 标记为正式版 | release.sh |
| `--skip-proxy` | 跳过 proxy 组件 | deploy, release |
| `--no-cache` | Docker 不使用缓存 | deploy, release |
| `--force` | 跳过 Secret 差异确认 | init |

## 镜像仓库规则

- `get_component_registry("admin")` → `$REGISTRY`（私有，EE 专用）
- `get_component_registry("其他")` → `$PUBLIC_REGISTRY`（公开）或回退 `$REGISTRY`
- 配置位于 `deploy/.env.local`（不进 git）

## Release Note / 公告称呼规则

- 对外 Release Note、群聊公告和发布摘要中，首次出现必须写成“DeskClaw 团队版 <version>”。
- 禁止写成“个人版”，也禁止省略“团队版”导致对外产品定位错误。
- 后文如需简称，必须先完整出现一次“DeskClaw 团队版”。
