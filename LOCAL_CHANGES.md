# 本地变更记录（LOCAL_CHANGES）

> 用途：记录本仓库相对于上游 `HKUDS/Vibe-Trading` 的本地定制内容，方便以后同步上游更新时快速处理冲突。
> 最后更新：2026-07-30

## 一、分支与仓库结构

| 项 | 说明 |
|---|---|
| `origin` | 我的 fork：`git@github.com:hzgyxczj/Vibe-Trading.git` |
| `upstream` | 上游官方仓库：`git@github.com:HKUDS/Vibe-Trading.git` |
| `main` | 纯同步分支，与 upstream/main 保持一致，**不放自己的改动** |
| `local-dev` | 开发分支，包含全部本地定制改动（作者：zhujie41631），推送到 `origin/local-dev` |

> 注意：upstream 曾重写过历史（force push），因此 main 与 upstream 之间不能靠普通 merge 同步，需要重置 + force push（见第五节）。

## 二、本地定制改动清单（local-dev 上，共 15 个提交）

### 1. QMT（miniQMT）数据与交易集成 —— 核心本地功能
| 文件 | 说明 |
|---|---|
| `agent/backtest/loaders/qmt_bridge.py` | QMT xtdata 桥接层（新增） |
| `agent/backtest/loaders/qmt_loader.py` | QMT 行情数据 loader（新增） |
| `agent/src/tools/qmt_ops_bridge.py` | QMT 实盘操作桥接（新增） |
| `agent/src/tools/qmt_daily_ops_tool.py` | QMT 每日运维/操作工具（新增） |
| `get_today_ops.py`（仓库根目录） | 每日运维脚本（新增） |
| `agent/backtest/loaders/registry.py` | 注册了 qmt 数据源 |
| `agent/src/tools/market_data_tool.py` | market data 工具接入 qmt |
| `agent/.env.example` | 增加了 daily ops 相关配置示例 |

相关提交：`5650e132`、`d2116ca8`、`f606f3a4`

### 2. 禁用 okx / yfinance loader
| 文件 | 说明 |
|---|---|
| `agent/src/config/env_schema.py` | 新增 `VIBE_TRADING_DISABLED_LOADERS` 配置项 |
| `agent/backtest/loaders/okx.py` | 增加禁用检查 |
| `agent/backtest/loaders/yfinance_loader.py` | 增加禁用检查 |
| `agent/backtest/loaders/registry.py` | 注册时过滤被禁用的 loader |
| `agent/src/live/enforcement.py`、`agent/src/preflight.py` | 相应适配 |

运行时通过 `agent/.env` 中 `VIBE_TRADING_DISABLED_LOADERS=okx,yfinance` 生效。
相关提交：`165f1e2e`、`b809aeaf`

### 3. 删除 local_loader（有意删除，勿恢复）
`636185e8` 删除了 `agent/backtest/loaders/local_loader.py` 及全部引用，涉及文件：
`agent/SKILL.md`、`agent/backtest/benchmark.py`、`agent/backtest/engines/base.py`、`agent/backtest/loaders/registry.py`、`agent/src/agent/context.py`、`agent/src/market_data.py`、`agent/src/skills/data-routing/SKILL.md`、`agent/src/tools/market_data_tool.py` 及多个测试文件。
本地数据改用 TDX 目录 + QMT 方案。

### 4. LLM 调整
`738b610e`：`agent/src/providers/llm.py` —— 从 langchain 参数中移除 `top_p`（当前使用的 agnes 网关不支持）。

### 5. api_server 模块解析修复
`52385edf`、`1425f9cd`：新增 `agent/__init__.py`，修复 `agent/src/api/` 下 12 个路由模块的导入路径与转义语法错误（alpha/auth/channels/live/qveris/runs/scheduled/sessions/settings/swarm/system/uploads_routes.py）。

### 6. 本地启动脚本
`start.bat`（仓库根目录）：本地一键启动脚本。
`a8ec0bff`：`.gitignore` 增加忽略 `api_server`/`vt.ps1` 等本地文件。

## 三、本地独有配置（git 不跟踪，勿提交）

`agent/.env`（已被 .gitignore 忽略），关键配置项：

| 变量 | 用途 |
|---|---|
| `LANGCHAIN_PROVIDER` / `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LANGCHAIN_MODEL_NAME` | LLM 网关（agnes）接入，**密钥不要写入任何文档/提交** |
| `TUSHARE_TOKEN` | Tushare 数据 token，**同上** |
| `VIBE_TRADING_DISABLED_LOADERS=okx,yfinance` | 禁用 loader |
| `VIBE_TRADING_ALLOWED_FILE_ROOTS=D:\software\new_tdx\vipdoc` | 允许的本地文件根目录（通达信数据） |
| `QMT_DIR=D:\software\miniQMT` | miniQMT 安装目录 |

## 四、合并上游时的冲突处理原则

同步 upstream 到 local-dev 遇到冲突时，按以下原则解决：

1. **`agent/backtest/loaders/local_loader.py` 及其引用**：保持删除（参考 `c6f7bebf`）。
2. **数据源注册（registry / market_data_tool）**：保留 qmt、mt5、local 等全部数据源，不互相顶替（参考 `8451211e`）。
3. **okx / yfinance loader**：保留禁用检查逻辑。
4. **`agent/src/providers/llm.py`**：保留"移除 top_p"的改动。
5. **`agent/src/api/*_routes.py`**：若上游重写了导入方式，需重新验证本地模块解析修复是否仍需要。
6. **`.gitignore`、`start.bat`、`get_today_ops.py`、`agent/.env`**：纯本地文件，保持不动。

## 五、以后更新的标准流程

### A. 只同步 fork 的 main（不影响 local-dev）

```powershell
git fetch upstream
git branch -f main upstream/main
git push --force origin main   # upstream 重写过历史，需 force push；确认 main 无自有提交后执行
```

### B. 把上游最新内容合入开发分支 local-dev

```powershell
git checkout local-dev
git fetch upstream
git merge upstream/main      # 或 git merge main
# 按第四节的原则解决冲突后提交
git push origin local-dev
```

### C. 检查本地改动是否完整（更新前后各跑一次，便于对比）

```powershell
git log 531ee6b2..local-dev --author=zhujie41631 --oneline
```

当前本地提交（基线 `531ee6b2`，旧 main）：

```
f606f3a4 daily ops tool added
d2116ca8 qmt
b809aeaf okx，yfinance loader disabled
165f1e2e yfinance okx loader disabled check added
c6f7bebf Merge upstream/main: keep local_loader.py deleted
636185e8 remove local_loader
5650e132 qmt: add bridge for QMT xtdata
8451211e Merge upstream/main: keep both local and mt5 data sources
738b610e llm: remove top_p from langchain
1425f9cd fix: repair syntax errors in route modules caused by incorrect escaping
52385edf fix: resolve api_server module resolution error
eea9f1ef Merge branch 'main' of github.com:HKUDS/Vibe-Trading into local-dev
484e2c83 Merge remote-tracking branch 'upstream/main' into local-dev
79c512d1 1
a8ec0bff chore: local dev setup (loader tweaks, start.bat, ignore api_server/vt.ps1)
```
