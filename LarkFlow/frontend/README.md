# Frontend Scaffold

这是基于 `Vite + React + TypeScript + MSW` 的前端脚手架，当前目标是：

- 按 `pipeline/contracts.py` / `pipeline/api/routes.py` 的冻结契约建控制台外壳
- 在真实 API 联调前，全部通过 `MSW` mock 跑通列表页、详情页、首页、仪表盘
- 后续只替换数据源，不重做页面结构

当前已经落地：

- 首页：能力说明与后续联调顺序
- Pipeline 列表页：创建 mock pipeline、搜索、状态筛选、Provider 筛选
- Pipeline 详情页：`start/pause/resume/stop`、Provider 切换、checkpoint approve/reject、artifact 预览
- 仪表盘：Pipeline 总数、耗时、token、状态分布、Provider 分布
- 共享 mock store：详情页状态变化会同步反映到列表页与仪表盘
- 构建验收：`npm run build` 已通过

后端 D4 已具备真实联调能力：

- `PUT /pipelines/:id/provider` 已可在 `start` 前切换 provider，并真实影响后续 pipeline 启动 provider
- `GET /metrics/pipelines` 已返回真实 token / duration 聚合
- 当前前端默认仍走 `MSW mock`，真实 API 接线放在 D5

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

## 验收建议

本地验收顺序建议如下：

1. `npm run dev`
2. 打开 `http://localhost:4173`
3. 手动验证列表页、详情页、仪表盘联动
4. `npm run build`

重点关注：

- 详情页状态切换后，列表页和仪表盘是否同步更新
- Provider 切换后，Provider 分布是否变化
- checkpoint approve/reject 后，状态分布是否变化
- `updated_at` 是否跟随 mock 写操作刷新
