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
