# 福兰特轻量生产计划执行系统

面向不锈钢管材、管件制造企业的轻型 MES。阶段 2 已在阶段 1 工程、认证、RBAC 和审计基础上建立 Excel 数据导入中心。

当前支持销售出货、实时库存、水管在制、管件在制、常规排产产品和现有周计划的上传、分析、映射、预览、校验、确认、问题下载及受控撤销。仍明确不包含补库建议计算、生产需求池、正式排产、工序任务和生产报工。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、Vitest。
- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Pydantic 2、Alembic、openpyxl、pytest。
- 数据库：Windows 本地开发默认 SQLite；Docker/生产配置预留 PostgreSQL 16。
- 部署：Docker Compose，Nginx 托管前端并代理 API。

## 项目结构

```text
flante-lite-mes/
├─ backend/                 FastAPI、SQLAlchemy、Alembic、Excel解析和pytest
├─ frontend/                Vue 3、登录、主布局和数据导入中心
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
阶段 2 的范围、测试与人工验收见 [阶段 2 完成报告](docs/phase-2-excel-import-report.md)。

## 健康检查与认证接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 服务、版本和数据库连接状态 |
| POST | `/api/v1/auth/login` | 用户名/密码换取 JWT |
| GET | `/api/v1/auth/me` | 当前用户、角色和权限 |
| PUT | `/api/v1/users/{id}/roles` | ADMIN 权限修改用户角色并写审计 |
| GET | `/api/v1/users/permission-check` | 权限依赖的 401/403 骨架验证 |
| POST | `/api/v1/imports/upload` | 安全上传 `.xlsx` 并建立批次 |
| GET/POST | `/api/v1/imports/{id}/sheets`、`/analyze` | 工作表与真实范围分析 |
| GET/PUT | `/api/v1/imports/{id}/preview`、`/mapping` | 预览与字段映射 |
| POST | `/api/v1/imports/{id}/validate` | 全量校验，不写业务表 |
| POST | `/api/v1/imports/{id}/confirm` | 事务确认导入 |
| POST | `/api/v1/imports/{id}/rollback` | 撤销未被后续业务引用的批次 |
| GET | `/api/v1/imports`、`/{id}`、`/{id}/issues` | 批次、详情与问题查询 |

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

## 阶段 1 审查修复

- 系统保护最后一个启用状态的 `ADMIN` 用户；角色修改不能导致系统没有管理员，`init_db` 会恢复配置的初始管理员 `ADMIN` 角色且不重置既有密码。
- 生产环境启动会校验 `SECRET_KEY`、`INITIAL_ADMIN_PASSWORD` 和显式 `CORS_ORIGINS`。
- `X-Request-ID` 会规范化为最多 64 位，且只允许字母、数字、短横线和下划线；非法值在进入审计日志前自动替换为 UUID。
- CI 会运行后端测试和 Alembic 升降级检查、前端类型检查/测试/构建，并真实启动 Docker Compose 做健康检查和登录冒烟测试。
- 测试数据脱敏规则见 [docs/脱敏测试数据规则.md](docs/脱敏测试数据规则.md)，不得提交真实 Excel 或未脱敏生产数据。

## 阶段 2：Excel 导入中心

- 上传文件只允许 `.xlsx`，默认限制 20 MB；服务端使用随机安全文件标识并计算 SHA-256，不使用原文件名作为路径。
- `openpyxl` 负责工作簿、公式、合并区域和单元格类型处理；服务端按连续空行截断真实数据范围，不遍历百万格式残留行。
- 上传和分析不会写正式快照表；只有状态为 `READY` 且没有错误行的批次可以事务确认。
- 产品编码以字符串保存；文本前导零保留，科学计数法和数值歧义会进入问题列表。
- 库存可用量统一复算为 `现存 + 预计入库 - 预计出库`；Excel 原值只用于差异警告。
- 负出货/在制数量保留原值并产生警告；不会在阶段 2 自动改为 0。
- `ADMIN` 拥有全部导入权限，`PLANNER` 可查看/上传/校验/确认，`VIEWER` 只读，`FOREMAN` 默认无导入权限。
- 测试工作簿由 pytest 或 CI 使用 openpyxl 动态生成，仓库忽略所有 `.xlsx` 文件。
- 隐藏数据行默认参与导入，并在原始元数据中保留隐藏标记；用户可主动选择仅导入可见行，批次会显示隐藏及排除数量。
- 库存、管材在制和管件在制的快照日期优先取 Excel 映射值，缺失时回退到上传数据日期；两者都缺失时禁止确认。
- 真实结构周计划支持制管、包装、成型、下料四类工作表和七日计划/实际。缺少产品编码的行只进入待匹配区，人工选择产品后才生成标准化周计划原始记录，不会按名称自动创建或确认产品。
- 产品主数据默认只补充现有空字段；跨批次名称、规格、类别或单位冲突会警告，非空字段仅允许管理员填写原因后明确覆盖，所有变更均审计并追溯最近导入批次。
- 问题 CSV 使用 UTF-8 BOM，并对潜在 Excel 公式文本做安全转义，同时保留合法负数数值和中文显示。
- 导入确认严格要求 `READY`，通过数据库锁和原子状态认领防止重复确认；映射、数据日期或解析选项变化后必须重新校验。
- 重复批次在上传、数据日期修改和确认前统一复查；PostgreSQL 使用事务级 advisory lock 保护并发窗口，管理员强制重复必须记录原因。
- 产品导入创建、补空和管理员覆盖均写入可逆变更记录；撤销批次会在同一事务中恢复产品与删除快照，存在后续引用或后续修改时整体拒绝撤销。
- 批次审计使用显式批次上下文关联产品变更、周计划匹配和撤销恢复，不依赖 JSON 模糊查询。
