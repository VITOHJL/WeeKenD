#!/usr/bin/env python
"""WeekenD 端到端验证脚本。

验证 WeekenD（基于 deer-flow 实现的周末出行助手）的完整 SOP 流程是否跑通：

    WAIT → SEARCH → EXTRACT → PLAN → CHECK → CONFIRM → PUBLISH → CHECKIN → FEEDBACK → CARD

本脚本分两部分：

1. 【工具链验证 · 默认】无需任何 API key，直接串联 WeekenD 的 6 个 Skill 工具，
   模拟一次完整的「上海法租界周末出行」，逐状态打印数据流。用于证明 Skills 层
   端到端可用。

2. 【真实 Agent 验证 · 可选】加 --with-agent 时，用 create_deerflow_agent 挂载
   WeekenD 工具与 weekend-planner 提示，跑一轮真实 LLM 对话（需要在 config.yaml /
   环境变量里配置好模型）。

运行：
    cd deer-flow/backend
    uv run python scripts/weekend_e2e_demo.py
    uv run python scripts/weekend_e2e_demo.py --with-agent
"""

from __future__ import annotations

import argparse
import json
import sys


def _h(title: str) -> None:
    print("\n" + "=" * 68)
    print(f"  {title}")
    print("=" * 68)


def _call(tool, **kwargs):
    """统一调用 @tool 装饰的工具并解析 JSON 返回。"""
    raw = tool.invoke(kwargs)
    return json.loads(raw)


