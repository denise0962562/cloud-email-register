# iCloud HME — 多账号聚合管理平台

基于 iCloud Hide My Email 协议，批量创建 `@icloud.com` 隐私邮箱的商用聚合平台。

- 👥 **多账号管理** — 同时管理多组 iCloud 账号，每个独立存储、独立会话
- 🔗 **账号-别名映射** — 自动提取真实 Apple ID，每个隐私邮箱标注归属账号
- ⏱ **定时调度** — 整点自动触发，多账号轮询创建，触达上限自动切下一个
- 🌐 **Web UI** — 暖色面板，仪表盘 + 账号列表 + 别名管理 + 跨账号批量创建

## 前提条件

- **iCloud+ 订阅**（Hide My Email 需要 iCloud+）
- Python 3.10+
- Windows / macOS / Linux

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动 Web UI
python web_ui.py

# 3. 打开 http://127.0.0.1:5050
#    点击左下角「导入 Cookie」添加第一个账号
#    支持粘贴 Cookie Editor 的 Header String 或 JSON
```

### Windows 启动与重启

`start.sh` 是 macOS/Linux 的 shell 脚本，Windows 的 CMD/PowerShell 请使用 `start.cmd` / `restart.cmd`。仓库没有名为 `restart.sh` 的脚本。首次在 Windows 部署时，在项目目录执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.cmd
# 重启本项目服务
.\restart.cmd
```

默认监听 `http://127.0.0.1:5050`，参数可附在脚本后，例如 `.\start.cmd --port 8080`。窗口保持打开，关闭窗口会停止服务。重启脚本只停止本项目 Windows 虚拟环境中以绝对路径启动的 `web_ui.py`，不会按端口或 Python 进程名批量结束其他项目；旧的手动相对路径启动进程请先在其窗口按 Ctrl+C。重启时正在执行的任务可能中断，已确认成功记录及配置保留在 SQLite，自动任务按已保存设置恢复。macOS 的 `.venv` 不能复制到 Windows 使用，需重新创建 Windows 虚拟环境。

## 使用方式

### Web UI（推荐）

```bash
python web_ui.py                    # 启动 Web 界面
python web_ui.py --port 8080        # 指定端口
python web_ui.py --scheduler        # 启动时自动开启调度器
```

界面功能：

| 模块 | 功能 |
|------|------|
| **账号管理** | 添加/切换/删除账号，每个账号独立 Cookie + 会话 |
| **仪表盘** | 账号总数、总别名数、今日创建数，每账号一张状态卡片 |
| **别名列表** | 实时拉取所有别名，标注所属账号 + 真实邮箱 |
| **批量创建** | 勾选目标账号 → 输入数量 → 跨账号轮询创建 |
| **调度器** | 一键启停，每整点遍历所有活跃账号创建到上限 |

### 命令行调度器

```bash
# 多账号定时调度（需要先通过 Web UI 添加账号）
python scheduler.py

# 指定账号间间隔
python scheduler.py --interval 5

# 后台守护进程
python scheduler.py -d
```

### CLI 手动操作

```bash
# 列出所有别名
python icloud_hme.py list --cookies cookies.json

# 创建别名
python icloud_hme.py create -n 5 --cookies cookies.json

# 删除别名
python icloud_hme.py delete --email xxx@icloud.com --cookies cookies.json
```

## Cookie 获取

| 方式 | 说明 |
|------|------|
| Web UI 导入 | 点击左下角按钮，粘贴 Cookie Editor 的 Header String |
| Chrome 自动提取 | Windows 下 `python icloud_hme.py export-cookies` |
| 命令行 `--cookies` | 指定 JSON 文件路径 |

支持两种输入格式：
- **Header String**：`name1=value1; name2=value2; ...`
- **JSON**：`{"name1":"value1", "name2":"value2"}`

导入后自动持久化到项目目录 `icloud_hme.sqlite3`，重启无需重新粘贴。

## 一键创建与收件链接

使用 `./start.sh` 启动后，打开 `http://127.0.0.1:5050`：

