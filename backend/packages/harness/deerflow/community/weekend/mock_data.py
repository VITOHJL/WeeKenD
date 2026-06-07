"""WeekenD 内置 mock 数据集。

黑客松 MVP 阶段，第三方小红书接口 / 高德 API / 图片生成服务尚未真实接入，
这里提供一套以「上海 · 法租界周末出行」为主题的高质量种草数据，保证
端到端流程（对话→搜索→规划→打卡→海报）可以稳定跑通。

真实接入时，只需在 tools.py 中将对应函数替换为真实 API 调用即可，
数据结构与 PRD 中定义的 JSON schema 完全一致。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 4.1 xiaohongshu-search 的 mock 返回：种草笔记
# ---------------------------------------------------------------------------
MOCK_NOTES: list[dict] = [
    {
        "id": "note_001",
        "title": "安福路新展｜光影装置绝了📷",
        "content": (
            "# 安福路光影摄影展\n\n"
            "周末和闺蜜去看了安福路新开的光影摄影展，真的太出片了！\n"
            "- 地址：徐汇区安福路 300 号\n"
            "- 票价：68 元，现场扫码买票即可\n"
            "- 时间：10:00-21:00（周二至周日）\n"
            "- Tips：下午人少，二楼的光影装置最适合拍照\n"
            "- 周末上午会排队，大概 30 分钟\n\n"
            "看完展旁边就是武康庭，可以去喝杯咖啡☕️"
        ),
        "likes": 2300,
        "collections": 800,
        "url": "https://www.xiaohongshu.com/explore/note_001",
        "images": ["https://img.example/xhs/note001_1.jpg", "https://img.example/xhs/note001_2.jpg"],
    },
    {
        "id": "note_002",
        "title": "武康庭隐藏咖啡｜抹茶拿铁yyds🍵",
        "content": (
            "# 武康庭的宝藏咖啡\n\n"
            "藏在武康庭里的一家小咖啡馆，环境超安静。\n"
            "- 地址：徐汇区武康路 376 号武康庭内\n"
            "- 人均：35 元\n"
            "- 推荐：抹茶拿铁、燕麦冰美式\n"
            "- 有户外座位，天气好坐外面很惬意\n"
            "- 营业时间：09:00-20:00\n\n"
            "离安福路画廊步行就 10 分钟，看完展过来刚刚好。"
        ),
        "likes": 1500,
        "collections": 620,
        "url": "https://www.xiaohongshu.com/explore/note_002",
        "images": ["https://img.example/xhs/note002_1.jpg"],
    },
    {
        "id": "note_003",
        "title": "永平里法餐｜露台位看日落🌇人均120",
        "content": (
            "# 永平里宝藏法餐\n\n"
            "在永平里发现的一家法餐，性价比很高！\n"
            "- 地址：徐汇区永平里 12 号\n"
            "- 人均：120 元\n"
            "- 一定要提前预约，周末很满\n"
            "- 露台位可以看日落，氛围感拉满\n"
            "- 营业时间：11:30-22:00\n"
            "- 注意：菜里可能放香菜，介意的提前说\n\n"
            "适合周末晚上和朋友小聚。"
        ),
        "likes": 1900,
        "collections": 710,
        "url": "https://www.xiaohongshu.com/explore/note_003",
        "images": ["https://img.example/xhs/note003_1.jpg", "https://img.example/xhs/note003_2.jpg"],
    },
    {
        "id": "note_004",
        "title": "衡山路小众书店☕️一个人也很自在",
        "content": (
            "# 衡山路独立书店\n\n"
            "一个人也可以待一下午的地方。\n"
            "- 地址：徐汇区衡山路 880 号\n"
            "- 人均：消费随意，进店免费\n"
            "- 有咖啡，可以边看书边喝\n"
            "- 营业时间：10:00-22:00\n"
            "- 二楼靠窗位置很安静\n\n"
            "适合喜欢独处的朋友。"
        ),
        "likes": 980,
        "collections": 430,
        "url": "https://www.xiaohongshu.com/explore/note_004",
        "images": ["https://img.example/xhs/note004_1.jpg"],
    },
]


# ---------------------------------------------------------------------------
# 4.2 extract-poi 的 mock 返回：结构化 POI（与 note 一一对应）
# ---------------------------------------------------------------------------
MOCK_POIS: dict[str, dict] = {
    "note_001": {
        "name": "安福路光影摄影展",
        "city": "上海",
        "district": "徐汇区",
        "type": "展览",
        "sub_type": "摄影展",
        "estimated_price": 68,
        "opening_hours": "10:00-21:00 周二至周日",
        "tips": ["下午人少", "二楼光影装置适合拍照", "现场扫码买票"],
        "crowd_warning": "周末上午排队约30分钟",
        "note_comments": ["非常出片", "值回票价"],
        "source_note_id": "note_001",
        "confidence": 0.95,
    },
    "note_002": {
        "name": "武康庭隐藏咖啡",
        "city": "上海",
        "district": "徐汇区",
        "type": "咖啡",
        "sub_type": "精品咖啡",
        "estimated_price": 35,
        "opening_hours": "09:00-20:00",
        "tips": ["抹茶拿铁推荐", "有户外座位"],
        "crowd_warning": "",
        "note_comments": ["环境安静", "出品稳定"],
        "source_note_id": "note_002",
        "confidence": 0.9,
    },
    "note_003": {
        "name": "永平里法餐",
        "city": "上海",
        "district": "徐汇区",
        "type": "晚餐",
        "sub_type": "法餐",
        "estimated_price": 120,
        "opening_hours": "11:30-22:00",
        "tips": ["提前预约", "露台位可看日落"],
        "crowd_warning": "周末晚餐高峰需排队",
        "note_comments": ["氛围好", "性价比高"],
        "source_note_id": "note_003",
        "confidence": 0.92,
    },
    "note_004": {
        "name": "衡山路独立书店",
        "city": "上海",
        "district": "徐汇区",
        "type": "书店",
        "sub_type": "独立书店",
        "estimated_price": 0,
        "opening_hours": "10:00-22:00",
        "tips": ["二楼靠窗安静", "可边看书边喝咖啡"],
        "crowd_warning": "",
        "note_comments": ["适合独处", "氛围好"],
        "source_note_id": "note_004",
        "confidence": 0.85,
    },
}


# ---------------------------------------------------------------------------
# 4.3 amap-route 步行距离 mock（地点对 -> (km, 分钟)）
# 缺省按 1.2km / 15min 估算
# ---------------------------------------------------------------------------
MOCK_WALK_SEGMENTS: dict[tuple[str, str], tuple[float, int]] = {
    ("安福路光影摄影展", "武康庭隐藏咖啡"): (1.0, 12),
    ("武康庭隐藏咖啡", "永平里法餐"): (1.5, 18),
    ("安福路光影摄影展", "永平里法餐"): (2.3, 28),
    ("武康庭隐藏咖啡", "衡山路独立书店"): (0.8, 10),
}
