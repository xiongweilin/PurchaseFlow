import { expect, test } from "@playwright/test";

test("high-value purchase waits for a distinct finance approval before real Odoo sync", async ({ page }) => {
  test.setTimeout(150_000);
  await page.goto("/");
  await page.getByRole("button", { name: /运营部申请人/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.getByRole("button", { name: "新建采购申请" }).click();

  const composer = page.getByRole("dialog");
  await composer.getByLabel("供应商").selectOption("PF-VENDOR-IT");
  await composer.getByPlaceholder("说明采购背景、使用场景与预期用途…").fill(
    "高额采购端到端验收：先部门审批，再由不同财务人员复核。",
  );
  await composer.getByLabel("商品明细 1").selectOption("PF-IT-MONITOR");
  await composer.getByLabel("数量 1").fill("2");
  await composer.getByLabel("未税单价 1").fill("4000.00");
  await composer.getByRole("button", { name: "保存草稿" }).click();

  let detail = page.getByRole("dialog");
  const requestNumber = (await detail.getByRole("heading", { name: /^PR-/ }).innerText()).trim();
  await detail.getByRole("button", { name: "提交审批" }).click();
  await page.getByRole("button", { name: "关闭详情" }).click();
  await page.getByRole("button", { name: "退出演示身份" }).click();

  await page.getByRole("button", { name: /运营部负责人/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.getByRole("button", { name: /^部门审批/ }).click();
  const managerCard = page.locator(".approval-card").filter({ hasText: requestNumber });
  await expect(managerCard).toBeVisible();
  await managerCard.click();
  detail = page.getByRole("dialog");
  await detail.getByRole("button", { name: "通过申请" }).click();
  await expect(detail.getByText("待财务复核").first()).toBeVisible();

  const managerCannotSecondApprove = await page.evaluate(async (number: string) => {
    const requests = await fetch("/api/procurements").then((response) => response.json());
    const request = requests.find((item: { request_number: string }) => item.request_number === number);
    if (!request) throw new Error("The manager could not reload the approved request.");
    const response = await fetch(`/api/procurements/${request.id}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": `e2e-same-person-${request.id}` },
      body: JSON.stringify({ decision: "approve", expected_version: request.version }),
    });
    return response.status;
  }, requestNumber);
  expect(managerCannotSecondApprove).toBe(403);
  await page.getByRole("button", { name: "关闭详情" }).click();
  await page.getByRole("button", { name: "退出演示身份" }).click();

  await page.getByRole("button", { name: /财务复核人甲/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.getByRole("button", { name: "财务复核", exact: true }).click();
  const financeCard = page.locator(".approval-card").filter({ hasText: requestNumber });
  await expect(financeCard).toBeVisible();
  await financeCard.click();
  detail = page.getByRole("dialog");
  await detail.getByRole("button", { name: "通过申请" }).click();
  await expect(detail.getByText("审批完成").first()).toBeVisible();

  let verified = false;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (await detail.getByText("Odoo 采购草稿已核验").count()) {
      verified = true;
      break;
    }
    await page.waitForTimeout(1500);
    await detail.getByRole("button", { name: "刷新申请状态" }).click();
  }
  expect(verified, "the Odoo draft must wait until the distinct finance approval").toBe(true);
  await expect(detail.getByText(/订单编号 P000\d+/)).toBeVisible();
});
