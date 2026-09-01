"""
任务系统（软任务，可选参与）
- 单任务：可接/进行中/完成待交付/已交付
- 系列任务：多个任务串成一条剧情线，前置完成才能接下一个
- 进度自动触发：战斗胜利、获得物品、进入地点
玩家可以不接任务，但功能必须存在。
"""
from typing import Dict, List, Optional, Tuple
import copy

# ─────────────────────────────────────────────
# 英↔中术语别名（解决"任务关键词是用英文内部ID、而运行时数据是中文"的匹配断层）
# 各组内的词都是"同一概念"的等价表述，匹配时若关键词命中任一组，则用整组词去命中数据。
# 例：任务关键词 "slime"，要把中文敌人"史莱姆"也算命中 → 组 ["slime","史莱姆",...]。
# 注意：只放语义明确的等价物，避免过宽误判（用户要求"准确"）。
# ─────────────────────────────────────────────
_TERM_ALIASES = [
    ["slime", "史莱姆"],
    ["zombie", "丧尸", "僵尸", "行尸"],
    ["wolf", "狼", "野狼", "灰狼", "暗影狼"],
    ["beast", "野兽", "凶兽", "野猪", "棕熊", "灰熊"],
    ["herb", "草药", "药草", "药材"],
    ["canned", "罐头", "罐头食物", "午餐肉", "肉罐头"],
    ["manacrystal", "法力水晶", "魔力水晶", "魔晶"],
    ["crystal", "水晶"],
    ["shade", "影魔", "影刃", "暗影刺客", "影刺客"],
    ["skeleton", "骷髅", "骷髅兵", "亡灵", "不死生物"],
    ["goblin", "哥布林"],
    ["spider", "蜘蛛"],
    ["bat", "蝙蝠"],
    ["snake", "蛇", "毒蛇"],
    ["mushroom", "蘑菇"],
    ["element", "元素"],
    ["vine", "藤蔓"],
    ["guardian", "守卫", "守门人", "守护者", "圣所守卫"],
    ["boss", "boss", "首领", "魔王", "领主", "主宰", "头目"],
    ["trial", "试炼", "试炼之地"],
    ["guild", "公會", "公会", "帮派"],
    ["army", "军团", "军队", "军队", "反抗军"],
    ["scout", "斥候", "侦察兵"],
    ["merchant", "商人", "掌柜", "店主", "老板"],
    ["guard", "卫兵", "守卫"],
    ["sanctum", "圣所", "圣殿", "圣地", "光辉圣所"],
    ["capital", "王都", "皇都", "都城", "首都"],
    ["kingdom", "王国", "皇国", "帝国"],
    ["town", "镇", "小镇", "村庄", "村落"],
    ["forest", "森林", "林", "密林"],
    ["mine", "矿洞", "矿区", "矿脉", "矿井"],
    ["harbor", "port", "港口", "码头", "海港"],
    ["dungeon", "地下城", "地牢", "密室"],
]


def _smart_match(kw: str, texts) -> bool:
    """智能匹配：keyword 是否命中任意一条 text。
    支持：
    - 大小写不敏感
    - 关键词拆分（_ / - / 空格）
    - 英↔中术语别名扩展到 _TERM_ALIASES
    texts: 可迭代的待匹配文本（str）。
    """
    kw = str(kw).strip().lower()
    if not kw:
        return False
    terms = {kw}
    for sep in ("_", "-", " "):
        if sep in kw:
            terms.update(p for p in kw.split(sep) if p)
    # 命中任一组别名 → 扩展整组词
    for group in _TERM_ALIASES:
        if any(t and t in kw for t in group):
            terms.update(group)
    lowered = [str(t).lower() for t in texts if t]
    if not lowered:
        return False
    for term in terms:
        if not term:
            continue
        for t in lowered:
            if term in t:
                return True
    return False


# ─────────────────────────────────────────────
# 任务状态常量
# ─────────────────────────────────────────────
QUEST_AVAILABLE = "available"      # 可接但未接
QUEST_ACTIVE = "active"            # 已接，进行中
QUEST_COMPLETED = "completed"      # 目标达成，待交付
QUEST_TURNED_IN = "turned_in"      # 已交付，已领奖
QUEST_FAILED = "failed"


