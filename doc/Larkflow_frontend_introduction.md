# Larkflow - 前端说明文档

## 1. 简介

代码位于项目中的 `LarkFlow/frontend/` 目录下。当前阶段的前端控制台采用 `MSW mock` 方式运行，主要目标是先稳定页面结构、交互流程和契约消费方式。因此，在默认情况下，即使后端服务未启动，前端页面也可以单独运行和演示。

当前实现基于以下技术栈：

- `Vite`
- `React 18`
- `TypeScript`
- `react-router-dom`
- `MSW`

开始前，请确认本机已安装 `Node.js` 以及 `npm`。建议先执行以下命令确认环境可用：

```bash
node -v
npm -v
```

如果命令无法执行，请先完成 `Node.js` 环境安装，再继续后续步骤。

## 2. 首次启动

### 2.1 进入前端目录

```bash
cd LarkFlow/frontend
```

### 2.2 安装依赖

该命令用于安装 `package.json` 中定义的全部前端依赖。

```bash
npm install
```

### 2.3 初始化 MSW Worker

该命令用于生成浏览器侧 `mockServiceWorker.js` 文件。  
这是 `MSW` 生效的必要步骤，仅在首次初始化或该文件被删除后需要重新执行。

```bash
npx msw init public/ --save
```

### 2.4 启动开发服务器

```bash
npm run dev
```

启动成功后，终端中将显示本地访问地址。当前默认地址为：`http://localhost:4173`

## 3. 日常启动

如果已经完成过依赖安装和 `MSW` 初始化，后续日常开发只需要执行：

```bash
cd LarkFlow/frontend
npm run dev
```

## 4. 页面访问入口

前端启动后，可访问以下页面：

- `http://localhost:4173/`
  首页，用于说明当前控制台能力和后续联调方向

  ![frontend](assets/larkflow-fronted/img1.png)

- `http://localhost:4173/pipelines`
  Pipeline 列表页，支持 mock 创建、搜索、状态筛选、Provider 筛选
  
  ![frontend](assets/larkflow-fronted/img2.png)

- `http://localhost:4173/pipelines/DEMAND-a1f2c3d4`
  Pipeline 详情页，支持状态切换、Provider 切换、checkpoint approve/reject、artifact 预览
  
  ![frontend](assets/larkflow-fronted/img3.png)

- `http://localhost:4173/dashboard`
  仪表盘页，展示 mock 指标汇总、状态分布、Provider 分布和耗时排名
  
  ![frontend](assets/larkflow-fronted/img4.png)