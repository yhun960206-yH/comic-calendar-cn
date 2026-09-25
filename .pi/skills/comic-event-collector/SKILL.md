---
name: comic-event-collector
description: 用户要求 AI 帮忙收集中国漫展、同人展或兽展活动，按城市更新本仓库的日历，并保存证据时使用。一次性研究官方公开公告、验证日期地点、隔离缺失或矛盾记录；不绕过平台访问限制，不自动在 GitHub Actions 中运行 AI。
---

# 漫展活动 AI 辅助采集（本仓库）

## 边界

本 Skill 是**运行中的 AI**按需执行的一次性研究和导入指南，不是后台采集服务。`src.sources.fec_web` 的无密钥网页适配器才会按 Actions 工作流定时运行。发布本 Skill 到 GitHub **不会使 GitHub Actions 获得 AI 搜索能力、模型凭据或自动联网检索**。未经用户另行批准，不增加定时 AI 调用及费用。

仅处理与漫展、同人展、动漫游戏展、兽展直接相关的中国城市实体活动；不将一般游戏节、长期主题咖啡馆或纯文创商贸会混充漫展。称呼以官方类型为准。目标是尽量收录能核对的活动，**不是**宣称全国完整覆盖。用户无需亲自逐条录入，AI 做检索和字段核验；但 AI 的核验不等于主办方保证或现场人工核实。

## 一次采集流程

1. 先读仓库 `README.md`、`src/model.py`、`src/history.py`、`data/events.json` 及最近的 `data/collection_evidence/`。读取线上 `events.json` 以识别已有 UID；已发布活动不能静默删除，取消需保持 UID、递增 `revision`。不复用 `data/seed_events.json`（DEMO）。
2. 用多组不同城市/月份/主办方词检索。优先主办方官网的**公开活动公告**，再用市政府、官方场馆或具名主办方的其他公开网页交叉核对场馆地址。官网找不到时，可用不同的可信来源互证，但不得仅靠搜索结果摘要或聚合站点的预测排期发布。查看 robots/站点条款；不绕过登录、验证码、限流、私有接口。微博通用 robots 禁抓、B 站/抖音未经确认的自动取数权限均不能用“其他人也在抓”替代许可。仅整理公开的短事实字段与原始 URL；不拷贝原创文字、海报、图片或票务数据。批量导入第三方数据库必须先确认其数据再发布条件。
3. 对每场候选记录：确认活动名称、**年份明确的首尾日期**、实体场馆、精确地址、所属城市与官方原文 URL；对取消/延期优先检查更晚公告。缺失、来源互相矛盾、地址仅为全市或假设场馆、仅有报名窗口而无开展日期时**隔离，不发布**。不能把 AI 推测说成已确认。记录证据 URL 和未采用原因，格式参考 `references/evidence-format.md`。
4. 对确认为独立活动的候选分配稳定小写 ASCII `event_id`（如 `ai-cicf-agf-guangzhou-2026`）；同一展会不同公告不能建多个 UID。核对线上/本地是否已经有相同主办方、标题、城市、日期或来源 URL 的记录。字段必须遵循 `src/model.py`：`city_code` 在 `config/cities.json` 内，行政细分对应 `config/area_to_city.json`，`end_date` 是**最后一天的次日**；没有具体开闭馆时间就使用全天，不填 `start_at/end_at`；`updated_at` 为本次查阅的 UTC 时间，不表示人工实地核验。票务、地图、嘉宾不确定则不填。`source_url` 为可访问的官方 HTTPS 页面；其他佐证写证据文件而不是编造按钮链接。
5. 将完整记录增量写入 `data/events.json`；将本次接受/隔离的证据索引写入 `data/collection_evidence/YYYY-MM-DD-<slug>.json`，只保留短事实、URL 和判断，不复制文章/图片。每个变更先检查后发布：

   ```sh
   python3 -m src.validate --input data/events.json
   python3 -m src.history
   python3 -m unittest discover -s tests -q
   python3 -m src.sources.pipeline --base-url https://yhun960206-yh.github.io/comic-calendar-cn/ --input data/events.json --output /tmp/comic-ai-candidate.json --public-web
   python3 -m src.build --base-url https://yhun960206-yh.github.io/comic-calendar-cn/ --input /tmp/comic-ai-candidate.json --output /tmp/comic-ai-preview
   ```

   最后两步读取 FEC 官网和上次已发布 Pages 检查点；任一步失败就不发布，而不是以零条覆盖旧站。检查 `/tmp/comic-ai-preview/events.json` 中新增数量、对应城市 ICS 的 `VEVENT` 和来源链接。绝不直接编辑 `public/` 或把 DEMO 打包上线。
6. 推送前遵循仓库 Git 规则：feature 分支、`git status` 和 `git diff --staged` 查敏感内容及大型产物、Conventional Commit、fetch、防分叉、PR；merge 后手动运行 Pages 工作流并核对线上计数及订阅源。汇报“新增几条/排除几条/还有哪些城市空白/哪些来源不可使用”。旧活动的自动取消不能仅由搜索不到推定。

## 注意

若用户要求**无人值守 AI 定时采集**，暂停实施并先确认模型供应商、API 凭据存放、调用费用、搜索服务条款、运行频率和错误预算；此 Skill 本身不解决这些问题。与 `src.sources.fec_web` 自动源不同，`data/events.json` 中的 AI 一次性录入不会自行追踪后续改期；要定期再次调用本 Skill 或新增获准的数据接口。
