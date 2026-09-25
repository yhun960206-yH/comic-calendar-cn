"""Bilibili 会员购「漫展演出」频道适配器（未公开接口，需设备指纹 cookie）。

风险与授权现状（必须与代码一起保留）：
- 使用的 listV2 / getV2 是站点内部接口，不是官方开放平台能力；官方开放平台
  不提供会员购展会目录，也没有可自助申请的授权路径。
- 列表接口在不携带 buvid3/buvid4 设备指纹时会忽略 page 参数、反复返回首页，
  实测第 2 页与第 1 页重合 18/20。因此必须先生成指纹，且指纹失败一律视为
  硬失败，绝不能把退化结果当成「今天活动少」发布。
- 本项目只整理活动名称、日期、城市、场馆、地址、嘉宾等短事实字段与原始链接，
  不复制封面图、详情正文、票档价格，不模拟登录。
- 该适配器可按需移除：去掉后日历退回官方公开源，历史记录不删除。
"""
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from ..model import CITY_CODES, CITY_PROVINCES, InputError, https_url

SPI_URL = "https://api.bilibili.com/x/frontend/finger/spi"
LIST_URL = ("https://show.bilibili.com/api/ticket/project/listV2"
            "?version=134&pagesize=20&area=-1&filter=start_time&platform=web&p_type=-1&page={page}")
DETAIL_URL = "https://show.bilibili.com/api/ticket/project/getV2?version=134&platform=web&id={pid}"
DETAIL_PAGE = "https://show.bilibili.com/platform/detail.html?id={pid}"

# 频道里混有主题餐厅、音乐会、话剧等；只保留真正的漫展与同人展。
CATEGORIES = {"漫展", "Only同人展"}
# B 站把取消写进活动名，实测 52/1144 条以「（取消）」结尾。
CANCELLED = re.compile(r"[（(]\s*取消\s*[)）]|延期")
PAGE_SIZE = 20
MAX_PAGES = 200
REQUEST_PAUSE = 0.35
MAX_GUESTS = 30
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
ATTRIBUTION = ("数据来源：B 站会员购漫展频道（未公开接口，非官方授权 API）。"
               "仅整理活动名称、日期、城市、场馆、地址与嘉宾；票务与最新安排以会员购页面及主办方为准。")
# 源异常缩水保护：上次有记录时，本次结果不得低于一半。
MIN_KEEP_RATIO = 2


class BiliSourceError(RuntimeError):
    pass


def _get_json(url, cookie, opener=urllib.request.urlopen, *, tries=3, pause=0.0):
    headers = {"User-Agent": UA, "Accept": "application/json", "Referer": "https://show.bilibili.com/"}
    if cookie:
        headers["Cookie"] = cookie
    last = None
    for attempt in range(tries):
        try:
            with opener(urllib.request.Request(url, headers=headers), timeout=30) as response:
                if response.geturl() != url:
                    raise BiliSourceError("unexpected redirect from bilibili endpoint")
                payload = json.loads(response.read(2_000_000).decode("utf-8"))
            if not isinstance(payload, dict):
                raise BiliSourceError("unexpected payload type")
            if pause:
                time.sleep(pause)
            return payload
        except BiliSourceError:
            raise
        except (OSError, ValueError, UnicodeError) as exc:
            last = exc
            if attempt < tries - 1:
                time.sleep(1.0 * (attempt + 1))
    raise BiliSourceError(f"bilibili endpoint unavailable: {last}")


def mint_cookie(*, opener=urllib.request.urlopen):
    """申请设备指纹。失败即硬失败：没有它分页会静默退化。"""
    payload = _get_json(SPI_URL, "", opener)
    data = payload.get("data") or {}
    b3, b4 = data.get("b_3"), data.get("b_4")
    if not (isinstance(b3, str) and isinstance(b4, str) and b3 and b4):
        raise BiliSourceError("device fingerprint unavailable; refusing to crawl")
    return f"buvid3={b3}; buvid4={b4}"


