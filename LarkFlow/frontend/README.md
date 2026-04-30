# Frontend Scaffold

这是基于 `Vite + React + TypeScript + MSW` 的前端控制台。

当前已支持两种运行模式：

- live API：真实请求后端 REST API
- MSW mock：本地 mock 数据源，用于脱离后端演示和页面开发

D5 已完成的真实 API 接线范围：

- 列表页：先读 `GET /metrics/pipelines`，再补 `GET /pipelines/{id}`
- 仪表盘：复用同一套真实聚合数据源
- 详情页：读取 `GET /pipelines/{id}` 和 `GET /pipelines/{id}/stages/{stage}/artifact`

当前已经落地：

- 首页：能力说明与后续联调顺序
- Pipeline 列表页：创建 pipeline、搜索、状态筛选、Provider 筛选
- Pipeline 详情页：`start/pause/resume/stop`、Provider 切换、checkpoint approve/reject、artifact 预览
- 仪表盘：Pipeline 总数、耗时、token、状态分布、Provider 分布
- 保留 `MSW` mock 作为开发态回退
- 构建验收：`npm run build` 已通过

后端 D4-D5 已具备真实联调能力：

- `PUT /pipelines/:id/provider` 已可在 `start` 前切换 provider，并真实影响后续 pipeline 启动 provider
- `GET /metrics/pipelines` 已返回真实 token / duration 聚合
- D5 已完成真实 API 接线
- 当前开发态若未配置 `VITE_API_BASE_URL`，默认走 `MSW`
- 显式设置 `VITE_USE_MSW=0` 且提供 `VITE_API_BASE_URL` 时，走真实后端

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

## 启动方式

mock 模式：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
VITE_USE_MSW=1 npm run dev
```

live API 模式：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
VITE_USE_MSW=0 VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

如果不显式传环境变量：

- 开发态未配置 `VITE_API_BASE_URL` 时，默认启用 `MSW`

## 当前 API / mock 覆盖范围

真实 API 与 MSW 当前共同覆盖以下契约：

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
4. 视需要切换 `MSW` 或 live API 模式
5. `npm run build`

重点关注：

- 详情页状态切换后，列表页和仪表盘是否同步更新
- Provider 切换后，Provider 分布是否变化
- checkpoint approve/reject 后，状态分布是否变化
- live API 模式下 `/metrics/pipelines` 与 `GET /pipelines/:id` 是否返回 JSON
