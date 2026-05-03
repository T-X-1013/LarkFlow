# Frontend Scaffold

这是基于 `Vite + React + TypeScript + MSW` 的前端脚手架，当前目标是：

- 按 `pipeline/contracts.py` / `pipeline/api/routes.py` 的冻结契约建控制台外壳
- 在保留 `MSW` 本地演示能力的同时，逐步把列表页、详情页和圈选能力接到真实 API
- 后续继续以“替换数据源、不重做页面结构”为原则推进联调

当前已经落地：

- 首页：能力说明与后续联调顺序
- Pipeline 列表页：创建 pipeline、搜索、状态筛选、Provider 筛选，并轮询真实 `/pipelines`
- Pipeline 详情页：`start/pause/resume/stop`、Provider 切换、checkpoint approve/reject、artifact 预览
- 仪表盘：Pipeline 总数、耗时、token、状态分布、Provider 分布
- 浏览器圈选入口：左下角悬浮小球可直接发起页面元素圈选
- Visual Edit MVP：支持持续圈选、自然语言意图、预览、确认、回滚、交付摘要、提交前检查、准备提交与安全 commit
- 构建验收：`npm run build` 已通过

当前已接通的真实接口能力：

- `GET /pipelines` 已用于列表页轮询与创建后刷新
- `GET /pipelines/:id`、`POST /pipelines/:id/start|pause|resume|stop` 已用于详情页控制
- `PUT /pipelines/:id/provider` 已可在 `start` 前切换 provider，并真实影响后续 pipeline 启动 provider
- `GET /metrics/pipelines` 已返回真实 token / duration 聚合
- `POST /visual-edits/*` 已用于圈选后的预览、确认、回滚、交付检查和安全 commit

当前仍保留 `MSW` 的部分：

- 仪表盘默认仍可走本地 mock/fixtures 做独立演示
- 后端未启动时，前端页面仍可单独开发和验证样式结构

## 目录约定

```text
frontend/
  src/
    lib/api.ts
    mocks/
      browser.ts
      handlers.ts
      store.ts
      metrics.ts
      fixtures/
        pipelines.ts
        metrics.ts
    pages/
      HomePage.tsx
      PipelinesPage.tsx
      PipelineDetailPage.tsx
      DashboardPage.tsx
    picker/
      PickerPanel.tsx
      locator.ts
      overlay.ts
```

## 启动

首次拉起前端，建议按下面顺序执行：

```bash
cd LarkFlow/frontend
npm install
npx msw init public/ --save
npm run dev
```

默认开发地址为 `http://localhost:4173`。

如果只是后续日常启动，命令可以简化为：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
npm run dev
```

如果需要预览生产构建：

```bash
npm run build
npm run preview
```

## 当前 mock 范围

MSW 已覆盖以下契约：

- `POST /pipelines`
- `GET /pipelines`
- `POST /pipelines/:id/start`
- `POST /pipelines/:id/pause`
- `POST /pipelines/:id/resume`
- `POST /pipelines/:id/stop`
- `GET /pipelines/:id`
- `GET /pipelines/:id/stages/:stage/artifact`
- `POST /pipelines/:id/checkpoints/:cp/approve`
- `POST /pipelines/:id/checkpoints/:cp/reject`
- `PUT /pipelines/:id/provider`
- `GET /metrics/pipelines`
- `GET /healthz`
- `POST /visual-edits/preview`
- `GET /visual-edits/:id`
- `POST /visual-edits/:id/confirm`
- `POST /visual-edits/:id/cancel`
- `GET /visual-edits/:id/delivery-check`
- `GET /visual-edits/:id/prepare-commit`
- `POST /visual-edits/:id/commit`

## 验收建议

本地验收顺序建议如下：

1. `npm run dev`
2. 打开 `http://localhost:4173`
3. 手动验证列表页、详情页、仪表盘联动
4. `npm run build`

重点关注：

- 列表页是否能稳定轮询真实 `/pipelines`
- 详情页状态切换、Provider 切换和 checkpoint 操作是否正确回显错误或成功提示
- 圈选元素后，是否能持续切换目标、生成预览、执行确认/回滚，并正确展示交付摘要与提交前检查结果
- `data-lark-src` 缺失时，圈选能力是否返回可读错误
