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

## 6. 阶段 1 审查修复补充

本次仅修复阶段 1 基础框架审查问题，未进入阶段 2，未开发 Excel 导入、补库计算、排产或报工功能。

### 6.1 管理员保护

- 角色修改接口会阻止移除最后一个启用状态 `ADMIN` 用户的管理员角色。
- 唯一管理员移除自己的 `ADMIN` 角色时返回稳定错误码 `CANNOT_REMOVE_LAST_ADMIN`。
- 其他有 `user.manage` 权限的用户尝试让系统不存在管理员时返回稳定错误码 `LAST_ADMIN_REQUIRED`。
- `init_db` 对已存在的初始管理员不会重置密码；如果该用户缺少 `ADMIN` 角色或处于停用状态，会恢复为启用管理员。

新增测试：

- `backend/tests/test_admin_protection.py::test_last_admin_cannot_remove_own_admin_role`
- `backend/tests/test_admin_protection.py::test_role_change_cannot_leave_system_without_admin`
- `backend/tests/test_admin_protection.py::test_init_db_restores_admin_role_without_resetting_password`

### 6.2 生产配置安全

- `APP_ENV=production` 时拒绝开发默认 `SECRET_KEY`。
- `SECRET_KEY` 长度必须至少 32 位。
- 生产环境必须设置 `INITIAL_ADMIN_PASSWORD`。
- 生产环境必须显式设置 `CORS_ORIGINS`。

新增测试：

- `backend/tests/test_config.py::test_development_settings_allow_local_cors_default`
- `backend/tests/test_config.py::test_production_rejects_development_secret_key`
- `backend/tests/test_config.py::test_secret_key_must_be_at_least_32_characters`
- `backend/tests/test_config.py::test_production_requires_initial_admin_password`
- `backend/tests/test_config.py::test_production_requires_explicit_cors_origins`
- `backend/tests/test_config.py::test_valid_production_settings_are_accepted`

### 6.3 请求编号安全

- `X-Request-ID` 最大长度为 64 位。
- 仅允许字母、数字、短横线和下划线。
- 缺失、超长或包含非法字符时自动生成 UUID。
- 规范化后的请求编号会写入响应头和审计日志，避免 PostgreSQL 审计日志字段超长失败。

新增测试：

- `backend/tests/test_request_id.py::test_valid_request_id_is_preserved_in_response_and_audit_log`
- `backend/tests/test_request_id.py::test_overlong_request_id_is_replaced_before_audit_log_write`
- `backend/tests/test_request_id.py::test_request_id_with_invalid_characters_is_replaced`

### 6.4 CI 和测试数据规则

- 新增 `.github/workflows/ci.yml`，PR 和 push 时执行后端、前端和 Docker Compose 三类验证。
- Docker CI 会真实构建镜像、启动 PostgreSQL/backend/frontend、等待健康检查、检查 `/health`、检查前端首页并调用登录接口做冒烟测试，结束后执行 `docker compose down -v`。
- 新增 `docs/脱敏测试数据规则.md`，明确不得提交客户名称、价格金额、真实订单号、真实批次号、员工信息和未脱敏经营数据。
- 新增 `tests/fixtures/README.md`，为阶段 2 预留虚拟产品编码和虚拟数量的测试样本规则。

### 6.5 本次验证结果

- 后端：`.\.venv\Scripts\python.exe -m pytest`，结果 `17 passed, 1 warning`。
- Alembic：`.\.venv\Scripts\python.exe -m alembic upgrade head`、`downgrade base`、再次 `upgrade head`、`check` 均通过，`check` 输出 `No new upgrade operations detected.`。
- 前端类型检查：`npm.cmd run type-check` 通过。
- 前端测试：`npm.cmd run test:run`，结果 `2 passed`。
- 前端构建：`npm.cmd run build` 通过；存在 Vite/Rollup 对第三方 PURE 注释和 chunk 大小的 warning，不影响构建结果。
- 本机 Docker Compose：当前 Windows 环境没有 Docker CLI，`docker compose version` 返回 `The term 'docker' is not recognized`，因此本机无法实际启动容器。
- GitHub Actions：PR 和 push 触发的两组 CI 均已通过。
- GitHub Actions Docker Compose：已真实执行 `docker compose config`、`docker compose build`、`docker compose up -d --wait --wait-timeout 240`、`curl http://localhost:8000/health`、`curl http://localhost:8080/`、登录接口冒烟测试和 `docker compose down -v`，结果通过。
