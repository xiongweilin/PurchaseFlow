import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const scenarioPath = path.resolve(process.cwd(), "..", ".local", "erp-mismatch-demo.json");

test("procurement sees real Odoo field differences and cannot close the mismatch", async ({ page }) => {
  test.setTimeout(60_000);
  test.skip(!fs.existsSync(scenarioPath), "Run the controlled Odoo mismatch scenario first.");
  const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8")) as {
    request_number: string;
    external_intent_id: string;
  };

  await page.goto("/");
  await page.getByRole("button", { name: /采购管理员/ }).click();
  await page.getByRole("button", { name: /进入工作台/ }).click();
  await page.getByRole("button", { name: "ERP 核验" }).click();

  const row = page.locator(".erp-row").filter({ hasText: scenario.request_number });
  await expect(row).toBeVisible();
  await row.click();
  const detail = page.getByRole("dialog");
  await expect(detail.getByText("远端事实不匹配", { exact: true })).toBeVisible();
  await expect(detail.getByText(`稳定意图 ${scenario.external_intent_id}`)).toBeVisible();
  await expect(detail.getByText("结案已阻止：Odoo 实际字段与审批快照不一致")).toBeVisible();
  const priceDifference = detail.locator(".erp-difference-entry").filter({ hasText: "line_1" });
  await expect(priceDifference).toContainText("审批快照");
  await expect(priceDifference).toContainText("Odoo 实际");
  await expect(priceDifference).toContainText("1201");
  await expect(detail.getByRole("button", { name: "结案归档" })).toHaveCount(0);

  await detail.getByRole("button", { name: "只读核验" }).click();
  await expect(detail.getByText("远端事实不匹配", { exact: true })).toBeVisible();
  await expect(priceDifference).toContainText("1201");
  await expect(detail.getByRole("button", { name: "结案归档" })).toHaveCount(0);
});
