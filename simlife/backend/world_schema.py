"""
世界设定标准 Schema

设计目标：
- 所有世界（用户生成/下载）产出统一的标准结构，保证下游（地图、战斗、叙事、NPC）稳定读取
- 每个实体（区域/势力/NPC/危险）都有标准字段模板 + 默认值
- 清洗时：缺字段填默认值、多余字段归入 extensions（可扩展空间），绝不崩溃

结构：
  world_setting.json     核心世界观（元信息 + 全局概述 + 势力/危险索引）
  regions/<id>.json      每个区域独立标准结构
  relations.json         跨区域关系（势力据点/跨区域剧情/人物行踪）
"""
from typing import Dict, Any


# ────────────────────────────────
# 标准 Schema 定义（带默认值）
# ────────────────────────────────

REGION_SCHEMA = {
    "id": "",            # 唯一 id（小写下划线）
    "name": "",          # 区域名
    "description": "",   # 地理/环境描述
    "climate": "",       # 气候
    "key_locations": [], # 关键地点（数组）
    "dangers": [],       # 本区危险/怪物概述（数组或对象数组，供叙事用）
    "monsters": [],      # 本区怪物战斗数据（MONSTER_SCHEMA 数组，供战斗系统用）
    "boss": None,        # 区域 BOSS（dict 或 None）
    "npcs": [],          # 本区人物（标准 NPC 卡，见 NPC_SCHEMA）
    "factions": [],      # 本区驻留势力 id（数组，关联 factions）
    "level_range": [],   # 建议等级范围 [min, max]
    "biome": "",         # 生态/地貌类型（town/wild/dungeon/boss_lair/secret）
}

NPC_SCHEMA = {
    "id": "",
    "name": "",
    "role": "",          # 身份/职责
    "description": "",   # 性格/背景
    "faction_id": "",    # 所属势力 id
    "is_key": False,     # 是否关键剧情人物
}

FACTION_SCHEMA = {
    "id": "",
    "name": "",
    "type": "",          # 组织类型（公会/王国/教会等）
    "ideology": "",      # 理念/立场
    "description": "",
    "leader": "",
    "base_region_id": "",# 总部所在区域
    "regions": [],       # 活动/据点区域 id 列表（跨区域）
}

MONSTER_SCHEMA = {
    "name": "",
    "level": 1,
    "hp": 50,
    "max_hp": 50,
    "attack_power": 5,
    "defense_power": 5,
    "exp_reward": 20,
    "gold_reward": 10,
    "stats": {"strength": 5, "agility": 5, "intelligence": 3, "vitality": 5, "luck": 3},
    "equipment": [],
    "skills": [],
    "type": "normal",    # normal/elite/boss
    "behavior": "",      # 行为/攻击特性描述（供叙事用）
}

DUNGEON_SCHEMA = {
    "id": "",
    "name": "",
    "region_id": "",     # 所在区域
    "level_range": [],   # 建议等级
    "floors": 1,         # 层数
    "boss": "",          # BOSS 名
    "drops": [],         # 掉落物
    "description": "",
}

RELATIONS_SCHEMA = {
    "faction_presence": {},  # {faction_id: [region_id, ...]} 势力据点
    "storylines": [],        # 跨区域剧情线 [{id,name,regions,description,progress}]
    "characters": [],        # 跨区域人物行踪 [{id,name,role,current_region,faction_id}]
    # routes 字段已废弃（全代码库无读取逻辑），保留 schema 以兼容旧数据
}

# 世界 BOSS 等级固定曲线（玩家上限 60，全程高于玩家保证挑战性）
WORLD_BOSS_LEVELS = {
    "boss": 65,          # 世界 BOSS 本体
    "subordinate": 64,   # 直属手下
    "elite": 62,         # 精英
    "minion": 60,        # 精锐小兵
}

# 世界 BOSS 数量约束（按用户提供的世界，最少 3 个，最多 8 个）
WORLD_BOSS_MIN = 3
WORLD_BOSS_MAX = 8

WORLD_BOSS_SCHEMA = {
    "name": "",            # BOSS名
    "type": "monster",     # monster/evil_faction/special_race/other
    "identity": "",        # 身份/性格/目标（供身份交流：谈判/求饶/逃跑/加入）
    "level": 65,           # BOSS本体等级（固定公式，忽略LLM乱填）
    "territories": [],     # 领地区域名（2-3个，都会自动生成 worldboss 区域）
    "minions": [],         # 精锐小兵名列表（Lv.60）
    "elites": [],          # 精英名列表（Lv.62）
    "subordinates": [],    # 直属手下名列表（Lv.64）
    "can_surrender": True, # 是否允许玩家求饶/逃跑
    "can_join": True,      # 是否允许玩家加入该BOSS势力
    "description": "",     # 背景描述
}


# ────────────────────────────────
# 清洗/标准化工具
# ────────────────────────────────

def _normalize_list(value, item_schema=None) -> list:
    """规范化数组：确保是 list，若 item_schema 则逐项清洗"""
    if value is None:
        return []
    if not isinstance(value, list):
        value = [value]
    if not item_schema:
        return [v for v in value if v is not None]
    out = []
    for v in value:
        if isinstance(v, dict):
            out.append(_apply_schema(v, item_schema))
        elif v is not None:
            out.append(v)
    return out


