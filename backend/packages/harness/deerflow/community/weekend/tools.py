"""WeekenD Skill 工具实现。

对应 WeekenD 技术方案 v3.0 第四章定义的 6 个 Skill。每个工具都是一个
独立的可调用单元，Agent 通过 function calling 触发，不直接操作外部资源。

黑客松 MVP 策略：内置 mock 数据保证端到端可跑通；真实接入点已标注 TODO，
替换为真实 API 即可平滑升级。所有工具的输入/输出 JSON 结构与 PRD 一致。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from langchain.tools import tool

from deerflow.community.weekend.mock_data import (
    MOCK_NOTES,
    MOCK_POIS,
    MOCK_WALK_SEGMENTS,
)
from deerflow.community.weekend.rpa_bridge import (
    call_amap_route,
    call_ctrip_flight,
    call_ctrip_flight_batch,
    city_to_code,
    extract_pois_from_notes,
    get_ask_raw,
    get_xhs_search_raw,
    render_amap_markdown,
    render_ask_markdown,
    render_ctrip_markdown,
    render_xhs_search_markdown,
    search_notes,
    search_posts,
)

logger = logging.getLogger(__name__)

# 简单内存缓存：同一天内相同 query 走缓存不重复请求（PRD 4.1 要求）
_SEARCH_CACHE: dict[str, Any] = {}
# 搜索结果的笔记存储（按 note_id 索引），供 extract_poi 查找真实数据
_SEARCH_NOTE_CACHE: dict[str, dict] = {}
# 打卡卡片内存存储：checkin_id -> card 状态
_CHECKIN_CARDS: dict[str, dict] = {}
# RPA 是否可用（首次调失败后禁用，避免反复尝试）
_RPA_AVAILABLE = True
# 逐天行程提交存储：plan_id -> {days: {...}, total_days, ...}
_DAILY_PLANS: dict[str, dict] = {}


def _looks_like_url(s: Any) -> bool:
    """粗略判断一个字符串是否是可点开的链接。"""
    if not isinstance(s, str):
        return False
    low = s.strip().lower()
    return low.startswith("http://") or low.startswith("https://") or "xiaohongshu.com" in low


def _extract_source_urls(stop: dict) -> list[str]:
    """从一个 stop 里提取所有信源 URL，兼容 sources/source、dict/str 多种写法。"""
    urls: list[str] = []
    for key in ("sources", "source"):
        raw = stop.get(key)
        if not raw:
            continue
        items = raw if isinstance(raw, list) else [raw]
        for it in items:
            if isinstance(it, dict):
                u = it.get("url") or it.get("href") or ""
                if _looks_like_url(u):
                    urls.append(u.strip())
            elif _looks_like_url(it):
                urls.append(it.strip())
    return urls


# "逐点坐实"类信源：必须是针对具体地点真正查过的，而不是点点攻略骨架里抄的名字
_GROUNDED_FROM = {
    "xiaohongshu_post_search",
    "web_search",
    "web_fetch",
}
# 点点攻略骨架类信源：只能作为方向，不能作为某个地点的唯一信源
_SKELETON_FROM = {
    "xiaohongshu_guide_search",
}


def _looks_like_grounded_url(u: str) -> bool:
    """URL 启发式：是否像"逐点坐实"拿到的链接（具体帖子/官网/媒体），而非点点攻略页。

    用于某条 source 没标 from 字段时的兜底判断，避免误伤。
    - 小红书具体帖子 explore/discovery/item 链接 → 算坐实
    - 任何非小红书域名（官网/媒体等）→ 算坐实
    - 其余小红书域名（疑似攻略/搜索页）→ 不算坐实
    """
    low = (u or "").strip().lower()
    if not low:
        return False
    if "xiaohongshu.com" in low or "xhslink.com" in low:
        # 小红书：只有指向"具体一篇笔记"的才算坐实
        return any(seg in low for seg in ("/explore/", "/discovery/", "/item/", "xhslink.com"))
    # 非小红书域名（官网/媒体/票务等）一律算坐实
    return low.startswith("http://") or low.startswith("https://")


def _source_is_grounded(src: Any) -> bool:
    """判断单条 source 是否属于"逐点坐实"信源。"""
    if isinstance(src, dict):
        frm = str(src.get("from", "")).strip()
        if frm in _GROUNDED_FROM:
            return True
        if frm in _SKELETON_FROM:
            return False
        # 没标 from（或标了别的）→ 用 URL 启发式兜底
        url = src.get("url") or src.get("href") or ""
        return _looks_like_grounded_url(url)
    if isinstance(src, str):
        return _looks_like_grounded_url(src)
    return False


def _stop_grounded_sources(stop: dict) -> list[Any]:
    """返回一个 stop 里所有"逐点坐实"类信源。"""
    grounded: list[Any] = []
    for key in ("sources", "source"):
        raw = stop.get(key)
        if not raw:
            continue
        items = raw if isinstance(raw, list) else [raw]
        for it in items:
            if _source_is_grounded(it):
                grounded.append(it)
    return grounded


def _stops_missing_sources(stops: list[dict]) -> list[str]:
    """返回缺少真实信源 URL 的站点名列表（空列表 = 全部通过）。"""
    missing: list[str] = []
    for s in stops or []:
        if not _extract_source_urls(s):
            missing.append(s.get("name", "") or "(未命名地点)")
    return missing


def _stops_missing_grounded_sources(stops: list[dict]) -> list[str]:
    """返回"虽然有 URL、但没有任何逐点坐实信源（全靠点点攻略蒙混）"的站点名列表。

    用于 D 轻量版硬校验：每个地点至少要有一条来自 xiaohongshu_post_search /
    web_search / web_fetch 的真实信源，不能整条 sources 全是点点攻略骨架。
    """
    weak: list[str] = []
    for s in stops or []:
        # 先得有 URL（无 URL 由 _stops_missing_sources 负责报错，这里只看"有 URL 但都不坐实"）
        if not _extract_source_urls(s):
            continue
        if not _stop_grounded_sources(s):
            weak.append(s.get("name", "") or "(未命名地点)")
    return weak


def _source_is_xhs_post(src: Any) -> bool:
    """判断单条 source 是否是一篇【小红书帖子】（带封面图的那种真实笔记）。

    判定：from == "xiaohongshu_post_search"，或 URL 指向小红书具体一篇笔记
    （/explore/、/discovery/、/item/、xhslink.com）。
    点点攻略（xiaohongshu_guide_search）不算帖子。
    """
    if isinstance(src, dict):
        frm = str(src.get("from", "")).strip()
        if frm == "xiaohongshu_post_search":
            return True
        if frm == "xiaohongshu_guide_search":
            return False
        url = src.get("url") or src.get("href") or ""
    elif isinstance(src, str):
        url = src
    else:
        return False
    low = (url or "").strip().lower()
    if "xhslink.com" in low:
        return True
    if "xiaohongshu.com" in low:
        return any(seg in low for seg in ("/explore/", "/discovery/", "/item/"))
    return False


def _day_has_post_source(stops: list[dict]) -> bool:
    """这一天的所有地点里，是否【至少有一个】采用了小红书帖子作为信源。

    需求：每天至少要去访问并采用一篇小红书帖子，因为帖子带封面图，最生动。
    """
    for s in stops or []:
        for key in ("sources", "source"):
            raw = s.get(key)
            if not raw:
                continue
            items = raw if isinstance(raw, list) else [raw]
            for it in items:
                if _source_is_xhs_post(it):
                    return True
    return False


def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


# ===========================================================================
# 4.1 xiaohongshu-guide-search — 小红书点点攻略搜索（点点 AI 攻略总结）
# ===========================================================================
@tool("xiaohongshu_guide_search", parse_docstring=True)
def xiaohongshu_guide_search_tool(
    query: str,
    city: str = "上海",
    budget_max: int = 0,
    max_results: int = 20,
) -> str:
    """用小红书「点点 AI」搜索出行攻略：基于真实笔记给出 AI 总结的攻略（含地点推荐、行程建议）。

    适合"帮我规划""有什么推荐"这类需要攻略总结的场景。返回的 JSON 包含
    display_markdown（点点 AI 的真实攻略回答）和 notes（结构化笔记列表）。
    请把 display_markdown 原封不动展示给用户，再用 notes 继续后续处理。

    如果用户想看一篇篇真实帖子（带封面图）而不是 AI 总结，请改用 xiaohongshu_post_search。

    Args:
        query: 搜索关键词，例如 "周末 展览 下午茶"。应包含类型、时段等信息。
        city: 城市名，默认上海。
        budget_max: 预算上限（元），0 表示不限。
        max_results: 最多返回的笔记数量，默认 20。
    """
    cache_key = f"guide::{_today_key()}::{city}::{query}::{budget_max}"
    if cache_key in _SEARCH_CACHE:
        logger.info("xiaohongshu_guide_search cache hit: %s", cache_key)
        return _SEARCH_CACHE[cache_key]

    global _RPA_AVAILABLE
    notes: list[dict] = []
    display_markdown = ""  # 点点 AI 原文，原封不动展示给用户

    # 尝试真实 RPA 搜索（点点 AI）
    if _RPA_AVAILABLE:
        try:
            raw = get_ask_raw(query, city)
            if raw:
                # 1) 渲染点点原文 Markdown（核心：原封不动展示）
                display_markdown = render_ask_markdown(raw, query, city)
                # 2) 解析结构化笔记，供后续 extract_poi 使用
                rpa_notes = search_notes(query, city)
                if rpa_notes:
                    notes = rpa_notes
                logger.info(
                    "RPA returned answer (%d chars) + %d notes for query=%r (city=%s)",
                    len(display_markdown), len(notes), query, city,
                )
            else:
                logger.warning("RPA returned empty result, falling back to mock")
        except Exception as e:
            logger.warning("RPA call failed (%s), falling back to mock", e)
            _RPA_AVAILABLE = False

    # 降级：mock 数据
    if not notes:
        notes = [dict(n) for n in MOCK_NOTES]
        notes.sort(
            key=lambda n: n.get("likes", 0) + n.get("collections", 0),
            reverse=True,
        )
        logger.info("Using mock data: %d notes", len(notes))

    notes = notes[:max_results]

    # 缓存笔记详情供 extract_poi 使用
    for n in notes:
        _SEARCH_NOTE_CACHE[n["id"]] = n

    result: dict[str, Any] = {"notes": notes}
    # display_markdown：点点 AI 的原始回答，Agent 应原封不动展示给用户
    if display_markdown:
        result["display_markdown"] = display_markdown
        result["_instruction"] = (
            "请把 display_markdown 字段的内容【原封不动】展示给用户"
            "（这是小红书点点 AI 的真实攻略回答，包含真实地点推荐和配图），"
            "然后再基于 notes 继续后续的 POI 提取和路线规划。"
        )

    output = json.dumps(result, ensure_ascii=False, indent=2)
    _SEARCH_CACHE[cache_key] = output
    logger.info("xiaohongshu_guide_search returned %d notes for query=%r", len(notes), query)
    return output


# ===========================================================================
# 4.1b xiaohongshu-post-search — 小红书帖子搜索（真实笔记 + 封面图）
# ===========================================================================
@tool("xiaohongshu_post_search", parse_docstring=True)
def xiaohongshu_post_search_tool(
    query: str,
    city: str = "上海",
    max_results: int = 12,
) -> str:
    """在小红书上按关键词搜索真实帖子，返回一篇篇笔记卡片（含标题、封面图、点赞数、作者、原帖链接）。

    适合"看看小红书上的帖子""有什么真实笔记"这类想浏览原始内容的场景。
    返回的 JSON 包含 display_markdown（带封面图的帖子卡片列表）和 notes（结构化笔记）。
    请把 display_markdown 原封不动展示给用户，让用户看到真实的帖子和配图。

    如果用户想要 AI 总结的攻略（而不是一篇篇帖子），请改用 xiaohongshu_guide_search。

    Args:
        query: 搜索关键词，例如 "周末 展览"。
        city: 城市名，默认上海。
        max_results: 最多展示的帖子数量，默认 12。
    """
    cache_key = f"post::{_today_key()}::{city}::{query}"
    if cache_key in _SEARCH_CACHE:
        logger.info("xiaohongshu_post_search cache hit: %s", cache_key)
        return _SEARCH_CACHE[cache_key]

    notes: list[dict] = []
    display_markdown = ""

    try:
        raw = get_xhs_search_raw(query, city)
        if raw:
            display_markdown = render_xhs_search_markdown(raw, max_notes=max_results)
            notes = search_posts(query, city)[:max_results]
            logger.info(
                "xhs post search returned %d posts for query=%r (city=%s)",
                len(notes), query, city,
            )
        else:
            logger.warning("xhs post search returned empty result")
    except Exception as e:  # noqa: BLE001
        logger.warning("xhs post search failed: %s", e)

    # 缓存笔记供 extract_poi 使用
    for n in notes:
        _SEARCH_NOTE_CACHE[n["id"]] = n

    if not display_markdown:
        display_markdown = (
            f"📕 **小红书帖子搜索**（{city} {query}）\n\n"
            "> 这次没搜到帖子（可能是网络/登录态问题或关键词太窄），建议换个关键词再试。"
        )

    result: dict[str, Any] = {
        "notes": notes,
        "display_markdown": display_markdown,
        "_instruction": (
            "请把 display_markdown 字段的内容【原封不动】展示给用户"
            "（这是小红书的真实帖子卡片，含封面图、点赞、作者和原帖链接），"
            "然后再基于 notes 继续后续处理。"
        ),
    }

    output = json.dumps(result, ensure_ascii=False, indent=2)
    _SEARCH_CACHE[cache_key] = output
    logger.info("xiaohongshu_post_search returned %d posts for query=%r", len(notes), query)
    return output


# ===========================================================================
# 4.2 extract-poi — 地点信息提取
# ===========================================================================
@tool("extract_poi", parse_docstring=True)
def extract_poi_tool(note_ids: list[str]) -> str:
    """从种草笔记中提取结构化的 POI（地点）信息：名称、类型、人均、营业时间、注意事项、用户评价等。

    Args:
        note_ids: 要提取的笔记 id 列表（来自 xiaohongshu_search 返回的 notes[].id）。
    """
    pois: list[dict] = []
    seen_names: set[str] = set()

    # 优先从搜索缓存中提取真实 POI
    cached_notes = [n for nid in note_ids if (n := _SEARCH_NOTE_CACHE.get(nid))]
    if cached_notes:
        rpa_pois = extract_pois_from_notes(cached_notes)
        if rpa_pois:
            for poi in rpa_pois:
                if poi["name"] not in seen_names:
                    seen_names.add(poi["name"])
                    pois.append(poi)
            logger.info("extract_poi from RPA: %d POIs", len(pois))
            return json.dumps({"pois": pois}, ensure_ascii=False, indent=2)

    # 降级：mock 数据
    for nid in note_ids:
        poi = MOCK_POIS.get(nid)
        if poi is None:
            logger.warning("extract_poi: no POI found for note_id=%s", nid)
            continue
        if poi["name"] in seen_names:
            continue
        seen_names.add(poi["name"])
        pois.append(dict(poi))

    logger.info("extract_poi extracted %d POIs from %d notes", len(pois), len(note_ids))
    return json.dumps({"pois": pois}, ensure_ascii=False, indent=2)


# ===========================================================================
# 4.3 amap-route — 路线规划
# ===========================================================================
@tool("amap_route", parse_docstring=True)
def amap_route_tool(
    origin: str,
    waypoints: list[str],
    city: str = "上海",
    mode: str = "步行",
) -> str:
    """调用高德地图真实路径规划 API 验证出行路线，计算各路段距离和耗时。支持步行/公交/驾车。

    返回的 JSON 含 display_markdown（每段路线的真实导航结果），请原封不动展示给用户，
    让用户看到「真的去高德验证了路线」。

    Args:
        origin: 起点地点名称。
        waypoints: 途经/终点地点名称列表，按访问顺序排列。
        city: 城市名，默认上海。
        mode: 出行方式，可选 步行/公交/驾车，默认步行。
    """
    stops = [origin, *waypoints]
    segments: list[dict] = []
    total_distance = 0.0
    total_time = 0
    markdown_blocks: list[str] = []
    used_real = False

    for i in range(len(stops) - 1):
        a, b = stops[i], stops[i + 1]
        data = None
        try:
            data = call_amap_route(a, b, mode=mode, city=city)
        except Exception as e:  # noqa: BLE001
            logger.warning("amap_route real call failed for %s->%s: %s", a, b, e)

        if data and data.get("route"):
            used_real = True
            route = data["route"]
            rtype = data.get("type", "")
            if rtype in ("driving", "walking"):
                km = round(int(route.get("distance", 0)) / 1000, 2)
                minutes = round(int(route.get("duration", 0)) / 60)
            elif rtype == "transit":
                transits = route.get("transits", []) or []
                first = transits[0] if transits else {}
                km = round(int(first.get("distance", 0) or 0) / 1000, 2)
                minutes = round(int(first.get("duration", 0) or 0) / 60)
            else:
                km, minutes = 0.0, 0
            buffered = int(round(minutes * 1.3))
            segments.append(
                {"from": a, "to": b, "distance_km": km, "walk_min": buffered}
            )
            total_distance += km
            total_time += buffered
            md = render_amap_markdown(data)
            if md:
                markdown_blocks.append(md)
        else:
            # 降级：mock 段
            km, minutes = (
                MOCK_WALK_SEGMENTS.get((a, b))
                or MOCK_WALK_SEGMENTS.get((b, a))
                or (1.2, 15)
            )
            buffered = int(round(minutes * 1.3))
            segments.append(
                {"from": a, "to": b, "distance_km": km, "walk_min": buffered}
            )
            total_distance += km
            total_time += buffered

    route = {
        "total_distance_km": round(total_distance, 1),
        "total_time_min": total_time,
        "segments": segments,
    }
    result: dict[str, Any] = {"routes": [route]}

    if markdown_blocks:
        header = f"🗺️ **路线验证完成**（共 {len(segments)} 段 · 全程约 {round(total_distance, 1)} km · {total_time} 分钟）"
        result["display_markdown"] = header + "\n\n" + "\n\n---\n\n".join(markdown_blocks)
        result["_instruction"] = (
            "请把 display_markdown 字段的内容【原封不动】展示给用户"
            "（这是高德地图的真实路线验证结果，含每段距离、耗时和导航步骤），"
            "然后再继续后续的行程整理。"
        )

    logger.info(
        "amap_route planned %d segments, %.1fkm, %dmin (real=%s)",
        len(segments), total_distance, total_time, used_real,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ===========================================================================
# 4.3b flight-search — 机票查询（携程）
# ===========================================================================
def _validate_flight_segment(seg: dict) -> str | None:
    """校验单个航段参数。返回 None 表示通过，否则返回错误描述。"""
    dep = (seg.get("dep_city") or "").strip()
    arr = (seg.get("arr_city") or "").strip()
    date = (seg.get("date") or "").strip()
    if not dep or not arr or not date:
        return "航段缺少 dep_city / arr_city / date 之一"
    if city_to_code(dep) == city_to_code(arr):
        return (
            f"出发地和目的地解析后相同（都是 {dep}）。dep_city 应是【出发地】、"
            "arr_city 应是【目的地】，两者必须不同。"
        )
    return None


@tool("flight_search", parse_docstring=True)
def flight_search_tool(
    dep_city: str = "",
    arr_city: str = "",
    date: str = "",
    segments: list[dict] | None = None,
) -> str:
    """调用携程查询真实机票价格和航班时刻（用于跨城周末/小长假出行）。

    支持两种用法：
    1) 单段查询：直接传 dep_city / arr_city / date。
    2) 多段并发查询（推荐用于来程+回程，或多城对比）：传 segments，
       每个元素是 {"dep_city","arr_city","date"}。多段会【同时并发】查询，速度更快。
       例如来回程：segments=[
         {"dep_city":"上海","arr_city":"东京","date":"2026-06-12"},
         {"dep_city":"东京","arr_city":"上海","date":"2026-06-15"}
       ]

    返回的 JSON 含 display_markdown（航班价格表），请原封不动展示给用户，
    让用户看到「真的去携程查了机票」。

    重要：每段的 dep_city 是【出发地】、arr_city 是【目的地】，两者不能相同；
    顺序不要颠倒（「上海到东京」= dep_city 上海、arr_city 东京）。

    Args:
        dep_city: 单段查询的出发城市名（如 "上海"）或三字码（如 "SHA"）。
        arr_city: 单段查询的到达城市名（如 "东京"）或三字码（如 "TYO"）。
        date: 单段查询的出发日期，格式 YYYY-MM-DD。
        segments: 多段并发查询列表，每个含 dep_city/arr_city/date；传了它则忽略上面三个单段参数。
    """
    # 归一化：把单段参数也收敛成 segments 列表
    if segments:
        seg_list = [dict(s) for s in segments]
    elif dep_city and arr_city and date:
        seg_list = [{"dep_city": dep_city, "arr_city": arr_city, "date": date}]
    else:
        return json.dumps(
            {
                "error": "missing_params",
                "_instruction": (
                    "缺少查询参数。请传 dep_city/arr_city/date 做单段查询，"
                    "或传 segments 列表做多段并发查询（来程+回程）。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # 参数校验：任一航段出发==目的地 → 报错引导纠正
    for i, seg in enumerate(seg_list):
        err = _validate_flight_segment(seg)
        if err:
            logger.warning("flight_search bad segment[%d]: %s", i, err)
            return json.dumps(
                {
                    "error": "invalid_segment",
                    "segment_index": i,
                    "_instruction": (
                        f"第 {i + 1} 个航段参数有误：{err} 请修正后重新调用。"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )

    # 并发查询所有航段（单段时内部走非并发路径）
    try:
        results = call_ctrip_flight_batch(seg_list)
    except Exception as e:  # noqa: BLE001
        logger.warning("flight_search batch failed: %s", e)
        results = [None] * len(seg_list)

    # 渲染：每段一个 markdown 块，拼成总展示
    blocks: list[str] = []
    seg_outputs: list[dict] = []
    seg_labels = ["去程", "回程"] if len(seg_list) == 2 else None

    for i, (seg, data) in enumerate(zip(seg_list, results)):
        dep = seg["dep_city"]
        arr = seg["arr_city"]
        d = seg["date"]
        label = seg_labels[i] if seg_labels else (f"航段 {i + 1}" if len(seg_list) > 1 else "")

        if data:
            flights = data.get("flights", []) or []
            md = render_ctrip_markdown(data, dep, arr)
            if label:
                md = f"### {label}\n\n" + md
            blocks.append(md)
            seg_outputs.append(
                {
                    "label": label,
                    "route": data.get("route", ""),
                    "date": data.get("date", d),
                    "count": len(flights),
                    "flights": flights,
                }
            )
        else:
            fail_md = (
                (f"### {label}\n\n" if label else "")
                + f"✈️ **携程机票查询**（{dep} → {arr}）\n\n"
                + f"> 这次没能查到 {d} 的航班（可能是网络/登录态/无直飞），建议稍后再试。"
            )
            blocks.append(fail_md)
            seg_outputs.append(
                {"label": label, "route": f"{dep}->{arr}", "date": d, "count": 0, "flights": []}
            )

    display_markdown = "\n\n---\n\n".join(blocks)
    result = {
        "segments": seg_outputs,
        "display_markdown": display_markdown,
        "_instruction": (
            "请把 display_markdown 字段的内容【原封不动】展示给用户"
            "（这是携程的真实机票价格表，多段已并发查询），然后再基于航班信息继续规划行程。"
        ),
    }
    logger.info(
        "flight_search returned %d segments (concurrent)", len(seg_outputs)
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ===========================================================================
# 4.4 feasibility-check — 路线可行性校验
# ===========================================================================
@tool("feasibility_check", parse_docstring=True)
def feasibility_check_tool(
    stops: list[dict],
    budget_max: int = 0,
    hard_constraints: list[str] | None = None,
) -> str:
    """校验路线在时间和用户约束（预算、暗线/硬约束）下是否可行。硬约束违反直接判不通过，软约束（排队风险）标记 warning。

    Args:
        stops: 路线站点列表，每个站点应包含 name、type、estimated_price、tips、crowd_warning 等字段。
        budget_max: 用户预算上限（元），0 表示不限。
        hard_constraints: 用户硬约束/暗线列表，例如 ["不吃香菜"]。
    """
    hard_constraints = hard_constraints or []
    issues: list[dict] = []
    warnings: list[dict] = []
    suggestions: list[str] = []

    total_price = sum(int(s.get("estimated_price", 0) or 0) for s in stops)

    # 硬约束 1：预算
    if budget_max and total_price > budget_max:
        issues.append(
            {
                "type": "budget",
                "detail": f"预计总花费 {total_price} 元超过预算上限 {budget_max} 元",
                "severity": "high",
            }
        )

    # 硬约束 2：暗线命中（如忌口）
    for s in stops:
        text = " ".join([s.get("name", ""), *(s.get("tips", []) or []), s.get("crowd_warning", "")])
        for c in hard_constraints:
            # 简单关键词命中：例如 "不吃香菜" -> 命中 "香菜"
            kw = c.replace("不吃", "").replace("不要", "").strip()
            if kw and kw in text:
                warnings.append(
                    {
                        "type": "hard_constraint",
                        "item": s.get("name", ""),
                        "detail": f"该地点可能涉及用户约束「{c}」，建议提醒用户确认",
                        "severity": "medium",
                    }
                )

    # 软约束：排队/人流风险（从笔记 crowd_warning 提取）
    for s in stops:
        cw = s.get("crowd_warning", "")
        if cw:
            warnings.append(
                {
                    "type": "crowd",
                    "item": s.get("name", ""),
                    "detail": cw,
                    "severity": "low",
                }
            )

    if any(w["type"] == "crowd" for w in warnings):
        suggestions.append("建议错峰出行，避开排队高峰")

    result = {
        "pass": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "suggestions": suggestions,
        "total_estimated_price": total_price,
    }
    logger.info("feasibility_check pass=%s issues=%d warnings=%d", result["pass"], len(issues), len(warnings))
    return json.dumps(result, ensure_ascii=False, indent=2)


# ===========================================================================
# 4.4b daily-plan — 逐天行程提交（带信源硬校验）
# ===========================================================================
@tool("daily_plan", parse_docstring=True)
def daily_plan_tool(
    day_index: int,
    day_title: str,
    stops: list[dict],
    total_days: int = 1,
    plan_id: str = "",
    date: str = "",
) -> str:
    """提交"某一天"的行程安排（一次只提交一天，逐天推进）。会硬校验每个地点都带真实信源。

    使用方式：复杂出行（如周末两天、小长假多天）要【一天一天】规划，不要一次性生成一整周。
    规划好第 1 天就调用本工具提交 day_index=1，工具校验通过并告诉你"还剩几天"，
    再去规划第 2 天……直到所有天提交完毕。

    硬性要求（工具会强制校验，不满足直接报错退回）：
    1) 每个 stop 必须带 sources 字段，sources 是一个数组，每个元素形如
       {"title": "来源标题", "url": "https://...", "from": "xiaohongshu_post_search"}，
       URL 必须是可点开的真实链接（小红书原帖 / 官网 / 媒体）。没有信源的地点不允许提交。
    2) 每个 stop 至少要有【一条逐点坐实的信源】——即来自 xiaohongshu_post_search /
       web_search / web_fetch 的真实链接（标在每条 source 的 from 字段里）。
       不允许某个地点的信源【全是】点点攻略（xiaohongshu_guide_search）——点点只能给方向/骨架，
       不能当成具体地点的唯一证据。换句话说：点点说"去武康路"后，你必须再用帖子搜索/web
       把"武康路这家店"真正查到，拿到那篇帖子或官网的链接，才算坐实。
    3) 这一天里【至少要有一个地点采用一篇小红书帖子】（xiaohongshu_post_search）作为信源——
       因为帖子带封面图，最生动直观。不能整天全用 web 链接而一篇小红书帖子都没采用。
       所以每天规划时务必去 xiaohongshu_post_search 搜该天某个地点的真实帖子并采用它。

    Args:
        day_index: 第几天，从 1 开始。
        day_title: 这一天的主题名，例如 "Day1 武康路漫步"。
        stops: 这一天的站点列表。每个 stop 至少含 name、time_range、estimated_price、
            tips，以及【必填】sources（信源数组，每条含 title、url，建议带 from 标明来源工具）。
        total_days: 本次出行总天数，默认 1。
        plan_id: 行程 id；第一天可留空（自动生成），后续天传入上一次返回的 plan_id。
        date: 这一天的日期，格式 YYYY-MM-DD（可选）。
    """
    # 硬校验 1：每个地点必须有真实信源 URL
    missing = _stops_missing_sources(stops)
    if missing:
        return json.dumps(
            {
                "error": "missing_sources",
                "missing_stops": missing,
                "_instruction": (
                    f"以下地点没有提供真实信源，无法提交：{('、'.join(missing))}。\n"
                    "每个地点都必须带 sources 数组（至少一条可点开的 URL，来自小红书帖子/官网/媒体）。\n"
                    "请先用 xiaohongshu_post_search 或 web_search/web_fetch 查到这些地点的真实链接，"
                    "把 sources 补全后再重新调用 daily_plan 提交这一天。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # 硬校验 2（逐点坐实）：每个地点至少要有一条非点点的真实信源，不能全靠点点攻略蒙混
    weak = _stops_missing_grounded_sources(stops)
    if weak:
        return json.dumps(
            {
                "error": "sources_not_grounded",
                "weak_stops": weak,
                "_instruction": (
                    f"以下地点【没有逐点坐实】，目前的信源全是点点攻略（骨架），无法提交：{('、'.join(weak))}。\n"
                    "点点攻略只能给方向，不能当成某个具体地点的唯一证据。\n"
                    "请针对这些地点，分别用 xiaohongshu_post_search（搜这家店/这个展的真实帖子）"
                    "或 web_search/web_fetch（查官网/媒体/票务页）拿到一条专门针对它的真实链接，\n"
                    "并在该 stop 的 sources 里加上这条信源（建议标 from='xiaohongshu_post_search' "
                    "或 'web_fetch'），然后重新调用 daily_plan。\n"
                    "记住：点点说去哪、你就得逐家把那个地方真正查实，才算坐实。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # 硬校验 3（每天至少一篇小红书帖子）：帖子带封面图，最生动，每天必须采用至少一篇
    if not _day_has_post_source(stops):
        return json.dumps(
            {
                "error": "no_xhs_post_source",
                "_instruction": (
                    f"第 {day_index} 天还没有采用任何一篇【小红书帖子】作为信源，无法提交。\n"
                    "要求：每天至少要去 xiaohongshu_post_search 搜该天某个地点的真实帖子并采用它"
                    "（因为帖子带封面图，最生动直观），不能整天全用 web 链接。\n"
                    "请用 xiaohongshu_post_search 搜这一天里某个地点（店/展/景点）的真实帖子，"
                    "把那篇帖子加进对应 stop 的 sources（标 from='xiaohongshu_post_search'，"
                    "url 用帖子原帖链接），然后重新调用 daily_plan 提交这一天。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    pid = plan_id or f"plan_{uuid.uuid4().hex[:8]}"
    plan = _DAILY_PLANS.setdefault(
        pid, {"plan_id": pid, "total_days": total_days, "days": {}}
    )
    plan["total_days"] = max(total_days, plan.get("total_days", 1))

    # 给每个 stop 附上归一化后的信源列表，方便前端/卡片直接用
    norm_stops = []
    for s in stops:
        s2 = dict(s)
        s2["source_urls"] = _extract_source_urls(s)
        norm_stops.append(s2)

    plan["days"][str(day_index)] = {
        "day_index": day_index,
        "day_title": day_title,
        "date": date,
        "stops": norm_stops,
    }

    submitted = sorted(int(k) for k in plan["days"].keys())
    remaining = [d for d in range(1, plan["total_days"] + 1) if d not in submitted]
    all_done = len(remaining) == 0

    md_path = f"/mnt/user-data/workspace/weekend_plan/day{day_index}.md"
    # A 方案：把"立刻写当天 md"做成最顶部、最显眼的强指令——离决策点最近，最难被忽略
    next_step = (
        f"🔴【下一步必做，不许跳过、不许做别的】立刻调用 write_file，"
        f'path="{md_path}"，把第 {day_index} 天写成一个独立 markdown 文件落盘。\n'
        f"   - 路径必须是上面这个绝对虚拟路径（在 /mnt/user-data/workspace/weekend_plan/ 下），相对路径会被拒绝。\n"
        f"   - md 里每个地点都要带【来源链接】（用刚校验通过的 sources 里的 URL）。\n"
        f"   - 在写完 day{day_index}.md 之前：不许规划下一天、不许给用户发整体总结、不许收口。\n"
        f"   - 这样做的原因：趁这天细节还在手上、上下文还干净时落盘，质量最高，最后只需读回拼接。"
    )
    if all_done:
        after = (
            "\n\n🎉 所有天都已提交且通过信源校验。等你把当天的 dayN.md 也写完后，"
            "进入收口：用 read_file 逐个读回 /mnt/user-data/workspace/weekend_plan/day1.md…dayN.md，"
            "拼接成完整方案（不要凭记忆重写），再走确认 / 生成路线卡。"
        )
    else:
        after = (
            f"\n\n写完 day{day_index}.md 后，再继续【一天一天】规划："
            f"还剩 {len(remaining)} 天（第 {('、'.join(map(str, remaining)))} 天）。"
            "把当前天的 todo 标 completed、下一天标 in_progress，"
            "和用户对一下下一天偏好，搜资料、逐点坐实拿信源，再调 daily_plan 提交下一天（带同一个 plan_id）。"
        )
    result = {
        "plan_id": pid,
        "day_index": day_index,
        "total_days": plan["total_days"],
        "submitted_days": submitted,
        "remaining_days": remaining,
        "all_days_done": all_done,
        "must_write_file": md_path,
        "_instruction": (
            f"✅ 第 {day_index} 天已提交并通过信源校验"
            f"（共 {len(norm_stops)} 个地点，均带信源且已逐点坐实）。\n\n"
            + next_step
            + after
        ),
    }
    logger.info(
        "daily_plan submitted day %d/%d for plan %s (%d stops, remaining=%s)",
        day_index, plan["total_days"], pid, len(norm_stops), remaining,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ===========================================================================
# 4.5 checkin — 打卡服务
# ===========================================================================
@tool("checkin", parse_docstring=True)
def checkin_tool(
    action: str,
    checkin_id: str = "",
    stops: list[dict] | None = None,
    current_stop_index: int = 0,
    photo_url: str = "",
    text: str = "",
) -> str:
    """管理打卡卡片的生命周期：创建打卡卡片、更新打卡状态、提交打卡反馈。

    Args:
        action: 操作类型，可选 "create_card"（创建卡片）、"update_status"（更新某站点为已打卡）、"submit_feedback"（提交反馈）。
        checkin_id: 打卡卡片 id；create_card 时可留空（自动生成）。
        stops: 仅 create_card 时需要，站点列表（含 name、type、time_range 等）。
        current_stop_index: 当前操作的站点索引（update_status / submit_feedback 用）。
        photo_url: 打卡上传的照片地址（OSS）。
        text: 打卡文字或反馈内容。
    """
    if action == "create_card":
        cid = checkin_id or f"checkin_{uuid.uuid4().hex[:8]}"
        card_stops = []
        for i, s in enumerate(stops or []):
            card_stops.append(
                {
                    "order": i + 1,
                    "name": s.get("name", ""),
                    "type": s.get("type", ""),
                    "time_range": s.get("time_range", ""),
                    "checkin_status": "pending",
                    "photo_url": "",
                    "text": "",
                }
            )
        card = {"checkin_id": cid, "stops": card_stops, "all_checked_in": False}
        _CHECKIN_CARDS[cid] = card
        logger.info("checkin created card %s with %d stops", cid, len(card_stops))
        return json.dumps(card, ensure_ascii=False, indent=2)

    card = _CHECKIN_CARDS.get(checkin_id)
    if card is None:
        return json.dumps({"error": f"checkin card not found: {checkin_id}"}, ensure_ascii=False)

    if action in ("update_status", "submit_feedback"):
        stops_list = card["stops"]
        if 0 <= current_stop_index < len(stops_list):
            stop = stops_list[current_stop_index]
            stop["checkin_status"] = "done"
            if photo_url:
                stop["photo_url"] = photo_url
            if text:
                stop["text"] = text
        card["all_checked_in"] = all(s["checkin_status"] == "done" for s in card["stops"])
        logger.info("checkin %s stop[%d] updated, all_checked_in=%s", checkin_id, current_stop_index, card["all_checked_in"])
        return json.dumps(card, ensure_ascii=False, indent=2)

    return json.dumps({"error": f"unknown action: {action}"}, ensure_ascii=False)


# ===========================================================================
# 4.6 route-card-gen — 路线卡海报生成
# ===========================================================================
@tool("route_card_gen", parse_docstring=True)
def route_card_gen_tool(
    route_name: str,
    stops: list[dict],
    total_budget: int = 0,
    date: str = "",
    style: str = "小清新",
    poster_text: str = "",
) -> str:
    """生成纪念路线卡海报。先由 Agent 写好海报文案，再调用图片生成服务合成海报（打卡照片+路线+文案拼版）。

    Args:
        route_name: 路线名称，例如 "衡复漫步"。
        stops: 站点列表，每个含 name、photo（打卡照）、user_comment、time。
        total_budget: 总花费（元）。
        date: 出行日期，例如 "2026-06-06"。
        style: 海报风格，可选 "小清新"/"胶片"/"极简"。
        poster_text: 由 Agent 生成的海报文案。
    """
    # 硬校验 1：生成路线卡前，每个站点都必须带真实信源 URL
    missing = _stops_missing_sources(stops)
    if missing:
        return json.dumps(
            {
                "error": "missing_sources",
                "missing_stops": missing,
                "_instruction": (
                    f"以下地点没有真实信源，不能生成路线卡：{('、'.join(missing))}。\n"
                    "请先把这些地点的 sources（小红书帖子/官网/媒体的真实 URL）补全后再生成。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # 硬校验 2（逐点坐实）：每个地点至少要有一条非点点的真实信源
    weak = _stops_missing_grounded_sources(stops)
    if weak:
        return json.dumps(
            {
                "error": "sources_not_grounded",
                "weak_stops": weak,
                "_instruction": (
                    f"以下地点的信源全是点点攻略（骨架），没有逐点坐实，不能生成路线卡：{('、'.join(weak))}。\n"
                    "请针对这些地点用 xiaohongshu_post_search 或 web_search/web_fetch 拿到专门的真实链接"
                    "（标 from='xiaohongshu_post_search' 或 'web_fetch'）后再生成。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # TODO(real-api): 替换为真实图片生成服务，合成真实海报图片
    poster_id = f"poster_{uuid.uuid4().hex[:8]}"
    poster_url = f"oss://weekend-posters/{poster_id}.png"

    # 同时产出一个可在前端直接渲染的 HTML 海报，便于 Demo 展示（无需真实图片服务）
    def _src_links(s: dict) -> str:
        urls = _extract_source_urls(s)
        if not urls:
            return ""
        links = " · ".join(f'<a href="{u}">来源{i + 1}</a>' for i, u in enumerate(urls))
        return f'<div class="src">{links}</div>'

    stop_blocks = "".join(
        f'<div class="stop"><span class="t">{s.get("time", "")}</span>'
        f'<b>{s.get("name", "")}</b>'
        f'<p>{s.get("user_comment", "")}</p>'
        f"{_src_links(s)}</div>"
        for s in stops
    )
    poster_html = (
        f'<div class="route-card route-card--{style}">'
        f"<h1>{route_name}</h1>"
        f'<div class="meta">{date} · 全程预算 {total_budget} 元</div>'
        f'<div class="caption">{poster_text}</div>'
        f'<div class="stops">{stop_blocks}</div>'
        f"</div>"
    )

    result = {
        "poster_url": poster_url,
        "content_type": "image/png",
        "poster_html": poster_html,
        "style": style,
    }
    logger.info("route_card_gen generated poster %s for route=%r", poster_id, route_name)
    return json.dumps(result, ensure_ascii=False, indent=2)