# ─────────────────────────────────────────────
# 内置任务定义（按世界类型分组）
# 每个任务 def 是不可变的模板；玩家接取后生成 instance
# ─────────────────────────────────────────────
QUEST_DEFS = {
    # ========= 奇幻世界 =========
    "fantasy": [
        # —— 系列一：第一层清扫（适合新手）——
        {
            "id": "q_fantasy_floor1_slimes",
            "title": "草原清剿",
            "description": "酒馆老板抱怨草原上的史莱姆越来越多，请玩家清理 3 只。",
            "series_id": "series_fantasy_floor1",
            "series_order": 1,
            "req_level": 1,
            "req_quests": [],
            "quest_giver": "酒馆老板",
            "location_hint": "Town of Beginnings",
            "objectives": [
                {"type": "kill", "target_keyword": "slime", "count": 3}
            ],
            "rewards": {"exp": 40, "gold": 25},
            "auto_complete": True,
        },
        {
            "id": "q_fantasy_floor1_crystals",
            "title": "水晶收集",
            "description": "铁匠铺需要 2 块 mana crystal 修复装备。",
            "series_id": "series_fantasy_floor1",
            "series_order": 2,
            "req_level": 2,
            "req_quests": ["q_fantasy_floor1_slimes"],
            "quest_giver": "铁匠",
            "location_hint": "Town of Beginnings",
            "objectives": [
                {"type": "collect", "target_keyword": "mana crystal", "count": 2}
            ],
            "rewards": {"exp": 60, "gold": 40},
            "auto_complete": True,
        },
        {
            "id": "q_fantasy_floor1_boss",
            "title": "圣所之首",
            "description": "前往 Luminous Sanctum 击败第一层 Boss，为 Liberation Army 打开通道。",
            "series_id": "series_fantasy_floor1",
            "series_order": 3,
            "req_level": 5,
            "req_quests": ["q_fantasy_floor1_crystals"],
            "quest_giver": "Liberation Army 斥候",
            "location_hint": "Luminous Sanctum",
            "objectives": [
                {"type": "visit_location", "target_keyword": "sanctum", "count": 1},
                {"type": "kill", "target_keyword": "boss", "count": 1},
            ],
            "rewards": {"exp": 200, "gold": 150, "items": [{"name": "魔法师之戒", "rarity": "rare"}]},
            "auto_complete": False,  # 需回酒馆交付
        },
        # —— 系列二：暗影潜伏（中阶）——
        {
            "id": "q_fantasy_dark_scout",
            "title": "暗影线索",
            "description": "Mage Council 派人调查 Dark Guild 在 Tenebralis 的活动，需要一名冒险者潜入侦察。",
            "series_id": "series_fantasy_dark_guild",
            "series_order": 1,
            "req_level": 8,
            "req_quests": [],
            "quest_giver": "Mage Council 学者",
            "location_hint": "Silvamagica",
            "objectives": [
                {"type": "visit_location", "target_keyword": "tenebralis", "count": 1},
            ],
            "rewards": {"exp": 120, "gold": 80},
            "auto_complete": True,
        },
        {
            "id": "q_fantasy_dark_strike",
            "title": "暗影反击",
            "description": "Dark Guild 已发现你的调查，击败 3 名影刃刺客以自保。",
            "series_id": "series_fantasy_dark_guild",
            "series_order": 2,
            "req_level": 10,
            "req_quests": ["q_fantasy_dark_scout"],
            "quest_giver": "Mage Council 学者",
            "location_hint": "Tenebralis",
            "objectives": [
                {"type": "kill", "target_keyword": "shade", "count": 3},
            ],
            "rewards": {"exp": 200, "gold": 120},
            "auto_complete": False,
        },
    ],

    # ========= 修真世界 =========
    "cultivation": [
        {
            "id": "q_cult_spirit_beast",
            "title": "妖兽退治",
            "description": "外门长老委托清剿 3 只山外的低阶妖兽。",
            "series_id": "series_cult_outer_disciple",
            "series_order": 1,
            "req_level": 1,
            "req_quests": [],
            "quest_giver": "外门长老",
            "location_hint": "外门",
            "objectives": [
                {"type": "kill", "target_keyword": "beast", "count": 3},
            ],
            "rewards": {"exp": 40, "gold": 30},
            "auto_complete": True,
        },
        {
            "id": "q_cult_spirit_herb",
            "title": "采灵草",
            "description": "炼丹房需要 2 株灵草炼制丹药。",
            "series_id": "series_cult_outer_disciple",
            "series_order": 2,
            "req_level": 2,
            "req_quests": ["q_cult_spirit_beast"],
            "quest_giver": "丹房执事",
            "location_hint": "药园",
            "objectives": [
                {"type": "collect", "target_keyword": "herb", "count": 2},
            ],
            "rewards": {"exp": 60, "gold": 50},
            "auto_complete": True,
        },
        {
            "id": "q_cult_inner_trial",
            "title": "内门试炼",
            "description": "通过内门试炼，击败试炼守护者。",
            "series_id": "series_cult_outer_disciple",
            "series_order": 3,
            "req_level": 6,
            "req_quests": ["q_cult_spirit_herb"],
            "quest_giver": "内门长老",
            "location_hint": "试炼塔",
            "objectives": [
                {"type": "visit_location", "target_keyword": "trial", "count": 1},
                {"type": "kill", "target_keyword": "guardian", "count": 1},
            ],
            "rewards": {"exp": 250, "gold": 100, "items": [{"name": "内门弟子令", "rarity": "rare"}]},
            "auto_complete": False,
        },
    ],

    # ========= 末日世界 =========
    "apocalypse": [
        {
            "id": "q_apoc_scavenge",
            "title": "废土搜刮",
            "description": "避难所需要 3 份罐头食物。",
            "series_id": "series_apoc_survivor",
            "series_order": 1,
            "req_level": 1,
            "req_quests": [],
            "quest_giver": "避难所所长",
            "location_hint": "避难所",
            "objectives": [
                {"type": "collect", "target_keyword": "canned", "count": 3},
            ],
            "rewards": {"exp": 40, "gold": 25},
            "auto_complete": True,
        },
        {
            "id": "q_apoc_clear_zombies",
            "title": "尸潮清剿",
            "description": "避难所外围出现丧尸潮，清理 4 只。",
            "series_id": "series_apoc_survivor",
            "series_order": 2,
            "req_level": 3,
            "req_quests": ["q_apoc_scavenge"],
            "quest_giver": "避难所所长",
            "location_hint": "避难所外围",
            "objectives": [
                {"type": "kill", "target_keyword": "zombie", "count": 4},
            ],
            "rewards": {"exp": 80, "gold": 60},
            "auto_complete": True,
        },
    ],
}

