"""RPA 桥接模块 — 调用 Node.js 脚本（xiaohongshu-ask.mjs）获取真实小红书数据。

通过子进程调用 WebDriver BiDi RPA 脚本，解析其 JSON 输出或 stdout 文本，
返回结构化数据供 WeekenD 工具层使用。RPA 失败时降级到 mock 数据，保证 Demo
不崩。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 配置（可通过环境变量覆盖）─────────────────────────────────────────────
_RPA_DIR = Path(
    os.environ.get("WEEKEND_RPA_DIR", "/Users/hejunlin/Downloads/rpa")
)
_ASK_SCRIPT = _RPA_DIR / "xiaohongshu/ask/xiaohongshu-ask.mjs"
_ASK_DATA_DIR = _RPA_DIR / "xiaohongshu/ask/data"
_ASK_JSON = _ASK_DATA_DIR / "ask-answer.json"

# 小红书帖子关键词搜索（xiaohongshu.mjs，返回带封面图的真实笔记列表）
_XHS_SEARCH_SCRIPT = _RPA_DIR / "xiaohongshu/xiaohongshu/xiaohongshu.mjs"
_XHS_SEARCH_DATA_DIR = _RPA_DIR / "xiaohongshu/xiaohongshu/data"
_XHS_SEARCH_JSON = _XHS_SEARCH_DATA_DIR / "xhs-search.json"

# 高德路径规划（基于高德 REST API，速度快）
_AMAP_SCRIPT = _RPA_DIR / "amap/route/amap-route.mjs"
_AMAP_DATA_DIR = _RPA_DIR / "amap/route/data"

# 携程机票查询（浏览器 RPA，较慢）
_CTRIP_SCRIPT = _RPA_DIR / "ctrip/flight/ctrip-flight.mjs"
_CTRIP_DATA_DIR = _RPA_DIR / "ctrip/flight/data"
_CTRIP_JSON = _CTRIP_DATA_DIR / "ctrip-flight.json"
# 携程登录态所在的主 profile（并发时复制它，让每个隔离 profile 都带登录态）
_CTRIP_MAIN_PROFILE = Path.home() / ".rpa-profiles" / "ctrip-flight"
# 并发时隔离 profile 的存放根目录
_CTRIP_PROFILE_ROOT = Path.home() / ".rpa-profiles"
# 并发上限：同时开几个携程浏览器（过多会吃内存/被风控，2 比较稳）
_CTRIP_MAX_CONCURRENCY = int(os.environ.get("WEEKEND_CTRIP_CONCURRENCY", "2"))

# 城市名 -> 携程三字码
_CITY_CODE = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "成都": "CTU",
    "深圳": "SZX", "杭州": "HGH", "重庆": "CKG", "西安": "XIY",
    "武汉": "WUH", "南京": "NKG", "天津": "TSN", "青岛": "TAO",
    "厦门": "XMN", "昆明": "KMG", "长沙": "CSX", "三亚": "SYX",
    "海口": "HAK", "大连": "DLC", "沈阳": "SHE", "郑州": "CGO",
    "哈尔滨": "HRB", "济南": "TNA", "福州": "FOC", "贵阳": "KWE",
    "南宁": "NNG", "兰州": "LHW", "乌鲁木齐": "URC", "拉萨": "LXA",
    "香港": "HKG", "澳门": "MFM", "台北": "TPE",
    "东京": "TYO", "大阪": "OSA", "首尔": "SEL", "曼谷": "BKK",
    "新加坡": "SIN", "吉隆坡": "KUL", "巴黎": "PAR", "伦敦": "LON",
    "纽约": "NYC", "洛杉矶": "LAX",
}

# 缓存：同一天内相同 query 不重复调 RPA
_cache: dict[str, dict] = {}

# 并发端口段分配：每个隔离任务分到一个独立的端口起始值，互不重叠。
_port_lock = threading.Lock()
_next_port_base = 9300  # 避开 9222 默认段，留给非隔离调用


def _alloc_port_base(step: int = 20) -> int:
    """线程安全地分配一个端口起始段，供并发隔离任务使用。"""
    global _next_port_base
    with _port_lock:
        base = _next_port_base
        _next_port_base += step
        # 防止无限增长，回绕到起始段
        if _next_port_base > 9900:
            _next_port_base = 9300
    return base


def _today_key() -> str:
    return time.strftime("%Y-%m-%d")


def _call_ask_rpa(question: str, timeout: int = 120) -> dict | None:
    """调用 xiaohongshu-ask.mjs，解析返回的 JSON 文件。

    脚本成功后会写入 ask-answer.json。我们等脚本退出后读取该文件。
    增加超时容忍度：RPA 需要启动浏览器+等待 AI 回复，通常需要 60-90s。
    """
    cache_key = f"{_today_key()}::{question}"
    if cache_key in _cache:
        logger.info("RPA cache hit: %s", cache_key)
        return _cache[cache_key]

    if not _ASK_SCRIPT.exists():
        logger.warning("RPA script not found: %s", _ASK_SCRIPT)
        return None

    # 记录旧文件 mtime，用于判断 RPA 是否写入了新结果
    old_mtime = _ASK_JSON.stat().st_mtime if _ASK_JSON.exists() else 0

    logger.info("Calling RPA: %s %r", _ASK_SCRIPT, question)
    try:
        result = subprocess.run(
            ["node", str(_ASK_SCRIPT), question],
            cwd=str(_RPA_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr_tail = result.stderr.strip().split("\n")[-5:]
            logger.warning(
                "RPA exited with code %d, stderr: %s",
                result.returncode,
                stderr_tail,
            )

        # 读取 JSON 文件（仅当比调用前更新时）
        if _ASK_JSON.exists():
            new_mtime = _ASK_JSON.stat().st_mtime
            if new_mtime > old_mtime:
                raw = _ASK_JSON.read_text(encoding="utf-8")
                data = json.loads(raw)
                _cache[cache_key] = data
                return data
            else:
                logger.info("RPA JSON file not updated, using stdout fallback")

        # 兜底：从 stdout 提取 JSON 块
        stdout = result.stdout
        json_match = re.search(r"\{[\s\S]*\}", stdout)
        if json_match:
            data = json.loads(json_match.group())
            _cache[cache_key] = data
            return data

        logger.warning("RPA produced no JSON output")
        return None

    except subprocess.TimeoutExpired:
        # 超时后检查 RPA 是否已写入文件（Node 进程可能仍在运行）
        if _ASK_JSON.exists():
            new_mtime = _ASK_JSON.stat().st_mtime
            if new_mtime > old_mtime:
                raw = _ASK_JSON.read_text(encoding="utf-8")
                data = json.loads(raw)
                _cache[cache_key] = data
                logger.info("RPA timed out but JSON file was updated, using it")
                return data
        logger.warning("RPA timed out after %ds, no new data", timeout)
        return None
    except json.JSONDecodeError as e:
        logger.warning("RPA JSON parse error: %s", e)
        return None
    except Exception as e:
        logger.warning("RPA call failed: %s", e)
        return None


def _parse_answer_to_notes(answer: str, summary: str = "") -> list[dict]:
    """从点点 AI 的纯文本回答中提取结构化笔记。

    当 refNotes 为空时，点点 AI 会把地点信息嵌入在 answer 文本中。
    我们通过正则提取其中的地点名称和描述。
    """
    notes: list[dict] = []
    seen: set[str] = set()

    # 策略1：匹配格式如 "**地点名**：描述" 或 "​​地点名​​：描述"
    # 也匹配 "地点名：描述" 段落
    lines = answer.split("\n")
    current_note = None

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 匹配标题行：**地点名** 或 ​​地点名​​ 或 ### 地点名
        title_match = re.match(
            r"^(?:\*\*|​​|###\s*)([^*​#]+?)(?:\*\*|​​)\s*[：:]?\s*(.*)$", line
        )
        if title_match:
            name = title_match.group(1).strip()
            desc = title_match.group(2).strip() if title_match.group(2) else ""
            if name and name not in seen and len(name) >= 2:
                seen.add(name)
                current_note = {"name": name, "content": desc, "extra": []}
                notes.append(current_note)
            continue

        # 匹配格式：数字. 地点名 — 描述
        list_match = re.match(r"^\d+[\.\、]\s*(.+?)\s*[—\-]\s*(.+)$", line)
        if list_match:
            name = list_match.group(1).strip()
            desc = list_match.group(2).strip()
            if name and name not in seen and len(name) >= 2:
                seen.add(name)
                current_note = {"name": name, "content": desc, "extra": []}
                notes.append(current_note)
            continue

        # 匹配格式：- 地点名：描述
        bullet_match = re.match(r"^[-•]\s*(.+?)\s*[：:]\s*(.+)$", line)
        if bullet_match:
            name = bullet_match.group(1).strip()
            desc = bullet_match.group(2).strip()
            if name and name not in seen and len(name) >= 2:
                seen.add(name)
                current_note = {"name": name, "content": desc, "extra": []}
                notes.append(current_note)
            continue

        # 追加到当前笔记的 extra 内容
        if current_note and len(line) > 5:
            current_note["extra"].append(line)

    # 合并 extra 到 content，并过滤非地点条目
    _non_poi_keywords = {"预约", "闭馆", "交通", "建议", "贴士", "小贴士", "注意", "Tips"}
    filtered: list[dict] = []
    for note in notes:
        name = note["name"]
        # 跳过明显的非地点条目
        if any(kw in name for kw in _non_poi_keywords):
            continue
        if note["extra"]:
            note["content"] = note["content"] + "\n" + "\n".join(note["extra"])
        del note["extra"]
        filtered.append(note)

    return filtered


def get_ask_raw(query: str, city: str = "上海") -> dict | None:
    """获取点点 AI 的原始回答数据（answer / summaryNote / refNotes）。

    返回原始 dict，供工具层既能"原封不动展示"answer，又能解析出结构化笔记。
    """
    question = f"{city} 周末 {query}"
    return _call_ask_rpa(question)


def render_ask_markdown(data: dict, query: str = "", city: str = "上海") -> str:
    """把点点 AI 的原始回答渲染成可直接展示给用户的 Markdown。

    核心理念：点点 AI 的 answer 本身写得很好，原封不动展示，只补一个来源说明
    和（若有）参考笔记的封面图，让用户看到"真的去小红书搜了"。
    """
    if not data:
        return ""

    answer = (data.get("answer") or "").strip()
    summary = (data.get("summaryNote") or "").strip()
    ref_notes = data.get("refNotes", []) or []

    parts: list[str] = []

    # 头部：来源说明
    header = "📕 **小红书「点点」帮你找到了这些**"
    if summary:
        header += f"（{summary}）"
    parts.append(header)
    parts.append("")

    # 主体：点点 AI 原文，原封不动
    if answer:
        parts.append(answer)

    # 参考笔记（若点点返回了图文卡片）：展示封面图
    if ref_notes:
        parts.append("")
        parts.append("---")
        parts.append(f"**📎 参考笔记（{len(ref_notes)} 篇）**")
        parts.append("")
        for i, ref in enumerate(ref_notes, 1):
            name = (ref.get("name") or "").strip() or f"笔记 {i}"
            cover = (ref.get("cover") or "").strip()
            if cover:
                parts.append(f"{i}. **{name}**")
                parts.append(f"   ![{name}]({cover})")
            else:
                parts.append(f"{i}. **{name}**")
        parts.append("")

    return "\n".join(parts).strip()


def search_notes(query: str, city: str = "上海") -> list[dict]:
    """调用点点 AI 搜索小红书笔记，返回结构化笔记列表。

    返回的笔记格式与 mock_data.MOCK_NOTES 兼容，保证 extract_poi 等
    下游工具无需修改即可工作。
    """
    question = f"{city} 周末 {query}"
    data = _call_ask_rpa(question)

    if data is None:
        return []

    notes: list[dict] = []
    answer = data.get("answer", "")
    summary = data.get("summaryNote", "")
    ref_notes = data.get("refNotes", []) or []

    # 从 summaryNote 提取笔记数量，如 "ai总结39篇笔记"
    note_count = 0
    m = re.search(r"(\d+)篇", summary or "")
    if m:
        note_count = int(m.group(1))

    if ref_notes:
        # 有结构化 refNotes，直接转换
        for i, ref in enumerate(ref_notes):
            note_id = f"xhs_ask_{i:03d}"
            notes.append({
                "id": note_id,
                "title": ref.get("name", ""),
                "content": ref.get("text", ""),
                "likes": 0,
                "collections": 0,
                "url": "",
                "images": [ref.get("cover", "")] if ref.get("cover") else [],
                "confidence": 0.85,
                "source": "xhs_ask",
            })
    elif answer:
        # refNotes 为空，从 answer 文本中解析地点
        parsed = _parse_answer_to_notes(answer, summary)
        for i, p in enumerate(parsed):
            note_id = f"xhs_ask_parsed_{i:03d}"
            notes.append({
                "id": note_id,
                "title": p["name"],
                "content": p["content"],
                "likes": 0,
                "collections": 0,
                "url": "",
                "images": [],
                "confidence": 0.75,
                "source": "xhs_ask_parsed",
            })

    # 追加一个特殊笔记：点点 AI 的完整回答（供 Agent 参考）
    if answer:
        notes.append({
            "id": "xhs_ask_summary",
            "title": f"点点AI总结 ({summary or '基于真实笔记'})",
            "content": answer,
            "likes": 0,
            "collections": 0,
            "url": "",
            "images": [],
            "confidence": 0.9,
            "source": "xhs_ask_summary",
        })

    logger.info(
        "RPA returned %d refNotes + %d parsed + AI summary (total %d notes, %d raw notes)",
        len(ref_notes), len(notes) - len(ref_notes) - (1 if answer else 0),
        len(notes), note_count,
    )
    return notes


def extract_pois_from_notes(notes: list[dict]) -> list[dict]:
    """从点点 AI 返回的笔记中提取 POI（兼容 extract_poi 输出格式）。

    点点 AI 的 refNotes 已经带有名称和描述，这里直接转换为 POI 格式。
    """
    pois: list[dict] = []
    seen_names: set[str] = set()

    for note in notes:
        source = note.get("source", "")
        if source == "xhs_ask_summary":
            # 跳过 AI 总结伪笔记，只提取真实地点
            continue

        name = note.get("title", "")
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        # 从 content 中提取推荐度
        recommend = ""
        m = re.search(r"(\d+)%人推荐", note.get("content", ""))
        if m:
            recommend = f"{m.group(1)}% 用户推荐"

        pois.append({
            "name": name,
            "city": "上海",
            "district": "",
            "type": "地点",
            "sub_type": "",
            "estimated_price": 0,
            "opening_hours": "",
            "tips": [recommend] if recommend else [],
            "crowd_warning": "",
            "note_comments": [note.get("content", "")[:120]],
            "source_note_id": note.get("id", ""),
            "confidence": note.get("confidence", 0.85),
        })

    logger.info("extracted %d POIs from %d notes", len(pois), len(notes))
    return pois


# ===========================================================================
# 小红书帖子关键词搜索桥接（xiaohongshu.mjs，返回带封面图的真实笔记）
# ===========================================================================
def _call_xhs_search_rpa(query: str, timeout: int = 120) -> dict | None:
    """调用 xiaohongshu.mjs 做关键词搜索，解析返回的 xhs-search.json。

    返回原始 dict：{fetchedAt, query, count, notes:[...], firstDetail}。
    """
    cache_key = f"xhs_search::{_today_key()}::{query}"
    if cache_key in _cache:
        logger.info("xhs_search cache hit: %s", cache_key)
        return _cache[cache_key]

    if not _XHS_SEARCH_SCRIPT.exists():
        logger.warning("xhs search script not found: %s", _XHS_SEARCH_SCRIPT)
        return None

    old_mtime = _XHS_SEARCH_JSON.stat().st_mtime if _XHS_SEARCH_JSON.exists() else 0

    logger.info("Calling xhs search RPA: %r", query)
    try:
        result = subprocess.run(
            ["node", str(_XHS_SEARCH_SCRIPT), query],
            cwd=str(_RPA_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.strip().split("\n")[-3:]
            logger.warning(
                "xhs search exited code %d: %s", result.returncode, stderr_tail
            )

        if _XHS_SEARCH_JSON.exists() and _XHS_SEARCH_JSON.stat().st_mtime > old_mtime:
            data = json.loads(_XHS_SEARCH_JSON.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            return data

        logger.warning("xhs search produced no new output")
        return None
    except subprocess.TimeoutExpired:
        if _XHS_SEARCH_JSON.exists() and _XHS_SEARCH_JSON.stat().st_mtime > old_mtime:
            data = json.loads(_XHS_SEARCH_JSON.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            logger.info("xhs search timed out but file updated, using it")
            return data
        logger.warning("xhs search timed out after %ds", timeout)
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("xhs search call failed: %s", e)
        return None


def get_xhs_search_raw(query: str, city: str = "上海") -> dict | None:
    """获取小红书帖子搜索的原始数据。"""
    keyword = f"{city} {query}".strip()
    return _call_xhs_search_rpa(keyword)


def render_xhs_search_markdown(data: dict, max_notes: int = 12) -> str:
    """把小红书帖子搜索结果渲染成带封面图的 Markdown 卡片列表。"""
    if not data:
        return ""

    query = data.get("query", "")
    notes = data.get("notes", []) or []

    parts: list[str] = []
    header = f"📕 **小红书帖子搜索**"
    if query:
        header += f"（关键词：{query}）"
    if notes:
        header += f" · 找到 {len(notes)} 篇"
    parts.append(header)
    parts.append("")

    if not notes:
        parts.append("> 这次没搜到帖子，建议换个关键词再试。")
        return "\n".join(parts).strip()

    # 按点赞数降序（点赞是字符串，转 int 排序）
    def _likes(n: dict) -> int:
        try:
            return int(str(n.get("likes", "0")).replace("+", "").replace("万", "0000"))
        except ValueError:
            return 0

    sorted_notes = sorted(notes, key=_likes, reverse=True)[:max_notes]

    for i, n in enumerate(sorted_notes, 1):
        title = (n.get("title") or "").strip() or "(无标题)"
        cover = (n.get("cover") or "").strip()
        likes = n.get("likes", "")
        author = (n.get("author") or "").split("\n")[0].strip()
        href = (n.get("href") or "").strip()
        url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}" if href else ""

        line = f"**{i}. {title}**"
        meta_bits = []
        if likes:
            meta_bits.append(f"👍 {likes}")
        if author:
            meta_bits.append(author)
        if meta_bits:
            line += f"  ·  {' · '.join(meta_bits)}"
        parts.append(line)
        if cover:
            parts.append(f"![{title}]({cover})")
        if url:
            parts.append(f"[查看原帖]({url})")
        parts.append("")

    return "\n".join(parts).strip()


def search_posts(query: str, city: str = "上海") -> list[dict]:
    """调用小红书帖子搜索，返回结构化笔记列表（与 search_notes 格式兼容）。"""
    data = _call_xhs_search_rpa(f"{city} {query}".strip())
    if not data:
        return []

    notes: list[dict] = []
    for i, n in enumerate(data.get("notes", []) or []):
        href = (n.get("href") or "").strip()
        url = href if href.startswith("http") else f"https://www.xiaohongshu.com{href}" if href else ""
        notes.append({
            "id": f"xhs_post_{i:03d}",
            "title": (n.get("title") or "").strip(),
            "content": "",
            "likes": _safe_int(n.get("likes")),
            "collections": 0,
            "url": url,
            "images": [n.get("cover", "")] if n.get("cover") else [],
            "author": (n.get("author") or "").split("\n")[0].strip(),
            "confidence": 0.8,
            "source": "xhs_post",
        })
    logger.info("xhs search returned %d posts", len(notes))
    return notes


def _safe_int(v: Any) -> int:
    try:
        return int(str(v).replace("+", "").replace("万", "0000"))
    except (ValueError, TypeError):
        return 0


# ===========================================================================
# 高德路径规划桥接（amap-route.mjs，基于高德 REST API）
# ===========================================================================
def _amap_safe(s: str) -> str:
    """复刻 amap-route.mjs 的文件名安全化：替换特殊字符为 _，截断 40 字符。

    对应 JS: s.replace(/[/:\\?%*|"<> ]/g, '_').slice(0, 40)
    """
    out = re.sub(r'[/:\\?%*|"<> ]', "_", s)
    return out[:40]


def call_amap_route(
    origin: str,
    dest: str,
    mode: str = "步行",
    city: str = "上海",
    strategy: int = 0,
    timeout: int = 60,
) -> dict | None:
    """调用 amap-route.mjs 规划单段路线，返回解析后的 JSON。

    mode 取值：驾车 / 公交 / 步行。
    输出文件名由 amap-route.mjs 决定：route-{safe(origin)}--{safe(dest)}-{mode}.json
    """
    cache_key = f"amap::{origin}::{dest}::{mode}::{city}::{strategy}"
    if cache_key in _cache:
        logger.info("amap cache hit: %s", cache_key)
        return _cache[cache_key]

    if not _AMAP_SCRIPT.exists():
        logger.warning("amap script not found: %s", _AMAP_SCRIPT)
        return None

    out_file = _AMAP_DATA_DIR / f"route-{_amap_safe(origin)}--{_amap_safe(dest)}-{mode}.json"
    old_mtime = out_file.stat().st_mtime if out_file.exists() else 0

    args = ["node", str(_AMAP_SCRIPT), origin, dest, mode, str(strategy)]
    if city:
        args.append(city)

    logger.info("Calling amap RPA: %s -> %s (%s)", origin, dest, mode)
    try:
        result = subprocess.run(
            args,
            cwd=str(_RPA_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.strip().split("\n")[-3:]
            logger.warning("amap exited code %d: %s", result.returncode, stderr_tail)

        if out_file.exists() and out_file.stat().st_mtime > old_mtime:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            return data

        logger.warning("amap produced no new output file: %s", out_file.name)
        return None
    except subprocess.TimeoutExpired:
        if out_file.exists() and out_file.stat().st_mtime > old_mtime:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            return data
        logger.warning("amap timed out after %ds", timeout)
        return None
    except Exception as e:
        logger.warning("amap call failed: %s", e)
        return None


def render_amap_markdown(data: dict) -> str:
    """把高德路线 JSON 渲染成可直接展示给用户的 Markdown。"""
    if not data:
        return ""

    q = data.get("query", {})
    resolved = data.get("resolved", {})
    rtype = data.get("type", "")
    route = data.get("route", {})

    origin = resolved.get("origin") or q.get("origin", "")
    dest = resolved.get("dest") or q.get("dest", "")
    mode = q.get("mode", "")

    parts: list[str] = []
    parts.append(f"🗺️ **高德路线规划**（{mode}）")
    parts.append("")
    parts.append(f"- 起点：{origin}")
    parts.append(f"- 终点：{dest}")
    parts.append("")

    if rtype in ("driving", "walking"):
        dist_km = round(int(route.get("distance", 0)) / 1000, 1)
        dur_min = round(int(route.get("duration", 0)) / 60)
        summary = f"**全程 {dist_km} km · 约 {dur_min} 分钟**"
        if rtype == "driving":
            taxi = data.get("taxi_cost") or route.get("taxi_cost")
            tolls = route.get("tolls", "0")
            if taxi:
                summary += f" · 打车约 ¥{taxi}"
            if tolls and str(tolls) != "0":
                summary += f" · 过路费 ¥{tolls}"
        parts.append(summary)
        parts.append("")
        steps = route.get("steps", []) or []
        if steps:
            parts.append("**导航步骤：**")
            for i, s in enumerate(steps, 1):
                instr = s.get("instruction", "")
                d = s.get("distance", "")
                parts.append(f"{i}. {instr}（{d}m）")
    elif rtype == "transit":
        transits = route.get("transits", []) or []
        parts.append(f"**找到 {len(transits)} 个公交方案：**")
        parts.append("")
        for ti, t in enumerate(transits[:3], 1):
            dur_min = round(int(t.get("duration", 0)) / 60)
            walk = t.get("walking_distance", "0")
            cost = t.get("cost", "0")
            parts.append(f"**方案 {ti}** · {dur_min} 分钟 · 步行 {walk}m · ¥{cost}")
            for seg in t.get("segments", []) or []:
                bus = seg.get("bus", {}) or {}
                buslines = bus.get("buslines", []) or []
                if buslines:
                    bl = buslines[0]
                    name = bl.get("name", "")
                    dep = (bl.get("departure_stop", {}) or {}).get("name", "")
                    arr = (bl.get("arrival_stop", {}) or {}).get("name", "")
                    via = bl.get("via_num", 0)
                    parts.append(f"  - 🚇 {name}：{dep} → {arr}（{via} 站）")
            parts.append("")

    return "\n".join(parts).strip()


# ===========================================================================
# 携程机票查询桥接（ctrip-flight.mjs，浏览器 RPA）
# ===========================================================================
def city_to_code(city: str) -> str:
    """城市名转携程三字码。已是三字码则原样返回。"""
    city = (city or "").strip()
    if len(city) == 3 and city.isascii() and city.isupper():
        return city
    # 去掉「市」后缀再查
    key = city.rstrip("市")
    return _CITY_CODE.get(key, _CITY_CODE.get(city, city.upper()[:3]))


def _provision_isolated_profile() -> Path:
    """为一次并发查询创建独立的 Firefox profile 目录，并复制主 profile 的登录态。

    携程登录 cookie 存在主 profile（_CTRIP_MAIN_PROFILE）里。并发时若用空 profile
    会丢登录态，所以从主 profile 复制一份。复制失败则返回空 profile（降级）。
    """
    iso_dir = _CTRIP_PROFILE_ROOT / f"ctrip-flight-iso-{uuid.uuid4().hex[:8]}"
    try:
        if _CTRIP_MAIN_PROFILE.exists():
            shutil.copytree(_CTRIP_MAIN_PROFILE, iso_dir, dirs_exist_ok=True)
            # 删除可能存在的 Firefox 锁文件，避免「profile in use」
            for lock_name in ("lock", ".parentlock", "parent.lock"):
                lock = iso_dir / lock_name
                try:
                    if lock.exists() or lock.is_symlink():
                        lock.unlink()
                except OSError:
                    pass
        else:
            iso_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("failed to provision isolated profile: %s", e)
        iso_dir.mkdir(parents=True, exist_ok=True)
    return iso_dir


def call_ctrip_flight(
    dep_city: str,
    arr_city: str,
    date: str,
    timeout: int = 150,
    *,
    isolated: bool = False,
) -> dict | None:
    """调用 ctrip-flight.mjs 查询机票，返回解析后的 JSON。

    dep_city / arr_city 可传中文城市名或三字码，date 格式 YYYY-MM-DD。

    isolated=False（默认）：使用脚本默认的 profile/输出文件（单次查询，最简单）。
    isolated=True：分配独立的 profile 目录、浏览器实例名、输出文件，
        供多个进程并发查询时互不干扰（来程+回程同时查）。
    """
    dcode = city_to_code(dep_city)
    acode = city_to_code(arr_city)
    cache_key = f"ctrip::{dcode}::{acode}::{date}"
    if cache_key in _cache:
        logger.info("ctrip cache hit: %s", cache_key)
        return _cache[cache_key]

    if not _CTRIP_SCRIPT.exists():
        logger.warning("ctrip script not found: %s", _CTRIP_SCRIPT)
        return None

    # 隔离模式：为本次调用准备独立的 profile / 浏览器名 / 输出文件
    env = os.environ.copy()
    iso_profile: Path | None = None
    if isolated:
        iso_profile = _provision_isolated_profile()
        token = uuid.uuid4().hex[:8]
        out_file = _CTRIP_DATA_DIR / f"ctrip-flight-{token}.json"
        env["CTRIP_PROFILE_DIR"] = str(iso_profile)
        env["CTRIP_BROWSER_NAME"] = f"ctrip_f_{token}"
        env["CTRIP_OUT_FILE"] = str(out_file)
        # 关键：跳过 RPA 框架的"杀同二进制僵尸进程"逻辑。
        # 否则后启动的浏览器会把先启动的杀掉，导致并发只剩最后一个窗口可用。
        env["WEBRPA_NO_KILL_ZOMBIE"] = "1"
        # 给每个并发进程分配不同的端口起始段，降低抢同一端口的竞态。
        # port_base 由全局计数器递增分配（每个任务间隔 20 个端口足够）。
        env["WEBRPA_PORT_BASE"] = str(_alloc_port_base())
    else:
        out_file = _CTRIP_JSON

    old_mtime = out_file.stat().st_mtime if out_file.exists() else 0

    logger.info(
        "Calling ctrip RPA: %s -> %s %s (isolated=%s)", dcode, acode, date, isolated
    )
    try:
        result = subprocess.run(
            ["node", str(_CTRIP_SCRIPT), dcode, acode, date],
            cwd=str(_RPA_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if result.returncode != 0:
            stderr_tail = result.stderr.strip().split("\n")[-3:]
            logger.warning("ctrip exited code %d: %s", result.returncode, stderr_tail)

        if out_file.exists() and out_file.stat().st_mtime > old_mtime:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            return data

        logger.warning("ctrip produced no new output")
        return None
    except subprocess.TimeoutExpired:
        if out_file.exists() and out_file.stat().st_mtime > old_mtime:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            _cache[cache_key] = data
            logger.info("ctrip timed out but file updated, using it")
            return data
        logger.warning("ctrip timed out after %ds", timeout)
        return None
    except Exception as e:
        logger.warning("ctrip call failed: %s", e)
        return None
    finally:
        # 清理隔离 profile 和临时输出文件
        if isolated:
            if iso_profile is not None:
                shutil.rmtree(iso_profile, ignore_errors=True)
            try:
                if out_file != _CTRIP_JSON and out_file.exists():
                    # 保留数据已读入内存，删除临时文件
                    out_file.unlink()
            except OSError:
                pass


def call_ctrip_flight_batch(
    queries: list[dict],
    timeout: int = 180,
) -> list[dict | None]:
    """并发查询多个机票航段（如来程+回程，或多城对比），返回与输入等长的结果列表。

    每个 query 是 {"dep_city", "arr_city", "date"}。并发数受 _CTRIP_MAX_CONCURRENCY 限制，
    每个任务在独立 profile + 浏览器 + 输出文件下运行，互不干扰。

    返回列表与 queries 顺序一一对应；某个航段失败则对应位置为 None。
    """
    if not queries:
        return []

    if len(queries) == 1:
        q = queries[0]
        return [
            call_ctrip_flight(
                q["dep_city"], q["arr_city"], q["date"], timeout=timeout
            )
        ]

    results: list[dict | None] = [None] * len(queries)

    def _run(idx: int, q: dict) -> None:
        results[idx] = call_ctrip_flight(
            q["dep_city"],
            q["arr_city"],
            q["date"],
            timeout=timeout,
            isolated=True,
        )

    max_workers = min(_CTRIP_MAX_CONCURRENCY, len(queries))
    logger.info(
        "ctrip batch: %d queries, concurrency=%d", len(queries), max_workers
    )
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run, i, q) for i, q in enumerate(queries)]
        for fut in futures:
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                logger.warning("ctrip batch task failed: %s", e)

    return results


def render_ctrip_markdown(data: dict, dep_city: str = "", arr_city: str = "") -> str:
    """把携程机票 JSON 渲染成可直接展示给用户的 Markdown 表格。"""
    if not data:
        return ""

    route = data.get("route", "")
    date = data.get("date", "")
    flights = data.get("flights", []) or []

    parts: list[str] = []
    title = f"✈️ **携程机票查询**"
    if dep_city and arr_city:
        title += f"（{dep_city} → {arr_city}）"
    elif route:
        title += f"（{route}）"
    parts.append(title)
    if date:
        parts.append(f"出行日期：{date} · 共 {len(flights)} 个航班")
    parts.append("")

    if not flights:
        parts.append("> 暂未查询到航班，可能是日期太远或无直飞，建议换个日期试试。")
        return "\n".join(parts).strip()

    # 按价格升序展示
    def _price(f: dict) -> int:
        try:
            return int(str(f.get("price", "0")).replace(",", ""))
        except ValueError:
            return 999999

    sorted_flights = sorted(flights, key=_price)

    parts.append("| 航班 | 起飞 | 到达 | 价格 |")
    parts.append("| --- | --- | --- | --- |")
    for f in sorted_flights:
        parts.append(
            f"| {f.get('flightNo', '')} | {f.get('depTime', '')} | "
            f"{f.get('arrTime', '')} | ¥{f.get('price', '')} |"
        )

    cheapest = sorted_flights[0]
    parts.append("")
    parts.append(
        f"💡 最便宜：**{cheapest.get('flightNo', '')}** "
        f"{cheapest.get('depTime', '')}-{cheapest.get('arrTime', '')} "
        f"¥{cheapest.get('price', '')}"
    )

    return "\n".join(parts).strip()