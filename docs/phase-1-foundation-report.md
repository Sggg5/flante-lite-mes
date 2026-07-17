# 阶段 1：项目基础框架完成报告

## 1. 完成范围

- Vue 3 + TypeScript + Vite + Element Plus 前端工程。
- FastAPI + SQLAlchemy 2 + Alembic 后端工程。
- 本地 SQLite 默认配置与 PostgreSQL `postgresql+psycopg` 配置入口。
- 用户、角色、权限、用户角色、角色权限和审计日志基础表。
- Argon2 密码哈希、JWT 登录、当前用户和后端权限依赖。
- 修改用户角色时记录操作者、请求号、前值、后值和原因。
- 登录页、系统主布局、左侧菜单、工作台和八个空白业务路由。
- PostgreSQL、后端、Nginx 前端三服务 Docker Compose。
- `/health` 服务/数据库健康检查。
- pytest、Vitest、前端类型检查和生产构建。
- 根目录与前端 `.env.example`，真实 `.env` 被忽略。
- README Windows 本地启动、Docker 启动、迁移和测试说明。

明确未开发：Excel 导入、补库计算、生产需求业务、排产、报工及其数据表/API/页面。

## 2. 数据库基础

首个迁移：`20260717_0001_identity_foundation.py`。

创建表：

- `users`
- `roles`
- `permissions`
- `user_roles`
- `role_permissions`
- `audit_logs`
- Alembic 自身的 `alembic_version`

初始化命令会幂等创建 ADMIN、PLANNER、FOREMAN、VIEWER 四角色和 `system.view`、`user.manage`、`audit.view` 三个基础权限，并按环境变量创建管理员。管理员密码没有代码内可用默认值。

## 3. 验证命令与结果

### 3.1 后端测试

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest
```

结果：5 个测试全部通过。覆盖健康检查、JWT 登录、错误密码统一响应、未认证 401、无权限 403、角色变更与审计前后值。

环境提示：FastAPI 当前依赖对 `starlette.testclient` 给出 1 条上游弃用警告，不影响测试结果；后续依赖升级时跟踪。

### 3.2 Alembic 迁移链

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.scripts.init_db
.\.venv\Scripts\python.exe -m alembic downgrade base
.\.venv\Scripts\python.exe -m alembic upgrade head
```

结果：升级、初始化、降级和再次升级全部成功；最终 SQLite 表结构已核对。

另执行 `python -m alembic check`，结果为 `No new upgrade operations detected`；说明 SQLAlchemy 模型与当前迁移一致。`python -m compileall -q app tests` 同样通过。

### 3.3 本地 API 运行验证

以隐藏后台进程启动 Uvicorn 后调用：

- `GET /health`：`status=ok`、`database=ok`、`version=0.1.0`。
- `POST /api/v1/auth/login`：返回 `token_type=bearer`，有效期 28,800 秒。

验证结束后已停止临时 Uvicorn 进程。

### 3.4 前端类型检查

```powershell
cd frontend
npm.cmd run type-check
```

结果：通过，无 TypeScript 错误。首次运行发现 Vite 配置的测试类型来源错误，改用 `vitest/config` 后重新执行通过。

### 3.5 前端测试

```powershell
npm.cmd run test:run
```

结果：2 个测试文件通过，覆盖认证状态清理和登录页账号/密码/提交入口渲染。

### 3.6 前端生产构建

```powershell
npm.cmd run build
```

结果：构建成功。Vite 输出 Element Plus 首包大于 500 kB 的优化提示以及第三方依赖 PURE 注释提示，均非构建失败；业务页面增加后应按路由拆包并评估按需引入 Element Plus。

### 3.7 Docker Compose

要求命令：

```powershell
docker compose up --build -d
docker compose ps
```

本机结果：**未能执行实机启动**。当前 Windows 环境未安装 Docker CLI/Docker Desktop、Podman 或 Rancher Desktop，也没有可用 WSL 发行版。因此不能声称容器已启动成功。

已完成的替代静态验证：

- `compose.yaml` 可被 YAML 解析器读取；服务集合严格为 `postgres`、`backend`、`frontend`。
- backend 等待 PostgreSQL `service_healthy`，frontend 等待 backend `service_healthy`。
- 两个 Dockerfile、Nginx 配置、Python 项目描述和 npm lockfile 均存在。
- PostgreSQL、后端和前端都配置健康检查。

验收机安装并启动 Docker Desktop 后，应严格按 README 执行 Compose 命令，补记 `docker compose ps`、`/health` 和登录验证结果。这是本阶段唯一未完成的环境实机验证。

## 4. 新增和修改文件

### 根目录

- 新增 `.env.example`
- 新增 `.gitignore`
- 新增 `compose.yaml`
- 修改 `README.md`
- 新增 `docs/phase-1-foundation-report.md`

### 后端

- `backend/.dockerignore`
- `backend/Dockerfile`
- `backend/pyproject.toml`
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/alembic/script.py.mako`
- `backend/alembic/versions/20260717_0001_identity_foundation.py`
- `backend/app/__init__.py`
- `backend/app/main.py`
- `backend/app/core/__init__.py`
- `backend/app/core/config.py`
- `backend/app/core/database.py`
- `backend/app/core/errors.py`
- `backend/app/core/security.py`
- `backend/app/models/__init__.py`
- `backend/app/models/identity.py`
- `backend/app/schemas/__init__.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/common.py`
- `backend/app/services/__init__.py`
- `backend/app/services/audit.py`
- `backend/app/services/identity.py`
- `backend/app/api/__init__.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/router.py`
- `backend/app/api/routes/__init__.py`
- `backend/app/api/routes/auth.py`
- `backend/app/api/routes/health.py`
- `backend/app/api/routes/users.py`
- `backend/app/scripts/__init__.py`
- `backend/app/scripts/init_db.py`
- `backend/tests/conftest.py`
- `backend/tests/test_auth.py`
- `backend/tests/test_health.py`

### 前端

- `frontend/.dockerignore`
- `frontend/.env.example`
- `frontend/.nvmrc`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tsconfig.json`
- `frontend/tsconfig.app.json`
- `frontend/tsconfig.node.json`
- `frontend/vite.config.ts`
- `frontend/src/env.d.ts`
- `frontend/src/main.ts`
- `frontend/src/App.vue`
- `frontend/src/api/http.ts`
- `frontend/src/api/auth.ts`
- `frontend/src/api/health.ts`
- `frontend/src/stores/auth.ts`
- `frontend/src/router/index.ts`
- `frontend/src/layouts/MainLayout.vue`
- `frontend/src/views/LoginView.vue`
- `frontend/src/views/DashboardView.vue`
- `frontend/src/views/PlaceholderView.vue`
- `frontend/src/styles/main.css`
- `frontend/tests/setup.ts`
- `frontend/tests/auth-store.spec.ts`
- `frontend/tests/login-view.spec.ts`

虚拟环境、`node_modules`、构建产物、SQLite 数据库和真实 `.env` 均被 `.gitignore` 排除，不属于交付文件。

## 5. 验收注意事项

- 首次使用必须从 `.env.example` 复制 `.env` 并替换所有密钥/密码占位值。
- 本地初始化顺序是 Alembic 升级后运行 `python -m app.scripts.init_db`。
- Docker 验收必须在具备 Docker Desktop 的环境补跑，不能用静态 YAML 校验替代最终验收。
- 阶段 1 完成后停止，不进入 Excel、补库、排产或报工开发。
