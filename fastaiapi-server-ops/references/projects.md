# 32 服务器项目与部署清单

核对日期：2026-10-26（Asia/Shanghai）。来源为服务器目录、Git 元数据、Docker 容器及 Compose 标签、systemd 服务与监听端口。分支、提交和运行状态均为本次快照，执行更新前重新核对。

## 登录与目录

```bash
# 直接登录 10.10.10.32，不需要先登录 PVE
ssh -p 6009 ubuntu@192.200.102.214
cd /opt/fastaiapi-groups
```

- 主机名：`xiaopi-fastapi`；内网 IP：`10.10.10.32`。
- 登录用户 `ubuntu`，使用本机现有 SSH 密钥；服务器上可用免密码 `sudo`。
- 部署根目录 `/opt/fastaiapi-groups`；本地项目根目录 `/Users/atom/workspace/fastaiapi-groups`。本地和服务器的项目目录名可能不同，以本清单及仓库 origin 为准。
- Docker CLI 实际位置为 `/xp/server/docker/docker`，不能假设普通 `docker` 命令在 PATH 中。使用 `sudo /xp/server/docker/docker ...`。本次确认 `docker compose` 子命令不可用；独立 Compose 可执行文件为 `/xp/server/docker/docker-compose`，使用 `sudo /xp/server/docker/docker-compose ...` 并显式传入实际 `-f` 配置。
- 不复制本机私钥到服务器。GitHub 公有仓库可通过 HTTPS 克隆；私有仓库先检查读取权限，不能把认证失败误判为仓库不存在。

## 项目目录清单

下表“运行”指关联服务或容器存在，不保证整套业务功能正常。“未确认运行”只表示未找到对应运行服务，不能据此自动删除或重启。

