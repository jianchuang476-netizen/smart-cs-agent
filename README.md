# Smart CS Agent

面向电商售后场景的企业级客服 Agent。项目演示从“客户提问”到“知识检索、订单工具、风险审批、动作执行和审计”的完整闭环，重点体现 LangGraph 编排、RAG 可评测性、Human-in-the-loop 和工程化能力。

## 架构

```text
React 客服工作台
        |
        v
FastAPI + JWT/RBAC + SSE
        |
        v
LangGraph Supervisor
  |         |          |
Knowledge  Order   After-sales
混合 RAG     MySQL   高风险中断/审批
  |                    |
Chroma              PostgreSQL checkpoint
                       |
                MySQL 业务与审计记录
                       |
                Redis / Celery / 通知适配器
```

核心组件：

- **LangGraph**：主管节点将请求路由到知识、订单、售后三个子图。
- **完整 RAG**：BGE Embedding + Chroma 向量检索、BM25、RRF 融合、BGE Reranker、引用来源。
- **HITL**：退款、补偿、取消订单等写操作通过 `interrupt()` 暂停，客服批准后从 checkpoint 恢复。
- **数据分离**：MySQL 保存业务数据，PostgreSQL 保存 LangGraph checkpoint，Redis 负责缓存、限流和 Celery。
- **安全**：Argon2、HttpOnly JWT Cookie、CSRF、RBAC、Redis 限流、PII 脱敏和审计日志。
- **可观测**：Langfuse 追踪模型/工具链路，Prometheus 指标和 Grafana 面板放入 `observability` profile。

## 快速启动

复制环境变量并填写新的 DeepSeek Key：

```powershell
Copy-Item .env.example .env
```


> Docker 构建默认使用 `wheels/torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl` 以避免拉取 CUDA 依赖。该本地缓存文件已在 `.gitignore` 中；全新环境缺少文件时，可执行：
>
> ```powershell
> New-Item -ItemType Directory wheels -Force | Out-Null
> curl.exe --ssl-no-revoke -L -o wheels/torch-2.9.1+cpu-cp312-cp312-manylinux_2_28_x86_64.whl "https://download-r2.pytorch.org/whl/cpu/torch-2.9.1%2Bcpu-cp312-cp312-manylinux_2_28_x86_64.whl"
> ```

启动核心服务：

```powershell
docker compose up --build -d
```

初始化 20 个客户、100 个订单、5 份政策和 RAG 索引：

```powershell
docker compose --profile tools run --rm bootstrap
```

打开：

- 客服工作台：http://localhost:5173
- FastAPI 文档：http://localhost:8002/docs
- API 备用端口：http://localhost:8002
- Chroma：http://localhost:8001
- Prometheus：http://localhost:9090
- Grafana：http://localhost:3000

启动完整可观测组件：

```powershell
docker compose --profile observability up -d
```

首次运行会下载 `BAAI/bge-small-zh-v1.5` 和 `BAAI/bge-reranker-base`，建议预留至少 3 GB 模型缓存空间。模型缓存位于 `data/models`。

## 演示账号

所有账号密码均为 `Demo123!`：

| 角色 | 邮箱 | 能力 |
|---|---|---|
| 客户 | customer@example.com | 聊天、订单查询、发起售后 |
| 客服 | agent@example.com | 审批退款/补偿、查看会话 |
| 管理员 | admin@example.com | 客服能力 + 知识库管理 |

## 核心 API

- `POST /api/v1/auth/login`、`POST /refresh`、`POST /logout`、`GET /me`
- `POST /api/v1/chat/stream`：SSE 返回 `session`、`token`、`tool_call`、`citation`、`approval_required`、`done`、`error`
- `GET /api/v1/sessions`、`GET /api/v1/sessions/{id}/messages`
- `GET /api/v1/approvals?status=pending`
- `POST /api/v1/approvals/{id}/decision`：批准或拒绝后直接返回恢复执行 SSE
- `POST /api/v1/knowledge/documents`、`GET /documents`、`DELETE /documents/{id}`
- `POST /api/v1/knowledge/search-test`
- `GET /health/live`、`GET /health/ready`、`GET /metrics`

## 开发运行

使用项目已有虚拟环境：

```powershell
.\qiye_agent\Scripts\python.exe -m pip install -r requirements-dev.txt
.\qiye_agent\Scripts\python.exe -m scripts.bootstrap
.\qiye_agent\Scripts\python.exe -m uvicorn app.main:app --reload
```

前端：

```powershell
cd frontend
npm install
npm run dev
```

测试：

```powershell
.\qiye_agent\Scripts\python.exe -m pytest
cd frontend
npm run lint
npm test
npm run build
```

RAG 评测：

```powershell
.\qiye_agent\Scripts\python.exe tests/eval/run_eval.py
```

评测集位于 `data/eval/after_sales_eval.jsonl`，包含 50 条售后问题。真实模型评测需要配置 Key，CI 使用确定性路由和 FakeLLM 保证稳定。

## 面试讲解重点

1. Supervisor 如何将开放域问题限制在受控子图中。
2. 为什么退款必须先持久化审批记录，再调用 `interrupt()`。
3. PostgreSQL checkpoint 如何实现服务重启后的恢复。
4. 审批版本号和幂等键如何防止重复退款。
5. 混合检索为什么比单独向量检索更适合售后政策。
6. RAG、工具和审批如何分别评测，而不是只看最终回答。
7. 如何通过 SSE 将 token、工具状态和审批事件实时展示给前端。
8. 如何用结构化日志、Prometheus 和 Langfuse 定位线上 Agent 问题。

## 范围说明

当前版本聚焦单租户、中文优先的 Web/API 场景，不包含语音客服、模型微调、Kubernetes 和多云部署。生产环境需要把 `.env` 中的开发密钥换成密钥管理服务，并启用 HTTPS、Cookie Secure 和数据库备份。
