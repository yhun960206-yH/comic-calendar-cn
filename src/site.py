"""Render self-contained, escaped static pages inside the build staging tree."""

from datetime import date, timedelta
from html import escape
from pathlib import Path


ASSETS = Path(__file__).resolve().parent / "assets"


def text(value):
    return escape(str(value), quote=True)


def date_label(event):
    start = date.fromisoformat(event["start_date"])
    last = date.fromisoformat(event["end_date"]) - timedelta(days=1)
    first_label = f"{start.year} 年 {start.month} 月 {start.day} 日"
    if "start_at" in event:
        first_label += " " + event["start_at"][11:16]
        last_label = f"{last.year} 年 {last.month} 月 {last.day} 日 {event['end_at'][11:16]}"
        return first_label + " — " + last_label
    if last == start:
        return first_label
    return f"{first_label} — {last.year} 年 {last.month} 月 {last.day} 日"


def shell(title, content, *, depth=0, demo=False):
    prefix = "../" * depth
    warning = ('<aside class="demo-banner" role="alert">DEMO 演示模式：全部活动均为虚构，'
               '不可据此购票或前往。</aside>' if demo else '')
    caption = 'DEMO / 虚构活动' if demo else '全国城市 / 来源覆盖有限'
    footer = ('DEMO：仅用于本地界面演示，非真实活动。' if demo else
              '仅展示人工核实并录入的活动；尚未接入自动采集。')
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <title>{text(title)} · 漫展日历订阅</title>
  <link rel="stylesheet" href="{prefix}assets/site.css">
  <script src="{prefix}assets/site.js" defer></script>
</head>
<body>
  <header class="site-header"><div class="wrap header-inner">
    <a class="brand" href="{prefix}index.html">漫展日历 <span>订阅</span></a>
    <span class="header-caption">{caption}</span>
  </div></header>
  {warning}
  <main class="wrap">{content}</main>
  <footer class="wrap footer">{footer}日期与时间以活动公告为准；未公布开放时间时使用全天事件。</footer>
