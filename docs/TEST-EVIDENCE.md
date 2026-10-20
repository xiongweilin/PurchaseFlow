# 测试证据与环境边界

记录日期：2026-10-11（Asia/Shanghai）。运行结果来自本地隔离演示栈与全新 GitHub Actions runner；只记录已观察到的验收，不代表生产部署。

## 真实 Odoo 19 Community

| 检查 | 现场结果 |
|---|---|
| 官方 Odoo 镜像 | `odoo:19.0-20260926`；RepoDigest `sha256:dd9013e669caaa23d26765dc55814655eaeecca7cfc2c265dbabae913bce22fd` |
| 独立 PostgreSQL 镜像 | `postgres:17.6-alpine`；RepoDigest `sha256:ef257d85f76e48da1c64832459b59fcaba1a4dac97bf5d7450c77753542eee94` |
| 数据库隔离 | `purchaseflow-demo` 私有 Compose 集群内数据库 `purchaseflow_odoo`；最小权限角色 `purchaseflow_odoo` 为非 superuser、`NOCREATEDB`；PostgreSQL 不发布宿主端口 |
| Odoo 安装 | Odoo 报告版本 `19.0-20260926`；`base`、`account`、`purchase`、`purchaseflow_link` 均为 installed |
| 远端幂等约束 | `purchase.order.purchaseflow_intent_id` 的 PostgreSQL 唯一约束已从 `pg_constraint` 读回 |
| 网络绑定 | Odoo 只绑定 `127.0.0.1:18069`；PostgreSQL 仅在项目网络内访问 |
| 演示数据 | `Demo Office Ltd.`、CNY、供应商、商品、UoM 与税规则均从当前 Odoo 数据库按业务键查找，不依赖硬编码的远端 ID |
| 认证边界 | Odoo 登录页 HTTP 200；无 bearer 的 JSON-2 请求 HTTP 401；集成账户访问受保护的 `ir.config_parameter` 返回 HTTP 403 |
| 真实草稿与独立读回 | 确定性验收意图 `PF-STAGE1-ODOO-JSON2` 当前映射到真实 draft `P00029`；新的 `search_read/read` 核对公司、供应商、意图标记、行项目、数量、税率、金额及 `state=draft` |
| 金额口径 | 1 × 未税单价 CNY 1,200.00；13% 税额 CNY 156.00；含税总额 CNY 1,356.00 |
| 重放防重复 | 对相同 `purchaseflow_intent_id` 的第二次创建返回 HTTP 422；权威 `search_read` 仍只有一笔草稿 |
| 响应丢失与 UNKNOWN 恢复 | 受控脚本实际创建 Odoo draft 后丢弃成功响应；应用记录 `erp_unknown`、1 次派发。采购 UI 以同一意图只读核验并结案，没有再次创建 |
| 密钥引导边界 | Odoo 容器在自身 filestore volume 暂存新 API key；PowerShell 捕获一次性值但不回显日志，写入 Git 忽略的 `.local/odoo-api-key`（Linux mode 0600）；Odoo Web 服务不挂载整个 `.local` |
| Odoo 单据重启幂等 | PostgreSQL 与 Odoo 重启后，`PF-STAGE1-ODOO-JSON2` 仍读回同一草稿 `P00029`；重复 create 返回 HTTP 422，查询仍只有该稳定意图的一笔草稿 |
| 应用全栈重启持久化 | 重启 PurchaseFlow PostgreSQL、Odoo、API、worker、前端、n8n 与 Mailpit 后，`PR-202610-96BDCA11` 仍映射到 Odoo draft `P00027`；重新向 Odoo 读回且匹配持久审批快照。应用请求、n8n 工作流和 Mailpit 邮件也保留 |

现场验证的是自托管 Odoo 19 Community，不推断 Odoo Online 或其他托管版套餐的 API 许可。所有采购单均保持草稿；流程不会确认采购、收货、过账或付款。

## 本地自动化与前端验收

| 检查 | 结果 |
|---|---|
| Python 静态质量 | Ruff 通过；mypy 对 20 个 Python 源文件无问题 |
| Python 单测 | 本地运行 26 passed、1 skipped；唯一 skip 是需要 `DATABASE_URL_TEST` 的 PostgreSQL 并发测试 |
| 隔离 PostgreSQL 容器测试 | 在独立 `purchaseflow_test` 数据库的 Python 3.12 容器中 27 passed（含并发幂等测试）；仅有 Starlette `TestClient` 弃用提示 |
| Python 依赖审计 | `pip-audit`：No known vulnerabilities found |
| 前端依赖审计 | `npm audit --registry=https://registry.npmjs.org/ --audit-level=moderate`：0 vulnerabilities |
| 前端构建 | TypeScript 检查与 Vite production build 通过 |
| 浏览器 E2E | 3 passed：申请人 → 部门负责人 → Odoo draft、不同财务人员复核高额申请、真实 Odoo 响应丢失后的人工核验；另验证申请人无法通过 API 自批 |
| n8n / API | webhook 未认证返回 403、无效 payload 返回 422、相同事件重放返回同一申请、同 ID 不同内容返回 409；每日摘要邮件到达本机 Mailpit |
| 服务持久化 | `scripts/verify-persistence.ps1` 重启项目服务且不删卷；API、工作流、邮件及 Odoo 外部订单读回均通过 |
| Feishu 离线适配器 | 7 个合成单元测试覆盖 URL challenge、Verification Token、v2.0 event ID、字段映射、稳定幂等键与签名新鲜度；未连接租户 |
| 演示录屏 | `docs/assets/purchaseflow-demo.mp4` 时长 4:32.96；12 条中文字幕覆盖至片尾，截图和视频来自本地真实 UI |

