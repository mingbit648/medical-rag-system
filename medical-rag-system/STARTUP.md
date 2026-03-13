# 启动文档

本文档只覆盖当前仓库的实际启动方式，分为两种：
- 默认基础模式：优先保证 Docker 可快速部署
- ML 增强模式：启用真实 embedding 与 Cross-Encoder，构建明显更慢

## 1. 前置条件

需要本机已安装：
- Docker Desktop
- PowerShell

建议确认 Docker 正常运行：

```powershell
docker version
docker compose version
```

## 2. 默认 Docker 启动（推荐）

适用场景：
- 先把系统完整跑起来
- 验证前后端接口、页面、文档导入、会话、基础检索链路
- 避免构建阶段下载超大的 `torch` wheel

执行命令：

```powershell
cd C:\Users\lmd16\Desktop\medical-rag-system
docker compose -f medical-rag-system/docker-compose.yml up -d --build
```

默认行为：
- 启动 `postgres`
- 构建并启动 `backend`
- 构建并启动 `frontend`
- 后端使用基础依赖运行
- 若未安装 `sentence-transformers` / `torch`，后端自动回退到 hash embedding 与启发式 rerank

查看状态：

```powershell
docker compose -f medical-rag-system/docker-compose.yml ps
```

健康检查：

```powershell
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:3000/
```

访问地址：
- 前端首页：`http://localhost:3000`
- 联调页：`http://localhost:3000/legal-shell/`
- 后端健康检查：`http://localhost:8001/health`

## 3. ML 增强模式启动

适用场景：
- 需要真实 embedding
- 需要 Cross-Encoder rerank
- 可以接受更长的镜像构建时间

执行命令：

```powershell
cd C:\Users\lmd16\Desktop\medical-rag-system
$env:BACKEND_INSTALL_ML='true'
docker compose -f medical-rag-system/docker-compose.yml up -d --build
```

说明：
- 这个模式会额外安装 `requirements-ml.txt`
- 其中包含 CPU 版 PyTorch
- 首次构建时间会明显更长

构建完成后，如果不想影响后续默认构建，可关闭当前终端，或执行：

```powershell
Remove-Item Env:BACKEND_INSTALL_ML
```

## 4. 彻底清理后重启

如果要从干净状态重新部署：

```powershell
cd C:\Users\lmd16\Desktop\medical-rag-system
docker compose -f medical-rag-system/docker-compose.yml down --remove-orphans --volumes
docker compose -f medical-rag-system/docker-compose.yml up -d --build
```

## 5. 常见问题

### 构建卡在 `pip install`

现象：
- 构建长时间停在 `torch` 或 `sentence-transformers`

原因：
- 你启用了 ML 增强模式，或旧镜像缓存仍在重建完整 ML 依赖

建议：
- 优先使用默认基础模式
- 如确实需要 ML 模式，接受首次构建较慢是正常现象

### `docker compose ps` 有旧容器

现象：
- 出现当前 compose 文件里没有的旧服务

处理：

```powershell
docker compose -f medical-rag-system/docker-compose.yml down --remove-orphans --volumes
```

### 前端 3000 可访问，但后端不可用

检查：

```powershell
docker compose -f medical-rag-system/docker-compose.yml ps
docker compose -f medical-rag-system/docker-compose.yml logs backend --tail 200
```

### PostgreSQL 启动失败

检查端口 `5432` 是否已被本机其他数据库占用。

## 6. 本地非 Docker 启动

后端：

```powershell
cd C:\Users\lmd16\Desktop\medical-rag-system\medical-rag-system\backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

如需 ML 增强：

```powershell
pip install -r requirements-ml.txt
```

前端：

```powershell
cd C:\Users\lmd16\Desktop\medical-rag-system\medical-rag-system\frontend
npm install
npm run dev
```

