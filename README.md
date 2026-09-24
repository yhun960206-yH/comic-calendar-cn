# 北京 / 上海漫展日历订阅

Python 3 标准库构建的静态首页、活动详情页、每城市完整 ICS 订阅与 JSON。**当前 `data/events.json` 为空，没有已核实的真实活动；尚未接入自动采集。** `data/seed_events.json` 全部为虚构 DEMO，不可用于正式部署。定时工作流只重新发布仓库内人工核实的真实文件，不会自动发现或核对新活动。

## 本地验证和预览

```sh
python3 -m src.validate --input data/events.json
python3 -m unittest discover -s tests -v
# 请替换成你真正要部署的 HTTPS Pages 根 URL，子路径和末尾 / 必须保留：
python3 -m src.build --base-url https://YOUR_ACCOUNT.github.io/YOUR_REPO/ --output public
python3 -m http.server 8000 --directory public
# 本地访问 http://localhost:8000/；订阅 URL 则仍指向指定的生产 HTTPS 地址
```

仓库内现有 `public/` 是以 `example.github.io` 占位 URL 生成的零真实活动本地样本，**不可直接发布**；部署工作流会先按 `BASE_URL` 变量重新生成整个目录。

本地独立演示请输出到单独目录：`python3 -m src.build --base-url https://example.github.io/demo/ --output /tmp/comic-calendar-demo --demo`。演示首页、详情页、JSON 和 ICS 都显著标注 DEMO；**不得用 `--demo` 发布到 Pages**。`--demo` 才默认读取 `data/seed_events.json`，平常只读取 `data/events.json`。`--input` 可指定本地已审核的 JSON（显式覆盖默认或演示文件），但 seed 文件必须搭配 `--demo`；构建器不联网。`python3 -m src.validate --input path/to/events.json` 可单独验证。

首页选择北京/上海后可查看活动和复制相应的 HTTPS 绝对 ICS 地址；没有 JS 时两座城市都能直接查看。详情页显示活动日期、地点、嘉宾（如有）、UTC 核对时间、票务/导航及公告来源；日期展示为含首尾日，输入 `end_date` 则排他。无已核实活动时会直说，无虚构卡片或票务按钮。活动文本经 HTML 转义，链接在离线验证后输出。网站支持 `https://域名/仓库名/` 等子路径部署。

## GitHub Pages 配置（需仓库管理员完成）

1. 将源码放入你管理的 GitHub 仓库；在 Settings → Pages → Build and deployment 中设置 **Source: GitHub Actions**。此处没有执行任何推送或部署。
2. 在 Settings → Secrets and variables → Actions → Variables 中新建 `BASE_URL`，值为**实际**公开 HTTPS Pages 根地址，必须以 `/` 结尾且包含真实仓库子路径（如 `https://YOUR_ACCOUNT.github.io/YOUR_REPO/`）；自定义域名根目录则为 `https://your-domain.example/`。不要使用示例域名上线。构建时验证 URL 格式，无法联网核实该域名是否真的可用。
3. `.github/workflows/pages.yml` 只允许从仓库默认分支部署（手动选择其他分支的运行会跳过构建）；另请在 `github-pages` 环境限制部署分支为默认分支作为纵深防护。支持手动运行及每天 UTC 03:17/15:17 的非整点定时运行；GitHub 定时可能延迟或跳过。工作流先验证真实输入、比对完整 Git 历史中该文件的各个版本、跑测试，随后以 `--input data/events.json`（不传 `--demo`）构建并核验 `demo: false`，同一工作流上传并部署 Pages artifact。部署作业仅需 `pages: write`、`id-token: write`；构建仅读仓库。`github-pages` 环境如设置审批规则，须由管理员批准。Git 历史校验依赖完整历史，请勿改写默认分支历史；初次部署前应确认此前未经工具发布的活动已经进入版本库历史。不要把 `data/seed_events.json` 手动复制到 `public/`。
4. 部署前检查工作流结果与公开页面、两个订阅链接是否在指定根路径正常访问。README 不代表部署已成功。

没有已授权来源或新活动时只发布已人工核实的 `data/events.json`（目前空）。此流程不抓取网页；新增任何自动采集前应单独核实数据源许可、审核流程及真实性。

## 真实活动人工录入契约

`config/cities.json` 固定北京 `110100`、上海 `310100`。`data/events.json` 为 `{ "events": [ ... ] }`；没有核实的活动就保留空数组。以下字段每条均必填，除 `revision` 外为字符串：