</body></html>
'''


def copy_control(url):
    return (f'<div class="feed-copy"><a class="feed-url" href="{text(url)}">{text(url)}</a>'
            f'<button type="button" class="copy-button" data-copy="{text(url)}">复制订阅链接</button>'
            '<span class="copy-result" role="status" aria-live="polite"></span></div>')


def home(city_list, items, demo):
    links = ''.join(f'<a class="city-link" href="#city-{text(city["code"])}" '
                    f'data-city="{text(city["code"])}" data-name="{text(city["province"] + city["name"])}">{text(city["province"])} · {text(city["name"])}'
                    f'<span class="city-count">{city["event_count"]} 场</span></a>'
                    for city in city_list)
    sections = []
    for city in city_list:
        code = city["code"]
        rows = [event for event in items if event["city_code"] == code]
        if rows:
            cards = ''.join(
                '<article class="event-card">'
                f'<div class="eyebrow">{text(date_label(event))}</div>'
                f'<h3><a href="events/{text(event["event_id"])}.html">{text(event["title"])}</a></h3>'
                f'<p>{text(event["venue_name"])} · {text(event["venue_address"])}</p>'
                + ('<span class="cancelled">已取消</span>' if event["status"] == "cancelled" else '')
                + '</article>' for event in rows)
        else:
            cards = ('<p class="empty">暂无已核实活动。当前未接入自动采集；这里不是“活动已结束”或“城市没有漫展”的判断。'
                     '请稍后查看经人工核实的更新。</p>')
        sections.append(f'''<section class="city-panel" id="city-{text(code)}" data-panel="{text(code)}">
    <div class="section-heading"><div><p class="eyebrow">CITY / {text(code)}</p><h2>{text(city["name"])}漫展</h2></div>
    <span class="count">{city["event_count"]} 场已录入</span></div>
    <div class="feed-box"><p class="feed-label">日历订阅 · HTTPS 地址</p>
      <p class="hint">复制地址，添加到日历应用的“通过 URL 订阅”中。</p>
      {copy_control(city["feed_url"])}</div>
    <div class="event-list">{cards}</div>
  </section>''')
    lead = ('以下均为虚构 DEMO 活动，不代表真实漫展或票务信息。' if demo else
            '选择城市，订阅该市及所辖区县、乡镇已收录的活动。数据来源有限，不能保证完整覆盖。')
    verified = max((event["updated_at"] for event in items), default=None)
    freshness = ('最近人工核对：' + text(verified) + '（UTC）' if verified else
                 '尚无已核实活动；没有可报告的最近核对时间。')
    content = f'''<section class="hero"><p class="eyebrow">CITY CALENDAR / 全国城市</p>
    <h1>你的漫展日程，<br><em>按城市</em>订阅。</h1><p class="hero-lead">{lead}</p><p class="hint">{freshness}</p></section>
    <label for="city-search">搜索城市／省份</label>
    <input id="city-search" type="search" placeholder="例如：北京、广东深圳" autocomplete="off">
    <nav class="city-nav" aria-label="选择城市">{links}</nav>
    {''.join(sections)}'''
    return shell("北京 / 上海", content, demo=demo)


def detail(event, city, demo):
    status = '<span class="cancelled">已取消 · 保留在订阅日历中通知变更</span>' if event["status"] == "cancelled" else ''
    guests = ('<div class="info-row"><dt>嘉宾</dt><dd>'
              + '、'.join(text(guest) for guest in event["guests"]) + '</dd></div>'
              if event.get("guests") else '')
    links = ''.join(
        f'<a class="external-link" href="{text(event[field])}" target="_blank" rel="noopener noreferrer">{label} ↗</a>'
        for field, label in (("ticket_url", "票务"), ("map_url", "导航"), ("source_url", "公告来源"))
        if event.get(field))
    if not event.get("ticket_url"):
        links += '<span class="hint">票务链接待公布</span>'
    if not event.get("map_url"):
        links += '<span class="hint">导航地点待核实</span>'
    content = f'''<div class="detail-page">
    <a class="back-link" href="../index.html#city-{text(city["code"])}">← 返回{text(city["name"])}日历</a>
    <article><p class="eyebrow">{text(city["name"])} / 活动详情</p>
      <h1>{text(event["title"])}</h1>{status}
      <dl class="info-list">
        <div class="info-row"><dt>日期</dt><dd>{text(date_label(event))} <small>{'北京时间' if 'start_at' in event else '全天；具体开放时间待公布'}</small></dd></div>
        <div class="info-row"><dt>场馆</dt><dd>{text(event["venue_name"])}</dd></div>
        <div class="info-row"><dt>地址</dt><dd>{text(event["venue_address"])}</dd></div>
        {guests}
        <div class="info-row"><dt>最近核对</dt><dd><time datetime="{text(event["updated_at"])}">{text(event["updated_at"])}</time>（UTC）</dd></div>
      </dl>
      <div class="action-links">{links}</div>
      <section class="feed-box"><h2>订阅{text(city["name"])}日历</h2>
        <p class="hint">复制 HTTPS 地址并在日历应用中按 URL 添加。</p>
        {copy_control(city["feed_url"])}</section>
    </article></div>'''
    return shell(event["title"], content, depth=1, demo=demo)


def render_site(staging, city_list, items, demo):
    asset_output = staging / "assets"
    asset_output.mkdir()
    for name in ("site.css", "site.js"):
        (asset_output / name).write_bytes((ASSETS / name).read_bytes())
    (staging / "index.html").write_text(home(city_list, items, demo), encoding="utf-8")
    detail_output = staging / "events"
    detail_output.mkdir()
    cities_by_code = {city["code"]: city for city in city_list}
    for event in items:
        (detail_output / (event["event_id"] + ".html")).write_text(
            detail(event, cities_by_code[event["city_code"]], demo), encoding="utf-8")