1. 在「批量创建」中选择账号和数量（每账号 1–20 个）。
2. 点击「一键创建并配置收件」。后台自动创建 iCloud 隐藏地址、独立域名收件箱和仅匹配该别名的转发规则，并读回校验规则与收件凭据。
3. 结果文本框直接显示每行 `邮箱----收件链接`。可「复制本批文本」或「导出本批 TXT」。TXT 为 UTF-8 纯文本，每行一条，无标题、无 JSON 引号。

```text
别名1@icloud.com----https://webmail.fastaiapi.cloud/m/mbx_123456789.该邮箱的随机令牌
别名2@icloud.com----https://webmail.fastaiapi.cloud/m/mbx_987654321.另一个邮箱的随机令牌
```

当前复用账号已有的 `api.fastaiapi.cloud` 收件服务，收件域为 `fastaiapi.cloud`。`cloud_inbox/` 提供部署到 `webmail.fastaiapi.cloud/m/*` 的专属收件页：直接显示原 iCloud 别名、邮件列表及提取的验证码，每 10 秒自动刷新。每个别名分配独立域名收件箱和独立随机链接；公开页面不显示转发地址，不携带上游 JWT，也不能切换到其他邮箱。

本机 `gpt-auto-register` 的「iCloud 隐藏邮箱（中转）」已支持上述原始短链接：直接导入这里导出的 TXT 即可，程序自动读取链接下的 `/api/messages`，无需修改导出文本。同一链接可以在浏览器打开查看邮件。接收端会核对返回邮箱与导入地址一致，并按邮件 ID、时间过滤重复邮件和旧验证码。

开始前会检查 iCloud 会话和规则权限，并确认隐藏地址转发到本账号的 iCloud 邮箱。如果尚未设置且只有一个可用的 iCloud 邮箱，会自动将其设为默认转发目标（影响此账号隐藏地址的默认转发，不修改主邮箱的全局转发）。全新账号需先开通 iCloud 主邮箱；第一个隐藏地址保留后，再设置并读回确认默认转发目标，以兼容 Apple 的首次初始化要求。随后只添加 `发送至指定别名 → 转发至该别名独立域名邮箱` 的规则，不覆盖冲突规则。

部分失败会保留已创建的别名、域名收件箱和执行进度，停止本账号本轮继续创建，避免留下大量未配置邮箱。在「邮箱列表」点击「补全未完成配置」即可重试，复用原别名与收件箱。若请求超时，先读回规则再决定是否补建，避免重复规则。刷新浏览器后会继续查看同一后台任务；服务重启后任务查看状态失效，但仍可从已保存记录恢复和导出。

「邮箱列表」支持按账号筛选后复制或导出全部已配置记录。未完成配置的条目不混入最终文本。「收件已配置」表示已验证转发规则存在且收件凭据有效，不表示每个新地址都已实际收到测试邮件；Apple 提示规则生效可能需几分钟。遇到 Cookie 过期、服务验证要求或创建频率上限时会显示错误并停止，不绕过限制。

接口：

- `POST /api/create-jobs`：`{"account_ids":["账号ID"],"count_per_account":2,"label":"可选标签"}`，返回 `job_id`。补全已有记录可加 `"mode":"repair"`。
- `GET /api/create-jobs/{job_id}`：查询进度、每项结果及 `lines` / `output`，查询不会重复执行创建。
- `GET /api/create-jobs/{job_id}/export`：导出本批已配置成功的记录。
- `GET /api/inbox-links/export?account_id=账号ID`：按账号导出；省略参数导出全部已配置记录。

Cloudflare 页面只保存独立域名收件箱的读取凭据，不接收 Apple 登录 Cookie。`results/cloud_inbox_config.json` 保存本机注册链接所需的管理令牌，需完成首次 Cloudflare 部署后配置。首次部署使用 `cloud_inbox/wrangler.jsonc`，新 Worker 仅接管 `/m/*` 路由，保留已有临时邮箱站点；`schema.sql` 仅新增 `hme_public_inboxes` 表。

映射与恢复进度保存在被 Git 忽略的 `icloud_hme.sqlite3` 的 `inbox_links` 表，数据库文件权限为 600。导出内容含收件凭据，持链接者可以访问对应的独立收件箱。服务应保持仅本机访问。Web 界面、AccountManager 和调度器走完整流程；`icloud_hme.py create` 为底层仅创建别名的 CLI。