def run_tool_chain_demo() -> bool:
    """串联 6 个 WeekenD 工具，跑通完整 SOP 数据流。"""
    from deerflow.community.weekend.tools import (
        amap_route_tool,
        checkin_tool,
        extract_poi_tool,
        feasibility_check_tool,
        route_card_gen_tool,
        xiaohongshu_search_tool,
    )

    # 模拟用户画像（对应 user.md：预算、忌口、偏好区域）
    user_budget_max = 250
    user_hard_constraints = ["不吃香菜"]

    _h("STATE: WAIT — 用户表达意图")
    user_intent = "这周六想在上海法租界附近转转，预算250，想看展、喝咖啡、晚上吃顿好的"
    print(f"用户: {user_intent}")

    # ---------------- SEARCH ----------------
    _h("STATE: SEARCH — 调用 xiaohongshu_search")
    search = _call(
        xiaohongshu_search_tool,
        query="上海 周末 法租界 展览 咖啡 法餐",
        city="上海",
        budget_max=user_budget_max,
        max_results=20,
    )
    notes = search["notes"]
    print(f"搜到 {len(notes)} 篇种草笔记：")
    for n in notes:
        print(f"  - [{n['id']}] {n['title']}  ❤️{n['likes']} ⭐{n['collections']}")
    assert notes, "SEARCH 失败：没有搜到笔记"

    # ---------------- EXTRACT ----------------
    _h("STATE: EXTRACT — 调用 extract_poi")
    note_ids = [n["id"] for n in notes]
    extract = _call(extract_poi_tool, note_ids=note_ids)
    pois = extract["pois"]
    print(f"提取出 {len(pois)} 个结构化地点：")
    for p in pois:
        print(f"  - {p['name']} | {p['type']} | 人均{p['estimated_price']}元 | conf={p['confidence']}")
    assert pois, "EXTRACT 失败：没有提取到 POI"

    # Agent 决策：按 展览→咖啡→晚餐 选 3 个地点（排除纯书店）
    chosen = []
    for want in ("展览", "咖啡", "晚餐"):
        for p in pois:
            if p["type"] == want:
                chosen.append(p)
                break
    print("\nAgent 选定路线地点：" + " → ".join(p["name"] for p in chosen))
    assert len(chosen) >= 2, "可用地点不足以规划路线"

    # ---------------- PLAN ----------------
    _h("STATE: PLAN — 调用 amap_route")
    plan = _call(
        amap_route_tool,
        origin=chosen[0]["name"],
        waypoints=[p["name"] for p in chosen[1:]],
        city="上海",
        mode="步行",
    )
    route = plan["routes"][0]
    print(f"全程 {route['total_distance_km']}km / {route['total_time_min']}min（含缓冲）")
    for seg in route["segments"]:
        print(f"  - {seg['from']} → {seg['to']}: {seg['distance_km']}km, 步行{seg['walk_min']}min")

    # ---------------- CHECK ----------------
    _h("STATE: CHECK — 调用 feasibility_check")
    check = _call(
        feasibility_check_tool,
        stops=chosen,
        budget_max=user_budget_max,
        hard_constraints=user_hard_constraints,
    )
    print(f"可行性: pass={check['pass']} | 预计总花费={check['total_estimated_price']}元")
    for w in check["warnings"]:
        print(f"  ⚠️ [{w['type']}/{w['severity']}] {w.get('item','')}: {w['detail']}")
    for s in check["suggestions"]:
        print(f"  💡 {s}")
    assert check["pass"], "CHECK 失败：路线不可行（演示数据应当通过）"

    # ---------------- CONFIRM ----------------
    _h("STATE: CONFIRM — Agent 向用户呈现并等待确认（模拟用户同意）")
    print("Agent: 给你排了条衡复漫步：下午看光影摄影展(68)，旁边武康庭喝咖啡(35)，"
          "晚上永平里法餐(120)。全程步行不到3公里，人均不到250。画廊周末上午会排队，"
          "建议下午去。还有家法餐菜里可能放香菜，你忌口我帮你备注了。怎么样？")
    print("用户: 可以，就这个！")

    # ---------------- PUBLISH ----------------
    _h("STATE: PUBLISH — 生成路线方案 JSON + 创建打卡卡片")
    time_ranges = ["14:00-15:30", "15:45-17:00", "17:30-19:30"]
    route_stops = []
    for i, p in enumerate(chosen):
        route_stops.append(
            {
                "order": i + 1,
                "name": p["name"],
                "type": p["type"],
                "time_range": time_ranges[i] if i < len(time_ranges) else "",
                "estimated_price": p["estimated_price"],
                "tips": p["tips"],
                "checkin_status": "pending",
            }
        )
    route_plan = {
        "route_id": "route_demo_001",
        "route_name": "衡复漫步",
        "date": "2026-06-06",
        "weather": "晴天 22-28度",
        "stops": route_stops,
        "summary": {
            "total_budget": check["total_estimated_price"],
            "total_distance_km": route["total_distance_km"],
            "total_walk_min": route["total_time_min"],
            "user_note": "路线节奏可控，全程法租界，每站步行不超过20分钟。",
        },
    }
    print("路线方案 JSON:")
    print(json.dumps(route_plan, ensure_ascii=False, indent=2))

    card = _call(checkin_tool, action="create_card", stops=route_stops)
    checkin_id = card["checkin_id"]
    print(f"\n已生成打卡卡片: {checkin_id}（{len(card['stops'])} 个打卡点）")

    # ---------------- CHECKIN ----------------
    _h("STATE: CHECKIN — 逐个地点打卡")
    photos = ["oss://demo/p1.jpg", "oss://demo/p2.jpg", "oss://demo/p3.jpg"]
    comments = ["光影装置很绝", "抹茶拿铁绝了", "露台日落太美"]
    final_card = card
    for i in range(len(route_stops)):
        final_card = _call(
            checkin_tool,
            action="update_status",
            checkin_id=checkin_id,
            current_stop_index=i,
            photo_url=photos[i] if i < len(photos) else "",
            text=comments[i] if i < len(comments) else "",
        )
        done = sum(1 for s in final_card["stops"] if s["checkin_status"] == "done")
        print(f"  ✅ 打卡 {route_stops[i]['name']}（{done}/{len(route_stops)}）")
    assert final_card["all_checked_in"], "CHECKIN 失败：未能全部打卡"

    # ---------------- FEEDBACK ----------------
    _h("STATE: FEEDBACK — 收集反馈（模拟全部好评）")
    for s in final_card["stops"]:
        print(f"  {s['name']}: 😍 好评")
    print("（好评信号将由框架记忆系统沉淀进 user.md）")

    # ---------------- CARD ----------------
    _h("STATE: CARD — 生成路线卡海报")
    poster_text = "六月的衡复，从一束光开始。看展、喝咖啡、追日落——一个人的周末也可以很满。"
    poster_stops = [
        {
            "name": s["name"],
            "photo": photos[i] if i < len(photos) else "",
            "user_comment": comments[i] if i < len(comments) else "",
            "time": s["time_range"],
        }
        for i, s in enumerate(final_card["stops"])
    ]
    poster = _call(
        route_card_gen_tool,
        route_name="衡复漫步",
        stops=poster_stops,
        total_budget=check["total_estimated_price"],
        date="2026-06-06",
        style="小清新",
        poster_text=poster_text,
    )
    print(f"海报已生成: {poster['poster_url']}（{poster['content_type']}, 风格={poster['style']}）")
    print("海报 HTML 预览片段:")
    print("  " + poster["poster_html"][:160] + " ...")

    _h("✅ SOP 全流程跑通：WAIT→SEARCH→EXTRACT→PLAN→CHECK→CONFIRM→PUBLISH→CHECKIN→FEEDBACK→CARD")
    return True


