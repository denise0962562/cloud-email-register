# 域名与端口转发一览表

核对日期：2026-10-26。范围：`fastaiapi.cloud`、`tumeiapi.com` 及其子域名。根据美国 VPS 的 `/etc/caddy/sites/dev.caddy` 和 PVE 的 `sudo port-forward list` 实时读取结果整理。

## 服务器

| 角色 | 地址 | SSH 登录 | 配置位置 / 查看命令 |
| --- | --- | --- | --- |
| 美国 VPS（Caddy） | `45.78.71.86` | `ssh leo@45.78.71.86` | `/etc/caddy/sites/dev.caddy` |
| PVE 宿主机 | `192.200.102.214` | `ssh leo@192.200.102.214` | `sudo port-forward list` |
| 业务服务器（32） | `10.10.10.32` | `ssh -p 6009 ubuntu@192.200.102.214` | 项目根目录 `/opt/fastaiapi-groups` |

## 域名与业务端口

以下仅收录 `fastaiapi.cloud`、`tumeiapi.com` 及其子域名。域名由美国 VPS 的 Caddy 接入，再转发至上游。表中“映射存在”表示配置已核对，不代表本次已测试业务可用。

| 访问域名 | 路径 | Caddy 上游地址 | PVE 内网目标 | 应用名称 | 说明 |
| --- | --- | --- | --- | --- | --- |
| [regist.tumeiapi.com](https://regist.tumeiapi.com) | 全部 | `192.200.102.214:2223` | `10.10.10.32:2223` | 账号注册管理（gpt-auto-register） | 2026-10-26 HTTPS 和健康检查返回 200；自动注册关闭 |
| [icloud.tumeiapi.com](https://icloud.tumeiapi.com) | 全部 | `192.200.102.214:2224` | `10.10.10.32:2224` | iCloud HME 多账号管理（cloud-email-register） | 2026-10-26 HTTPS 返回 200；自动任务默认关闭 |
| [tumeiapi.com](https://tumeiapi.com) | 全部 | `192.200.102.214:6660` | `10.10.10.32:6660` | FastAiApi 官网 | 官网；映射存在；2026-10-25 HTTPS 返回 200 |
| [www.tumeiapi.com](https://www.tumeiapi.com) | 全部 | `192.200.102.214:6660` | `10.10.10.32:6660` | FastAiApi 官网 | 官网；映射存在；2026-10-25 HTTPS 返回 200 |
| [ui.fastaiapi.cloud](https://ui.fastaiapi.cloud) | 全部 | `192.200.102.214:6660` | `10.10.10.32:6660` | FastAiApi 官网 | 映射存在 |
| [flow.fastaiapi.cloud](https://flow.fastaiapi.cloud) | 全部 | `192.200.102.214:6661` | `10.10.10.32:6661` | 应用名待确认（flow 入口） | 映射存在 |
| [api.fastaiapi.cloud](https://api.fastaiapi.cloud) | 全部 | `192.200.102.214:6662` | **当前未找到映射** | 应用名待确认（API 入口） | 2026-10-25 上游连接超时；后端实际地址待确认 |
| [fastaiapi.cloud](https://fastaiapi.cloud)、[www.fastaiapi.cloud](https://www.fastaiapi.cloud) | `/fastaiui`、`/fastaiui/*`、`/fastaiapi`、`/fastaiapi/*` | `192.200.102.214:4446` | `10.10.10.32:80` | Nginx 站点（具体应用待确认） | 按路径分流；映射存在 |
| [fastaiapi.cloud](https://fastaiapi.cloud)、[www.fastaiapi.cloud](https://www.fastaiapi.cloud) | 其余路径 | `192.200.102.214:4444` | `10.10.10.32:4444` | FastAiAPI - AI API Gateway | 默认路由；映射存在 |
| [xiaopi.fastaiapi.cloud](https://xiaopi.fastaiapi.cloud) | 全部 | `192.200.102.214:25933` | `10.10.10.32:25933` | 小皮面板 | 映射存在 |
| [chatgpt.fastaiapi.cloud](https://chatgpt.fastaiapi.cloud) | 全部 | `192.200.102.214:2222` | `10.10.10.32:2222` | ChatGPT 号池管理 | 映射存在 |
| [newapi.fastaiapi.cloud](https://newapi.fastaiapi.cloud) | 全部 | `192.200.102.214:1111` | `10.10.10.32:1111` | FastAiApi（newapi 入口） | 映射存在 |
| [design.fastaiapi.cloud](https://design.fastaiapi.cloud) | 全部 | `192.200.102.214:5550` | `10.10.10.32:5550` | FastAIDesign AICG 平台 | 原配置注释为“备用”；映射存在 |
| [home.fastaiapi.cloud](https://home.fastaiapi.cloud) | 全部 | `192.200.102.214:5551` | `10.10.10.32:5551` | 应用名待确认（home 入口） | 映射存在 |
| [web.fastaiapi.cloud](https://web.fastaiapi.cloud) | 全部 | `192.200.102.214:6666` | `10.10.10.30:6666` | 未核查（其他内网服务器） | 映射存在 |
| [canvas.fastaiapi.cloud](https://canvas.fastaiapi.cloud) | 全部 | `192.200.102.214:7777` | `10.10.10.32:7777` | 图灵 AI · AI 影视短剧创作 | 映射存在 |
| [work.fastaiapi.cloud](https://work.fastaiapi.cloud) | 全部 | `192.200.102.214:9999` | `10.10.10.32:9999` | Flow2API | 映射存在 |
| [cpamp.fastaiapi.cloud](https://cpamp.fastaiapi.cloud) | 全部 | `192.200.102.214:18317` | `10.10.10.31:18317` | 未核查（其他内网服务器） | 映射存在 |

除明确标为 HTTPS 的上游外，表中当前 Caddy 上游使用 HTTP。公网 HTTPS 证书由 Caddy 处理，具体可用性需另行测试。


## 对应的 PVE 端口映射

下表公网 IP 均为 `192.200.102.214`，仅列出上述域名涉及且已存在的 15 条规则。`6662` 尚未找到映射，见下方待确认事项。

| 宿主机公网端口 | 内网目标 IP | 内网目标端口 | 应用名称 | 访问域名 |
| --- | --- | --- | --- | --- |
| 1111 | `10.10.10.32` | 1111 | FastAiApi（newapi 入口） | [newapi.fastaiapi.cloud](https://newapi.fastaiapi.cloud) |
| 2222 | `10.10.10.32` | 2222 | ChatGPT 号池管理 | [chatgpt.fastaiapi.cloud](https://chatgpt.fastaiapi.cloud) |
| 2223 | `10.10.10.32` | 2223 | 账号注册管理（gpt-auto-register） | [regist.tumeiapi.com](https://regist.tumeiapi.com) |
| 2224 | `10.10.10.32` | 2224 | iCloud HME 多账号管理 | [icloud.tumeiapi.com](https://icloud.tumeiapi.com) |
| 4444 | `10.10.10.32` | 4444 | FastAiAPI - AI API Gateway | [fastaiapi.cloud](https://fastaiapi.cloud)、[www.fastaiapi.cloud](https://www.fastaiapi.cloud) |
| 4446 | `10.10.10.32` | 80 | Nginx 站点（具体应用待确认） | [fastaiapi.cloud/fastaiui](https://fastaiapi.cloud/fastaiui)、[fastaiapi.cloud/fastaiapi](https://fastaiapi.cloud/fastaiapi)（www 同路径） |
| 5550 | `10.10.10.32` | 5550 | FastAIDesign AICG 平台 | [design.fastaiapi.cloud](https://design.fastaiapi.cloud) |
| 5551 | `10.10.10.32` | 5551 | 应用名待确认（home 入口） | [home.fastaiapi.cloud](https://home.fastaiapi.cloud) |
| 6660 | `10.10.10.32` | 6660 | FastAiApi 官网 | [tumeiapi.com](https://tumeiapi.com)、[www.tumeiapi.com](https://www.tumeiapi.com)、[ui.fastaiapi.cloud](https://ui.fastaiapi.cloud) |
| 6661 | `10.10.10.32` | 6661 | 应用名待确认（flow 入口） | [flow.fastaiapi.cloud](https://flow.fastaiapi.cloud) |
| 6666 | `10.10.10.30` | 6666 | 未核查（10.10.10.30） | [web.fastaiapi.cloud](https://web.fastaiapi.cloud) |
| 7777 | `10.10.10.32` | 7777 | 图灵 AI · AI 影视短剧创作 | [canvas.fastaiapi.cloud](https://canvas.fastaiapi.cloud) |
| 9999 | `10.10.10.32` | 9999 | Flow2API | [work.fastaiapi.cloud](https://work.fastaiapi.cloud) |
| 18317 | `10.10.10.31` | 18317 | 未核查（10.10.10.31） | [cpamp.fastaiapi.cloud](https://cpamp.fastaiapi.cloud) |
| 25933 | `10.10.10.32` | 25933 | 小皮面板 | [xiaopi.fastaiapi.cloud](https://xiaopi.fastaiapi.cloud) |

## 应用名称核对说明

应用名称于 2026-10-26 从 PVE 访问 `10.10.10.32` 各端口的 HTTP 页面标题识别，属于页面展示名称。早期采集时未能 SSH 登录；随后已用 ubuntu 成功登录，并验证 cloud-email-register 的项目目录和 systemd 服务，其他应用仍按原页面识别结果标注。

| 内网端口 | 识别依据 / 当前结果 |
| --- | --- |
| 80 | 根页面标题为 `Welcome to nginx!`；携带 `Host: fastaiapi.cloud` 访问 `/fastaiui` 返回 200 但无标题，`/fastaiapi` 返回 404，具体应用名待确认 |
| 1111 | 页面标题为 `FastAiApi`；“newapi 入口”根据已配置域名标注 |
| 2222 | 页面标题为 `ChatGPT 号池管理` |
| 4444 | 页面标题为 `FastAiAPI - AI API Gateway` |
| 5550 | 页面标题包含 `FastAIDesign AICG 平台` |
| 5551 | 连接超时，应用名待确认；home 为域名入口名称 |
| 6660 | 页面标题为 `FastAiApi · 让想法，成为作品`；官网用途由本次部署记录确认 |
| 6661 | 连接超时，应用名待确认；flow 为域名入口名称 |
| 6662 | 连接超时，应用名待确认；且未找到 PVE 映射；访问域名为 [api.fastaiapi.cloud](https://api.fastaiapi.cloud) |
| 7777 | 页面标题为 `图灵AI / AI影视短剧创作 · AI Image & Video Workspace` |
| 9999 | 页面标题为 `登录 - Flow2API` |
| 25933 | 页面标题为 `小皮面板` |

表中的访问域名为 Caddy 已配置的入口，链接存在不代表当前业务可用。

## 2026-10-26 新增域名部署记录

- `icloud.tumeiapi.com`：项目位于 `/opt/fastaiapi-groups/cloud-email-register`，服务 `cloud-email-register.service`。通过 systemd 的 `listen.conf` 覆盖文件监听 `0.0.0.0:2224`，保留 `--no-sync --disable-automation` 参数。公网 HTTPS 返回 200，三个自动任务配置均为关闭。
- `regist.tumeiapi.com`：项目 `/opt/fastaiapi-groups/gpt-auto-register`，分支 `dev`，版本 `2c80d27`；systemd 服务 `gpt-auto-register.service`，以 ubuntu 运行并开机启动，监听 `0.0.0.0:2223`。HTTPS 首页和 `/api/health` 均返回 200，浏览器仪表盘正常；自动注册停止、无在途任务。首次部署为空库；2026-10-26 后续已同步本地数据库：2,814 条邮箱、2,591 条注册结果、10,573 条运行记录，五张表全量内容核对一致。按用户要求不导入运行日志文件；自动任务仍关闭。
- 业务机原 INPUT 链末尾有 DROP。已添加仅放行 TCP 2223、2224 的规则，并使用 `tumeiapi-app-ports.service` 在开机时恢复；未改变其他端口规则。

## 待确认事项

- `api.fastaiapi.cloud` 已配置 Caddy 上游 `192.200.102.214:6662`，但本次读取的 PVE 规则中没有 `6662`。需要先确认实际业务 IP 和端口，再添加对应映射。
- 本次已检查 `10.10.10.32` 上相关端口的 HTTP 页面，未重新执行全部公网域名的 DNS、证书及业务访问测试。

详细新增与排障步骤见同目录的《美国VPS与域名转发操作手册.md》。


## 专属收件页与业务机代理的区别

- `webmail.fastaiapi.cloud/m/*` 是本项目 `cloud_inbox/` 部署的 Cloudflare Worker 专属收件页，使用各邮箱独立随机收件令牌，不属于上述 PVE 2224 转发。不要把整站改代理到 cloud-email-register，也不要写入真实收件链接。
- `icloud.tumeiapi.com` 是管理后台，需要管理员会话；公开 `/api/public/*` 使用 API Key。收件页令牌、管理员会话及 API Key 用途不同，不能互换。
- `api.fastaiapi.cloud:6662` 在旧 Caddy/PVE 采集记录中有未解决项；邮箱项目另有使用同名服务的配置记录。排障时先核对 DNS、Cloudflare 路由及实际请求路径，不根据旧表推断当前收件服务也不可用。
- 当前文档整理未重新核验 DNS、全部映射及各站点可用性；沿用原核验日期，不能视为本次实时检查结果。