## 自动注册页面

打开 `http://127.0.0.1:5050/auto`，或点击管理面板的「自动注册」。该页面创建的是 iCloud 隐藏邮箱，并自动配置转发和专属收件链接。

账号元数据和 Cookie 分别存放在 SQLite 的 `accounts`、`account_sessions` 表，登录态按账号 ID 独立存储，并通过外键关联；旧版 JSON 和独立会话文件只导入一次，之后不再写入。每个客户端有独立的 Cookie 副本和 HTTP 会话，Apple 成功响应中的 Cookie 更新只保存回所属账号，已替换会话不会被旧客户端覆盖。调度器直接读取各账号会话，无需浏览器切号；某账号失败后仍继续处理其他账号。Apple 已失效或撤销的会话无法靠本地保存恢复，需对该账号重新登录一次。多个账号建议使用独立浏览器个人资料保持登录。

- 可选择执行账号、每账号每轮数量（1–20）、每个邮箱间隔（0–300 秒）、标签前缀。
- 每轮间隔可设固定分钟数，或最小 / 最大分钟范围；上一轮结束后选定本轮等待时间。保存配置立即生效，不重置已排定的下一轮时间；新数量用于随后启动的任务，新间隔用于下一次重新计时。默认每轮 5 个、间隔 60–90 分钟，首次开关默认关闭。
- 开启后先等待设定间隔；「立即执行一轮」异步提交任务，在开关关闭时也可只跑一轮。立即执行至少成功创建并配置 1 个邮箱才重置下一轮倒计时；全部失败时保留原计划（包括执行期间继续倒计时），自动定时轮次失败则正常安排下一轮，避免连续重试。任务与手动批量创建共用互斥队列，不会并行重复创建。
- 关闭开关会取消下一轮，当前正在处理的邮箱完成后停止，不再开始下一个。Apple 限流或配置失败时保留成功结果，结束本账号本轮，按配置等待下一轮。
- 页面显示北京时间、下次启动倒计时、每轮成功 / 失败数、最近 40 轮任务及 300 条日志，每轮提供「查看结果」弹窗、一键复制全部以及 TXT 下载；下载状态和最近下载时间会保存，刷新或重启后仍可查看。结果格式为 `邮箱----收件链接`，无成功结果时禁用查看和下载。
- 配置、开关、下次时间、任务摘要和日志保存在忽略的 `icloud_hme.sqlite3`。任务历史和下载状态持久化到 `tasks` 表，旧任务超出页面最近 40 轮后仍可按任务 ID 查询和导出。关闭网页不影响执行；重启服务恢复开关和等待时间。重启中断的轮次不会自动重复提交，已创建但未配完的邮箱可在邮箱列表补全。

API：`GET/POST /api/auto-registration` 读取或更新配置；`POST /api/auto-registration/run` 提交单轮任务；`GET /api/auto-registration/export` 导出最近一轮成功结果；`GET /api/auto-registration/tasks/{job_id}` 查询指定轮次；`GET /api/auto-registration/tasks/{job_id}/export` 下载并记录该轮下载状态（仅允许已结束且有成功结果的任务）。原 `/api/scheduler/start`、`stop` 也使用同一调度器。

## 文件结构

```
├── icloud_hme.py        # 核心库：Cookie 提取 / HME API / 账号身份提取
├── account_manager.py   # 多账号管理器：CRUD / 批量创建 / 别名索引
├── web_ui.py            # Flask Web 面板 + 内置调度器
├── scheduler.py         # 独立命令行调度器
└── requirements.txt     # pip 依赖
```

运行时生成：

```
icloud_hme.sqlite3      # 账号、独立登录态、邮箱链接、任务和邮件缓存
scheduler_state.json   # 调度器历史状态
logs/                  # 运行日志
results/               # 创建的邮箱列表
```

## 依赖

```
requests>=2.25          # HTTP
pycryptodome>=3.15     # Chrome cookie 解密 (Windows)
pywin32>=305           # Windows DPAPI (仅 Windows)
flask>=3.0             # Web UI
```

