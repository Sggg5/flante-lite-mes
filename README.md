# 福兰特轻量生产计划执行系统

面向不锈钢管材、管件制造企业的轻型 MES。阶段 1 已建立 Vue 3 前端、FastAPI 后端、JWT 身份验证、RBAC/审计基础表、数据库迁移、测试与 Docker Compose 骨架。

当前明确不包含 Excel 导入、补库计算、生产需求业务、排产和报工功能；对应菜单仅为占位路由。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、Vitest。
- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、pytest。
- 数据库：Windows 本地开发默认 SQLite；Docker/生产配置预留 PostgreSQL 16。
- 部署：Docker Compose，Nginx 托管前端并代理 API。

## 项目结构

```text
flante-lite-mes/
├─ backend/                 FastAPI、SQLAlchemy、Alembic、pytest
├─ frontend/                Vue 3、登录页、主布局和占位路由
├─ docs/                    阶段分析、设计与完成报告
├─ compose.yaml             PostgreSQL、后端、前端
├─ .env.example             环境变量模板，不含真实密钥
└─ README.md
```

## Windows 本地启动

### 1. 准备环境变量

要求 Python 3.12 和 Node.js 22 LTS。PowerShell 在仓库根目录执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少替换 `SECRET_KEY`、`INITIAL_ADMIN_PASSWORD` 和 `POSTGRES_PASSWORD`。`.env` 已加入 `.gitignore`，不得提交。

本地开发默认使用：

```text
DATABASE_URL=sqlite:///./data/flante_mes.db
```

相对路径从 `backend/` 解析，数据库文件会生成在 `backend/data/`。

### 2. 启动后端

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m alembic upgrade head
python -m app.scripts.init_db
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

若 PowerShell 禁止激活脚本，可不激活虚拟环境，改用：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.scripts.init_db
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

后端地址：

- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/health>

`init_db` 会幂等创建 ADMIN、PLANNER、FOREMAN、VIEWER 四个角色、基础权限和 `.env` 指定的管理员。系统没有内置可用的默认密码。

### 3. 启动前端

另开 PowerShell：

```powershell
cd frontend
npm install
npm run dev
```

前端地址：<http://localhost:5173>。Vite 会把 `/api` 和 `/health` 代理到本地后端。如果执行策略阻止 `npm.ps1`，使用 `npm.cmd install` 和 `npm.cmd run dev`。

## Docker Compose 启动

要求已安装并启动 Docker Desktop，且 `docker compose version` 可执行。

```powershell
Copy-Item .env.example .env
# 编辑 .env 中的三个密码/密钥项后再启动
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health
Invoke-WebRequest http://localhost:8080
```

访问地址：

- 前端：<http://localhost:8080>
- 后端健康检查：<http://localhost:8000/health>
- 后端 API 文档：<http://localhost:8000/docs>

停止服务但保留 PostgreSQL 数据卷：

```powershell
docker compose down
```

Compose 启动时会等待 PostgreSQL 健康，随后自动执行 Alembic 升级和管理员/角色初始化。生产环境应进一步配置 HTTPS、备份和密钥管理。

## 测试与构建

后端：

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head
```

前端：

```powershell
cd frontend
npm.cmd run type-check
npm.cmd run test:run
npm.cmd run build
```

阶段 1 的实际执行结果见 [阶段 1 完成报告](docs/phase-1-foundation-report.md)。

## 健康检查与认证接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 服务、版本和数据库连接状态 |
| POST | `/api/v1/auth/login` | 用户名/密码换取 JWT |
| GET | `/api/v1/auth/me` | 当前用户、角色和权限 |
| PUT | `/api/v1/users/{id}/roles` | ADMIN 权限修改用户角色并写审计 |
| GET | `/api/v1/users/permission-check` | 权限依赖的 401/403 骨架验证 |

所有请求响应带 `X-Request-ID`；认证和授权错误返回稳定的 `code`、`message`、`details` 和 `request_id`。密码只保存 Argon2 哈希，不进入 API 或审计日志。

## 阶段 0 文档

- [Excel 样表与现行业务分析](docs/phase-0-excel-analysis.md)
- [系统设计草案（ER、API、页面、导入映射）](docs/phase-0-system-design.md)
- [分阶段开发计划与第一阶段验收清单](docs/phase-0-development-plan.md)

## 开源项目研究

- [OpenMES、ERPNext、frePPLe、yuwang/MES 对比分析](docs/开源项目对比分析.md)
- [可借鉴数据模型](docs/可借鉴数据模型.md)
- [可借鉴页面设计](docs/可借鉴页面设计.md)
- [许可证风险说明](docs/许可证风险说明.md)
- [本项目最终架构建议](docs/本项目最终架构建议.md)
