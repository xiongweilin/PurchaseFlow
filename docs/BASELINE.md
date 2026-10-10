# 开发基线

记录时间：2026-10-10（Asia/Shanghai）

## 工作区与隔离

- 项目：独立 PurchaseFlow 工作区，初始分支 main，开始时无提交、无源文件。
- 远程未配置。GitHub 上建议名称 xiongweilin/PurchaseFlow 在开始检查时返回 404；推送前会再次检查访问状态。
- 未发现已有 purchaseflow 容器、卷或网络。PurchaseFlow 不连接 ReturnOps-Mini、AIOS、commerce-orchestrator 或个人基础设施。
- Docker 中存在 ReturnOps-Mini 与 AIOS 服务。它们的容器、网络、卷和数据不由本项目管理；本任务不停止、修改或清理这些资源。
- 本地监听端口检查未发现 5432、5678、8025、8069、8072、8000、4173、8090、18069、18072 上的宿主进程。AIOS 使用 18080、18083、18086、18100、18110、19090；ReturnFlow 使用 25432、28000、28025、28090、28417、28567。
- PurchaseFlow Odoo 仅绑定 127.0.0.1:18069；PostgreSQL 不发布宿主端口。Odoo / PostgreSQL 容器、卷和网络以 purchaseflow-demo 命名。
- Odoo/PostgreSQL 使用独立数据库和角色。Odoo 数据库由非 superuser、NOCREATEDB 的 purchaseflow_odoo 角色拥有；PostgreSQL 管理角色只用于项目 bootstrap。

## 工具版本（本机实测）

| 工具 | 版本/结果 |
|---|---|
| PowerShell | 7.6.4 |
| Git | 2.56.0.windows.1 |
| Python | 3.14.8 |
| Node.js | v24.14.0 |
| Docker CLI / Engine | 29.7.2 / 29.7.2 |

当前 CI 与容器开发目标为 Python 3.12；本机 Python 3.14 只作辅助，不替代 CI 的目标运行时。

## Odoo 19 现场

- 官方 Community 镜像：odoo:19.0-20260926，RepoDigest sha256:dd9013e669caaa23d26765dc55814655eaeecca7cfc2c265dbabae913bce22fd。
- 独立 PostgreSQL 镜像：postgres:17.6-alpine，RepoDigest sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94。
- 数据库 purchaseflow_odoo 中 base、account、purchase、purchaseflow_link 均已安装；公司、CNY、供应商、商品及税规则通过 Odoo 模型写入。
- Odoo 登录页返回 HTTP 200；JSON-2 未认证返回 HTTP 401；真实限权账户完成采购单创建和独立读回。证据见 docs/TEST-EVIDENCE.md。
- Odoo 19 的模型约束使用 models.Constraint；运行时发现旧式 _sql_constraints 在 19.0 已不再生效，故改用官方约束 API，并从 PostgreSQL 读回唯一约束。
- 外部 JSON-2 API 格式与计划限制参见 Odoo 19 官方文档。官方文档说明托管计划限制；本机 self-hosted Community 实测可用，不把一个结论推广到另一个部署模式。

## 参考实现与复用边界

- ReturnOps-Mini：学习 PostgreSQL 幂等键、Outbox 租约、角色/组织服务端鉴权、审计事件、演示会话及健康检查模式。PurchaseFlow 只独立实现所需行为，不导入 ReturnOps 包或运行时服务。
- AIOS：学习区分 draft 准备与确认/付款，并把不可用、未知、缺失、错配与核验成功分开；不引入其 monorepo 或运行时。
- commerce-orchestrator：学习 Odoo 19 JSON-2 请求、结果未知分类、读取和并发审批模式；不引入 DBOS。
- agent-skills：以工作流 owner 与字段来源/允许用途契约指导本文档，不复制技能库。
- 参考仓库均使用 MIT 许可证；目前只复用设计经验，没有复制文件或代码。若后续复制代码，将按许可证保留声明并记录来源。

## 官方接口依据

- JSON-2 API：https://www.odoo.com/documentation/19.0/developer/reference/external_api.html
- Odoo CLI：https://www.odoo.com/documentation/19.0/developer/reference/cli.html
- Odoo ORM / constraints：https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html
- 官方 Odoo Docker source：https://github.com/odoo/docker/tree/master/19.0

## 基线时点说明

本文件记录项目开始时的环境和仓库状态，不代表最终交付状态。最终实际实现、验收运行、限制和未验证事项以 [`TEST-EVIDENCE.md`](TEST-EVIDENCE.md) 为准。Feishu 真实租户接入没有授权凭据，因此维持 `NOT VERIFIED`，不影响本地采购与 Odoo 主流程的范围。
