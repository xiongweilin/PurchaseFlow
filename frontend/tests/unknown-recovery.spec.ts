import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";

const scenarioPath = path.resolve(process.cwd(), "..", ".local", "unknown-demo.json");

test("procurement reconciles a committed real Odoo draft after a lost response", async ({ page }) => {
  test.setTimeout(90_000);
  test.skip(!fs.existsSync(scenarioPath), "Run scripts/run-erp-unknown-demo.ps1 first.");
  const scenario = JSON.parse(fs.readFileSync(scenarioPath, "utf8")) as {
    id: string;
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
  await expect(detail.getByText("写入结果未知", { exact: true })).toBeVisible();
  await expect(detail.getByText(`稳定意图 ${scenario.external_intent_id}`)).toBeVisible();
  await expect(detail.getByText("尝试 1 次")).toBeVisible();
  await detail.getByRole("button", { name: "只读核验" }).click();
  await expect(detail.getByText("Odoo 采购草稿已核验", { exact: true })).toBeVisible();
  await expect(detail.getByText(/订单编号 P000\d+/)).toBeVisible();
  await detail.getByRole("button", { name: "结案归档" }).click();
  await expect(page.getByText("采购记录已结案。")).toBeVisible();
});
