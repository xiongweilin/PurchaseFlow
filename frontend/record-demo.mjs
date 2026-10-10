import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { chromium, expect } from "@playwright/test";

const root = path.resolve(process.cwd(), "..");
const localDir = path.join(root, ".local");
const recordingDir = path.join(localDir, "recording");
const assetDir = path.join(root, "docs", "assets");
const scenarioPath = path.join(localDir, "unknown-demo.json");
const appUrl = "http://127.0.0.1:18081";
const n8nUrl = "http://127.0.0.1:18082";
const mailpitUrl = "http://127.0.0.1:18025";
const workflowIds = {
  intake: "9d047287-d2c9-4ee6-9669-1e488d3ef801",
  digest: "4ca07f03-9e91-443c-9b84-4af611df9a62",
};

if (!fs.existsSync(scenarioPath)) {
  throw new Error("Run scripts/run-erp-unknown-demo.ps1 first.");
}
if (!fs.existsSync(path.join(localDir, "n8n-owner-password"))) {
  throw new Error("Run scripts/start-demo.ps1 to provision the local n8n owner first.");
}
const unknownScenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8"));
fs.mkdirSync(recordingDir, { recursive: true });
fs.mkdirSync(assetDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  recordVideo: { dir: recordingDir, size: { width: 1440, height: 900 } },
});
const page = await context.newPage();
const video = page.video();
const recordingStartedAt = Date.now();
const subtitles = [];

async function chapter(text, action, holdMs = 20_000) {
  const start = Date.now() - recordingStartedAt;
  await action();
  await page.waitForTimeout(holdMs);
  subtitles.push({ start, end: Date.now() - recordingStartedAt, text });
}

