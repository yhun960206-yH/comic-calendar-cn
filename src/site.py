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
              '仅展示已录入且通过字段校验的活动；来源真实性与覆盖范围以公告为准。')
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
    <a class="brand" href="{prefix}index.html">漫展日历<span aria-hidden="true"> ↗</span></a>
    <nav class="header-nav" aria-label="站内导航"><a href="{prefix}index.html#city-picker">选择城市</a><a href="{prefix}index.html#how-to-subscribe">如何订阅</a></nav>
  </div></header>
  {warning}
  <main class="wrap">{content}</main>
  <footer class="wrap footer"><span>{caption}</span><p>{footer}日期与时间以活动公告为准；未公布开放时间时使用全天事件。</p></footer>
</body></html>
'''


def copy_control(url):
    return (f'<div class="feed-copy"><a class="feed-url" href="{text(url)}">{text(url)}</a>'
            f'<button type="button" class="copy-button" data-copy="{text(url)}">复制订阅链接</button>'
            '<span class="copy-result" role="status" aria-live="polite"></span></div>')


def home(city_list, items, demo):
    # A 372-city feed catalog does not mean 372 cities have events. Put the
    # populated cities first without changing their stable feed URLs.
    displayed_cities = sorted(city_list, key=lambda city: -city["event_count"])
    populated = sum(city["event_count"] > 0 for city in city_list)
    links = ''.join(f'<a class="city-link" href="#city-{text(city["code"])}" '
                    f'data-city="{text(city["code"])}" data-count="{city["event_count"]}" '
                    f'data-name="{text(city["province"] + city["name"])}">{text(city["province"])} · {text(city["name"])}'
                    f'<span class="city-count">{city["event_count"]} 场</span></a>'
                    for city in displayed_cities)
    sections = []
    for city in displayed_cities:
        code = city["code"]
        rows = [event for event in items if event["city_code"] == code]
        if rows:
            cards = ''.join(
                '<article class="event-card">'
                f'<p class="event-date">{text(date_label(event))}</p>'
                f'<h3><a href="events/{text(event["event_id"])}.html">{text(event["title"])}</a></h3>'
                f'<p>{text(event["venue_name"])} · {text(event["venue_address"])}</p>'
                + ('<span class="cancelled">已取消</span>' if event["status"] == "cancelled" else '')
                + '</article>' for event in rows)
        else:
            cards = ('<p class="empty">该城市暂无已收录活动；不代表这里没有漫展。'
                     '收录来源有限，不能保证普通漫展或其他活动被完整收录。你仍可提前订阅。</p>')
        sections.append(f'''<section class="city-panel" id="city-{text(code)}" data-panel="{text(code)}">
    <div class="section-heading"><div><p class="eyebrow">02 / GET YOUR LINK</p><h2>{text(city["name"])}日历</h2></div>
    <span class="count">目前已录入 {city["event_count"]} 场</span></div>
    <div class="feed-box"><p class="feed-label">订阅{text(city["name"])}及所辖区县已收录的活动</p>
      <p class="hint">复制这条 HTTPS 地址；接下来在日历应用中选择“通过 URL 订阅”。</p>
      {copy_control(city["feed_url"])}
      <p class="feed-after">复制后还需要在日历应用中添加地址；仅点击链接或下载文件不等于已订阅。</p></div>
    <div class="event-heading"><h3>已收录活动</h3><p>日期和地点以主办方最新公告为准。</p></div>
    <div class="event-list">{cards}</div>
  </section>''')
    lead = ('以下均为虚构 DEMO 活动，不代表真实漫展或票务信息。' if demo else
            '选好城市，把已收录的漫展添加到你常用的日历。无需账号，日历会按应用自身的周期检查更新。')
    verified = max((event["updated_at"] for event in items), default=None)
    freshness = ('最近来源观察／人工核对：' + text(verified) + '（UTC）' if verified else
                 '尚无已收录活动；没有可报告的最近观察时间。')
    content = f'''<section class="hero"><p class="eyebrow">漫展日历 / 按城市订阅</p>
    <h1>漫展消息太多？<br>订阅一座城市。</h1><p class="hero-lead">{lead}</p>
    <a class="hero-action" href="#city-picker">选择城市 <span aria-hidden="true">↗</span></a>
    <p class="hero-footnote">一座城市，一条长期订阅的日历地址。不是购票或活动报名。</p></section>
    <section class="picker" id="city-picker"><div class="picker-intro"><p class="eyebrow">01 / FIND YOUR CITY</p>
      <h2>先找你的城市。</h2><p>输入城市或省份，再从结果中选择。即使暂时没有活动，也可以先订阅。</p></div>
      <div class="picker-control"><label for="city-search">城市或省份</label>
      <input id="city-search" type="search" placeholder="例如：北京、广东深圳" autocomplete="off"
        aria-controls="city-nav">
      <details class="city-directory" id="city-directory"><summary>浏览全部 {len(city_list)} 个城市 <span aria-hidden="true">＋</span></summary>
        <nav class="city-nav" id="city-nav" aria-label="选择城市">{links}</nav>
        <p class="search-empty" hidden>没有匹配的城市，请换一个关键词试试。</p></details>
      <noscript><p class="hint">搜索需要启用 JavaScript；也可以展开上方目录逐个选择城市。</p></noscript></div></section>
    {''.join(sections)}
    <section class="guide" id="how-to-subscribe"><div class="guide-intro"><p class="eyebrow">03 / ADD TO YOUR CALENDAR</p>
      <h2>最后，在日历里添加。</h2><p>复制链接后，在你使用的应用里找“通过 URL 订阅”，不要选择只导入一次的 .ics 文件。不同应用的刷新时间由应用决定。</p></div>
      <div class="guide-options">
        <details><summary>iPhone / iCloud 日历</summary><p>打开「日历」中的日历列表，选择添加日历，再选择添加订阅日历并粘贴地址。具体菜单以设备系统版本为准。</p><a href="https://support.apple.com/en-us/102301" target="_blank" rel="noopener noreferrer">Apple 官方说明 ↗</a></details>
        <details><summary>Google 日历（电脑网页）</summary><p>在左侧「其他日历」旁选择添加，再选择「通过网址」，粘贴订阅地址。Google 的此操作需要在电脑浏览器中完成。</p><a href="https://support.google.com/calendar/answer/37100" target="_blank" rel="noopener noreferrer">Google 官方说明 ↗</a></details>
        <details><summary>Outlook 网页版</summary><p>进入日历，选择「添加日历」→「从 Web 订阅」，粘贴地址并保存。不同 Outlook 版本的菜单可能不同。</p><a href="https://support.microsoft.com/en-us/outlook/import-or-subscribe-to-a-calendar-in-outlook-com-or-outlook-on-the-web" target="_blank" rel="noopener noreferrer">Microsoft 官方说明 ↗</a></details>
      </div></section>
    <aside class="data-note"><p class="eyebrow">关于收录</p><p class="coverage">目前收录 {len(items)} 场活动，分布在 {populated} / {len(city_list)} 个城市。多数城市为 0，不代表没有漫展。</p>
      <p>日历只包含已录入且通过字段校验的活动，无法保证覆盖全部漫展；订阅前后都请核对主办方公告。{freshness}</p></aside>'''
    return shell("订阅城市日历", content, demo=demo)


def detail(event, city, demo):
    status = '<span class="cancelled">已取消 · 保留在订阅日历中通知变更</span>' if event["status"] == "cancelled" else ''
    guests = ('<div class="info-row"><dt>嘉宾</dt><dd>'
              + '、'.join(text(guest) for guest in event["guests"]) + '</dd></div>'
              if event.get("guests") else '')
    attribution = (f'<div class="info-row"><dt>数据来源</dt><dd>{text(event["attribution"])}</dd></div>'
                   if event.get("attribution") else '')
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
        {guests}{attribution}
        <div class="info-row"><dt>最近观察／核对</dt><dd><time datetime="{text(event["updated_at"])}">{text(event["updated_at"])}</time>（UTC）</dd></div>
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
