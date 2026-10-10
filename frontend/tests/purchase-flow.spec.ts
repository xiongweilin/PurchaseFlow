import { expect, test } from "@playwright/test";

test("requester → manager → verified Odoo draft → procurement detail", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");
  await page.getByRole("button", { name: /行政部申请人/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();

  await expect(page.getByRole("heading", { name: "采购协作工作台" })).toBeVisible();
  await page.getByRole("button", { name: "新建采购申请" }).click();
  const composer = page.getByRole("dialog");
  await expect(composer.getByRole("heading", { name: "新建采购申请" })).toBeVisible();
  await composer.getByLabel("供应商").selectOption("PF-VENDOR-OFFICE");
  await composer.getByPlaceholder("说明采购背景、使用场景与预期用途…").fill(
    "办公用品采购，用于本地 Playwright 端到端流程验收。",
  );
  await composer.getByLabel("商品明细 1").selectOption("PF-OFFICE-SET");
  await composer.getByLabel("数量 1").fill("1");
  await composer.getByLabel("未税单价 1").fill("1200.00");
  await composer.getByRole("button", { name: "保存草稿" }).click();

  const detail = page.getByRole("dialog");
  await expect(detail.getByRole("heading", { name: /^PR-/ })).toBeVisible();
  const requestNumber = (await detail.getByRole("heading", { name: /^PR-/ }).innerText()).trim();
  await detail.getByRole("button", { name: "提交审批" }).click();
  await expect(detail.getByText("待部门审批").first()).toBeVisible();

  const unauthorizedApprovalStatus = await page.evaluate(async (number: string) => {
    const requests = await fetch("/api/procurements").then((response) => response.json());
    const request = requests.find((item: { request_number: string }) => item.request_number === number);
    if (!request) throw new Error("The submitted request was not visible to its requester.");
    const response = await fetch(`/api/procurements/${request.id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": `e2e-unauthorized-${request.id}` },
      body: JSON.stringify({ decision: "approve", expected_version: request.version }),
    });
    return response.status;
  }, requestNumber);
  expect(unauthorizedApprovalStatus).toBe(403);

  await page.getByRole("button", { name: "关闭详情" }).click();
  await page.getByRole("button", { name: "退出演示身份" }).click();
  await page.getByRole("button", { name: /行政部负责人/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await expect(page.getByRole("heading", { name: "采购协作工作台" })).toBeVisible();

  await page.getByRole("button", { name: "部门审批" }).click();
  const card = page.locator(".approval-card").filter({ hasText: requestNumber });
  await expect(card).toBeVisible();
  await card.click();
  const managerDetail = page.getByRole("dialog");
  await managerDetail.getByRole("button", { name: "通过申请" }).click();
  await expect(page.getByText("审批已记录。")).toBeVisible();

  let verified = false;
  for (let attempt = 0; attempt < 24; attempt += 1) {
    if (await managerDetail.getByText("ERP 已核验").count()) {
      verified = true;
      break;
    }
    await page.waitForTimeout(1500);
    await managerDetail.getByRole("button", { name: "刷新申请状态" }).click();
  }
  expect(verified, "worker should create and independently verify a real Odoo draft").toBe(true);
  await expect(managerDetail.getByText(/订单编号 P000\d+/)).toBeVisible();

  await managerDetail.getByRole("button", { name: "关闭详情" }).click();
  await page.getByRole("button", { name: "退出演示身份" }).click();
  await page.getByRole("button", { name: /采购管理员/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.getByRole("button", { name: "ERP 核验" }).click();

  const erpRow = page.locator(".erp-row").filter({ hasText: requestNumber });
  await expect(erpRow).toBeVisible();
  await erpRow.click();
  const procurementDetail = page.getByRole("dialog");
  await expect(procurementDetail.getByText("稳定意图 PF-", { exact: false })).toBeVisible();
  await expect(procurementDetail.getByText("Odoo 采购草稿已核验")).toBeVisible();
});