`npm audit` 使用官方 npm registry，因为此环境配置的镜像未实现 advisory bulk endpoint。容器测试在独立 `_test` 数据库运行；测试夹具会拒绝在名称不以 `_test` 结尾的数据库中建/删表。

## CI 与可复现交付

GitHub Actions 的自动 CI 负责在全新 runner 上安装依赖、启动隔离 Docker/Odoo/n8n/Mailpit、运行 PostgreSQL 并发测试、静态工作流合同与浏览器验收。手动 `controlled-purchaseflow-integration` 工作流额外注入真实 Odoo 响应丢失、执行 UNKNOWN 浏览器恢复并在随后重启服务验证持久化。

初版源码提交 `ce25b1bba31655e555ad390a75c1252caa7f6b78` 在全新 GitHub runner 上通过自动 CI 与受控端到端验收：[PurchaseFlow CI #38067068398](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38067068398)；[controlled-purchaseflow-integration #38067080112](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38067080112)。受控验收包含真实 Odoo 响应丢失、UNKNOWN 人工核验、三个浏览器流程以及服务重启后的持久化检查。早期 clean-run 尝试发现并修复了引导顺序、Linux secret-file ownership 与 webhook 注册时序问题；上面链接是修复后的全绿结果。

## Worker 租约栅栏、真实 Odoo 错配与 PR 交付

源码验收提交 `ea26985665dff2b0f603fd7f1bf21aecdb804973` 增加 Outbox `lease_generation` 迁移和失效 Worker 写入栅栏。PostgreSQL 并发测试让 Worker A 阻塞在慢读回、租约过期后由 Worker B 接管并核验同一 Odoo 订单，再让 A 返回一份错配读回；最终意图仍为 `VERIFIED`、申请仍为 `erp_verified`、Outbox 保持 `done` 且代次为 2：[PR CI #38102500592](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38102500592) 的 PostgreSQL 并发测试及全套 `acceptance` 检查通过。

受控 runner 使用新建的合成申请和真实 Odoo 19 草稿，将订单行单价从 CNY 1,200.00 改为 CNY 1,201.00。PurchaseFlow 独立读回应进入 `erp_mismatch`，保存并在采购详情页展示审批快照与 Odoo 实际行价/金额差异；工作台不提供结案，直接结案请求返回 HTTP 409。随后脚本将同一 Odoo 草稿恢复到原价，重新读回应变为 `erp_verified`，订单 ID 与单号未变：[controlled-purchaseflow-integration #38102503416](https://github.com/xiongweilin/PurchaseFlow/actions/runs/38102503416)。浏览器差异显示、结案拦截、恢复及服务重启持久化均通过。

PR 交付记录：[PurchaseFlow PR #1](https://github.com/xiongweilin/PurchaseFlow/pull/1)。`main` 已配置分支保护：要求 Pull Request、`acceptance` 检查通过且分支保持最新，并对管理员启用；当前要求审批人数为 0，以便单人维护仓库仍能经 PR 合并。

## 未验证事项与数据边界

- Feishu 没有提供授权租户、应用凭据或回调地址，因此不注册回调、不调用 API。`backend/app/feishu_adapter.py` 只提供离线可测试的 v2.0 事件校验和租户字段映射边界；签名/加密解密与真实字段抽取仍需租户验收。详见 [Feishu 适配器状态](FEISHU.md)。
- PurchaseFlow 登录是显式演示身份选择器，不是生产级 SSO/MFA。演示角色、审批阈值和金额均为合成数据。
- 未连接支付、供应商邮箱、外部 Feishu 租户或生产 Odoo。SMTP 仅进入本机 Mailpit。
- `scripts/reset-demo.ps1` 需要输入精确确认语句；本地验收没有运行重置脚本，也没有删除本地服务卷。
- 本地 Docker 中其他项目（包括 ReturnOps-Mini 与 AIOS）不属于本仓库 Compose 范围；本地启动、重启、停止及持久化验收均使用 `purchaseflow-demo` 项目，不对它们执行操作。
