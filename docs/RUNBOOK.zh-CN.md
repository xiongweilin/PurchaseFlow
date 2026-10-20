# 本地运行手册

## 前置条件

- 带 Docker Compose v2 的 Docker Desktop。
- PowerShell 7（pwsh）。
- 首次运行需要网络访问以下载固定镜像和依赖包。
- 所有发布端口都绑定回环；不要在共享机器上改为 0.0.0.0。

## 启动与验证

~~~powershell
pwsh ./scripts/start-demo.ps1
pwsh ./scripts/verify-demo.ps1
~~~

启动会引导 Odoo、创建应用/n8n 数据库角色、运行 API 迁移与幂等种子、构建应用镜像、配置加密的 n8n 凭据/工作流，并等待健康检查。首次 Odoo 模块安装可能需要数分钟。

| 组件 | URL |
|---|---|
| PurchaseFlow | http://127.0.0.1:18081 |
| FastAPI 文档 | http://127.0.0.1:18000/docs |
| Odoo 19 | http://127.0.0.1:18069 |
| n8n 编辑器 | http://127.0.0.1:18082 |
| Mailpit | http://127.0.0.1:18025 |

在 PurchaseFlow 登录页选择合成应用角色。n8n owner 邮箱为 automation-admin@demo.local；生成的密码在 .local/n8n-owner-password。Odoo 管理员凭据只在 .local/odoo.env。

常规验证是只读的。以下可选演练会创建一条待审批合成申请并投递一封本地摘要邮件：

~~~powershell
pwsh ./scripts/verify-demo.ps1 -ExerciseN8nWorkflows
~~~

启动后可用 `pwsh ./scripts/seed-demo.ps1` 重新执行幂等迁移和种子。

要展示真实 Odoo 响应丢失恢复，运行：

~~~powershell
pwsh ./scripts/run-erp-unknown-demo.ps1
~~~

该命令只暂停 PurchaseFlow worker，同时由申请人提交、部门负责人批准一条合成申请。一次性 worker 调用会在真实 Odoo 创建草稿、丢弃创建响应，并验证已保存状态为 `erp_unknown` 且只有一次尝试。worker 会在 `finally` 中重启；以采购身份打开申请并选择 **只读核验** 即可恢复。

## 测试

~~~powershell
pwsh ./scripts/bootstrap-test-db.ps1
docker compose -p purchaseflow-demo -f docker-compose.yml --profile test run --rm tests
~~~

Postgres 集成 fixture 会拒绝在配置的数据库名不以 _test 结尾时创建/删除表。

~~~powershell
cd frontend
npm ci
npx playwright install chromium
npm run build
npm run e2e
~~~

浏览器测试覆盖申请人 -> 部门负责人 -> Odoo 草稿核验、高额不同审批人复核，以及申请人 API 授权检查。如果响应丢失脚本生成了 `.local/unknown-demo.json`，它们还会在采购工作列表中核对现有 Odoo 订单并结案。

浏览器恢复成功后，验证数据在普通服务重启后仍然存在：

~~~powershell
pwsh ./scripts/verify-persistence.ps1
~~~

该命令只重启 `purchaseflow-demo` 容器，绝不删除卷，并按稳定意图 ID 确认同一应用申请和 Odoo 草稿。它还会检查已导入的 n8n 工作流和 Mailpit 消息仍可用。失败时会尝试重新拉起同一服务栈。

## 停止与持久化

~~~powershell
pwsh ./scripts/stop-demo.ps1
~~~

该命令停止容器并保留命名卷。它不会清除申请、Odoo 草稿、n8n 工作流/凭据或 Mailpit 消息。再次用 scripts/start-demo.ps1 启动；种子例程是幂等的。

n8n 加密密钥存储在 .local/n8n.env，必须与持久化 n8n 数据库/卷保持配对。丢失它会使已保存凭据无法读取。n8n 服务凭据由 n8n 加密静态保存；临时导入 JSON 在配置完成后删除。

## 故障排查

- **端口已被占用：** 停止其他本地进程，或在 Compose、脚本和 Vite/Playwright 配置中一致地修改宿主机回环端口。
- **Docker 已停止：** 启动 Docker Desktop，然后重跑 scripts/start-demo.ps1。
- **服务不健康：** 检查 docker compose -p purchaseflow-demo -f docker-compose.yml ps 和 docker compose -p purchaseflow-demo -f docker-compose.yml logs --tail 120 SERVICE。
- **n8n 无法解密凭据：** 不要随意轮换 .local/n8n.env。恢复匹配的密钥或本地数据库/卷配对。
- **需要重置本地数据：** `scripts/reset-demo.ps1` 会打印仅限 PurchaseFlow 的卷范围，并要求精确确认短语 `RESET PURCHASEFLOW DEMO DATA`。它会删除该 Compose 项目的命名卷，保留 Git 忽略的 `.local/` 配置，且绝不针对其他 Compose 项目。`scripts/stop-demo.ps1` 始终是非破坏性的。
