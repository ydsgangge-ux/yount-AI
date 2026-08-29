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
import random
import re
from typing import Dict, Any, List, Optional


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
    "resources": [],     # 本区资源（RESOURCE_SCHEMA 数组：可采集/锻造/交易的材料）
    "quests": [],        # 本地剧情/任务（LOCAL_QUEST_SCHEMA 数组：本区域可触发的小剧情）
    "relationships": [], # 元素关系（RELATIONSHIP_SCHEMA：人/怪物/资源/势力/剧情 之间的关联）
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
    "taxonomy": "",      # 所属生态位（野兽/人形/亡灵/恶魔/元素/龙类…，关联世界生态册）
    "species": "",       # 所属具体物种（如"灰谷狼"，关联世界生态册 species）
    "habitat": "",       # 栖息地/出没环境
    "weakness": "",      # 弱点（供玩家应对/叙事）
    "drop_materials": [],  # 专属掉落材料（兽材等，联动"万物皆可锻造"）
}

# 世界生态位（怪物生态册第一级：如 野兽/人形/亡灵/恶魔/元素/龙类/构装体/虫群…）
TAXONOMY_SCHEMA = {
    "name": "",               # 生态位名（如"野兽"）
    "type": "",               # 生态位类型标签（野兽/人形/亡灵/恶魔/元素/龙类/构装体/虫群/异星兽/机械体…）
    "description": "",        # 生态位整体特征
    "habitat_biomes": [],     # 常出没的区域类型（town/wild/dungeon/secret…）
    "level_range": [],        # 生态位内物种的常见等级区间 [min, max]
    "loot_materials": [],     # 该类共享的基础兽材/材料（每物种另有专属掉落）
    "behavior": "",           # 该类共性行为（群居/独行/领地意识/主动攻击…）
}

# 具体物种（生态册第二级：如 野兽→灰谷狼、暮色黑豹、岩石巨熊…）
SPECIES_SCHEMA = {
    "name": "",               # 物种名
    "taxonomy": "",           # 所属生态位名（关联 TAXONOMY_SCHEMA.name）
    "biome": "",              # 主要栖息区域类型（wild/dungeon/secret…）
    "habitat": "",            # 具体栖息地描述（如"暮色森林北部"）
    "level_range": [],        # 该物种等级区间 [min, max]
    "description": "",        # 外观/习性描述
    "habits": "",             # 行为习性（昼伏夜出/成群结队/领地意识…）
    "weakness": "",           # 弱点
    "drop_materials": [],     # 专属掉落材料（兽材，联动锻造）
}

# 资源（每块区域的可采集/锻造/交易材料）——万物皆可锻造的基础
RESOURCE_SCHEMA = {
    "name": "",            # 资源名（如"幽谷魔铁矿"）
    "type": "矿石",        # 矿石/草药/木材/石材/食物/魔力/遗迹/兽材/水源/其他
    "rarity": "common",    # common/uncommon/rare/epic/legendary
    "amount": "",          # 储量描述（如"中等储量"）
    "description": "",     # 用途/特征描述（可锻造/附魔/交易）
    "guard": "",           # 守护/伴生怪物名（关联本区 monsters，体现"资源与怪物关系"）
}

# 本地剧情/任务（每块区域可触发的小剧情，软任务——可选参与）
LOCAL_QUEST_SCHEMA = {
    "id": "",
    "title": "",
    "description": "",
    "giver": "",           # 发布者 NPC 名（关联本区 npcs）
    "objectives": [],      # [{"type":"kill/collect/visit/talk","target_keyword":"","count":1}]
    "rewards": {},         # {"exp":..,"gold":..,"items":[...]}
    "auto_complete": True,
}