def run_real_agent_demo() -> bool:
    """用真实 LLM + create_deerflow_agent 跑一轮 WeekenD 对话（需配置模型）。"""
    _h("真实 Agent 验证（需要已配置模型）")
    try:
        from langchain_core.messages import HumanMessage

        from deerflow.agents.factory import create_deerflow_agent
        from deerflow.community.weekend.tools import (
            amap_route_tool,
            checkin_tool,
            extract_poi_tool,
            feasibility_check_tool,
            route_card_gen_tool,
            xiaohongshu_search_tool,
        )
        from deerflow.config import get_app_config
        from deerflow.models import create_chat_model
    except Exception as e:  # noqa: BLE001
        print(f"导入失败，跳过真实 Agent 验证: {e}")
        return False

    app_config = get_app_config()
    if not app_config.models:
        print("config.yaml 中未配置任何模型，跳过真实 Agent 验证。")
        return False

    # 读取 weekend-planner skill 内容作为系统提示
    try:
        from pathlib import Path

        skill_path = Path(__file__).resolve().parents[2] / "skills" / "public" / "weekend-planner" / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        skill_text = "你是 WeekenD，一个周末出行助手。"

    model = create_chat_model(attach_tracing=False)
    weekend_tools = [
        xiaohongshu_search_tool,
        extract_poi_tool,
        amap_route_tool,
        feasibility_check_tool,
        checkin_tool,
        route_card_gen_tool,
    ]
    agent = create_deerflow_agent(
        model=model,
        tools=weekend_tools,
        system_prompt=skill_text,
        name="weekend",
    )

    print("用户: 这周六想在上海法租界转转，预算250，想看展喝咖啡，晚上吃顿好的，帮我安排下")
    result = agent.invoke(
        {"messages": [HumanMessage(content="这周六想在上海法租界转转，预算250，想看展喝咖啡，晚上吃顿好的，帮我安排下")]},
        config={"configurable": {"thread_id": "weekend-demo-thread"}},
    )
    final = result["messages"][-1]
    print("\nWeekenD:")
    print(getattr(final, "content", final))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="WeekenD 端到端验证")
    parser.add_argument("--with-agent", action="store_true", help="额外用真实 LLM 跑一轮 Agent 对话（需配置模型）")
    args = parser.parse_args()

    ok = run_tool_chain_demo()
    if args.with_agent:
        run_real_agent_demo()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