| 项目 / 服务器目录名 | 完整部署目录 | 分支 / 提交 | 已确认运行方式、端口和入口 |
| --- | --- | --- | --- |
| `cloud-email-register` | `/opt/fastaiapi-groups/cloud-email-register` | `main` / `7285f54` | systemd `cloud-email-register.service`；2224；[icloud.tumeiapi.com](https://icloud.tumeiapi.com) |
| `gpt-auto-register` | `/opt/fastaiapi-groups/gpt-auto-register` | `dev` / `d0f5c93` | systemd `gpt-auto-register.service`；2223；[regist.tumeiapi.com](https://regist.tumeiapi.com) |
| `juya-web` | `/opt/fastaiapi-groups/juya-web` | `main` / `f114cad` | 官网；容器 `fastai-website-website-1`；6660；[tumeiapi.com](https://tumeiapi.com)、[www.tumeiapi.com](https://www.tumeiapi.com)、[ui.fastaiapi.cloud](https://ui.fastaiapi.cloud) |
| `chatgpt2api-go` | `/opt/fastaiapi-groups/chatgpt2api-go` | `fastai` / `c92a3ee` | Compose gateway/api/worker/postgres/redis；gateway 公布 2222；[chatgpt.fastaiapi.cloud](https://chatgpt.fastaiapi.cloud) |
| `new-api` | `/opt/fastaiapi-groups/new-api` | `fastaiapi` / `e0b3c9920` | 容器 `new-api`、`postgres`、`redis`；1111；[newapi.fastaiapi.cloud](https://newapi.fastaiapi.cloud)；另有 `extension/geekapi` 的 `geekapi-video` 容器 |
| `fastdesign` | `/opt/fastaiapi-groups/fastdesign` | `v1` / `4c38c5b` | 多容器；gateway 公布 5550，python-api 公布 8000；[design.fastaiapi.cloud](https://design.fastaiapi.cloud)，8000 的其他域名不纳入当前两组域名表 |
| `flow2api` | `/opt/fastaiapi-groups/flow2api` | `fastai` / `1472695` | 容器 `flow2api`；9999；[work.fastaiapi.cloud](https://work.fastaiapi.cloud)；不能因名称相似而认定它使用 flow 域名的 6661 |
| `turing-media` | `/opt/fastaiapi-groups/turing-media` | `fastai` / `7834fdd5` | web/backend/yingce-agent/postgres/redis；web 公布 7777；[canvas.fastaiapi.cloud](https://canvas.fastaiapi.cloud)；数据库另公布 55431 |
| `sub2api-deploy` | `/opt/fastaiapi-groups/sub2api-deploy` | 非 Git 部署目录 | 容器 `sub2api`、`sub2api-postgres`、`sub2api-redis`；4444；[fastaiapi.cloud](https://fastaiapi.cloud)、[www.fastaiapi.cloud](https://www.fastaiapi.cloud) 的默认路径 |
| `sub2apiSelf` | `/opt/fastaiapi-groups/sub2apiSelf` | `fastaiapi2` / `b81d0f094` | Git 源码目录；与 sub2api-deploy 的实际构建关联待核对，不在此目录盲目启动第二套服务 |
| `sub2api-creator-engine` | `/opt/fastaiapi-groups/sub2api-creator-engine` | `main` / `f258f05` | 容器 `design-ui`、`design-api`、`design-postgres`、`design-redis`；UI 公布 4445，API 公布 4455；域名关联未核实 |
| `CodexPlusPlus` | `/opt/fastaiapi-groups/CodexPlusPlus` | `main` / `dc02a8e` | 已确认子项目 `services/feedback` 的容器 `fastaiapi-feedback`；仅本机 127.0.0.1:6099；不代表整个仓库均已部署 |
| `fast-ai-media` | `/opt/fastaiapi-groups/fast-ai-media` | `main` / `a35ec81` | 已确认 `fast-ai-media-discovery-db-1` 数据库容器，本机 127.0.0.1:55432；应用服务未确认 |
| `comfyui-api-wrapper` | `/opt/fastaiapi-groups/comfyui-api-wrapper` | `fastaiapi` / `b66178e` | 对应容器已退出，退出码 0；未确认业务监听 |
| `infinite-canvas` | `/opt/fastaiapi-groups/infinite-canvas` | `fastaiapi` / `fddaab5` | 源码目录存在，未确认运行；不能仅凭 canvas 域名把 7777 归到此目录 |
| `juya_drama` | `/opt/fastaiapi-groups/juya_drama` | `main` / `c07dc8a` | 源码目录存在，未确认运行 |
| `old-image2api` | `/opt/fastaiapi-groups/old-image2api` | `main` / `903cc36` | 源码目录存在，未确认运行 |
| `newapi-old` | `/opt/fastaiapi-groups/newapi-old` | 非 Git 部署目录 | 有 docker-compose.yml，未确认关联运行容器 |

共 16 个 Git 项目目录和 2 个非 Git 部署目录。`backups`、`newapi_backup`、`sub2api_backup` 为独立备份目录，不作为运行项目。隐藏的 `.juya-ssh` 不纳入项目清单，不读取或复制其中凭据。

另有运行中的旧 `chatgpt2api-postgres` 容器，Compose 标签指向 `/opt/fastaiapi-groups/chatgpt2api`，但本次目录清单中未见此目录；它是待核对的遗留容器，不自动重建目录或清理容器。

## 仓库来源

以下相对仓库名默认位于 `github.com/fastaiapi-groups/`；协议按实际读取权限选择。

| 目录名 | Git origin 仓库 |
| --- | --- |
| `cloud-email-register` | `cloud-email-register.git`（已通过 HTTPS 拉取） |
| `gpt-auto-register` | `gpt-auto-register.git` |
| `juya-web` | `juya-web.git` |
| `chatgpt2api-go` | `chatgpt2apibatch.git`（仓库名与目录名不同） |
| `new-api` | `new-api.git` |
| `fastdesign` | `fastdesign.git` |
| `flow2api` | `flow2api.git` |
| `turing-media` | `turing-media.git` |
| `sub2apiSelf` | `sub2api.git`（仓库名与目录名不同） |
| `sub2api-creator-engine` | `sub2api-creator-engine.git` |
| `CodexPlusPlus` | `CodexPlusPlus.git` |
| `fast-ai-media` | `fast-ai-media.git` |
| `comfyui-api-wrapper` | `comfyui-api-wrapper.git` |
| `infinite-canvas` | `infinite-canvas.git` |
| `juya_drama` | `juya_drama.git` |
| `old-image2api` | `git@github.com:DevMac9990/image2api.git`（不同组织） |

## Compose 入口

执行更新前读取当前容器的 `com.docker.compose.project.working_dir` 和 `com.docker.compose.project.config_files` 标签；不要仅因为目录中存在默认 docker-compose.yml 就忽略实际叠加文件。

| 项目 | 本次读取到的 Compose 文件（相对项目目录） |
| --- | --- |
| `juya-web` | `compose.yaml` |
| `chatgpt2api-go` | `docker-compose.yml` |
| `new-api` | `docker-compose.fastaiapi.yml`；扩展 `extension/geekapi/compose.yml` |
| `fastdesign` | `docker-compose.yml` |
| `flow2api` | `docker-compose.yml` |
| `turing-media` | `docker-compose.deploy.yml` + `docker-compose.build.yml` |
| `sub2api-deploy` | `docker-compose.yml` |
| `sub2api-creator-engine` | UI/API 使用 `docker-compose.yml` + `compose.production.yml` + `compose.client-updates.yml`；数据库与 Redis 标签只包含前两份 |
| `CodexPlusPlus` feedback | `services/feedback/compose.yaml`，工作目录也是该子目录 |
| `fast-ai-media` discovery DB | `compose.discovery.yaml` |

## 两个注册项目的部署约束

### cloud-email-register / iCloud 管理

- 服务 `cloud-email-register.service`，用户 `ubuntu`，独立 `.venv`；开机启动。
- 主 unit `/etc/systemd/system/cloud-email-register.service`；监听覆盖文件 `/etc/systemd/system/cloud-email-register.service.d/listen.conf` 将基础模板的回环监听改为 `0.0.0.0:2224`。更新部署时保留覆盖文件。
- 参数 `--no-sync --disable-automation`：每次进程启动先关闭自动注册、自动分裂、FastAI 自动同步和周期账号检查。用户未明确要求时保留此设置；手动操作仍可使用。
- 本地同步过 `icloud_hme.sqlite3` 和 `results/`，数据库与会话/收件凭据不进 Git。2026-10-26 首次导入为 2 个账号、434 条邮箱记录、434 条收件映射、50 条任务，此后数量可能变化。
- 更新代码不能用旧本地快照覆盖服务器新数据。需要再次迁移时先备份目标数据，SQLite 使用在线备份或停服务后的完整快照。
- 2026-10-26 后续迁移：按用户确认，以 `iCloud_migration_20261026_015916.zip` 完整备份替换生产数据，最终 2 个账号、980 个唯一邮箱、980 条就绪收件映射、118 条任务。两个 Cookie 从生产环境实时验证有效，苹果别名为 500 + 480，邮箱与归属集合与备份完全一致；自动任务仍关闭。替换前最终回退备份：`/opt/fastaiapi-groups/cloud-email-register/backup/before-final-migration-980-20261025T180625Z`。上述数量为本次验收快照。

- 2026-10-26 已部署管理登录和公开 API 鉴权（版本 `f181f00`）。管理员用户名 `admin`；初始登录信息保存在本机 `/Users/atom/workspace/fastaiapi-groups/cloud-email-register/backup/admin-auth-deploy-20261026/管理员登录信息.txt`，仅用户需要登录时按需读取，不能输出到日志或复制进 Skill。管理员可能已修改初始密码，以现状为准。
- 独立认证库 `admin_auth.sqlite3` 保存密码哈希、会话/API Key 摘要和持久化限流；后续邮箱数据迁移不得覆盖它，生产备份需要同时备份认证库。
- 会话默认固定 30 天；退出撤销当前会话，修改/重置密码撤销全部会话。管理 API 需要 Cookie，写操作附 `X-CSRF-Token`；公开 `/api/public/emails`、`/api/public/inbox-links/export`、`/api/public/mail` 需要对应权限的 API Key。不要将密钥放 URL。
- 生产覆盖文件 `/etc/systemd/system/cloud-email-register.service.d/auth.conf` 设置 `AUTH_COOKIE_SECURE=1`、`ADMIN_SESSION_DAYS=30`、`AUTH_TRUSTED_PROXIES=127.0.0.1,::1,45.78.71.86`。实际客户端 IP 只接受可信直接代理发送的 X-Forwarded-For，直连伪造头不受信任。Caddy 片段已确认覆盖转发头。
- 登录 IP 10 次/分钟；同账号/IP 8 次失败/15 分钟、跨 IP 同账号 12 次失败/15 分钟；公开接口 IP 120 次/分钟、每 Key 60 次/分钟（读取邮件 10 次/分钟）。超限返回 429 和 Retry-After，状态跨重启保留。验收已确认登录、重启保留会话、公开 Key 授权/吊销及真实 429；980 个邮箱和自动任务关闭状态保持。

- 2026-10-26 自动分裂规则更新（`2f83be5`）：新地址仅追加 `+` 和随机 4 位 `[a-z0-9]`，任务标签不拼入邮箱；同源重名最多重试 64 次，不覆盖已有链接。保留已存在地址及失败续配地址；检查本地部分 64 字节限制和点的位置。自动任务开关保持关闭。

### cloud-email-register 后续验收与操作注意

- 2026-10-26 生产单次分裂测试成功创建 1 个地址，确认后缀为 4 位小写字母/数字，专属收件链接页面和读取接口返回 200；当时生产邮箱总数为 981。980 是前次迁移验收数量，不是持续保持的目标；后续不能为恢复旧数量而删除用户新增邮箱。测试未发送新邮件，读取到已有邮件不能等同于新邮件投递验证。
- 分裂测试后恢复原分裂配置；当时发现用户已开启自动注册并保留其状态。启动默认关闭与运行中用户主动开启是不同状态，检查或发布静态文件不应主动关闭用户任务。
- 登录页面版本 `7285f54`：品牌 FastAiApi，移除会话期限说明文案；静态资源发布未重启服务。该版本是已记录的发布快照，更新前仍需核对最新提交。
- 本地管理员为 `admin`，用户已指定与生产相同的初始密码。密码仅在既有私密凭据文件中按需读取，不写入本技能和项目源码；实际能否登录以当前独立认证库为准。

### gpt-auto-register / 账号注册管理

- 2026-10-26 后续界面版本 `d0f5c93` 已推送 origin/dev 并通过增量 Git bundle 发布；品牌统一为 FastAiApi Register，优化登录页、导航和概览，支持手机及明暗主题。仅更新静态资源，未重启服务（发布前后 MainPID=1785666，NRestarts=0）；保留上一生产版本的哈希资源供已打开的页面使用，未改业务数据库和认证库。线上登录、静态入口资源一致性、匿名业务 API 401、健康检查 200 已验证。部署包和记录：`/opt/fastaiapi-groups/backups/gpt-auto-register/ui-20261026`。

- 服务 `gpt-auto-register.service`，用户 `ubuntu`，独立 `.venv`，监听 `0.0.0.0:2223`，开机启动和失败自动重启。
- 初始分支 `dev`，首次版本 `2c80d27`。首次通过本地已推送版本的完整 Git bundle 经 SSH 上传克隆，origin 保留原私有仓库，未复制本机私钥。
- 服务器首次部署时未配置该私有仓库读取凭据。更新前检查认证；必要时仍通过 Git bundle 导入已推送版本，不覆盖已有分支和未提交修改。
- 数据库 `webui/webui.db` 首次部署为空库；2026-10-26 后续已按用户要求用本地快照完整替换生产数据库。验收快照：2,814 条邮箱（可用 540、完成 2,261、失败 13、在用 0）、2,591 条注册结果、10,573 条运行记录、31 项配置、20 条短信退款记录。五张表的全部行内容规范化 SHA-256 与本地一致，仅将运行记录的日志路径适配到服务器目录。用户明确不需要生产新增的 16 条邮箱、23 条运行记录，正式库未保留；替换前回退备份 `/opt/fastaiapi-groups/backups/gpt-auto-register/data-sync-20261026-020940/before-production`。
- 用户明确不上传 10,549 份本地运行日志文件，最终仅导入数据库；先前临时上传的日志压缩包已从服务器删除，正式 webui/logs 中没有导入 .log 文件。因此历史运行记录仍在，但历史日志正文不可读取。自动注册、Hello/FastAi 定时任务保持关闭，无在途任务。后续不要再次用本地旧快照覆盖生产新数据。
- 使用 systemd 管理；不要同时用 restart.sh 启动第二个进程。更新时保留数据库和配置。
- 2026-10-26 已发布管理员登录，认证功能版本 `143ac2a`（dev）。本地和线上分别通过终端初始化 `admin`，初始密码由用户指定，未写入仓库、部署配置或本文档。认证库 `webui/admin_auth.sqlite3`（含 WAL/SHM）独立于业务库，0600 权限且已被 Git 忽略；更新/迁移业务数据时保留认证库，不能用本地会话库覆盖线上会话。默认会话绝对有效期 30 天，注销或重设密码会使相应会话失效。
- 所有业务 `/api/` 读写、导出、实时日志接口需要 Cookie 会话，写请求额外校验 CSRF 与来源；匿名返回 401。仅登录、认证初始化状态和无业务数据的 `/api/health` 公开。健康检查不能再匿名读取 /api/stats。管理终端命令：`.venv/bin/python admin_auth.py set-admin --username admin`，或 `revoke-sessions`；密码通过交互输入。
- systemd 覆盖文件 `/etc/systemd/system/gpt-auto-register.service.d/admin-auth.conf` 设置 `ADMIN_SESSION_DAYS=30` 和 `FORWARDED_ALLOW_IPS=127.0.0.1,::1,45.78.71.86`。仅信任现有 VPS Caddy；Caddy 已用 remote_host 覆盖 X-Forwarded-For/X-Real-IP。IP/账号退避与全局登录限流保存在认证库内，服务重启不会清空。
- 本次发布前无在途任务，自动注册暂停且两个定时任务关闭。发布后业务五张表全量哈希与发布前一致：2814 条邮箱、2601 条注册结果、10600 条运行记录、31 项配置、20 条退款记录；这是本次快照，包含数据迁移后用户新增的结果。回退业务备份 `/opt/fastaiapi-groups/backups/gpt-auto-register/admin-auth-20261026/before-business.sqlite3`，校验报告同目录 verification.json。
- 验证：本地 178 项回归通过，目标服务器 21 项鉴权测试通过（在独立临时数据库运行，补装了测试客户端依赖 httpx2）；本地和线上均验证指定账号登录，线上匿名业务请求 401，HTTPS 健康检查 200，默认会话 30 天。服务 active/running，NRestarts=0；自动任务未启用。


### 网络与验证

- 两个域名均经美国 VPS Caddy → PVE 公网同端口 → `10.10.10.32` 同端口转发。
- 业务机 INPUT 链末尾有 DROP。`tumeiapi-app-ports.service` 在开机时幂等放行 TCP 2223、2224；网络排障需要检查服务监听、该规则、PVE 映射及 Caddy 四层。
- 2026-10-26 核对时两个 systemd 服务均运行且开机启动；两个域名首页 HTTPS 均返回 200。

## 常用只读核对

```bash
systemctl show cloud-email-register gpt-auto-register -p WorkingDirectory -p User -p ActiveState
systemctl cat cloud-email-register
systemctl cat gpt-auto-register
sudo /xp/server/docker/docker ps -a --format '{{.Names}}\t{{.Status}}\t{{.Ports}}'
sudo ss -lntp
```

状态检查属于只读操作。只有用户要求更新或重启对应项目时，才执行相关服务变更；Skill 清单本身不授权全量重启。