## License

MIT

## SQLite 存储与迁移

数据库位置固定为项目根目录 `icloud_hme.sqlite3`，使用 Python 标准库 sqlite3，无需单独安装数据库服务。写入使用事务、外键和 WAL；账号会话更新使用条件写入，旧客户端不能覆盖已经替换的新会话。数据库及其 WAL/SHM 文件已加入 Git 忽略规则。

主要表：`accounts`（账号元数据）、`account_sessions`（按账号独立的 Cookie）、`email_records`（创建记录）、`inbox_links`（完整收件映射和恢复进度）、`tasks`（每轮结果和下载状态）、`task_logs`（日志）、`documents`（调度配置、原始异步任务、缓存和服务配置）、`legacy_sources`（原始文件的逐字节归档）。

迁移入口为 `python migrate_sqlite.py`。部署迁移前应停止服务并备份；脚本按模块事务导入、记录已完成标记，并核对账号、会话、邮箱顺序、完整收件凭据、任务配置、日志和历史是否一致。重复导入不会覆盖数据库中新数据。旧 JSON/TXT 文件保留作迁移前恢复材料，修改旧文件不会更新运行数据。TXT/CSV 仍是独立导出文件。

运行中的数据库请用 SQLite 在线备份，不能只复制主文件而漏掉 WAL。例如：

```python
from storage import Storage
Storage().backup("backup/icloud_hme_snapshot.sqlite3")  # 目标文件需尚不存在
```

恢复时先停止服务，保留当前数据库及 WAL/SHM 作为回退材料，再用备份替换数据库。原始迁移备份还包含旧版代码，可完整回退到迁移前版本。

## FastAI 同步

左侧「发送账号」菜单（`/fastai-sync`）提供独立配置页面：开关、导入接口、每轮提交数量、执行间隔、倒计时、同步日志及任务历史。每条任务可打开结果弹窗查看邮箱状态及失败原因。立即执行一轮同样遵守每轮数量上限，邮箱列表的「一键同步所有未同步」不受该上限限制。

邮箱列表提供「同步 FastAI」状态列、「一键同步所有未同步」「同步配置」「查看同步结果」。同步只处理已完成收件配置的邮箱，调用 gpt-auto-register 的 `POST /api/import`，请求为 `{"kind":"icloud_relay","text":"邮箱----收件链接"}`。逐条确认导入数量后才标记「已同步」，目标接口确认的重复记录也视为成功；验证失败或超时不会误标。关闭弹窗后后台继续执行，可重新打开查看进度和逐条结果。

接口地址、自动同步开关、执行间隔、每轮提交数量、最近 300 条日志及下次时间存放在 SQLite `documents` 的 `fastai_sync_state`；每轮进度及结果存放在 `fastai_sync_job`；每个邮箱的同步状态存放在 `fastai_sync` 表。默认接口是 `http://127.0.0.1:8766/api/import`，自动同步默认关闭，默认间隔 60 分钟，每轮最多同步 50 个。「包含已同步」默认关闭，只发送未同步账号；开启后允许再次发送已同步账号。邮箱列表的同步全部未同步按钮始终只处理未同步记录。只填服务根地址会自动补上 `/api/import`。同步状态同时绑定目标接口和收件链接；换目标或链接后会重新视为未同步。配置保存不改变已经排定的下次时间，新间隔用于下一次重新计时；当前任务继续使用启动时的目标地址。

自动同步与手动同步共用一个任务队列，重复点击会查看正在执行的任务。服务重启保留成功标记，将未完成的任务标记中断，可安全重试；不会为了重试而创建新邮箱。导入只传邮箱与收件链接，不发送 Apple Cookie。此操作是导入邮箱号池，未调用目标项目的注册接口。

API：`GET/POST /api/fastai-sync` 读取状态或保存 `{api_url,enabled,interval_minutes,batch_size,include_synced}`；`POST /api/fastai-sync/run` 按配置数量执行一轮（传 `{all:true}` 同步全部，或传 `{emails:[...]}` 指定子集）；`GET /api/fastai-sync/jobs/{id}` 查看任务进度。