def _crawl_once(cookie, *, opener=urllib.request.urlopen, pause=REQUEST_PAUSE, max_pages=MAX_PAGES):
    """单轮翻到底。任何「无新增却未标记末页」都视为退化并中止。"""
    items, seen, page = [], set(), 0
    while page < max_pages:
        page += 1
        payload = _get_json(LIST_URL.format(page=page), cookie, opener, pause=pause)
        if payload.get("code") != 0:
            raise BiliSourceError(f"list page {page} rejected: {payload.get('message')!r}")
        data = payload.get("data") or {}
        rows = data.get("result") or []
        fresh = 0
        for row in rows:
            pid = row.get("id")
            if pid not in seen:
                seen.add(pid)
                items.append(row)
                fresh += 1
        if data.get("isLastBrush") or not rows:
            return items
        if fresh == 0:
            raise BiliSourceError(f"pagination stalled at page {page}; refusing a truncated list")
    raise BiliSourceError("pagination exceeded safety limit")


def fetch_list(cookie, *, opener=urllib.request.urlopen, pause=REQUEST_PAUSE,
               max_pages=MAX_PAGES, passes=3):
    """多轮抓取并取最完整的一轮。

    实测该接口会偶发提前返回 isLastBrush=True（900 条 vs 实际 1144 条），
    单轮结果不可信。连续两轮数量一致才提前结束；不一致时最多跑 passes 轮，
    取条数最多的一轮。若每轮都被截断，则仍可能少收录，这一点写在 README。
    """
    results = []
    for _ in range(max(2, passes)):
        results.append(_crawl_once(cookie, opener=opener, pause=pause, max_pages=max_pages))
        if len(results) >= 2 and len(results[-1]) == len(results[-2]):
            break
        time.sleep(1.5)
    return max(results, key=len)


def fetch_detail(pid, cookie, *, opener=urllib.request.urlopen, pause=REQUEST_PAUSE):
    """单条详情。失败不致命：列表字段已足够入库，缺失的地址/嘉宾留空。"""
    try:
        payload = _get_json(DETAIL_URL.format(pid=pid), cookie, opener, tries=2, pause=pause)
    except BiliSourceError:
        return None
    if payload.get("code") != 0:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def _address(row, detail):
    """用我们自己的省市规范名拼地址，避开「上海上海」这类重复。"""
    info = (detail or {}).get("venue_info") or {}
    street = str(info.get("address_detail") or "").strip()
    code = str(row.get("cityId"))
    city = CITY_CODES.get(code, "")
    province = CITY_PROVINCES.get(code, "")
    if street:
        prefix = city if province == city else province + city
        return f"{prefix}{street}" if prefix else street
    parts = [str(info.get("province_name") or "").strip(), str(info.get("city_name") or "").strip(),
             str(row.get("district_name") or "").strip(), str(row.get("venue_name") or "").strip()]
    return "".join(dict.fromkeys(part for part in parts if part))


def _guests(detail):
    names = []
    for guest in (detail or {}).get("guests") or []:
        if not isinstance(guest, dict):
            continue
        name = guest.get("name")
        if isinstance(name, str) and name.strip():
            cleaned = " ".join(name.split())
            if cleaned and cleaned not in names:
                names.append(cleaned)
    return names[:MAX_GUESTS]


def _map_url(row, detail):
    raw = ((detail or {}).get("venue_info") or {}).get("coordinate") or {}
    if not raw:
        raw = {}
        text = row.get("coordinate")
        if isinstance(text, str):
            try:
                raw = json.loads(text)
            except ValueError:
                raw = {}
    coor = raw.get("coor")
    if not isinstance(coor, str) or "," not in coor:
        return None
    left, _, right = coor.partition(",")
    try:
        lng, lat = float(left), float(right)
    except ValueError:
        return None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        return None
    return "https://uri.amap.com/marker?position=" + urllib.parse.quote(f"{lng},{lat}", safe=",.")


