"""
世界观管理模块 — 加载、切换、注入世界观设定

核心逻辑：
- 现代世界（modern）是默认主题，不可删除，其角色卡/事件库保持原有结构
- 其他世界观（fantasy/scifi/...）的设定从 worlds/<world_id>/world_setting.json 加载
- generator 调用时自动注入世界观 context，LLM 生成内容自然贴合世界观
"""
import json
from pathlib import Path
from typing import Optional, Dict

WORLDS_DIR = Path(__file__).parent / "worlds"
WORLD_TEMPLATE = WORLDS_DIR / "world_setting_template.json"

# 现代世界的特殊标记
MODERN_WORLD = "modern"


def get_worlds_dir() -> Path:
    """获取 worlds 数据目录（用户创建的世界存放在 simlife/data/worlds/）"""
    data_dir = Path(__file__).parent.parent / "data" / "worlds"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def list_available_worlds() -> list:
    """列出所有可用世界观"""
    worlds = [{"world_id": MODERN_WORLD, "world_name": "现代世界（默认）", "world_type": "modern"}]

    # 扫描用户创建的世界
    data_dir = get_worlds_dir()
    if data_dir.exists():
        for d in sorted(data_dir.iterdir()):
            if d.is_dir():
                setting_file = d / "world_setting.json"
                if setting_file.exists():
                    try:
                        with open(setting_file, "r", encoding="utf-8") as f:
                            s = json.load(f)
                        worlds.append({
                            "world_id": s.get("world_id", d.name),
                            "world_name": s.get("world_name", d.name),
                            "world_type": s.get("world_type", "custom"),
                        })
                    except Exception:
                        worlds.append({
                            "world_id": d.name,
                            "world_name": d.name + "（加载失败）",
                            "world_type": "custom",
                        })

    return worlds


def get_current_world_id() -> str:
    """获取当前选择的世界观 ID"""
    from simlife.backend.main import DATA_DIR
    config_path = DATA_DIR / "simlife_config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f).get("world_id", MODERN_WORLD)
        except Exception:
            pass
    return MODERN_WORLD