# ─────────────────────────────────────────────
# 系列任务元信息
# ─────────────────────────────────────────────
QUEST_SERIES = {
    "series_fantasy_floor1": {
        "title": "第一层攻略线",
        "description": "从清理小怪到挑战 Boss，为 Liberation Army 打开通路。",
    },
    "series_fantasy_dark_guild": {
        "title": "暗影潜伏",
        "description": "调查 Dark Guild 的阴谋，揭开第五层的秘密。",
    },
    "series_cult_outer_disciple": {
        "title": "外门弟子之路",
        "description": "从外门杂役起步，一路晋升内门。",
    },
    "series_apoc_survivor": {
        "title": "废土求生",
        "description": "在丧尸横行的废土为避难所谋生存。",
    },
}


# ─────────────────────────────────────────────
# QuestSystem 核心类
# ─────────────────────────────────────────────
class QuestSystem:
    """任务系统核心，所有方法都是 classmethod，操作 state 字典"""

    @classmethod
    def _get_quest_def(cls, quest_id: str, world_type: str) -> Optional[Dict]:
        """根据 id 和世界类型查找任务定义"""
        for q in QUEST_DEFS.get(world_type, []):
            if q["id"] == quest_id:
                return q
        # 兜底：在其他世界类型里找（避免世界类型未匹配时拿不到）
        for world_quests in QUEST_DEFS.values():
            for q in world_quests:
                if q["id"] == quest_id:
                    return q
        return None

    @classmethod
    def _ensure_state(cls, state: Dict) -> Dict:
        """确保 state 中存在 quests 子结构"""
        if "quests" not in state:
            state["quests"] = {}
        q = state["quests"]
        q.setdefault("active", [])           # 已接进行中的任务实例
        q.setdefault("available_offers", []) # LLM 动态生成的任务委托（未接受）
        q.setdefault("turned_in_ids", [])    # 已交付任务 id
        q.setdefault("failed_ids", [])       # 失败任务 id
        q.setdefault("series_progress", {})  # series_id -> 当前可接的 order
        q.setdefault("dynamic_series", {})   # series_id -> {title, description}（LLM 生成的系列信息）
        return q

    # ── 动态任务生成（LLM 叙事触发）──
    @classmethod
    def create_dynamic_quests(cls, state: Dict, offers: List[Dict], ending_hint: str = "") -> Tuple[int, List[str]]:
        """
        接受 LLM 生成的任务 offer，存入 available_offers。
        支持：
        - 单个简单任务（1 个 offer，无 series_id）
        - 多目标单任务（1 个 offer，objectives 多个）
        - 系列任务（多个 offer，相同 series_id，按 series_order 排序）

        返回：(成功创建数量, [任务标题列表])
        """
        cls._ensure_state(state)
        if not isinstance(offers, list) or not offers:
            return 0, []

        # 记录结局方向上下文（供后续检查使用）
        if ending_hint:
            state["quests"]["ending_context"] = ending_hint

        # 已有 offer 标题（去重，避免 LLM 重复生成）
        existing_titles = {o.get("title", "").strip() for o in state["quests"]["available_offers"]}
        existing_titles |= {q.get("title", "").strip() for q in state["quests"]["active"]}
        existing_titles |= set()  # 不限制已交付的，允许重复委托

        created = 0
        created_titles = []
        for offer in offers:
            if not isinstance(offer, dict):
                continue
            # 校验必填字段
            title = str(offer.get("title", "")).strip()
            if not title or title in existing_titles:
                continue
            objectives = offer.get("objectives", [])
            if not isinstance(objectives, list) or not objectives:
                continue

            # 规范化 objectives
            norm_objs = []
            for o in objectives:
                if not isinstance(o, dict):
                    continue
                t = str(o.get("type", "")).strip()
                kw = str(o.get("target_keyword", "")).strip()
                cnt = int(o.get("count", 1))
                if t not in ("kill", "collect", "visit_location", "talk_npc"):
                    continue
                if not kw or cnt < 1:
                    continue
                norm_objs.append({
                    "type": t,
                    "target_keyword": kw,
                    "count": min(cnt, 20),  # 上限防止滥用
                })
            if not norm_objs:
                continue

            # 获取当前区域ID（用于到达新区域时过滤旧区域任务）
            _current_region = ""
            try:
                _wm = state.get("world_map") or {}
                _current_region = str(_wm.get("current_region_id", "") or "").strip()
            except Exception:
                pass

            # 生成唯一 id
            base = "dyn_" + "".join(c if c.isalnum() else "_" for c in title.lower())[:20]
            qid = base
            i = 1
            while cls._offer_id_exists(state, qid):
                qid = f"{base}_{i}"
                i += 1

            # 处理 series_id：避免 str(None) 变成字符串 "None"
            sid_raw = offer.get("series_id")
            sid_clean = str(sid_raw).strip() if sid_raw else ""
            sid_final = sid_clean if sid_clean and sid_clean.lower() != "none" else None

            offer_record = {
                "id": qid,
                "title": title,
                "description": str(offer.get("description", "")).strip(),
                "quest_giver": str(offer.get("quest_giver", "未知NPC")).strip(),
                "location_hint": str(offer.get("location_hint", "")).strip(),
                "difficulty": str(offer.get("difficulty", "normal")).strip().lower(),
                "series_id": sid_final,
                "series_order": int(offer.get("series_order", 1)) if sid_final else 0,
                "objectives": norm_objs,
                "rewards": {
                    "exp": int(offer.get("rewards", {}).get("exp", 30)),
                    "gold": int(offer.get("rewards", {}).get("gold", 20)),
                },
                "auto_complete": bool(offer.get("auto_complete", True)),
                "source": "dynamic",  # 标记为 LLM 动态生成
                "world_id": cls._current_world_id(state),  # 记录所属世界，切世界后过滤
                "region_id": _current_region,  # 记录当前区域，换区域后过滤
            }

            # 如果是系列任务，记录系列元信息
            if sid_final:
                if sid_final not in state["quests"]["dynamic_series"]:
                    state["quests"]["dynamic_series"][sid_final] = {
                        "title": str(offer.get("series_title", title)).strip(),
                        "description": str(offer.get("series_description", "")).strip(),
                    }

            state["quests"]["available_offers"].append(offer_record)
            existing_titles.add(title)
            created += 1
            created_titles.append(title)

        return created, created_titles

    @classmethod
    def _current_world_id(cls, state: Dict) -> str:
        """获取当前世界的 world_id（从 world_setting 读取）"""
        ws = state.get("world_setting") or {}
        return str(ws.get("world_id", "") or "").strip()

    @classmethod
    def _offer_id_exists(cls, state: Dict, qid: str) -> bool:
        """检查 offer id 是否已存在（offers + active + turned_in）"""
        for o in state["quests"].get("available_offers", []):
            if o.get("id") == qid:
                return True
        for q in state["quests"].get("active", []):
            if q.get("id") == qid:
                return True
        return qid in state["quests"].get("turned_in_ids", [])

    @classmethod
    def get_available_offers(cls, state: Dict) -> List[Dict]:
        """获取所有动态生成的任务 offer（未接受）
        按当前世界过滤：只返回属于当前世界的 offer；旧数据无 world_id 的视为当前世界
        按当前区域过滤：只返回属于当前区域的 offer；旧数据无 region_id 的视为当前区域
        """
        cls._ensure_state(state)
        cur_world = cls._current_world_id(state)
        # 获取当前区域ID
        cur_region = ""
        try:
            _wm = state.get("world_map") or {}
            cur_region = str(_wm.get("current_region_id", "") or "").strip()
        except Exception:
            pass
        offers = []
        for o in state["quests"]["available_offers"]:
            ow = str(o.get("world_id", "") or "").strip()
            # 无 world_id 的旧数据 → 视为当前世界（保留兼容）；有则必须匹配当前世界
            if ow and cur_world and ow != cur_world:
                continue
            # 区域过滤：有 region_id 的必须匹配当前区域
            ori = str(o.get("region_id", "") or "").strip()
            if ori and cur_region and ori != cur_region:
                continue
            offers.append(o)
        return offers

    @classmethod
    def remove_offer(cls, state: Dict, quest_id: str) -> bool:
        """从 offers 列表移除（接受/拒绝后调用）"""
        cls._ensure_state(state)
        before = len(state["quests"]["available_offers"])
        state["quests"]["available_offers"] = [
            o for o in state["quests"]["available_offers"] if o.get("id") != quest_id
        ]
        return len(state["quests"]["available_offers"]) < before

    # ── 可接任务 ──
    @classmethod
    def get_available_quests(cls, state: Dict, character: Dict) -> List[Dict]:
        """获取角色当前可接的任务（未接且满足前置/等级）
        自定义世界（有 world_id）只返回动态任务，不返回预定义任务
        """
        cls._ensure_state(state)
        world_type = state.get("world_type", "fantasy")
        char_level = character.get("level", 1)
        turned_in = set(state["quests"]["turned_in_ids"])
        active_ids = {q["id"] for q in state["quests"]["active"]}
        failed = set(state["quests"]["failed_ids"])

        # 自定义世界（有 world_id）不显示预定义任务，只靠 LLM 动态生成
        cur_world = cls._current_world_id(state)

        available = []
        if not cur_world:
            # 仅默认世界（无 world_id）才显示预定义任务
            for q_def in QUEST_DEFS.get(world_type, []):
                qid = q_def["id"]
                if qid in turned_in or qid in active_ids or qid in failed:
                    continue
                # 等级要求
                if q_def.get("req_level", 1) > char_level:
                    continue
                # 前置任务
                reqs = q_def.get("req_quests", [])
                if not all(r in turned_in for r in reqs):
                    continue
                available.append(q_def)
        return available

    # ── 进行中任务 ──
    @classmethod
    def get_active_quests(cls, state: Dict) -> List[Dict]:
        cls._ensure_state(state)
        cur_world = cls._current_world_id(state)
        active = []
        for q in state["quests"]["active"]:
            qw = str(q.get("world_id", "") or "").strip()
            if qw and cur_world and qw != cur_world:
                continue
            active.append(q)
        return active

    # ── 接受任务 ──
    @classmethod
    def accept_quest(cls, state: Dict, quest_id: str, character: Dict) -> Tuple[bool, str]:
        """接受任务：先查动态 offers，找不到再查预定义 QUEST_DEFS"""
        cls._ensure_state(state)

        # 1) 先在动态 offers 里找（只找当前世界的，防止接受旧世界任务）
        cur_world = cls._current_world_id(state)
        q_def = None
        is_dynamic = False
        for o in state["quests"]["available_offers"]:
            if o.get("id") != quest_id:
                continue
            ow = str(o.get("world_id", "") or "").strip()
            if ow and cur_world and ow != cur_world:
                continue  # 旧世界任务，跳过
            q_def = o
            is_dynamic = True
            break

        # 2) 找不到则查预定义
        if not q_def:
            world_type = state.get("world_type", "fantasy")
            q_def = cls._get_quest_def(quest_id, world_type)
        if not q_def:
            return False, "任务不存在"

        active_ids = {q["id"] for q in state["quests"]["active"]}
        if quest_id in active_ids:
            return False, "任务已在进行中"
        if quest_id in state["quests"]["turned_in_ids"]:
            return False, "任务已完成"
        if quest_id in state["quests"]["failed_ids"]:
            return False, "任务已失败"

        # 等级 & 前置检查
        if q_def.get("req_level", 1) > character.get("level", 1):
            return False, f"需要等级 {q_def['req_level']}"
        reqs = q_def.get("req_quests", [])
        missing = [r for r in reqs if r not in state["quests"]["turned_in_ids"]]
        if missing:
            return False, "前置任务未完成"

        # 创建任务实例（深拷贝 objectives，加 progress 字段）
        instance = {
            "id": q_def["id"],
            "title": q_def["title"],
            "description": q_def["description"],
            "series_id": q_def.get("series_id"),
            "series_order": q_def.get("series_order", 0),
            "quest_giver": q_def.get("quest_giver", "未知"),
            "objectives": [
                {
                    "type": o["type"],
                    "target_keyword": o["target_keyword"],
                    "count": o["count"],
                    "progress": 0,
                }
                for o in q_def["objectives"]
            ],
            "rewards": q_def.get("rewards", {}),
            "auto_complete": q_def.get("auto_complete", False),
            "status": QUEST_ACTIVE,
        }
        state["quests"]["active"].append(instance)

        # 如果来自动态 offers，从 offers 列表移除
        if is_dynamic:
            cls.remove_offer(state, quest_id)

        return True, f"已接受任务「{q_def['title']}」"

    # ── 记录进度（核心：战斗胜利/得物品/进地点时调用）──
    @classmethod
    def record_progress(cls, state: Dict, event_type: str, **kwargs) -> List[Dict]:
        """
        触发进度更新。返回被推进/完成的目标列表。

        event_type: "kill" | "collect" | "visit_location" | "talk_npc"
        kwargs:
            - kill: enemy_names=[...]
            - collect: items=[{"name":...}, ...]
            - visit_location: location="..."
            - talk_npc: npc_name="..."
            - narrative: "叙事文本"（可选，用于 fallback 匹配，当 LLM 输出中文名时兜底）
            - action_text: "用户行动文本"（可选，额外 fallback）
        """
        cls._ensure_state(state)
        active = state["quests"]["active"]
        if not active:
            return []

        # 提取 fallback 文本（叙事文本和用户行动文本）
        _narrative = str(kwargs.get("narrative", "") or "")
        _action = str(kwargs.get("action_text", "") or "")

        progressed = []
        for quest in active:
            if quest.get("status") != QUEST_ACTIVE:
                continue
            for obj in quest["objectives"]:
                if obj["progress"] >= obj["count"]:
                    continue  # 已完成的目标
                if obj["type"] != event_type:
                    continue
                kw = obj["target_keyword"].lower()
                if not kw:
                    continue
                matched = False
                if event_type == "kill":
                    names = kwargs.get("enemy_names", [])
                    matched = _smart_match(kw, names)
                    if not matched:
                        matched = _smart_match(kw, [_narrative])
                elif event_type == "collect":
                    items = kwargs.get("items", [])
                    matched = _smart_match(kw, [it.get("name", "") for it in items])
                    if not matched:
                        matched = _smart_match(kw, [_narrative, _action])
                elif event_type == "visit_location":
                    loc = str(kwargs.get("location", "") or "")
                    matched = _smart_match(kw, [loc])
                    if not matched:
                        matched = _smart_match(kw, [_narrative, _action])
                elif event_type == "talk_npc":
                    npc = str(kwargs.get("npc_name", "") or "")
                    matched = _smart_match(kw, [npc])
                    if not matched:
                        matched = _smart_match(kw, [_narrative, _action])

                if matched:
                    obj["progress"] = min(obj["count"], obj["progress"] + 1)
                    progressed.append({
                        "quest_id": quest["id"],
                        "quest_title": quest["title"],
                        "objective": obj,
                    })

            # 检查任务是否整体完成
            all_done = all(o["progress"] >= o["count"] for o in quest["objectives"])
            if all_done and quest["status"] == QUEST_ACTIVE:
                if quest.get("auto_complete", False):
                    # 自动完成 → 直接变 completed，玩家需主动交付领奖
                    quest["status"] = QUEST_COMPLETED
                # 如果 auto_complete=True 且没有 NPC 交付需求，也可以自动交付
                # 这里保持简单：auto_complete 表示"目标达成即完成"，但仍需 turn_in 领奖
        return progressed

    # ── 任务校验器：专项解决"到达地点"判定问题 ──
    @classmethod
    def validate_visit_locations(cls, state: Dict, **kwargs) -> List[Dict]:
        """
        任务校验器：基于【玩家当前实际所在区域】的多源数据，校验进行中的
        "到达地点"(visit_location) 目标是否真实达成。

        解决的问题：
        1. 目标关键词是英文内部ID(如 port_area/sanctum)，而触发只用中文区域名，
           导致 kw in loc 永远不匹配 → 到了却不打勾。
        2. 目标指向某区域的子地点(如"王都的港口区")，玩家到达父区域时无法精确判断。
        3. 触发只依赖 LLM 叙事文本的措辞，地点描写有差距就判不中。

        数据来源（多源取并集，提高准确性）：
        - state["world_map"]：当前区域 region_id / name / description
        - state["story"]：current_location / scene_description / 子场景栈（LLM叙事设置的子地点）
        - 任务自带 location_hint（可能含英文ID或中文名）
        - kwargs 允许补充：location(子地点名)、region_id、narrative、action_text

        返回：本次被推进/完成的目标列表（与 record_progress 一致的结构）。
        """
        cls._ensure_state(state)
        active = state["quests"]["active"]
        if not active:
            return []

        # ── 搜集当前实际所在区域数据 ──
        # 1) 显式传入的 region_id（最高优先）
        cur_id = str(kwargs.get("region_id", "") or "").strip()
        # 2) 从 state.world_map 读取（触发处未传时兜底）
        _wm = state.get("world_map") or {}
        if not cur_id:
            cur_id = str(_wm.get("current_region_id", "") or "").strip()
        cur_name = ""
        cur_desc = ""
        _regions = _wm.get("regions") or {}
        if isinstance(_regions, dict):
            _reg = _regions.get(cur_id)
            if isinstance(_reg, dict):
                cur_name = str(_reg.get("name", "") or "")
                cur_desc = str(_reg.get("description", "") or "")
        # 3) story 上下文：LLM叙事设置的当前地点/场景描述/子场景栈（子地点常在此）
        _story = state.get("story") or {}
        _story_ctx = " ".join([
            str(_story.get("current_location", "") or ""),
            str(_story.get("scene_description", "") or ""),
        ])
        try:
            _stack = _story.get("sub_scene_stack") or []
            if isinstance(_stack, list):
                _story_ctx += " " + " ".join(
                    str(s.get("location", "") or "") for s in _stack if isinstance(s, dict))
        except Exception:
            pass
        # 4) 显式补充的 location（子地点名）与叙事/行动文本
        extra_location = str(kwargs.get("location", "") or "")
        extra_text = " ".join([
            str(kwargs.get("narrative", "") or ""),
            str(kwargs.get("action_text", "") or ""),
        ])

        def _variants(kw: str) -> List[str]:
            vs = {kw}
            for sep in ("_", "-", " "):
                if sep in kw:
                    vs.update(p for p in kw.split(sep) if p)
            # 英文内部地点ID → 扩展到中译文名（如 sanctum → 圣所）
            for group in _TERM_ALIASES:
                if any(t and t in kw for t in group):
                    vs.update(group)
            return list(vs)

        progressed = []
        for quest in active:
            if quest.get("status") != QUEST_ACTIVE:
                continue
            # 任务自带 location_hint 作为额外匹配源
            q_hint = str(quest.get("location_hint", "") or "").lower()
            for obj in quest["objectives"]:
                if obj.get("type") != "visit_location":
                    continue
                if obj.get("progress", 0) >= obj.get("count", 1):
                    continue
                kw_raw = str(obj.get("target_keyword", "") or "").strip()
                if not kw_raw:
                    continue
                kw = kw_raw.lower()
                # ── 多维判定 ──
                matched = False
                # ① 当前区域英文ID（解决英文ID vs 中文名）
                if cur_id and kw in str(cur_id).lower():
                    matched = True
                # ② 当前区域中文名
                if not matched and cur_name and kw in str(cur_name).lower():
                    matched = True
                # ③ 当前区域描述（解决子地点藏在描述里、措辞有差距）
                if not matched and cur_desc:
                    for _v in _variants(kw):
                        if _v and _v in str(cur_desc).lower():
                            matched = True
                            break
                # ③' story上下文：LLM叙事设置的当前地点/场景描述/子场景栈（子地点常在此）
                if not matched and _story_ctx:
                    for _v in _variants(kw):
                        if _v and _v in _story_ctx.lower():
                            matched = True
                            break
                # ④ 触发时补充的子地点名/叙事/行动文本
                if not matched and extra_location:
                    for _v in _variants(kw):
                        if _v and _v in str(extra_location).lower():
                            matched = True
                            break
                if not matched and extra_text:
                    for _v in _variants(kw):
                        if _v and _v in extra_text.lower():
                            matched = True
                            break
                # ⑤ 任务自带的 location_hint（含英文ID或中文名）
                if not matched and q_hint:
                    for _v in _variants(kw):
                        if _v and _v in q_hint:
                            matched = True
                            break
                if not matched:
                    continue

                obj["progress"] = min(obj.get("count", 1), obj.get("progress", 0) + 1)
                progressed.append({
                    "quest_id": quest["id"],
                    "quest_title": quest["title"],
                    "objective": obj,
                })

            # 目标全部达成 → 更新任务状态（与 record_progress 保持一致）
            if quest["status"] == QUEST_ACTIVE:
                all_done = all(o.get("progress", 0) >= o.get("count", 1) for o in quest["objectives"])
                if all_done and quest.get("auto_complete", False):
                    quest["status"] = QUEST_COMPLETED
        return progressed

    # ── 交付任务（领奖）──
    @classmethod
    def turn_in_quest(cls, state: Dict, quest_id: str, character: Dict) -> Tuple[bool, str, Dict]:
        """
        交付任务并发放奖励。返回 (success, message, rewards)
        """
        cls._ensure_state(state)
        active = state["quests"]["active"]
        quest = None
        for q in active:
            if q["id"] == quest_id:
                quest = q
                break
        if not quest:
            return False, "任务不在进行中", {}
        if quest["status"] not in (QUEST_ACTIVE, QUEST_COMPLETED):
            return False, "任务状态异常", {}

        # 检查目标是否全部完成
        all_done = all(o["progress"] >= o["count"] for o in quest["objectives"])
        if not all_done:
            unfinished = [
                f"{o['type']}:{o['target_keyword']} ({o['progress']}/{o['count']})"
                for o in quest["objectives"] if o["progress"] < o["count"]
            ]
            return False, "目标未完成: " + " / ".join(unfinished), {}

        # 发放奖励
        rewards = quest.get("rewards", {})
        exp_gain = rewards.get("exp", 0)
        gold_gain = rewards.get("gold", 0)
        items_gain = rewards.get("items", [])

        character["gold"] = character.get("gold", 0) + gold_gain
        # 经验单独返回，由 death_mode 调用 GrowthSystem 处理
        # 这里只更新任务状态
        for i, q in enumerate(active):
            if q["id"] == quest_id:
                active.pop(i)
                break
        state["quests"]["turned_in_ids"].append(quest_id)

        # 更新系列进度
        series_id = quest.get("series_id")
        if series_id:
            cur = state["quests"]["series_progress"].get(series_id, 0)
            state["quests"]["series_progress"][series_id] = max(cur, quest.get("series_order", 0))

        msg = f"任务「{quest['title']}」已交付！获得 经验+{exp_gain} 金币+{gold_gain}"
        if items_gain:
            msg += f" 物品：{', '.join(it.get('name','?') for it in items_gain)}"
        return True, msg, rewards

    # ── 清理旧区域任务委托 ──
    @classmethod
    def cleanup_offers_by_region(cls, state: Dict) -> int:
        """当玩家进入新区域时，清理属于旧区域的可接任务委托。
        返回被移除的 offer 数量。
        """
        cls._ensure_state(state)
        cur_region = ""
        try:
            _wm = state.get("world_map") or {}
            cur_region = str(_wm.get("current_region_id", "") or "").strip()
        except Exception:
            pass
        if not cur_region:
            return 0
        before = len(state["quests"]["available_offers"])
        state["quests"]["available_offers"] = [
            o for o in state["quests"]["available_offers"]
            if not str(o.get("region_id", "") or "").strip()  # 无 region_id 的不清理（旧数据兼容）
            or str(o.get("region_id", "") or "").strip() == cur_region  # 属于当前区域的保留
        ]
        removed = before - len(state["quests"]["available_offers"])
        if removed > 0:
            print(f"[QuestSystem] 区域变更，清理 {removed} 个旧区域任务委托")
        return removed

    # ── 放弃任务 ──
    @classmethod
    def abandon_quest(cls, state: Dict, quest_id: str) -> Tuple[bool, str]:
        """放弃进行中的任务：从 active 移除，加入 failed_ids"""
        cls._ensure_state(state)
        active = state["quests"]["active"]
        quest = None
        for i, q in enumerate(active):
            if q["id"] == quest_id:
                quest = q
                active.pop(i)
                break
        if not quest:
            return False, "任务不在进行中"
        # 加入失败列表（后续不再显示）
        state["quests"]["failed_ids"].append(quest_id)
        # 如果是系列任务，不影响系列进度（只是当前任务放弃）
        return True, f"已放弃任务「{quest['title']}」"

    # ── 系列任务信息 ──
    @classmethod
    def get_series_overview(cls, state: Dict, world_type: str) -> List[Dict]:
        """获取本世界所有系列任务的总览（含进度）—— 预定义 + LLM 动态生成"""
        cls._ensure_state(state)
        result = []
        turned_in = set(state["quests"]["turned_in_ids"])
        active_ids = {q["id"] for q in state["quests"]["active"]}
        offer_ids = {o["id"] for o in state["quests"]["available_offers"]}

        # 按 series_id 分组（预定义 + 动态 offers）
        series_map: Dict[str, List[Dict]] = {}
        cur_world = cls._current_world_id(state)
        # 自定义世界（有 world_id）不显示预定义系列，只显示动态系列
        if not cur_world:
            for q_def in QUEST_DEFS.get(world_type, []):
                sid = q_def.get("series_id")
                if not sid:
                    continue
                series_map.setdefault(sid, []).append(q_def)

        # 加入动态 offers 中的系列任务（未接受）— 按当前世界过滤
        for o in state["quests"]["available_offers"]:
            sid = o.get("series_id")
            if not sid:
                continue
            # 过滤旧世界任务
            ow = str(o.get("world_id", "") or "").strip()
            if ow and cur_world and ow != cur_world:
                continue
            series_map.setdefault(sid, []).append(o)

        # 加入已接受的动态任务（active 中）— 按当前世界过滤
        for q in state["quests"]["active"]:
            sid = q.get("series_id")
            if not sid:
                continue
            # 避免和 offers / QUEST_DEFS 重复（按 id 去重）
            existing_ids = {x["id"] for x in series_map.get(sid, [])}
            if q["id"] not in existing_ids:
                series_map.setdefault(sid, []).append(q)

        for sid, quests in series_map.items():
            quests.sort(key=lambda q: q.get("series_order", 0))
            # 系列元信息：优先用动态生成的，否则查预定义
            dyn_info = state["quests"].get("dynamic_series", {}).get(sid)
            if dyn_info:
                series_info = dyn_info
            else:
                series_info = QUEST_SERIES.get(sid, {"title": sid, "description": ""})
            quest_list = []
            for q in quests:
                if q["id"] in turned_in:
                    status = "turned_in"
                elif q["id"] in active_ids:
                    status = "active"
                elif q["id"] in offer_ids:
                    status = "available_offer"
                else:
                    status = "available"
                quest_list.append({
                    "id": q["id"],
                    "title": q["title"],
                    "order": q.get("series_order", 0),
                    "req_level": q.get("req_level", 1),
                    "status": status,
                })
            completed_count = sum(1 for q in quest_list if q["status"] == "turned_in")
            result.append({
                "series_id": sid,
                "title": series_info.get("title", sid),
                "description": series_info.get("description", ""),
                "total_quests": len(quest_list),
                "completed_quests": completed_count,
                "quests": quest_list,
            })
        return result

    # ── 暴露任务给 LLM prompt（让叙事能引用任务）──
    @classmethod
    def get_active_quests_summary(cls, state: Dict) -> str:
        """生成简短的进行中任务摘要，供 story_agent prompt 使用"""
        cls._ensure_state(state)
        active = state["quests"]["active"]
        if not active:
            return ""
        lines = []
        for q in active:
            obj_lines = []
            for o in q["objectives"]:
                obj_lines.append(f"{o['type']}:{o['target_keyword']}({o['progress']}/{o['count']})")
            lines.append(f"· {q['title']} - {'/'.join(obj_lines)}")
        return "当前任务：\n" + "\n".join(lines)

    # ── 按系列查询任务（供隐藏结局系统使用）──
    @classmethod
    def get_quests_by_series(cls, state: Dict, series_id: str) -> List[Dict]:
        """获取指定系列的所有任务（包括已交付、进行中、可接的）"""
        cls._ensure_state(state)
        result = []
        turned_in = set(state["quests"]["turned_in_ids"])
        active_ids = {q["id"] for q in state["quests"]["active"]}

        # 从预定义任务中查找
        world_type = state.get("world_type", "fantasy")
        for q_def in QUEST_DEFS.get(world_type, []):
            if q_def.get("series_id") == series_id:
                qid = q_def["id"]
                result.append(q_def)

        # 从动态任务中查找
        for o in state["quests"].get("available_offers", []):
            if o.get("series_id") == series_id:
                result.append(o)
        for q in state["quests"].get("active", []):
            if q.get("series_id") == series_id and q not in result:
                result.append(q)

        # 按 series_order 排序
        result.sort(key=lambda x: x.get("series_order", 0))
        return result

    # ── 坏人路线：NPC被杀时处理任务断裂 ──
    @classmethod
    def on_npc_killed(cls, state: Dict, npc_name: str) -> List[str]:
        """当NPC被玩家杀死时，处理相关任务：
        1. talk_npc类型目标涉及该NPC的进行中任务 → 标记失败
        2. 从待接委托中移除涉及该NPC的offer
        返回受影响的任务标题列表。
        """
        cls._ensure_state(state)
        affected = []
        npc_lower = npc_name.lower()

        # 1. 进行中任务：talk_npc目标涉及该NPC → 失败
        active = state["quests"]["active"]
        for quest in active:
            if quest.get("status") != QUEST_ACTIVE:
                continue
            for obj in quest.get("objectives", []):
                if obj.get("type") == "talk_npc" and obj.get("progress", 0) < obj.get("count", 1):
                    kw = str(obj.get("target_keyword", "")).lower()
                    if kw and (kw in npc_lower or npc_lower in kw):
                        quest["status"] = QUEST_FAILED
                        affected.append(f"{quest['title']}(NPC已死，任务失败)")
                        break

        # 2. 待接委托：涉及该NPC的offer → 移除
        offers = state["quests"].get("available_offers", [])
        before = len(offers)
        state["quests"]["available_offers"] = [
            o for o in offers
            if not any(
                str(o.get("quest_giver", "")).lower() in npc_lower or npc_lower in str(o.get("quest_giver", "")).lower()
                for _ in [1]
            )
        ]
        # 检查offer的objectives中是否涉及该NPC
        remaining_offers = []
        for o in state["quests"]["available_offers"]:
            has_dead_npc = False
            for obj in o.get("objectives", []):
                if obj.get("type") == "talk_npc":
                    kw = str(obj.get("target_keyword", "")).lower()
                    if kw and (kw in npc_lower or npc_lower in kw):
                        has_dead_npc = True
                        break
            if not has_dead_npc:
                remaining_offers.append(o)
            else:
                affected.append(f"委托『{o.get('title', '?')}』(NPC已死，委托消失)")
        state["quests"]["available_offers"] = remaining_offers

        if affected:
            print(f"[QuestSystem] NPC『{npc_name}』被杀，影响任务: {', '.join(affected)}")
        return affected
