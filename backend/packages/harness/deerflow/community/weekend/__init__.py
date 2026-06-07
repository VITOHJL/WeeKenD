"""WeekenD — 周末出行助手的 Skill 工具集。

WeekenD 技术方案 v3.0 中的 "Skill" 在 deer-flow 框架里实现为 Tools：
Agent 只做决策与解读，所有外部交互（搜索小红书、调高德、生成海报、打卡）
都通过这些工具完成，对用户透明。

工具清单：
- xiaohongshu_guide_search : 小红书点点攻略搜索（点点 AI 攻略总结）
- xiaohongshu_post_search  : 小红书帖子搜索（真实笔记 + 封面图）
- extract_poi             : 从笔记中提取结构化 POI
- amap_route              : 路线规划/验证（真实高德 API，距离/耗时/导航）
- flight_search           : 机票查询（真实携程，跨城出行，支持来回程并发）
- feasibility_check       : 路线可行性校验
- daily_plan              : 逐天行程提交（带信源硬校验，一天一天来）
- checkin                 : 打卡卡片生命周期管理
- route_card_gen          : 路线卡海报生成
"""

from deerflow.community.weekend.tools import (
    amap_route_tool,
    checkin_tool,
    daily_plan_tool,
    extract_poi_tool,
    feasibility_check_tool,
    flight_search_tool,
    route_card_gen_tool,
    xiaohongshu_guide_search_tool,
    xiaohongshu_post_search_tool,
)

__all__ = [
    "xiaohongshu_guide_search_tool",
    "xiaohongshu_post_search_tool",
    "extract_poi_tool",
    "amap_route_tool",
    "flight_search_tool",
    "feasibility_check_tool",
    "daily_plan_tool",
    "checkin_tool",
    "route_card_gen_tool",
]
