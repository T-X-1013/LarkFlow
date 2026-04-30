# LarkFlow 安装与启动说明 v0.8

本文档记录当前主干状态下，LarkFlow 后端双入口与前端控制台的本地安装、启动与联调方式。

## 1. 目录约定

仓库根目录：

```text
/Users/tao/PyCharmProject/LarkFlow
```

Python 项目目录：

```text
LarkFlow/
```

前端目录：

```text
LarkFlow/frontend/
```

## 2. 后端环境准备

进入 Python 项目目录：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow
```

创建并激活虚拟环境：

```bash
python3 -m venv venv
source venv/bin/activate
```

安装依赖：

```bash
pip install -r requirements.txt
```

准备环境变量：

```bash
cp .env.example .env
```

至少需要检查以下关键项：

- `LLM_PROVIDER`
- `LARK_APP_ID`
- `LARK_APP_SECRET`
- `LARK_CHAT_ID`
- `LARK_RECEIVE_ID_TYPE`
- `DATABASE_URL`

## 3. 启动后端双入口

当前主干已支持双入口：

- 飞书 WebSocket 长连
- FastAPI HTTP 控制面

推荐启动方式：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow
source venv/bin/activate
python -m pipeline.app
```

启动后可访问：

- Swagger UI: `http://localhost:8000/docs`
- 健康检查: `http://localhost:8000/healthz`

如果只想单独启动飞书监听器，也可执行：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow
source venv/bin/activate
PYTHONPATH=. PYTHONUNBUFFERED=1 python -m pipeline.lark_interaction >> logs/lark_listener.log 2>&1
```

## 4. 前端环境准备

进入前端目录：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
```

安装依赖：

```bash
npm install
```

首次初始化 MSW worker：

```bash
npx msw init public/ --save
```

## 5. 启动前端控制台

开发模式：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
npm run dev
```

默认访问地址：

```text
http://localhost:4173
```

当前可访问页面：

- `/`
- `/pipelines`
- `/pipelines/DEMAND-a1f2c3d4`
- `/dashboard`

## 6. 前后端联调建议

当前前端支持 `MSW mock` 与真实 API 双模式。

建议联调顺序：

1. 启动后端 `python -m pipeline.app`
2. 先验证 `GET /healthz`
3. 再验证 `GET /metrics/pipelines`
4. 再验证 `GET /pipelines/{id}`
5. 最后联调详情页中的 Provider 更新、checkpoint 操作、artifact 预览等动作

mock 模式启动：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
VITE_USE_MSW=1 npm run dev
```

真实后端联调模式启动：

```bash
cd /Users/tao/PyCharmProject/LarkFlow/LarkFlow/frontend
VITE_USE_MSW=0 VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

## 7. 常见问题

### 7.1 `ReferenceError: id is not defined`

通常是 JSX 文案里误写了 `{id}` 这类表达式，导致 React 把它当变量求值。  
应改成普通文本或 `<code>/pipelines/:id</code>` 形式。

### 7.2 页面能打开但没有数据

先确认：

- `npm run dev` 是否正常启动
- 后端 `python -m pipeline.app` 是否已启动
- `GET /healthz` 是否返回 200
- 前端是否以 live API 模式启动
- `VITE_API_BASE_URL` 是否指向正确的后端地址
- 浏览器 Network 中 `/metrics/pipelines` 是否返回 JSON，而不是 HTML 或 404

### 7.3 飞书需求文档读取失败

优先检查：

- Base 里“需求文档”字段是否是真实飞书 `docx/wiki` 链接
- 链接是否误填为文本、目录、sheet 或无权限文档
- 飞书应用是否被加入文档协作者

## 8. 当前版本边界

`v0.8` 阶段已覆盖：

- 后端双入口启动说明
- 前端脚手架与 MSW 启动说明
- 控制台页面访问入口
- 基础联调步骤

后续可继续补充：

- docker-compose 启动方式
- CI 状态与构建产物说明
