---
name: fastaiapi-server-ops
description: 管理 FastAiApi/TumeiApi 的部署服务器、项目清单、代码部署、域名代理和端口映射。用户要求登录 32 服务器、在 /opt/fastaiapi-groups 部署或更新项目、查询项目目录，或管理 fastaiapi.cloud、tumeiapi.com 及子域名时使用。
---

# FastAiApi 服务器与域名运维

## 技能来源与维护

- 项目内可分发源目录：`cloud-email-register/fastaiapi-server-ops/`，其下的 `SKILL.md` 与 `references/` 需要一起保留。当前本机路径为 `/Users/atom/workspace/fastaiapi-groups/cloud-email-register/fastaiapi-server-ops`。
- 本机安装目录：`${CODEX_HOME:-$HOME/.codex}/skills/fastaiapi-server-ops`。更新技能时先更新项目内源文件，再将同名文件同步到安装目录，并核对内容一致；安装位置不属于服务器部署目录。
- 技能保存 SSH 地址、账号、目录、服务入口和必要约束；不保存密码、私钥、Cookie、API Key 或真实收件令牌。新电脑需要另行配置自己的 SSH 访问权限。
- 本次文档整理依据已有验收记录，未重新连接服务器核验全部状态。下方日期、提交及数据量为历史快照，操作前按请求范围核对现状。

## 固定环境

- 美国 VPS：`45.78.71.86:22`，用户 `leo`，主机名曾为 `bwh-gateway`。登录：`ssh leo@45.78.71.86`。
- PVE 宿主机：`192.200.102.214:22`，用户 `leo`。登录：`ssh leo@192.200.102.214`。
- 两台服务器已通过这台 Mac 的现有 SSH 密钥验证登录。使用现有 SSH 配置/代理，不需要用户重复提供已记录的地址和账号；不要假定其他电脑也有相同密钥。
- 业务服务器主要为 `10.10.10.32`，主机名 `xiaopi-fastapi`。已于 2026-10-26 验证直接登录：`ssh -p 6009 ubuntu@192.200.102.214`，使用本机现有 SSH 密钥。公网 `6009` 映射到该机 SSH `22`；无需先登录 PVE。该机 `ubuntu` 具有免密码 sudo 权限。`leo` 是 PVE/VPS 的账号，不是这台业务机的登录账号。
- Caddy 站点文件：`/etc/caddy/sites/dev.caddy`。主文件 `/etc/caddy/Caddyfile` 导入 `snippets/*.caddy` 和 `sites/*.caddy`。
- VPS 上 `leo` 已获免密码权限：`sudoedit /etc/caddy/sites/dev.caddy`、`sudo /usr/bin/systemctl restart caddy`。`sudo cat`、`sudo cp` 等未获同等授权。可直接 `cat` 读取该文件。

## 需要读取的资料

- 处理具体域名或端口前，读取 [references/domain-ports.md](references/domain-ports.md)：包含应用名称、访问域名、映射和已知未解决项。它是 2026-10-26 的快照，修改前以服务器现状为准。
- 用户维护的表格：`/Users/atom/workspace/fastaiapi-groups/域名与端口转发一览表.md`。
- 详细操作手册：`/Users/atom/workspace/fastaiapi-groups/美国VPS与域名转发操作手册.md`。
- 原始凭据信息文档：`/Users/atom/workspace/fastaiapi-groups/美国虚拟服务器.md`。仅在确实需要平台登录时按需读取相关部分，不将密码复制到 Skill、日志或回复中。SSH 登录通常不需要该文档中的平台密码。

## 项目目录与部署入口

- 登录业务机、查询项目、部署或更新代码时，先读 [references/projects.md](references/projects.md)：完整项目目录、Git 仓库/分支、systemd 服务、Docker/Compose 入口、端口和域名，以及两个注册项目的数据与自动任务约束。
- 默认工作根目录：服务器 `/opt/fastaiapi-groups`，本地 `/Users/atom/workspace/fastaiapi-groups`。目录存在不等于应用运行；依据当前服务、容器标签和监听信息定位项目。
- `icloud.tumeiapi.com` 对应 `cloud-email-register`、systemd 服务 `cloud-email-register.service`、2224；`regist.tumeiapi.com` 对应 `gpt-auto-register`、systemd 服务 `gpt-auto-register.service`、2223。二者独立数据库与自动任务设置，不能互相套用迁移结论。
- Docker CLI：`sudo /xp/server/docker/docker`；独立 Compose 可执行文件为 `/xp/server/docker/docker-compose`。当前 `docker compose` 子命令不可用。操作 Compose 项目时保留实际标签中的全部配置文件。
- 读取清单即可定位已知环境；仅在实时状态矛盾、认证失效或未记录信息影响任务时向用户补充询问。清单不构成无关项目修改授权。

## 本项目开发与验收

