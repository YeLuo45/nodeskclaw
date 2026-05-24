# Runtime Onboarding Checklist（运行时接入检查清单）

本清单用于接入新的 AI employee runtime（AI 员工运行时）。目标是让每个 runtime（运行时）在注册、能力声明、配置、备份和前端展示上都有明确契约，避免继续继承 OpenClaw（默认员工引擎）的隐式语义。

## 1. RuntimeSpec（运行时规格）注册

新增 runtime（运行时）时，必须显式填写以下字段，不允许依赖默认值：

| 字段 | 说明 |
| --- | --- |
| `runtime_id` | runtime（运行时）唯一标识符 |
| `config_rel_path` | 主配置文件相对路径 |
| `config_format` | 配置格式，例如 `json`（JSON 配置）或 `yaml`（YAML 配置） |
| `channels_section_key` | channel（渠道）配置所在字段名 |
| `field_naming` | 配置字段命名风格，例如 `camelCase`（小驼峰） |
| `data_dir_container_path` | 容器内数据根目录 |
| `skills_dir_rel` | skill（技能）目录相对路径 |
| `scripts_dir_rel` | script（脚本）目录相对路径 |
| `gateway_port` | gateway（网关）端口 |
| `backup_dirs` | backup（备份）必须包含的目录 |
| `capabilities` | product capabilities（产品能力矩阵） |

`RuntimeSpec`（运行时规格）注册时会校验关键字段。漏填关键字段应该在启动或测试阶段暴露，而不是静默继承 OpenClaw（默认员工引擎）路径。

## 2. Product Capabilities（产品能力矩阵）

每个 runtime（运行时）必须完整声明以下 capability（能力）：

| Capability（能力） | 说明 |
| --- | --- |
| `genes` | 是否支持 Gene（基因）安装和管理入口 |
| `evolution_log` | 是否展示 evolution log（进化日志） |
| `llm_config` | 是否支持 LLM config（模型配置） |
| `channel_config` | 是否支持 channel config（渠道配置） |
| `channel_plugin_discovery` | 是否支持 channel plugin discovery（渠道插件发现） |
| `repo_channel_sync` | 是否支持 repo channel sync（仓库渠道同步） |
| `npm_channel_install` | 是否支持 npm channel install（npm 渠道安装） |
| `upload_channel_plugin` | 是否支持 upload channel plugin（上传渠道插件） |
| `gateway` | 是否提供 gateway（网关） |
| `health_endpoint` | 是否提供 health endpoint（健康检查端点） |
| `config_endpoint` | 是否提供 config endpoint（配置端点） |
| `web_ui` | 是否提供 Web UI（网页界面） |
| `backup` | 是否支持 backup（备份） |
| `runtime_config_patch` | 是否支持 runtime config patch（运行时配置补丁） |
| `tool_allow` | 是否支持 tool allowlist（工具允许列表） |

声明为 `true` 的 capability（能力）必须有真实实现。声明为 `false` 的 capability（能力）必须通过 `UnsupportedCapabilityError`（不支持能力错误）或 warnings（警告）明确表达，不允许静默忽略。

## 3. Adapter（适配器）要求

`GeneInstallAdapter`（基因安装适配器）需要明确实现或拒绝以下能力：

| 方法 | 要求 |
| --- | --- |
| `deploy_skill` | 支持时写入 runtime-native skill（运行时原生技能）目录 |
| `allow_tools` | 不支持 `tool_allow` 时必须返回 warnings（警告）或抛 `UnsupportedCapabilityError` |
| `deploy_scripts` | 支持时写入 runtime-native script（运行时原生脚本）目录 |
| `apply_config` | 不支持 `runtime_config_patch` 时必须返回 warnings（警告）或抛 `UnsupportedCapabilityError` |
| `invalidate_cache` | 支持时清理 runtime（运行时）缓存 |
| `remove_skill` | 支持时删除 runtime-native skill（运行时原生技能） |
| `post_remove_cleanup` | 支持时执行删除后的清理 |

`RuntimeConfigAdapter`（运行时配置适配器）需要负责配置读取、写入、channel（渠道）提取和 channel（渠道）合并。

Channel plugin（渠道插件）能力第一阶段通过 capability gate（能力门禁）表达。runtime（运行时）不支持时，相关操作必须返回 `UNSUPPORTED_CAPABILITY`（不支持能力）。

## 4. API（接口）与 Frontend（前端）

`/engines` API（引擎列表接口）必须返回完整 `capabilities`（能力矩阵）。

Frontend（前端）消费规则：

1. 优先使用 `/engines[].capabilities`（后端能力声明）。
2. 旧后端或接口异常时，fallback（兜底）到最小安全能力集。
3. 未知 runtime（运行时）不能 fallback（兜底）到 OpenClaw（默认员工引擎）。
4. UI（用户界面）入口显隐必须由 capability（能力）驱动。

## 5. Gene Manifest（基因清单）兼容性

新增 runtime（运行时）时，需要明确支持哪些 Gene manifest（基因清单）字段：

- `runtime_config`（运行时配置）
- `openclaw_config`（OpenClaw 专用配置）
- `tool_allow`（工具允许列表）
- `scripts`（脚本）
- `skill`（技能）

对于不支持的字段，安装结果必须返回 warnings（警告）或 structured unsupported（结构化不支持信息），说明哪些字段没有生效。

## 6. Test（测试）要求

每个新增 runtime（运行时）至少补充以下测试：

1. `RuntimeSpec`（运行时规格）关键字段断言。
2. capability matrix（能力矩阵）断言。
3. `/engines` API（引擎列表接口）响应断言。
4. unsupported capability（不支持能力）行为断言。
5. OpenClaw（默认员工引擎）回归测试，确保新增 runtime（运行时）不改变既有行为。

## 7. PR（合并请求）要求

接入新 runtime（运行时）的 PR（合并请求）需要在描述里逐条回应本清单：

- RuntimeSpec（运行时规格）字段是否完整。
- capabilities（能力矩阵）是否完整。
- unsupported（不支持能力）是否可见。
- `/engines` API（引擎列表接口）是否返回能力。
- Frontend（前端）是否正确消费能力。
- 测试是否覆盖 capability（能力）和 OpenClaw（默认员工引擎）回归。