| 字段 | 规则 |
| --- | --- |
| `event_id` | 全局唯一永久不变，小写 ASCII `[a-z0-9][a-z0-9._-]*`；改期/取消不换 ID |
| `revision` | 非负整数；每次修改已发布活动递增，映射 ICS `SEQUENCE`；不能回退 |
| `status` | `confirmed` 或 `cancelled`；仅录入已核实活动；已发布活动取消时保留原记录并标为 `cancelled`，不能直接删除 |
| `city_code` | `110100` / `310100` |
| `title` | 核实的名称，非空 |
| `start_date` / `end_date` | `YYYY-MM-DD`，结束日**排他**，例如 5 月 1–2 日写 2030-05-01 到 2030-05-03；无开放时间则输出全天事件 |
| `updated_at` | 最近人工核对/修订时间，UTC `YYYY-MM-DDTHH:MM:SSZ`；变更后更新 |
| `venue_name` / `venue_address` | 核实的场馆名称及详细地址，非空 |
| `start_at` / `end_at` | 可选但必须同时存在；已核实的开放时间，形如 `2030-05-01T09:30:00+08:00`；起止日须与日期范围吻合，输出精确 UTC 日历时间 |
| `ticket_url` / `map_url` | 可选；经人工核实的 HTTPS 绝对票务/导航 URL；缺失时展示待公布／待核实文字，不放虚构链接 |
| `source_url` | 经人工核实可信的 HTTPS 公告来源 URL，展示在详情并写入 ICS；不代表获得抓取许可 |
| `guests` | 可选字符串数组；只有确实公布并核实的嘉宾才录入，无则省略 |

人工记录时先核实公告来源、时间、会场、票务和导航 URL 与嘉宾，并保留来源与修订证据；本程序仅校验格式，不访问网页或保证事实。所有 URL 必须是 HTTPS ASCII 绝对 URL，非 ASCII 字符须百分号编码。文本不能含控制字符；输入不能有未定义或重复字段/ID。可参考**仅供结构演示、不可发布**的 `data/seed_events.json`。提交前运行上述验证、测试和生产构建，再人工检查 `public/` 内容。本地构建器会对比现有输出 `public/events.json`，阻止曾发布活动删除、换城、版本回退、取消复活及未增版本的更改；Actions 使用 `python3 -m src.history` 对比默认分支 Git 历史中的所有 `data/events.json` 版本。首次建库前的既有发布无法自动追溯，链接真实性仍须人工审核。活动纠错如需换城，应取消旧城市的 ID、在新城市创建新的独立场次 ID。

## 输出与发布约束

`public/feeds/cities/110100.ics` 和 `310100.ics` 即使零活动也每次生成完整日历。事件 UID 为 `<event_id>@comic-calendar.invalid`，`SEQUENCE` 用修订号，取消使用 `STATUS:CANCELLED`、标题标记已取消并保持 UID；全天事件使用排他的 DTEND；已核实开放时间时写入精确 UTC DTSTART/DTEND。ICS 为 UTF-8 CRLF、RFC 5545 文本转义和 75-octet 内容行折行。发布过的取消记录继续留在源文件以传播给订阅用户。

`public/events.json` 为 `{ "demo": boolean, "cities": [{"code", "name", "feed_url", "event_count"}], "events": [输入活动...] }`；`public/status.json` 为 `{ "ok": true, "demo": boolean, "event_count": number, "last_verified_at": UTC时间或null, "cities": [同上] }`。首页显示最近人工核对时间（不是最后成功部署时间）。订阅 URL 是从 HTTPS `--base-url` 拼接的绝对地址。`--demo` 时两个 JSON 的 `demo` 为 true，ICS 日历名与每条摘要/描述均有 DEMO 标记，页面也有显著警示。

构建前会完整验证输入，并在同一父目录准备整棵输出树（包含网页/样式/脚本、JSON 和 ICS）；成功后会**替换整个输出目录**，不得在 `public/` 手工维护资源。准备或验证失败不影响旧版；目录替换时两次重命名之间可能有短暂不可读窗口，不提供并发读严格原子性或断电级事务。无需第三方包；没有内置联网或采集功能；GitHub Actions 仅部署已人工录入数据。当前架构图是调研阶段的目标架构，不代表现有项目具备数据库、关键词搜索或自动采集。
