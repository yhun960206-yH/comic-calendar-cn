"""Render the MVP architecture reference image with Pillow (python3 architecture_diagram.py)."""
from PIL import Image, ImageDraw, ImageFont

W, H = 1800, 1110
im = Image.new('RGB', (W, H), '#f5f7fb')
d = ImageDraw.Draw(im)
font = '/System/Library/Fonts/Hiragino Sans GB.ttc'
F = lambda n: ImageFont.truetype(font, n)
navy, muted, blue = '#15243a', '#50627a', '#2470e6'

def text(x, y, s, size=24, color=navy):
    d.text((x, y), s, font=F(size), fill=color)

def box(x0, y0, x1, y1, title, rows, tint='#ffffff', accent=blue):
    d.rounded_rectangle((x0, y0, x1, y1), 20, fill=tint, outline='#d9e1eb', width=2)
    d.rounded_rectangle((x0+1, y0+1, x0+9, y1-1), 4, fill=accent)
    text(x0+28, y0+17, title, 30)
    for i, row in enumerate(rows):
        text(x0+28, y0+65+i*35, row, 22, muted)

def arrow(x0, y0, x1, y1, label=None, color=blue):
    d.line((x0, y0, x1, y1), fill=color, width=5)
    if x1 > x0: pts = [(x1,y1),(x1-15,y1-10),(x1-15,y1+10)]
    elif x1 < x0: pts = [(x1,y1),(x1+15,y1-10),(x1+15,y1+10)]
    elif y1 > y0: pts = [(x1,y1),(x1-10,y1-15),(x1+10,y1-15)]
    else: pts = [(x1,y1),(x1-10,y1+15),(x1+10,y1+15)]
    d.polygon(pts, fill=color)
    if label: text(min(x0,x1)+12, min(y0,y1)-31, label, 18, muted)

text(70, 43, '漫展日历订阅｜MVP 系统架构', 43)
text(72, 109, '从可信活动信息到持续更新的日历订阅；首版不依赖账号、推送或复杂爬虫', 23, muted)
d.line((70,156,1730,156), fill='#d9e1eb', width=2)

box(70,205,390,395,'信息来源',['官方活动页 / 主办方公告','人工录入与纠错'], '#eaf3ff')
box(530,205,850,395,'采集与整理',['定时检查 / 手动导入','提取来源链接与原始内容'], '#eaf3ff')
box(990,205,1330,395,'审核与规范化',['去重、地址 / 时区核对','待核实 → 发布 / 取消'], '#fff5e9', '#e88d24')
arrow(390,300,530,300)
arrow(850,300,990,300)

box(990,515,1330,705,'活动数据库',['活动 ID、来源、时间地点','状态、修订版本与更新时间'], '#edf8f2', '#20a36b')
arrow(1160,395,1160,515,'审核后入库')

box(530,515,850,705,'Web / 日历服务',['按城市、日期检索活动','生成公开筛选链接与 .ics'], '#eef0ff', '#6857c9')
arrow(990,610,850,610)
box(70,515,390,705,'访问入口',['网页选择城市 / 关键词','复制订阅 URL'], '#eef0ff', '#6857c9')
arrow(390,610,530,610)

box(70,825,710,1010,'日历客户端',['Apple 日历 / Google 日历 / Outlook','定期拉取 .ics，自动同步变更'], '#eaf3ff')
arrow(310,705,310,825,'订阅 URL')
arrow(630,705,630,825,'.ics 拉取')
box(910,825,1730,1010,'边界与保障',['统一时区存储；稳定 UID 与版本号，取消事件保留可同步','来源可追溯；遵守来源站点规则；HTTPS + 限流 + 缓存'], '#fff5e9', '#e88d24')
text(82,1050,'实线箭头：主要数据流  ·  活动先审核再发布  ·  初版优先人工收录，自动化采集按需扩展',20,muted)
im.save('漫展日历订阅-架构图.png', optimize=True)