def set_current_world(world_id: str):
    """切换当前世界观"""
    from simlife.backend.main import DATA_DIR
    config_path = DATA_DIR / "simlife_config.json"
    config = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass
    config["world_id"] = world_id
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_world_setting(world_id: str = None) -> Optional[Dict]:
    """
    加载世界观设定，返回字典或 None。
    world_id=None 时使用当前选择的世界。
    现代世界返回 None（使用原有逻辑）。
    """
    if world_id is None:
        world_id = get_current_world_id()

    if world_id == MODERN_WORLD:
        return None

    # 在用户数据目录查找
    setting_file = get_worlds_dir() / world_id / "world_setting.json"
    if setting_file.exists():
        try:
            with open(setting_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_world_setting(world_id: str, setting: Dict):
    """保存世界观设定到用户数据目录"""
    world_dir = get_worlds_dir() / world_id
    world_dir.mkdir(parents=True, exist_ok=True)
    with open(world_dir / "world_setting.json", "w", encoding="utf-8") as f:
        json.dump(setting, f, ensure_ascii=False, indent=2)

    # 如果该世界有专属事件库，也保存
    if "events" in setting:
        event_lib_path = world_dir / "event_library.json"
        with open(event_lib_path, "w", encoding="utf-8") as f:
            json.dump(setting["events"], f, ensure_ascii=False, indent=2)


def build_world_context(world_setting: Dict, max_length: int = 4000) -> str:
    """
    将世界观设定压缩成一段 context 文本，注入到 LLM prompt 中。
    控制在 max_length 字符以内，优先保留核心信息。
    """
    if not world_setting:
        return ""

    parts = []

    # 基础信息
    name = world_setting.get("world_name", "")
    wtype = world_setting.get("world_type", "")
    era = world_setting.get("era", "")
    parts.append(f"【世界观：{name}】类型：{wtype} | 时代：{era}")

    # 地理概要
    geo = world_setting.get("geography", {})
    if geo.get("overview"):
        parts.append(f"\n【地理】{geo['overview'][:500]}")
    regions = geo.get("regions", [])
    if regions:
        region_names = "、".join([r.get("name", "") for r in regions[:8]])
        parts.append(f"主要区域：{region_names}")

    # 力量体系
    ps = world_setting.get("power_system", {})
    if ps:
        ps_name = ps.get("name", "")
        ps_desc = ps.get("description", "")[:300]
        ps_levels = "、".join([l.get("name", "") for l in ps.get("levels", [])[:6]])
        parts.append(f"\n【力量体系：{ps_name}】{ps_desc}\n等级：{ps_levels}")

    # 种族
    races = world_setting.get("races", [])
    if races:
        race_list = "；".join([f"{r.get('name','')}（{r.get('average_lifespan','')}）" for r in races[:5]])
        parts.append(f"\n【种族】{race_list}")

    # 势力
    factions = world_setting.get("factions", [])
    if factions:
        faction_list = "；".join([f"{f.get('name','')}（{f.get('type','')}）" for f in factions[:5]])
        parts.append(f"\n【主要势力】{faction_list}")

    # 当前局势
    history = world_setting.get("history", {})
    if history.get("current_situation"):
        parts.append(f"\n【当前局势】{history['current_situation'][:400]}")

    # 日常生活
    daily = world_setting.get("daily_life", {})
    if daily:
        daily_parts = []
        if daily.get("currency", {}).get("name"):
            daily_parts.append(f"货币：{daily['currency']['name']}")
        if daily.get("transportation"):
            daily_parts.append(f"交通：{'、'.join(daily['transportation'][:4])}")
        if daily.get("entertainment"):
            daily_parts.append(f"娱乐：{'、'.join(daily['entertainment'][:4])}")
        if daily_parts:
            parts.append(f"\n【日常生活】{' | '.join(daily_parts)}")

    # 危险与副本
    dangers = world_setting.get("dangers", {})
    dungeons = dangers.get("dungeons", [])
    if dungeons:
        dungeon_list = "、".join([f"{d.get('name','')}({d.get('difficulty','')})" for d in dungeons[:5]])
        parts.append(f"\n【副本/地下城】{dungeon_list}")

    context = "\n".join(parts)

    # 截断
    if len(context) > max_length:
        context = context[:max_length] + "\n...(设定过长已截断)"

    return context


def build_character_guide(world_setting: Dict) -> str:
    """提取角色生成引导"""
    if not world_setting:
        return ""
    guide = world_setting.get("character_generation_guide", "")
    if guide:
        return f"\n\n【世界观角色生成引导】{guide}"

    # 自动生成简单引导
    name = world_setting.get("world_name", "这个世界")
    wtype = world_setting.get("world_type", "")
    power = world_setting.get("power_system", {}).get("name", "")
    ps = ""
    if power:
        levels = "、".join([l.get("name", "") for l in world_setting.get("power_system", {}).get("levels", [])[:4]])
        ps = f"\n力量体系：{power}，等级：{levels}"
    factions = world_setting.get("factions", [])
    faction_hint = ""
    if factions:
        faction_hint = f"\n可能加入的组织：{'、'.join([f.get('name', '') for f in factions[:4]])}"

    # 现世超武特殊引导
    if wtype == "modern_power":
        return f"\n\n【世界观角色生成引导】角色生活在「{name}」— 一个现代社会中隐藏着超能力者的世界。{ps}{faction_hint}\n角色卡应保留现代社会的字段结构（城市、通勤、日常作息等），但职业和日常活动要融入超能力元素。角色可能表面上是个普通上班族/学生，实际拥有异能或武道修为。"

    return f"\n\n【世界观角色生成引导】角色生活在「{name}」中。{ps}{faction_hint}\n角色卡的字段应适应这个世界观（如职业改为魔法师/战士/冒险者等）。"


def build_activity_guide(world_setting: Dict) -> str:
    """提取活动描述引导"""
    if not world_setting:
        return ""
    guide = world_setting.get("activity_generation_guide", "")
    if guide:
        return f"\n\n【世界观活动引导】{guide}"

    name = world_setting.get("world_name", "")
    wtype = world_setting.get("world_type", "")

    # 现世超武特殊引导
    if wtype == "modern_power":
        return f"\n\n【世界观活动引导】活动描述要符合「{name}」的世界观 — 现代社会+超能力。角色可能在正常上班/上学的同时，暗中修炼异能、执行秘密任务、与异能组织接触。活动描述可以包含现代元素（地铁、手机、咖啡店等），但要自然融入超能力相关内容。"

    return f"\n\n【世界观活动引导】活动描述要符合「{name}」的世界观设定。不要出现现代城市元素（如地铁、手机、咖啡店等），替换为该世界对应的行为和场景。"


def build_event_guide(world_setting: Dict) -> str:
    """提取事件生成引导"""
    if not world_setting:
        return ""
    guide = world_setting.get("event_generation_guide", "")
    if guide:
        return f"\n\n【世界观事件引导】{guide}"

    name = world_setting.get("world_name", "")
    wtype = world_setting.get("world_type", "")
    dangers = world_setting.get("dangers", {})
    dungeon_names = [d.get("name", "") for d in dangers.get("dungeons", [])]
    faction_names = [f.get("name", "") for f in world_setting.get("factions", [])]

    # 现世超武特殊引导
    if wtype == "modern_power":
        hints = []
        if faction_names:
            hints.append(f"组织相关：{'、'.join(faction_names[:3])}的秘密行动、任务委托")
        hints.append("异能失控事件、地下势力冲突、暗中修炼突破、超能力相关意外")
        hints.append("日常生活事件（工作、社交等），偶尔穿插超能力元素")
        return f"\n\n【世界观事件引导】角色生活在「{name}」中。{'; '.join(hints)}。事件可以包含现代生活元素，但要自然融入超能力维度。不要让超能力事件太过频繁，大部分时间角色还是过着正常的现代生活。"

    hints = []
    if dungeon_names:
        hints.append(f"可能的冒险：攻略{'、'.join(dungeon_names[:3])}")
    if faction_names:
        hints.append(f"组织相关：{'、'.join(faction_names[:3])}的任务或活动")
    hints.append("日常探索、修炼、社交、经商等")

    return f"\n\n【世界观事件引导】角色生活在「{name}」中。{'; '.join(hints)}。事件要符合世界观，不要出现现代元素。"


# ============================================================
# 区域文件化存储（每个区域一个独立 JSON + 跨区域关系文件）
# ============================================================
# 目录结构：
#   simlife/data/worlds/<world_id>/
#   ├── world_setting.json     # 核心世界观（元信息 + 全局概述）
#   ├── relations.json         # 跨区域关系（势力据点/跨区域剧情/人物行踪）
#   └── regions/
#       ├── <region_id>.json   # 每个区域独立设定（地理/气候/地点/怪物/NPC/势力据点）
#       └── ...


def get_region_dir(world_id: str) -> Path:
    """获取某世界的区域数据目录"""
    region_dir = get_worlds_dir() / world_id / "regions"
    region_dir.mkdir(parents=True, exist_ok=True)
    return region_dir


def _slugify(name: str) -> str:
    """将区域名转为安全的文件 id（英文小写下划线）"""
    import re
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s or "region"


def load_region(world_id: str, region_id: str) -> Optional[Dict]:
    """加载单个区域的设定。region_id 可为区域名或文件 id，自动匹配。"""
    if not region_id:
        return None
    region_dir = get_region_dir(world_id)
    # 优先按 id 直接匹配
    candidates = [
        region_dir / f"{region_id}.json",
        region_dir / f"{_slugify(region_id)}.json",
    ]
    # 再按名称模糊匹配
    if not any(c.exists() for c in candidates):
        slug = _slugify(region_id)
        for f in region_dir.glob("*.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    r = json.load(fh)
                if (r.get("id") or _slugify(r.get("name", ""))) == slug or \
                   (r.get("name", "").lower() == (region_id or "").lower()):
                    return r
            except Exception:
                continue
        return None
    file = next((c for c in candidates if c.exists()), None)
    if not file:
        return None
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_region(world_id: str, region: Dict) -> str:
    """保存区域设定到独立 JSON 文件，返回区域文件 id（自动用标准 schema 清洗）"""
    if not region:
        return ""
    try:
        from simlife.backend import world_schema
        region = world_schema.sanitize_region(region)
    except Exception:
        pass
    region_id = region.get("id") or _slugify(region.get("name", ""))
    region["id"] = region_id
    region_dir = get_region_dir(world_id)
    with open(region_dir / f"{region_id}.json", "w", encoding="utf-8") as f:
        json.dump(region, f, ensure_ascii=False, indent=2)
    return region_id


def list_regions(world_id: str) -> list:
    """列出某世界的所有区域（含每个区域的基础信息）"""
    region_dir = get_worlds_dir() / world_id / "regions"
    if not region_dir.exists():
        return []
    out = []
    for f in sorted(region_dir.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                r = json.load(fh)
            out.append({
                "id": r.get("id", f.stem),
                "name": r.get("name", f.stem),
                "description": r.get("description", ""),
                "climate": r.get("climate", ""),
            })
        except Exception:
            continue
    return out


def get_relations_path(world_id: str) -> Path:
    """跨区域关系文件路径"""
    return get_worlds_dir() / world_id / "relations.json"


def load_relations(world_id: str) -> Dict:
    """加载跨区域关系文件（势力据点/跨区域剧情/人物行踪）"""
    path = get_relations_path(world_id)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_relations(world_id: str, relations: Dict):
    """保存跨区域关系文件（自动用标准 schema 清洗）"""
    try:
        from simlife.backend import world_schema
        relations = world_schema.sanitize_relations(relations)
    except Exception:
        pass
    with open(get_relations_path(world_id), "w", encoding="utf-8") as f:
        json.dump(relations, f, ensure_ascii=False, indent=2)


def build_region_context(region: Dict, world_setting: Dict = None, relations: Dict = None) -> str:
    """
    将单个区域的完整设定压缩成一段 context 文本，用于 LLM 注入。
    区域驱动：玩家到哪个区域就注入该区域文件里的完整本地设定。
    """
    if not region:
        return ""
    parts = []
    rname = region.get("name", "未知区域")
    parts.append(f"【当前区域：{rname}】")

    desc = region.get("description", "")
    climate = region.get("climate", "")
    if desc:
        parts.append(f"环境：{desc[:260]}")
    if climate:
        parts.append(f"气候：{climate[:100]}")

    key_locs = region.get("key_locations", [])
    if key_locs:
        parts.append(f"关键地点：{'、'.join(key_locs[:5])}")

    # 本区危险/怪物（含特性）
    dangers = region.get("dangers", [])
    if dangers:
        names = []
        for d in dangers[:4]:
            if isinstance(d, dict):
                names.append(d.get("name", str(d)))
            else:
                names.append(str(d))
        parts.append(f"本区危险：{'、'.join(names)}")

    # 本区 NPC（标准 NPC 卡；无则按区域特征动态派生）
    npcs = region.get("npcs", [])
    if npcs:
        npc_desc = []
        for n in npcs[:4]:
            if isinstance(n, dict):
                npc_desc.append(f"{n.get('name','?')}（{n.get('role', n.get('description',''))}）")
            else:
                npc_desc.append(str(n))
        parts.append(f"本区人物：{'；'.join(npc_desc)}")
    else:
        derived = _derive_region_npcs(region, world_setting)
        if derived:
            parts.append(f"本区人物：{'；'.join(derived)}")

    # 本区驻留势力（跨区域关系 + 势力理念）
    region_faction_ids = region.get("factions", [])
    if world_setting:
        factions = world_setting.get("factions", [])
        # 若区域未显式标势力，尝试从 relations 推断
        if not region_faction_ids:
            region_faction_ids = _infer_region_factions(region, world_setting)
        for fid in region_faction_ids[:3]:
            for f in factions:
                if isinstance(f, dict) and (f.get("id") == fid or _slugify(f.get("name", "")) == fid):
                    parts.append(
                        f"势力『{f.get('name','?')}』：{str(f.get('ideology') or f.get('description') or '')[:120]}"
                        f"{'，领袖：' + str(f.get('leader')) if f.get('leader') else ''}"
                    )
                    break

    return "\n".join(parts)


def _derive_region_npcs(region: Dict, world_setting: Dict = None) -> list:
    """基于区域特征动态派生本区 NPC（不额外调 LLM，规则化生成）"""
    rname = (region.get("name") or "").lower()
    key_locs = region.get("key_locations", [])
    locs_str = "，".join(key_locs[:3]) if key_locs else region.get("name", "此区域")

    # 优先取一个势力作为本地驻军/联络人
    main_faction = "当地势力"
    if world_setting:
        factions = world_setting.get("factions", [])
        inferred = _infer_region_factions(region, world_setting)
        for fid in inferred[:1]:
            for f in factions:
                if isinstance(f, dict) and (f.get("id") == fid or _slugify(f.get("name", "")) == fid):
                    main_faction = f.get("name", "当地势力")
                    break

    npcs = []
    if "forest" in rname or "wood" in rname or "magic" in rname or "vale" in rname:
        npcs.append(f"{main_faction}在此镇守的队长")
        npcs.append(f"{locs_str}的本地猎人/药师")
    elif "water" in rname or "lake" in rname or "river" in rname or "iron" in rname or "coast" in rname:
        npcs.append(f"{main_faction}在港口/矿区的管事")
        npcs.append(f"{locs_str}的船夫/矿工")
    elif "high" in rname or "wind" in rname or "sky" in rname or "peak" in rname or "mount" in rname:
        npcs.append(f"{main_faction}在高地据点的观察员")
        npcs.append(f"{locs_str}的山地向导")
    elif "shadow" in rname or "dark" in rname or "waste" in rname or "glac" in rname:
        npcs.append(f"{main_faction}潜伏在此的密探")
        npcs.append(f"{locs_str}的守夜人")
    elif "thorn" in rname or "wall" in rname:
        npcs.append(f"{main_faction}在边陲的戍卫队长")
        npcs.append(f"{locs_str}的巡逻兵")
    else:
        npcs.append(f"{locs_str}的{main_faction}联络人")
        npcs.append(f"{locs_str}的本地旅店老板")

    return npcs[:3]


def _infer_region_factions(region: Dict, world_setting: Dict) -> list:
    """从势力描述中推断该区域关联的势力 id（按区域名/地点名匹配）"""
    if not world_setting:
        return []
    factions = world_setting.get("factions", [])
    if not factions:
        return []
    region_text = (region.get("name") or "") + " " + " ".join(region.get("key_locations", []))
    region_text = region_text.lower()
    found = []
    for f in factions:
        if not isinstance(f, dict):
            continue
        fname = f.get("name") or ""
        if not fname:
            continue  # 无名势力跳过
        fid = f.get("id") or _slugify(fname)
        if not fid or fid == "faction":
            continue  # id 无效则跳过
        desc = str(f.get("description", "")) + " " + str(f.get("ideology", ""))
        # 势力描述里提到区域名 → 关联
        if any(w in desc.lower() for w in [region.get("name", "").lower()] if w):
            found.append(fid)
            continue
        # 势力的 base/location 字段直接指定区域
        fbase = str(f.get("base_region", "") or f.get("location", "") or f.get("base", "")).lower()
        if fbase and (fbase in region_text or region.get("name", "").lower() in fbase):
            found.append(fid)
    return found[:3]


def build_relations_context(relations: Dict, current_region_id: str = "") -> str:
    """
    构建跨区域关系 context（势力据点 / 跨区域剧情 / 人物行踪）。
    只注入与当前区域相关 + 全局重要关联，避免超长。
    """
    if not relations:
        return ""
    parts = []

    # 跨区域势力据点
    faction_presence = relations.get("faction_presence", {})
    if faction_presence:
        items = []
        for fid, regions in faction_presence.items():
            if isinstance(regions, list) and regions:
                items.append(f"{fid}在{'、'.join(regions[:3])}")
        if items:
            parts.append(f"跨区域势力：{'；'.join(items[:6])}")

    # 跨区域剧情线
    storylines = relations.get("storylines", [])
    if storylines:
        lines = []
        for s in storylines[:3]:
            if isinstance(s, dict):
                if current_region_id and s.get("regions") and current_region_id not in s.get("regions", []):
                    continue
                lines.append(f"{s.get('name','')}：{str(s.get('description',''))[:100]}")
        if lines:
            parts.append(f"跨区域剧情：{'；'.join(lines)}")

    # 跨区域人物行踪
    characters = relations.get("characters", [])
    if characters:
        chars = []
        for c in characters[:3]:
            if isinstance(c, dict):
                if current_region_id and c.get("current_region") and c["current_region"] != current_region_id:
                    continue
                chars.append(f"{c.get('name','?')}（{c.get('role', c.get('description',''))}）")
        if chars:
            parts.append(f"跨区域人物：{'；'.join(chars)}")

    return "\n".join(parts)


def migrate_world_to_region_files(world_id: str) -> dict:
    """
    将旧版单文件 world_setting.json 迁移为：
      regions/<region_id>.json  每个区域独立文件
      relations.json            跨区域关系文件（势力据点/跨区域剧情）
    返回迁移统计。
    """
    result = {"regions_migrated": 0, "relations_built": False, "errors": []}
    setting = load_world_setting(world_id)
    if not setting:
        result["errors"].append("world_setting.json 不存在或加载失败")
        return result

    geo = setting.get("geography", {})
    regions = geo.get("regions", [])
    if not regions:
        result["errors"].append("world_setting 中没有 regions")
        return result

    # 1. 每个区域写独立文件
    region_map = {}
    for r in regions:
        if not isinstance(r, dict):
            continue
        rid = save_region(world_id, r)
        region_map[rid] = r.get("name", rid)
        result["regions_migrated"] += 1

    # 2. 生成跨区域关系文件
    relations = {}
    # 势力据点：根据已有 factions 推断（每个势力可能跨多区域，这里尽量从数据推断）
    # 若 factions 有 presence/regions 字段则用之，否则留空由后续扩展填充
    factions = setting.get("factions", [])
    faction_presence = {}
    for f in factions:
        if not isinstance(f, dict):
            continue
        fname = f.get("name", "")
        # 势力名转区域id关键词
        fid = _slugify(fname)
        # 尝试从势力描述推断活动区域（关键词匹配区域名）
        desc = str(f.get("description", "")) + " " + str(f.get("ideology", ""))
        linked = []
        for rid, rname in region_map.items():
            if rname.lower() in desc.lower():
                linked.append(rid)
        if linked:
            faction_presence[fid] = linked
    relations["faction_presence"] = faction_presence
    relations["storylines"] = []
    relations["characters"] = []
    save_relations(world_id, relations)
    result["relations_built"] = True

    # 3. 更新 world_setting.json：保留全局概述，去掉已迁移的区域明细（避免冗余）
    geo.pop("regions", None)
    save_world_setting(world_id, setting)

    return result


def repair_relations(world_id: str) -> dict:
    """修复跨区域关系文件：
    - 清理错误的据点 id（如 'region' 这种 slugify 默认值）
    - 势力有 base_region/regions 字段时重建正确据点
    """
    result = {"removed_bad": [], "rebuilt": 0}
    setting = load_world_setting(world_id)
    relations = load_relations(world_id)

    if not relations:
        return result

    # 1. 清理错误据点 id（非法值）
    presence = relations.get("faction_presence", {})
    bad_ids = ["region", "faction", "", None]
    for fid in list(presence.keys()):
        if fid in bad_ids or not isinstance(fid, str):
            result["removed_bad"].append(fid)
            presence.pop(fid, None)

    # 2. 基于势力数据的 base_region_id/regions 重建据点
    if setting:
        factions = setting.get("factions", [])
        regions = list_regions(world_id)
        region_ids = {r["id"] for r in regions}
        for f in factions:
            if not isinstance(f, dict):
                continue
            fname = f.get("name") or ""
            if not fname:
                continue
            fid = f.get("id") or _slugify(fname)
            if fid in bad_ids:
                continue
            # 收集该势力的据点：regions 字段 > base_region_id > 描述匹配
            linked = set(presence.get(fid, []) or [])
            for r in (f.get("regions") or []):
                if r in region_ids:
                    linked.add(r)
            base = f.get("base_region_id") or f.get("base_region") or f.get("location") or ""
            if base and base in region_ids:
                linked.add(base)
            # 描述关键词匹配
            desc = str(f.get("description", "")) + " " + str(f.get("ideology", ""))
            for r in regions:
                if r["name"].lower() and r["name"].lower() in desc.lower():
                    linked.add(r["id"])
            if linked:
                presence[fid] = sorted(linked)
                result["rebuilt"] += 1

    relations["faction_presence"] = presence
    save_relations(world_id, relations)
    return result


def refine_existing_regions(world_id: str) -> dict:
    """为已有世界的所有区域生成专属 NPC + 威胁怪物 + 势力据点（调用 LLM）。
    用于初次生成后的细化，或手动刷新已有世界。
    """
    try:
        from simlife.backend.generator import _refine_region_details
    except ImportError:
        return {"error": "无法导入 generator._refine_region_details"}

    setting = load_world_setting(world_id)
    if not setting:
        return {"error": "world_setting 不存在"}

    _refine_region_details(setting, world_id)
    # 重建 relations
    repair_relations(world_id)
    return {"refined": True, "regions": len(list_regions(world_id))}
