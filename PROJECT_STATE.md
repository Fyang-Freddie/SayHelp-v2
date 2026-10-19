# SayHelp 项目状态（单一入口）

> 最后更新：2026-10-19
> 这是「我们现在走到哪了」的唯一入口。细节见文末文件索引。

## 项目
从 `prompt.txt`（62KB 最终需求）开发**可运行、可验收的电商智能客服系统 SayHelp**。
技术栈：Python/FastAPI/SQLAlchemy + MySQL(Docker) + Milvus 2.5 + LangChain/LangGraph + BGE-M3 + bge-reranker-v2-m3 + 原生 HTML/CSS/JS + RoBERTa-wwm-ext(主题分类微调) + Langfuse。

## 已锁定决策（2026-10-19 确认）
| # | 决策点 | 结论 |
|---|---|---|
| D1 | 身份/账号 | 本地账户 + JWT；users/roles 表；admin + customer 映射真实客户ID（C0001–C0030） |
| D2 | 转人工 | 内置真实人工工作台（role=agent 后台接单接管会话，身份如实展示） |
| D3 | 写能力 | 仅 `create_ticket` 为真实写工具；退款=表单预览，明确提示未真实提交 |
| D4 | 模型角色 | 主力/指代消解/扩写/摘要/裁判 统一 `deepseek-flash`；jev 独立 |
| D5 | 嵌入/精排 | 本地自托管：BGE-M3 与 bge-reranker-v2-m3 各一进程 |
| D6 | 训练切分 | 保留现状 78.8/10.8/10.4%，如实记录 |
| D7 | 「其他」标签 | 单独成类，不与具体标签共存 |
| D8 | Milvus/Langfuse | Docker 自托管（Milvus 2.5 standalone 复用已给 MinIO 凭据） |

## 待补配置（阻塞项）
| 项 | 影响 | 状态 |
|---|---|---|
| jev 端点/协议/密钥 | P3 意图节点 | ✅ key=`TYPESAFE_API_KEY`（已在 .env）；base=`https://api.typesafe.ai`；协议=System One `/v1/systemone`（结构化判研，非 chat） |
| GPU 显存 | P7 sft 训练 | ✅ 16GB 5070 Ti（够 RoBERTa 全参微调） |
| Docker daemon 未启动 | MySQL/Milvus/Langfuse | 需启动 Docker Desktop |
| Context7 MCP 不可用 | 库接口核实 | 用 WebFetch/WebSearch 替代并如实标注 |

## 下一步
1. 用户审阅架构契约 `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md`。
2. 审阅通过后 → 写实施计划（Superpowers writing-plans）→ 开始 P0（git init、工程骨架、.env.example、迁移工具、真实数据导入）。
3. 并行推进不受阻塞项影响的底座工作。

## 文件索引
| 路径 | 内容 |
|---|---|
| `prompt.txt` | 原始最终需求（只读） |
| `knowledge_db/*.md` | 真实业务数据（订单/物流/政策/售后/商品/退款原因，只读） |
| `sft_dataset/*.jsonl` | 真实微调数据（17 类多标签，只读） |
| `.env` | 现有配置（含真实密钥，勿提交） |
| `dev-notes/00-inventory-and-plan.md` | 现状清单 + 问题 + 流程图 + 分阶段计划 |
| `docs/superpowers/specs/2026-10-19-sayhelp-architecture.md` | 架构契约（数据模型/契约/工作流） |
| `PROJECT_STATE.md` | 本文档 |
| `dev-notes/ch01.md`—`ch10.md` | 待建：按能力归属实时追记的需求追踪与开发记录 |
