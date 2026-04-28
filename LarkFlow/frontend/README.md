# Frontend Scaffold

这是基于 `Vite + React + TypeScript + MSW` 的前端脚手架，当前目标是：

- 按 `pipeline/contracts.py` / `pipeline/api/routes.py` 的冻结契约建控制台外壳
- 在真实 API 联调前，全部通过 `MSW` mock 跑通列表页、详情页、首页、仪表盘
- 后续只替换数据源，不重做页面结构

## 目录约定

```text
frontend/
  src/
    lib/api.ts
    mocks/
      browser.ts
      handlers.ts
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
