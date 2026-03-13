# 法律 RAG 工程壳（可运行）

已按《需求文档.md》《技术方案.md》实现基础链路：
- 后端：`/api/v1/docs`、`/api/v1/chat`、`/api/v1/retrieve`、`/api/v1/citations`、`/api/v1/experiments`
- 数据层：PostgreSQL 持久化（documents/chunks/citations/messages/runs）
- 前端：`legalRag` 接口层 + `/legal-shell` 联调页（阻塞/流式问答、引用高亮、实验评测）

> 仅供学习与辅助检索，不构成正式法律意见。

## 目录

```text
medical-rag-system/
├── backend/
│   └── app/
│       ├── core/rag_engine.py             # 业务层
│       ├── repositories/pg_repository.py  # 数据层
│       ├── routers/{docs,chat,retrieve,citations}.py
│       └── main.py
└── frontend/
    ├── app/legal-shell/page.tsx
    └── lib/api/legalRag.ts
```

## 启动说明

清晰版启动文档见 [STARTUP.md](./STARTUP.md)。

## Docker 部署

默认命令：

```bash
docker compose -f medical-rag-system/docker-compose.yml up -d --build
```

默认构建的是“基础可部署版”：
- 可以完整启动 PostgreSQL、后端、前端
- 后端默认使用内存向量检索 + hash embedding + 启发式 rerank 回退路径
- 不会在构建阶段强制下载超大的 `torch` wheel

如果确实需要真实 embedding / Cross-Encoder / Chroma 持久化：

```bash
$env:BACKEND_INSTALL_ML='true'
docker compose -f medical-rag-system/docker-compose.yml up -d --build
```

启动后访问：
- 前端：`http://localhost:3000`
- 后端健康检查：`http://localhost:8001/health`

## 本地启动（推荐先跑后端）

### 1) 后端

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如需 ML 增强：

```bash
pip install -r requirements-ml.txt
```

### 2) 前端

```bash
cd frontend
npm install
npm run dev
```

联调页：`http://localhost:3000/legal-shell/`