def _apply_schema(data: Dict, schema: Dict) -> Dict:
    """用 schema 清洗一个对象：缺字段补默认，多余字段归入 extensions"""
    result = {}
    extensions = {}
    for key, default in schema.items():
        if key in data and data[key] is not None:
            result[key] = data[key]
        else:
            result[key] = default
    # 多余字段归入 extensions（可扩展空间）
    for key in data:
        if key not in schema and key != "extensions":
            extensions[key] = data[key]
    if extensions:
        result["extensions"] = extensions
    return result


def sanitize_region(region: Dict) -> Dict:
    """清洗区域数据为标准结构"""
    if not isinstance(region, dict):
        region = {}
    # 旧数据兼容：features → key_locations（问题11）
    if "features" in region and not region.get("key_locations"):
        region["key_locations"] = region.pop("features")
    region = _apply_schema(region, REGION_SCHEMA)
    region["key_locations"] = _normalize_list(region.get("key_locations"))
    region["dangers"] = _normalize_list(region.get("dangers"))
    region["monsters"] = _normalize_list(region.get("monsters"), MONSTER_SCHEMA)
    region["npcs"] = _normalize_list(region.get("npcs"), NPC_SCHEMA)
    region["factions"] = _normalize_list(region.get("factions"))
    # boss 可以是 None 或 dict
    if region.get("boss") is not None and not isinstance(region.get("boss"), dict):
        region["boss"] = None
    if not region.get("id"):
        import re
        region["id"] = re.sub(r"[^a-zA-Z0-9]+", "_", (region.get("name") or "region").lower()).strip("_") or "region"
    return region


def sanitize_faction(faction: Dict) -> Dict:
    if not isinstance(faction, dict):
        faction = {}
    faction = _apply_schema(faction, FACTION_SCHEMA)
    faction["regions"] = _normalize_list(faction.get("regions"))
    if not faction.get("id"):
        import re
        faction["id"] = re.sub(r"[^a-zA-Z0-9]+", "_", (faction.get("name") or "faction").lower()).strip("_") or "faction"
    return faction


def sanitize_relations(relations: Dict) -> Dict:
    if not isinstance(relations, dict):
        relations = {}
    relations = _apply_schema(relations, RELATIONS_SCHEMA)
    relations["faction_presence"] = relations.get("faction_presence") or {}
    relations["storylines"] = _normalize_list(relations.get("storylines"))
    relations["characters"] = _normalize_list(relations.get("characters"))
    return relations


def sanitize_world_boss(boss: Dict) -> Dict:
    """清洗一个世界 BOSS 为标准结构，并强制使用固定等级曲线"""
    if not isinstance(boss, dict):
        boss = {}
    boss = _apply_schema(boss, WORLD_BOSS_SCHEMA)
    # 数量/内容用固定等级曲线兜底，防止 LLM 乱填导致失衡
    boss["level"] = WORLD_BOSS_LEVELS["boss"]
    boss["minions"] = _normalize_list(boss.get("minions"))
    boss["elites"] = _normalize_list(boss.get("elites"))
    boss["subordinates"] = _normalize_list(boss.get("subordinates"))
    boss["territories"] = _normalize_list(boss.get("territories"))
    # 类型规范化
    if boss.get("type") not in ("monster", "evil_faction", "special_race", "other"):
        boss["type"] = "monster"
    # 布尔字段兜底
    boss["can_surrender"] = bool(boss.get("can_surrender", True))
    boss["can_join"] = bool(boss.get("can_join", True))
    return boss


def build_world_boss_prompt_schema() -> str:
    """生成给 LLM 的世界 BOSS Schema 模板（约束 LLM 输出标准结构）"""
    return """每个世界 BOSS 必须返回如下 JSON 对象（数量 3-8 个，可混合种族/势力/怪物）：
{
  "name": "世界BOSS名",
  "type": "monster/evil_faction/special_race/other",
  "identity": "身份、性格、目标（供玩家谈判/求饶/逃跑/加入时使用）",
  "description": "背景故事",
  "territories": ["领地区域名1", "领地区域名2", "领地区域名3"],
  "minions": ["精锐小兵名", "精锐小兵名"],
  "elites": ["精英名", "精英名"],
  "subordinates": ["直属手下名", "直属手下名"],
  "can_surrender": true,
  "can_join": true
}
（等级由系统固定：小兵60/精英62/手下64/BOSS65，无需填写）"""


def build_region_prompt_schema() -> str:
    """生成给 LLM 的区域 Schema 模板（约束 LLM 输出标准结构）"""
    return """每个区域必须返回如下 JSON 结构：
{
  "name": "区域名",
  "description": "地理/环境详细描述",
  "climate": "气候",
  "key_locations": ["关键地点1", "关键地点2"],
  "dangers": ["本区危险/怪物概述（供叙事用）"],
  "monsters": [{"name": "怪物名", "level": 等级, "type": "normal/elite/boss", "behavior": "行为描述"}],
  "boss": null 或 {"name": "BOSS名", "description": "BOSS描述"},
  "biome": "生态/地貌类型（town/wild/dungeon/boss_lair/secret）",
  "level_range": [最低等级, 最高等级]
}
（本区 NPC 和势力在后续步骤单独生成，这里不填）"""


def build_faction_prompt_schema() -> str:
    return """每个势力必须返回如下 JSON 结构：
{
  "id": "势力英文id",
  "name": "势力名",
  "type": "组织类型（公会/王国/教会/帝国等）",
  "ideology": "理念与立场",
  "description": "详细描述",
  "leader": "领袖名",
  "base_region_id": "总部所在区域id",
  "regions": ["活动/据点区域id1", "活动/据点区域id2"]
}"""