async function enterRole(name) {
  await page.goto(appUrl);
  await page.getByRole("button", { name }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await expect(page.getByRole("heading", { name: "采购协作工作台" })).toBeVisible();
}

async function signOut() {
  await page.getByRole("button", { name: "退出演示身份" }).click();
}

async function closeN8nProductionChecklist() {
  const close = page.locator('[data-test-id="suggested-actions-close"]');
  if (await close.isVisible().catch(() => false)) {
    await close.click();
    await page.waitForTimeout(350);
  }
}

try {
  await chapter("PurchaseFlow 把采购申请、人工审批与 ERP 结果放在同一条业务记录中。", async () => {
    await enterRole(/运营部申请人/);
    await expect(page.getByRole("heading", { name: "采购协作工作台" })).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-overview.png") });
  });

  let requestNumber = "";
  await chapter("申请人提交采购理由、供应商和商品。金额由系统按 CNY 与税率计算。", async () => {
    await page.getByRole("button", { name: "新建采购申请" }).click();
    const composer = page.getByRole("dialog");
    await composer.getByLabel("供应商").selectOption("PF-VENDOR-IT");
    await composer.getByPlaceholder("说明采购背景、使用场景与预期用途…").fill(
      "录屏合成样例：运营部门采购两台显示器，演示分级审批和 Odoo 草稿核验。",
    );
    await composer.getByLabel("商品明细 1").selectOption("PF-IT-MONITOR");
    await composer.getByLabel("数量 1").fill("2");
    await composer.getByLabel("未税单价 1").fill("4000.00");
    await composer.getByRole("button", { name: "保存草稿" }).click();
    const detail = page.getByRole("dialog");
    requestNumber = (await detail.getByRole("heading", { name: /^PR-/ }).innerText()).trim();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-draft-request.png") });
  });

  await chapter("提交后，审批内容被冻结。含税总额超过 5,000 CNY，系统要求两名不同岗位人员决定。", async () => {
    const detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "提交审批" }).click();
    await expect(detail.getByText("待部门审批").first()).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-submitted-request.png") });
    await page.getByRole("button", { name: "关闭详情" }).click();
  }, 15_000);

  await chapter("运营部负责人核对申请并批准。此时仍未创建 Odoo 采购单，流程转入财务复核。", async () => {
    await signOut();
    await enterRole(/运营部负责人/);
    await page.getByRole("navigation", { name: "主导航" }).getByRole("button", { name: /^部门审批/ }).click();
    const managerCard = page.locator(".approval-card").filter({ hasText: requestNumber });
    await expect(managerCard).toBeVisible();
    await managerCard.click();
    const detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "通过申请" }).click();
    await expect(detail.getByText("待财务复核").first()).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-pending-finance.png") });
    await page.getByRole("button", { name: "关闭详情" }).click();
  });

  await chapter("财务由另一位员工复核后，worker 才会把已批准版本写成 Odoo 草稿。", async () => {
    await signOut();
    await enterRole(/财务复核人甲/);
    await page.getByRole("button", { name: "财务复核", exact: true }).click();
    const card = page.locator(".approval-card").filter({ hasText: requestNumber });
    await expect(card).toBeVisible();
    await card.click();
    const detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "通过申请" }).click();
    await expect(detail.getByText("审批完成").first()).toBeVisible();
    let verified = false;
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (await detail.getByText("Odoo 采购草稿已核验").count()) {
        verified = true;
        break;
      }
      await page.waitForTimeout(1500);
      await detail.getByRole("button", { name: "刷新申请状态" }).click();
    }
    expect(verified).toBe(true);
    await expect(detail.getByText(/订单编号 P000\d+/)).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-odoo-verified.png") });
  }, 25_000);

  await chapter("Odoo 草稿通过独立读回核对供应商、商品、金额、币种和 draft 状态；HTTP 写入成功本身不作为完成证据。", async () => {
    const detail = page.getByRole("dialog");
    await expect(detail.getByText("Odoo 采购草稿已核验", { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-verified-detail.png") });
    await page.getByRole("button", { name: "关闭详情" }).click();
  }, 15_000);

  await chapter("模拟 Odoo 已提交，但创建响应丢失。PurchaseFlow 记录 UNKNOWN 和一次派发，暂停自动创建。", async () => {
    await signOut();
    await enterRole(/采购管理员/);
    await page.getByRole("button", { name: "ERP 核验" }).click();
    const row = page.locator(".erp-row").filter({ hasText: unknownScenario.request_number });
    await expect(row).toBeVisible();
    await row.click();
    const detail = page.getByRole("dialog");
    await expect(detail.getByText("写入结果未知", { exact: true })).toBeVisible();
    await expect(detail.getByText("尝试 1 次")).toBeVisible();
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-unknown-before-reconcile.png") });
  });

  await chapter("采购人员按稳定意图对 Odoo 做只读查询。发现原草稿并核对匹配后，才允许恢复状态。", async () => {
    const detail = page.getByRole("dialog");
    await detail.getByRole("button", { name: "只读核验" }).click();
    await expect(detail.getByText("Odoo 采购草稿已核验", { exact: true })).toBeVisible();
    await expect(detail.getByText(/订单编号 P000\d+/)).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-unknown-recovered.png") });
    await detail.getByRole("button", { name: "结案归档" }).click();
    await expect(page.getByText("采购记录已结案。")).toBeVisible();
  });

  const n8nPassword = fs.readFileSync(path.join(localDir, "n8n-owner-password"), "utf8").trim();
  await chapter("n8n 的接单流只把经过身份验证的事件转给 PurchaseFlow API，并用事件编号防重复。", async () => {
    await page.goto(`${n8nUrl}/signin`);
    await page.locator("input[name=emailOrLdapLoginId]").fill("automation-admin@demo.local");
    await page.locator("input[name=password]").fill(n8nPassword);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForTimeout(1500);
    await page.goto(`${n8nUrl}/workflow/${workflowIds.intake}`);
    await page.waitForTimeout(2500);
    await closeN8nProductionChecklist();
    await expect(page.locator("body")).toContainText("Authenticated Intake");
    await page.screenshot({ path: path.join(assetDir, "n8n-procurement-intake.png") });
  });

  await chapter("摘要流定时读取岗位待办和 ERP 异常，经 Mailpit 发送给虚构岗位邮箱。", async () => {
    await page.goto(`${n8nUrl}/workflow/${workflowIds.digest}`);
    await page.waitForTimeout(2500);
    await closeN8nProductionChecklist();
    await expect(page.locator("body")).toContainText("Send local-only Mailpit digest");
    await page.screenshot({ path: path.join(assetDir, "n8n-daily-digest.png") });
  });

  await chapter("Mailpit 展示由当前业务数据生成的摘要邮件；演示环境不会向真实供应商或员工发送邮件。", async () => {
    await page.goto(mailpitUrl);
    await page.waitForTimeout(2500);
    await expect(page.locator("body")).toContainText("PurchaseFlow");
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-mailpit-digest.png") });
  });

  await chapter("本作品自动处理接入、记录和核验；采购审批仍由明确岗位承担。结果未知时，先查证，再决定下一步。", async () => {
    await page.goto(`${appUrl}/`);
    await expect(page.getByRole("heading", { name: /有据可循|采购协作工作台|采购申请/ }).first()).toBeVisible();
    await page.screenshot({ path: path.join(assetDir, "purchaseflow-final-worklist.png") });
  });
} finally {
  await context.close();
  const videoPath = await video.path();
  await browser.close();
  fs.copyFileSync(videoPath, path.join(recordingDir, "purchaseflow-demo-raw.webm"));

  const mp4Path = path.join(assetDir, "purchaseflow-demo.mp4");
  execFileSync(
    "ffmpeg",
    ["-hide_banner", "-loglevel", "error", "-y", "-i", path.join(recordingDir, "purchaseflow-demo-raw.webm"), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "27", "-pix_fmt", "yuv420p", "-movflags", "+faststart", mp4Path],
    { stdio: "inherit" },
  );
  const srt = subtitles
    .map((caption, index) => `${index + 1}\n${srtTime(caption.start)} --> ${srtTime(caption.end)}\n${caption.text}\n`)
    .join("\n");
  fs.writeFileSync(path.join(assetDir, "purchaseflow-demo.zh-CN.srt"), srt, "utf8");
  console.log(`Saved MP4 and Chinese subtitles to ${assetDir}`);
}

function srtTime(milliseconds) {
  const totalMs = Math.max(0, Math.floor(milliseconds));
  const hours = Math.floor(totalMs / 3_600_000);
  const minutes = Math.floor((totalMs % 3_600_000) / 60_000);
  const seconds = Math.floor((totalMs % 60_000) / 1000);
  const millis = totalMs % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")},${String(millis).padStart(3, "0")}`;
}
