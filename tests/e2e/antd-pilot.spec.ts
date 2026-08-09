import { test, expect } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * G1 — AntD 试点页截图基线（docs/design/upgrade-plan.md §七）
 *
 * 4 场景截图（表单 / 表格 / 弹窗 / 暗色），输出到
 * test-results/screenshots/antd-pilot-*.png，供人工比对 + 后续 diff 基线。
 *
 * 运行前提：需先安装 @playwright/test 并启动 web（npm run dev 或 preview）：
 *   pnpm add -Dw @playwright/test
 *   npx playwright install chromium
 *   E2E_BASE_URL=http://localhost:5173 npx playwright test --project=chromium tests/e2e/antd-pilot.spec.ts
 *
 * 注意：本 spec 不阻塞当前 CI——CI（.github/workflows/ci.yml）目前没有
 * Playwright job；G1 基线截图将在后续独立 workflow（e2e.yml）中启用。
 * 现有 tests/e2e 目录沿用同一 playwright.config.ts（4 个项目），
 * 本 spec 建议只跑 chromium 项目（基线固定浏览器，避免跨浏览器差异）。
 */

const SHOT_DIR = resolve(process.cwd(), 'test-results', 'screenshots');

test.describe('AntD Pilot (G1 screenshot baseline)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/antd-pilot');
    await expect(page.locator('[data-testid="pilot-form"]')).toBeVisible();
    mkdirSync(SHOT_DIR, { recursive: true });
  });

  test('baseline 1/4 — form scenario', async ({ page }) => {
    await page
      .locator('[data-testid="pilot-form"]')
      .screenshot({ path: resolve(SHOT_DIR, 'antd-pilot-form.png') });
  });

  test('baseline 2/4 — table scenario', async ({ page }) => {
    await page
      .locator('[data-testid="pilot-table"]')
      .screenshot({ path: resolve(SHOT_DIR, 'antd-pilot-table.png') });
    // 表格内容冒烟：5 行基因数据 + Tag 渲染
    await expect(page.locator('[data-testid="pilot-table"] .ant-table-row')).toHaveCount(5);
    await expect(page.locator('[data-testid="pilot-table"] .ant-tag')).toHaveCount(5);
  });

  test('baseline 3/4 — modal scenario', async ({ page }) => {
    await page.locator('[data-testid="pilot-modal-open"]').click();
    const modal = page.locator('.ant-modal');
    await expect(modal).toBeVisible();
    await page.screenshot({ path: resolve(SHOT_DIR, 'antd-pilot-modal.png') });
    // Drawer 冒烟：打开侧栏
    await page.keyboard.press('Escape');
    await page.locator('[data-testid="pilot-drawer-open"]').click();
    await expect(page.locator('.ant-drawer')).toBeVisible();
  });

  test('baseline 4/4 — dark scenario', async ({ page }) => {
    await page.locator('[data-testid="pilot-dark-toggle"]').click();
    // 暗色切换后按钮文案变化 = 局部 ConfigProvider 已用 darkAlgorithm 重渲染
    await expect(page.locator('[data-testid="pilot-dark-toggle"]')).toContainText('Light mode');
    await page
      .locator('[data-testid="pilot-form"]')
      .screenshot({ path: resolve(SHOT_DIR, 'antd-pilot-dark.png') });
  });
});
