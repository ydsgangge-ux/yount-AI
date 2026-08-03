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
    "dangers": [],       # 本区危险/怪物（数组或对象数组）
    "npcs": [],          # 本区人物（标准 NPC 卡，见 NPC_SCHEMA）
    "factions": [],      # 本区驻留势力 id（数组，关联 factions）
    "level_range": [],   # 建议等级范围 [min, max]
    "biome": "",         # 生态/地貌类型
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
    "routes": [],            # 区域间交通/传送 [{from,to,type,duration}]
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
    region = _apply_schema(region, REGION_SCHEMA)
    region["key_locations"] = _normalize_list(region.get("key_locations"))
    region["dangers"] = _normalize_list(region.get("dangers"))
    region["npcs"] = _normalize_list(region.get("npcs"), NPC_SCHEMA)
    region["factions"] = _normalize_list(region.get("factions"))
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
    relations["routes"] = _normalize_list(relations.get("routes"))
    return relations


def build_region_prompt_schema() -> str:
    """生成给 LLM 的区域 Schema 模板（约束 LLM 输出标准结构）"""
    return """每个区域必须返回如下 JSON 结构：
{
  "name": "区域名",
  "description": "地理/环境详细描述",
  "climate": "气候",
  "key_locations": ["关键地点1", "关键地点2"],
  "dangers": ["本区危险/怪物1（含特性）", "本区危险/怪物2"],
  "biome": "生态/地貌类型",
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
