# Admin 最终验收（2026-10-16）

## 结果

- 单元测试：19 个文件，146 passed，零跳过；`/tmp/admin-final-unit-20261015.log`。冻结安装后的全工作区验收中再次 146 passed，详见 `/tmp/workspace-final-20261016.log`（总计 1071 tests / 36 tasks 通过）。
- 最终正常构建成功；`/tmp/admin-final-build-20261015.log`。构建显式选择 internal 站点和本地预览 API，随后运行 CSP finalizer。
- 浏览器布局：375 / 768 / 1024 / 1440 像素下页面宽度均等于视口；移动抽屉开关、导航关闭、跳转及标题检查通过。结果 `/tmp/admin-responsive-acceptance.json`，375/768 截图已人工检查。
- 管理流程：会话恢复、显式 internal 列表、发布/草稿详情、来源信息处理和缺失来源接口回退通过；没有页面 JS 错误。此浏览器轮次模拟 API；真实授权和公开边界由 API PostgreSQL 测试覆盖。
- 上传组件使用真实 Ant Design Upload 的回归保留在单元测试中。
- 官方 Ant Design CLI 6.6.6：161 个源码文件、73 个 facade imports，零 lint 问题、零配置失败；CSS-in-JS/SSR 提示对当前 SPA 不构成失败。源码扫描不代表浏览器验收。
- ECharts 清单、catalog、lock 已移除；管理图表使用共享 AntV 包。
- 最终 `python3 scripts/check_artifact_headers.py --require-dual`：4 份 header 通过，包括 Admin；CSP 保留 frame-ancestors none 和明确配置的 API origin。

## 可复现命令

```sh
cd apps/admin
node node_modules/vitest/vitest.mjs run
# 构建须显式配置实际环境的 API origin；不要复制预览地址发布生产。
SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true VITE_SITE_VARIANT=internal \
VITE_DEPLOYMENT_MODE=demo VITE_API_BASE_URL=http://100.77.182.76:8010/api/v1 \
GOMAXPROCS=1 RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 \
node node_modules/@umijs/max/bin/max.js build
SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED=true VITE_API_BASE_URL=http://100.77.182.76:8010/api/v1 \
node --import tsx scripts/finalize-csp.ts
```

CLI 扫描入口 `scripts/scan-ant-design.mjs`，使用已安装官方 CLI 路径设置 `ANTD_CLI_BIN`。
正式报告：[最新扫描](ant-design-scan-20261015/summary.json)。

Docker 部署、真实后端跨服务浏览器链路不在此轮 mock API 页面验收的证明范围内。