def normalize(row, detail, observed_at):
    """返回一个完整候选，或一条隔离原因。字段缺失时不猜、不编。"""
    if not isinstance(row, dict):
        return None, "not an object"
    pid = row.get("id")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None, "missing event id"
    code = str(row.get("cityId") or "")
    if code not in CITY_CODES:
        return None, f"unsupported cityId {code!r}"
    name = row.get("project_name")
    if not isinstance(name, str) or not name.strip():
        return None, "missing title"
    title = " ".join(name.split())
    start = row.get("start_time")
    end = row.get("end_time") or start
    try:
        start_day = datetime.strptime(start, "%Y-%m-%d").date()
        end_day = datetime.strptime(end, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None, "missing or malformed dates"
    if end_day < start_day:
        return None, "end date before start"
    venue = str(row.get("venue_name") or "").strip()
    if not venue:
        venue = str(((detail or {}).get("venue_info") or {}).get("name") or "").strip()
    address = _address(row, detail)
    if not venue or not address:
        return None, "venue or address not published"
    try:
        source = https_url(DETAIL_PAGE.format(pid=pid), "bilibili detail page")
    except InputError as exc:
        return None, f"invalid source url: {exc}"
    candidate = {
        "event_id": f"bili-{pid}",
        "revision": 0,
        "status": "cancelled" if CANCELLED.search(title) else "confirmed",
        "city_code": code,
        "title": CANCELLED.sub("", title).strip() or title,
        "start_date": start_day.isoformat(),
        "end_date": (end_day + timedelta(days=1)).isoformat(),
        "updated_at": observed_at,
        "venue_name": venue,
        "venue_address": address,
        "source_url": source,
        "ticket_url": source,
        "attribution": ATTRIBUTION,
    }
    guests = _guests(detail)
    if guests:
        candidate["guests"] = guests
    map_url = _map_url(row, detail)
    if map_url:
        candidate["map_url"] = map_url
    return candidate, None


def fetch_candidates(*, opener=urllib.request.urlopen, pause=REQUEST_PAUSE, detail_limit=None,
                     previous=None):
    """抓取全量频道并规范化。返回 (accepted, quarantined, observed_at)。

    传 previous 时，对「已在库里且场馆未变」的活动跳过详情请求，直接复用已存的
    街道地址与嘉宾。首次跑约 1144 次详情请求（~10 分钟），往后只抓新增活动，
    既减负也降低接口提前截断的概率。
    """
    cookie = mint_cookie(opener=opener)
    rows = fetch_list(cookie, opener=opener, pause=pause)
    channel = [row for row in rows if row.get("third_category_name") in CATEGORIES]
    if not channel:
        raise BiliSourceError("channel returned no 漫展/Only同人展 rows; retain previous site")
    known = {}
    for event in previous or []:
        if isinstance(event, dict) and str(event.get("event_id", "")).startswith("bili-"):
            known[event["event_id"]] = event
    observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    accepted, quarantined = [], []
    reused = 0
    for index, row in enumerate(channel):
        pid = row.get("id")
        stored = known.get(f"bili-{pid}")
        same_venue = bool(stored) and stored.get("venue_name") == str(row.get("venue_name") or "").strip()
        detail = None
        if not same_venue and (detail_limit is None or index < detail_limit):
            detail = fetch_detail(pid, cookie, opener=opener, pause=pause)
        elif same_venue:
            reused += 1
        candidate, reason = normalize(row, detail, observed_at)
        if candidate is None:
            quarantined.append({"source_url": DETAIL_PAGE.format(pid=pid) if pid else "bilibili-channel",
                                "reason": reason})
            continue
        if same_venue:
            candidate["venue_address"] = stored.get("venue_address", candidate["venue_address"])
            for field in ("map_url", "guests"):
                if field not in candidate and stored.get(field):
                    candidate[field] = stored[field]
        accepted.append(candidate)
    if not accepted:
        raise BiliSourceError("no complete bilibili events; retain previous site")
    return accepted, quarantined, observed_at


def count_published(previous):
    return sum(1 for event in previous if str(event.get("event_id", "")).startswith("bili-"))


def prune_expired(previous, *, today=None, keep_days=30):
    """丢弃很久以前结束的 B 站活动，避免检查点无限增长。

    只影响 bili- 前缀的源管理记录，且必须已经结束超过 keep_days 天；
    不触碰人工核对记录与其它来源。这样做的代价是历史记录不再保留，
    所以阈值写在 README 里而不是隐式生效。
    """
    cutoff = (today or datetime.now(timezone.utc).date()) - timedelta(days=keep_days)
    kept, dropped = [], 0
    for event in previous:
        if str(event.get("event_id", "")).startswith("bili-"):
            try:
                ended = datetime.strptime(event["end_date"], "%Y-%m-%d").date()
            except (KeyError, TypeError, ValueError):
                kept.append(event)
                continue
            if ended < cutoff:
                dropped += 1
                continue
        kept.append(event)
    return kept, dropped