- `cloud-email-register` 默认在本地仓库开发和验证，再按用户要求提交、推送与部署；线上路径是运行目录，避免在两端分别维护不同源码。
- 项目显示名称为 **FastAiApi**。管理员登录入口 `/login`，账号与 API Key 管理 `/admin/security`；本地通过 `./start.sh` 访问 `http://127.0.0.1:2224`，生产入口 `https://icloud.tumeiapi.com`。本地与生产的认证库独立，不能相互覆盖。
- 登录、会话、公开 API、限流、邮箱数据及自动任务约束见 [references/projects.md](references/projects.md) 的 cloud-email-register 小节；端口转发与专属收件站点的关系见 [references/domain-ports.md](references/domain-ports.md)。
- 更新静态页面时，若运行方式支持直接加载静态文件，可仅部署静态改动并验证页面，避免不必要的服务重启。需要重启时先检查在途任务；启动参数会关闭自动任务，不能把启动默认值当成用户当前的运行开关状态。

## 项目部署和更新

1. 按用户指定项目读取项目清单，登录 `ssh -p 6009 ubuntu@192.200.102.214`。核对真实工作目录、origin、当前分支/提交、未提交改动与运行服务，保留项目既有分支；不要默认全部项目都用 main。
2. 在任务实际涉及的本地仓库和服务器目录分别读取适用的 AGENTS.md。按项目既有方式构建和验证；系统服务与 Compose 项目采用各自的部署入口。
3. 用户要求提交或发布代码时，提交所需代码并推送对应仓库；数据库、Cookie、账号凭据、.env 和运行数据通过授权的迁移流程处理，不能混入 Git。服务器 Git 认证失败时先区分公有 HTTPS 与私有读取权限；可将已推送版本通过 Git bundle 经 SSH 传输，不复制私钥。
4. 迁移数据前确认来源和目标，并备份目标已有数据。SQLite 使用在线备份或停服务后的完整快照；传输后检查完整性和关键表行数。更新代码与重新同步本地数据是独立动作，不能用旧快照覆盖线上新数据。
5. 两个注册项目保持自动任务默认关闭，除非用户明确要求开启；保留项目清单中记录的启动参数、服务覆盖文件、数据库及运行配置。依赖在目标机独立安装，不上传本机 .venv/node_modules。
6. 只重启本次操作的服务或 Compose 服务，核对监听、实际 HTTP/健康检查、必要的数据和任务状态；记录实际成功项与未解决项。完成部署变更后维护项目清单中对应行和核对日期，不覆盖其他项目的最新记录。

## 操作流程

按用户当前请求进行检查或修改；Skill 提供环境信息，不授权无关站点变更或删除。已明确要求的域名/映射修改可直接完成，不需要因为使用 Skill 再次确认。

1. 先读取最新 Caddy 文件和相关 `sudo port-forward list`，确认域名、宿主机端口、内网 IP、业务端口。宿主机端口可能与内网端口不同。新增域名通常代理至 `192.200.102.214:<宿主机端口>`；沿用相关站点现有公共请求头片段。
2. 在 PVE 上管理映射：
   ```bash
   sudo port-forward list
   sudo port-forward add <宿主机端口> <目标IP> <目标端口>
   sudo port-forward del <宿主机端口> <目标IP> <目标端口>
   ```
   仅改用户要求的规则，核对已有端口，避免重复或覆盖。不要把 `6661` 的映射当作 `6662` 的映射。
3. 在 VPS 上用 `curl --connect-timeout 5 --max-time 10 http://192.200.102.214:<端口>/` 验证上游。无法 SSH 登录业务机时，可从 PVE 访问内网端口识别页面标题；标题只能证明页面展示名称，不能证明实际进程或容器名。未知项明确标注，不猜测。
4. 修改 Caddy 前备份可读文件到 `leo` 家目录：`cp /etc/caddy/sites/dev.caddy "$HOME/dev.caddy.backup.$(date +%Y%m%d%H%M%S)"`。使用已授权的 `sudoedit` 修改，可使用临时 `SUDO_EDITOR` 脚本完成精确编辑，结束后删除临时编辑器。
5. 执行 `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`。校验成功后再执行 `sudo /usr/bin/systemctl restart caddy`，并检查 `systemctl is-active caddy`。校验失败时不重启；修正本次错误或恢复本次更改，避免遗留不明确的文件状态。现有请求头冗余警告不等同于校验失败。
6. 检查域名 A/AAAA 记录与 HTTPS。此架构的 A 记录通常指向 VPS `45.78.71.86`，Caddy 对外处理 TLS，上游多为 HTTP。新证书签发初期可能短暂出现 TLS 错误；稍后有限次复查，未解决则报告实际障碍，不能仅凭服务 active 宣称网站正常。
7. 完成实际映射/域名变更后，同步用户表格和 Skill 中相关快照，保持范围为 fastaiapi.cloud 与 tumeiapi.com 系列，注明核对日期及未验证项。检查网站或单纯登录不需要重写文档。

## 管理平台与边界

- VPS 服务商：<https://bandwagonhost.com/>，账号 `noreply@deeptradex.ai`。
- PVE 后台：<https://pve-dev.deeptradex.ai/>，平台账号 `root`。
- GoDaddy：<https://dcc.godaddy.com/>，账号 `fastaiapis@gmail.com`。
- 平台账号不等于 SSH 账号。DNS、服务状态和映射会变化，先查现状。需要新的认证、MFA 或未记录的后端登录信息时再向用户索取，不尝试猜密码或绕过认证。