# 元素关系（人/怪物/资源/势力/剧情 之间的关系，让区域像迷你世界一样自洽）
RELATIONSHIP_SCHEMA = {
    "from": "",            # 源元素名
    "from_type": "",       # npc/monster/faction/resource/quest
    "to": "",              # 目标元素名
    "to_type": "",         # npc/monster/faction/resource/quest
    "relation": "",        # 守护/控制/隶属/发布/敌对/依赖/交易/信仰/供养...
    "description": "",     # 一句话说明关系
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


def sanitize_monster(monster: Dict) -> Dict:
    """清洗一个怪物为标准结构，并保证掉落材料是数组"""
    if not isinstance(monster, dict):
        monster = {}
    monster = _apply_schema(monster, MONSTER_SCHEMA)
    monster["skills"] = _normalize_list(monster.get("skills"))
    monster["drop_materials"] = _split_material_names(monster.get("drop_materials"))
    monster["level"] = _to_int(monster.get("level"), 1)
    monster["hp"] = _to_int(monster.get("hp"), 50)
    monster["max_hp"] = _to_int(monster.get("max_hp"), monster["hp"])
    monster["attack_power"] = _to_int(monster.get("attack_power"), 5)
    monster["defense_power"] = _to_int(monster.get("defense_power"), 5)
    monster["exp_reward"] = _to_int(monster.get("exp_reward"), 20)
    monster["gold_reward"] = _to_int(monster.get("gold_reward"), 10)
    if monster.get("type") not in ("normal", "elite", "boss"):
        monster["type"] = "normal"
    return monster


def _split_material_names(value) -> list:
    """把掉落材料/共享材料拆成独立的材料名列表。

    LLM 常把多个材料写成含逗号的单字符串（如 "Shadow Pelt, Fang of the Pack"
    或 "兽皮, 兽牙, 兽骨"），会导致按名匹配失效。这里统一按中英文逗号拆开。
    """
    out = []
    for v in _normalize_list(value):
        if not isinstance(v, str):
            continue
        for piece in re.split(r"[，,]", v):
            piece = piece.strip()
            if piece:
                out.append(piece)
    return out


def sanitize_taxonomy(tax: Dict) -> Dict:
    """清洗一个生态位（生态册第一级）"""
    if not isinstance(tax, dict):
        tax = {}
    tax = _apply_schema(tax, TAXONOMY_SCHEMA)
    # LLM 常把生态位名称放进 type 字段而 name 为空 → 同步到 name（规范化）
    if not tax.get("name") and tax.get("type"):
        tax["name"] = tax["type"]
    tax["habitat_biomes"] = _normalize_list(tax.get("habitat_biomes"))
    tax["level_range"] = _normalize_list(tax.get("level_range"))
    tax["loot_materials"] = _split_material_names(tax.get("loot_materials"))
    return tax


def sanitize_species(sp: Dict) -> Dict:
    """清洗一个具体物种（生态册第二级）"""
    if not isinstance(sp, dict):
        sp = {}
    sp = _apply_schema(sp, SPECIES_SCHEMA)
    sp["level_range"] = _normalize_list(sp.get("level_range"))
    sp["drop_materials"] = _split_material_names(sp.get("drop_materials"))
    return sp


def _to_int(value, default: int = 0) -> int:
    """把可能为字符串的数字/文本转成 int"""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        return int(s) if s.isdigit() else default
    return default


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
    region["monsters"] = [sanitize_monster(m) for m in region.get("monsters", [])]
    region["npcs"] = _normalize_list(region.get("npcs"), NPC_SCHEMA)
    region["factions"] = _normalize_list(region.get("factions"))
    region["resources"] = _normalize_list(region.get("resources"), RESOURCE_SCHEMA)
    region["quests"] = _normalize_list(region.get("quests"), LOCAL_QUEST_SCHEMA)
    region["relationships"] = _normalize_list(region.get("relationships"), RELATIONSHIP_SCHEMA)
    # boss 可以是 None 或 dict
    if region.get("boss") is not None and not isinstance(region.get("boss"), dict):
        region["boss"] = None
    if not region.get("id"):
        import re
        region["id"] = re.sub(r"[^a-zA-Z0-9]+", "_", (region.get("name") or "region").lower()).strip("_") or "region"
    return region


# ────────────────────────────────
# 区域完整性兜底（让每块区域都是"迷你世界设定"）
# ────────────────────────────────

# ────────────────────────────────
# 生态册 → 区域怪物实例化（解决"怪物种类少"：从世界生态册按区域环境挑物种，保证多样性）
# ────────────────────────────────


def get_ecology(world_setting: Dict) -> tuple:
    """取出世界生态册：生态位名→生态位 映射 + 物种列表"""
    dangers = (world_setting or {}).get("dangers", {}) or {}
    taxonomies = dangers.get("monster_taxonomy", []) or []
    species = dangers.get("monster_species", []) or []
    tax_map = {}
    for t in taxonomies:
        if isinstance(t, dict) and (t.get("name") or t.get("type")):
            tax_map[t.get("name") or t.get("type")] = t
    return tax_map, [s for s in species if isinstance(s, dict)]


def _species_biome_score(sp: Dict, biome: str) -> int:
    """物种与区域类型的契合度：0=不匹配，越高越契合"""
    biome = (biome or "").lower()
    sp_biome = (sp.get("biome") or "").lower()
    if sp_biome and sp_biome == biome:
        return 3
    # 中英文别名模糊匹配
    aliases = {
        "wild": ["野外", "荒野", "森林", "草原", "wild", "forest", "grove"],
        "dungeon": ["地下城", "洞窟", "矿井", "副本", "dungeon", "cave", "mine"],
        "secret": ["隐秘", "秘境", "遗迹", "secret", "ruin"],
        "boss_lair": ["巢穴", "龙穴", "boss", "lair"],
    }
    for k, words in aliases.items():
        if biome == k and any(w in sp_biome for w in words):
            return 2
    # 栖息地文字模糊匹配（物种未写 biome 时兜底）
    habitat = (sp.get("habitat") or "").lower()
    if biome == "wild" and any(k in habitat for k in ["野", "林", "原", "山", "漠", "森"]):
        return 1
    return 0


def _level_for_species(sp: Dict, region_lo: int, region_hi: int) -> int:
    """物种实例化等级：优先取物种等级区间与区域等级的交叉段，避免低危区刷出高阶怪"""
    sp_range = [int(v) for v in (sp.get("level_range") or []) if isinstance(v, int) or (isinstance(v, str) and v.isdigit())]
    lo = max((sp_range[0] if sp_range else region_lo or 1), region_lo or 1)
    hi = min((sp_range[-1] if sp_range else region_hi or (region_lo or 1) + 2), region_hi or (region_lo or 1) + 2)
    if hi >= lo:
        return random.randint(lo, hi)
    return sp_range[0] if sp_range else max(1, region_lo or 1)


def instantiate_species(sp: Dict, taxonomy: Optional[Dict], level: int) -> Dict:
    """把一个物种实例化为带战斗数据的怪物（MONSTER_SCHEMA），掉落联动锻造"""
    level_scale = 1 + (level - 1) * 0.3
    hp = int(50 * level_scale)
    stats = {
        "strength": max(5, int(8 * level_scale)),
        "agility": max(5, int(7 * level_scale)),
        "intelligence": max(5, int(6 * level_scale)),
        "vitality": max(5, int(8 * level_scale)),
        "luck": max(1, int(5 * level_scale)),
    }
    # 掉落：物种专属兽材 + 所属生态位共享基础材料（万物皆可锻造）
    drop = list(sp.get("drop_materials") or [])
    if taxonomy:
        for m in (taxonomy.get("loot_materials") or []):
            if m not in drop:
                drop.append(m)
    return {
        "name": sp.get("name", "未知物种"),
        "level": level,
        "hp": hp,
        "max_hp": hp,
        "attack_power": stats["strength"] * 2,
        "defense_power": int(stats["vitality"] * 1.5),
        "exp_reward": int(30 * level_scale),
        "gold_reward": int(15 * level_scale),
        "stats": stats,
        "equipment": [],
        "skills": [],
        "type": "normal",
        "behavior": (taxonomy or {}).get("behavior", ""),
        "taxonomy": sp.get("taxonomy", ""),
        "species": sp.get("name", ""),
        "habitat": sp.get("habitat", ""),
        "weakness": sp.get("weakness", ""),
        "drop_materials": drop,
    }


def select_species_for_region(world_setting: Dict, biome: str, level_range: List[int], count: int = 3) -> List[Dict]:
    """从生态册挑选最契合该区域环境的 N 个物种并实例化（按契合度+等级匹配排序）"""
    tax_map, species = get_ecology(world_setting)
    if not species:
        return []
    lo, hi = (level_range or [None, None])
    lo = lo or 1
    hi = hi or (lo + 4)
    scored = []
    for sp in species:
        score = _species_biome_score(sp, biome)
        sp_range = [int(v) for v in (sp.get("level_range") or []) if isinstance(v, int) or (isinstance(v, str) and v.isdigit())]
        if sp_range:
            if sp_range[0] <= hi and sp_range[-1] >= lo:  # 等级区间与区域有交集
                score += 1
            if sp_range[0] <= lo <= sp_range[-1]:  # 区域起始等级落在物种区间内
                score += 1
        scored.append((score, sp))
    scored.sort(key=lambda x: -x[0])
    # 同契合度的物种随机打乱，避免不同区域永远刷同一批
    chosen = scored[: max(count * 2, 1)]
    random.shuffle(chosen)
    result = []
    for score, sp in chosen:
        if score <= 0:
            continue
        level = _level_for_species(sp, lo, hi)
        tax = tax_map.get(sp.get("taxonomy", ""))
        result.append(instantiate_species(sp, tax, level))
        if len(result) >= count:
            break
    return result


def _default_region_monsters(biome: str, lo: int, hi: int) -> List[Dict]:
    """生态册缺失时的主题兜底怪物（2种），保证野外/地下城区域不空"""
    theme = {
        "dungeon": [("洞穴巨蛛", "蛛丝"), ("暗影蝙蝠", "蝠翼")],
        "secret": [("秘境守卫", "秘晶碎片"), ("迷雾灵体", "灵气残片")],
        "boss_lair": [("巢穴精英", "龙鳞碎片"), ("巢穴爪牙", "兽牙")],
        "wild": [("荒原野狼", "狼牙"), ("丛林食人花", "花蜜结晶")],
    }
    names = theme.get(biome, theme["wild"])
    out = []
    for idx, (name, mat) in enumerate(names):
        level = lo + idx
        sp = {"name": name, "biome": biome, "drop_materials": [mat], "level_range": [lo, hi]}
        out.append(instantiate_species(sp, None, level))
    return out


def enrich_region_monsters(world_setting: Dict, region: Dict) -> List[Dict]:
    """用生态册补齐区域怪物：保留已有 LLM 怪物，缺额用生态册物种补足，保证物种多样化。
    城镇不刷怪；野外/地下城/隐秘/巢穴默认补到 2-4 种。"""
    biome = region.get("biome") or region.get("region_type") or "wild"
    if biome == "town":
        return region.get("monsters", []) or []
    lo, hi = region.get("level_range") or [None, None]
    if not lo:
        dl = region.get("danger_level") or 1
        lo, hi = max(1, dl * 3 - 2), dl * 3 + 2
    target = {"wild": 3, "dungeon": 4, "secret": 3, "boss_lair": 2}.get(biome, 2)
    existing = [m for m in (region.get("monsters") or []) if isinstance(m, dict) and m.get("name")]
    existing_names = {m["name"] for m in existing}
    need = target - len(existing)
    if need > 0:
        for m in select_species_for_region(world_setting, biome, [lo, hi], count=need + 1):
            if m["name"] in existing_names:
                continue
            existing.append(m)
            existing_names.add(m["name"])
            if len(existing) >= target:
                break
    if not existing:  # 生态册空且无已有怪物 → 主题兜底
        existing = _default_region_monsters(biome, lo, hi)
    return existing


def ensure_region_completeness(region: Dict, world_setting: Dict = None) -> Dict:
    """确保区域是完整的"迷你世界设定"：人/怪物/资源/势力/剧情齐全且互有关联。

    对 LLM 可能遗漏的部分用规则化模板兜底，保证任何区域都不会是空壳。
    在预设区域细化与动态空白区域生成后统一调用。
    """
    region = sanitize_region(region)
    biome = region.get("biome") or region.get("region_type") or ""
    rname = region.get("name", "此区域")

    # ── 人：城镇/村落必须有人 ──
    npcs = region.get("npcs", [])
    if biome == "town" and not npcs:
        npcs = [{
            "name": "当地村民", "role": "村民",
            "description": "世代居住于此的村民，熟悉本地的一切。",
            "faction_id": "", "is_key": False,
        }]
        region["npcs"] = npcs

    # ── 怪物：从世界生态册按区域环境挑物种补足（保证种类多样、掉落联动锻造）──
    # 保留 LLM 已生成的怪物，缺额用生态册物种补齐；无生态册时用主题兜底
    if world_setting:
        region["monsters"] = enrich_region_monsters(world_setting, region)

    # ── 资源：按区域类型/名字关键词兜底 ──
    if not region.get("resources"):
        region["resources"] = _default_region_resources(region)

    # ── 剧情：城镇/野外/地下城都应有本地小剧情 ──
    if not region.get("quests"):
        q = _default_region_quest(region, npcs)
        if q:
            region["quests"] = [q]

    # ── 关系：从已有元素自动推导（资源→守护怪物 / NPC→势力 / 剧情→发布者）──
    region["relationships"] = _derive_region_relationships(region)

    return region


def _default_region_resources(region: Dict) -> list:
    """按区域类型与名字关键词兜底 1-2 种资源"""
    biome = region.get("biome") or region.get("region_type") or ""
    rname = (region.get("name") or "").lower()
    if biome == "town":
        return [{
            "name": "本地特产", "type": "食物", "rarity": "common", "amount": "充足",
            "description": "城镇集市上的日常物资，可用于交易与烹饪。", "guard": "",
        }]
    pools = [
        (["矿", "石", "山", "峰", "mine", "rock", "mountain", "洞", "cave"],
         {"name": "矿脉矿石", "type": "矿石", "rarity": "common", "amount": "中等储量",
          "description": "可开采的普通矿石，是锻造的基础材料。", "guard": ""}),
        (["森", "林", "木", "翠", "forest", "wood", "grove"],
         {"name": "硬木", "type": "木材", "rarity": "common", "amount": "丰富",
          "description": "质地坚韧的木材，可用于制造与燃料。", "guard": ""}),
        (["湖", "河", "水", "海", "岸", "lake", "river", "water", "coast"],
         {"name": "淡水鱼群", "type": "食物", "rarity": "common", "amount": "充足",
          "description": "水域里的鱼群，可捕捞烹饪或交易。", "guard": ""}),
        (["冰", "雪", "寒", "glac", "ice", "snow"],
         {"name": "寒晶碎屑", "type": "魔力", "rarity": "uncommon", "amount": "少量",
          "description": "蕴含寒冰魔力的晶石碎屑，可作附魔材料。", "guard": ""}),
        (["沙", "漠", "荒", "desert", "sand", "waste"],
         {"name": "耐旱草药", "type": "草药", "rarity": "common", "amount": "零星分布",
          "description": "在干旱地带顽强生长的草药，可用于炼药。", "guard": ""}),
        (["废", "烬", "火", "熔", "ash", "ember", "fire", "volcano"],
         {"name": "余烬晶", "type": "矿石", "rarity": "rare", "amount": "少量",
          "description": "火焰之力凝成的晶石，可作高级附魔材料。", "guard": ""}),
        (["魔", "秘", "禁", "magic", "arcane", "forbid"],
         {"name": "魔力残渣", "type": "魔力", "rarity": "uncommon", "amount": "少量",
          "description": "魔力逸散留下的结晶，可用于炼金与附魔。", "guard": ""}),
    ]
    for keywords, res in pools:
        if any(k in rname for k in keywords):
            return [res]
    return [{
        "name": "野生材料", "type": "草药", "rarity": "common", "amount": "零星分布",
        "description": "散落在荒野的植物与矿物，可用于炼药、锻造与交易。", "guard": "",
    }]


def _default_region_quest(region: Dict, npcs: list) -> dict:
    """按区域类型兜底一个本地小剧情"""
    biome = region.get("biome") or region.get("region_type") or ""
    rname = region.get("name", "此区域")
    giver = npcs[0].get("name") if npcs else "当地居民"
    if biome == "town":
        return {
            "title": "本地的小麻烦", "giver": giver,
            "description": f"{giver}遇到了点麻烦，需要一位路过的冒险者搭把手，报酬谈好就开工。",
            "objectives": [], "rewards": {"exp": 30, "gold": 20}, "auto_complete": True,
        }
    return {
        "title": f"{rname}的传闻", "giver": giver,
        "description": f"附近流传着关于{rname}的传闻，似乎藏着不为人知的秘密或财宝。",
        "objectives": [], "rewards": {"exp": 25, "gold": 15}, "auto_complete": True,
    }


def _derive_region_relationships(region: Dict) -> list:
    """从区域已有元素自动推导关系，补齐 LLM 未显式声明但客观存在的关系"""
    rels = list(region.get("relationships") or [])
    npc_names = [n.get("name", "") for n in region.get("npcs", []) if n.get("name")]
    monster_names = [m.get("name", "") for m in region.get("monsters", []) if m.get("name")]
    resource_names = [r.get("name", "") for r in region.get("resources", []) if r.get("name")]

    def _has(a, b):
        return any((r.get("from") == a and r.get("to") == b) or
                   (r.get("from") == b and r.get("to") == a) for r in rels)

    # 资源 ← 守护怪物
    for r in region.get("resources", []):
        guard = r.get("guard", "")
        if guard and guard in monster_names and not _has(guard, r.get("name", "")):
            rels.append({
                "from": guard, "from_type": "monster", "to": r.get("name", ""),
                "to_type": "resource", "relation": "守护",
                "description": f"{guard}盘踞在{r.get('name','')}附近，想采集先得过它这关。",
            })
    # 资源 ← 怪物伴生（无显式守护者时，用首个怪物建立"出没"关系，保证资源与怪物挂钩）
    for r in region.get("resources", []):
        rname = r.get("name", "")
        if not rname or rname not in resource_names:
            continue
        if any(x.get("to") == rname and x.get("to_type") == "resource" for x in rels):
            continue
        if monster_names and not _has(monster_names[0], rname):
            rels.append({
                "from": monster_names[0], "from_type": "monster", "to": rname,
                "to_type": "resource", "relation": "出没",
                "description": f"{monster_names[0]}常在{rname}附近出没，采集时要小心。",
            })
    # NPC → 势力
    for n in region.get("npcs", []):
        fid = n.get("faction_id", "")
        if fid and not _has(n.get("name", ""), fid):
            rels.append({
                "from": n.get("name", ""), "from_type": "npc", "to": fid,
                "to_type": "faction", "relation": "隶属",
                "description": f"{n.get('name','')}隶属于势力『{fid}』。",
            })
    # 剧情 → 发布者 NPC
    for q in region.get("quests", []):
        giver = q.get("giver", "")
        if giver and giver in npc_names and not _has(giver, q.get("title", "")):
            rels.append({
                "from": giver, "from_type": "npc", "to": q.get("title", ""),
                "to_type": "quest", "relation": "发布",
                "description": f"{giver}发布了剧情『{q.get('title','')}』。",
            })
    # 剧情兜底：无NPC发布者时，把剧情挂到首资源/首怪物上，保证剧情与区域元素挂钩
    for q in region.get("quests", []):
        qtitle = q.get("title", "")
        if not qtitle:
            continue
        if any(x.get("to") == qtitle and x.get("to_type") == "quest" for x in rels):
            continue
        if resource_names and not _has(resource_names[0], qtitle):
            rels.append({
                "from": resource_names[0], "from_type": "resource", "to": qtitle,
                "to_type": "quest", "relation": "关联",
                "description": f"剧情『{qtitle}』与{resource_names[0]}的来龙去脉有关。",
            })
        elif monster_names and not _has(monster_names[0], qtitle):
            rels.append({
                "from": monster_names[0], "from_type": "monster", "to": qtitle,
                "to_type": "quest", "relation": "敌对",
                "description": f"剧情『{qtitle}』与{monster_names[0]}的威胁息息相关。",
            })
    return rels


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
