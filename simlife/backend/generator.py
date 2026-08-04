"""
AI 生成器 - 生成人物卡 + NPC卡 + Activity描述 + 事件队列
支持多种工作模式：上班族 / 自由职业 / 学生 / 旅行博主
支持多世界观：现代世界（默认）+ 自定义世界（fantasy/scifi/...）
"""
import json
import random
import sys
from pathlib import Path

# 复用主项目的 LLM 客户端
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from engine.llm_client import create_client


def _strip_controls_json(s: str) -> str:
    """清理 JSON 中的控制字符（保持引号内语义）"""
    import re as _re_sj
    def fix_string(m):
        inner = m.group(1)
        inner = inner.replace('\t', ' ').replace('\n', '\\n').replace('\r', '')
        return '"' + inner + '"'
    return _re_sj.sub(r'"((?:[^"\\]|\\.)*)"', fix_string, s)


def _repair_json(text: str) -> str:
    """尽力修复 LLM 输出中的常见 JSON 语法错误（保守、不误伤）"""
    import re as _re_rj
    s = text
    # 1. 去掉代码块围栏 ```json ... ```
    s = _re_rj.sub(r'```(?:json)?', '', s)
    # 2. 去掉尾随逗号（对象和数组内）
    s = _re_rj.sub(r',(\s*[}\]])', r'\1', s)
    # 3. 把单引号字符串转双引号（只处理简单无转义情况）
    s = _re_rj.sub(r"(?<!\\)'([^'\\]*)'(?=\s*[,:}\]])", r'"\1"', s)
    # 4. 保守补缺逗号：
    #    a) 值后紧跟下一个键：闭合括号/数字/布尔/null 后跟引号 → "a":1 "b" → "a":1, "b"
    s = _re_rj.sub(r'([}\]0-9truefalsenul])(\s*)("(?![:\s]))', r'\1,\2\3', s)
    #    b) 对象/数组后跟对象/数组：} {、] [、} [、] { → 补逗号
    s = _re_rj.sub(r'([}\]](?:\s*))([\[\{](?!\s*[,:\}]))', r'\1,\2', s)
    #    c) 相邻字符串：字符串值后紧跟另一个字符串键（非冒号前） → "a" "b" → "a", "b"
    s = _repair_adjacent_strings(s)
    # 5. 提取第一个 JSON 对象/数组（若前后有杂文本）
    match = _re_rj.search(r'[\{\[][\s\S]*[\}\]]', s)
    if match:
        s = match.group(0)
    return s


def _repair_adjacent_strings(s: str) -> str:
    """用字符扫描修复相邻字符串缺逗号：'值'后紧跟'"'(新键开头)时补逗号。
    只处理成对匹配的字符串，避免误伤冒号/逗号后的正常结构。
    """
    out = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == '"':
            # 找字符串结束
            j = i + 1
            while j < n:
                if s[j] == '\\':
                    j += 2
                    continue
                if s[j] == '"':
                    break
                j += 1
            if j >= n:
                # 未闭合，直接追加剩余
                out.append(s[i:])
                break
            # 完整字符串 s[i:j+1]
            out.append(s[i:j+1])
            k = j + 1
            # 跳过空白
            while k < n and s[k] in ' \t\r\n':
                k += 1
            # 如果后面紧跟 '"'（新字符串），且前面不是 ':' 或 ','，则补逗号
            if k < n and s[k] == '"':
                # 检查这个字符串是否前面是冒号(即它是键) — 通过看 i 前面一个非空白字符判断
                prev = _last_non_space(out)
                if prev not in (':', ',', '[', '{'):
                    out.append(',')
            i = k
        else:
            out.append(ch)
            i += 1
    return ''.join(out)


def _last_non_space(parts: list) -> str:
    """取已输出部分的最后一个非空白字符（用于判断上下文）"""
    for p in reversed(parts):
        if p is None:
            continue
        if isinstance(p, str):
            for c in reversed(p):
                if c not in ' \t\r\n':
                    return c
    return ''


def _safe_json_loads(text: str):
    """安全解析JSON：清理控制字符 + 修复常见语法错误 + 提取JSON块
    依次尝试：直接解析 → 控制字符清理 → 语法修复 → 正则提取
    """
    import re as _re_sj
    if not text or not isinstance(text, str):
        raise ValueError("空或非字符串的JSON输入")

    def _try_load(s):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    # 1. 直接解析
    r = _try_load(text)
    if r is not None:
        return r

    # 2. 清理控制字符后解析
    cleaned = _strip_controls_json(text)
    r = _try_load(cleaned)
    if r is not None:
        return r

    # 3. 语法修复（尾随逗号/缺逗号/单引号/围栏/杂文本）
    repaired = _repair_json(cleaned)
    r = _try_load(repaired)
    if r is not None:
        return r

    # 4. 修复后再清一次控制字符
    r = _try_load(_strip_controls_json(repaired))
    if r is not None:
        return r

    # 5. 正则提取 JSON 块
    match = _re_sj.search(r'[\{\[][\s\S]*[\}\]]', text)
    if match:
        r = _try_load(match.group(0))
        if r is not None:
            return r
        r = _try_load(_repair_json(match.group(0)))
        if r is not None:
            return r

    raise json.JSONDecodeError("无法修复的JSON", text, 0)


def _get_world_context() -> str:
    """获取当前世界观的 context 文本，现代世界返回空字符串"""
    try:
        from simlife.worlds.world_manager import load_world_setting, build_world_context
        ws = load_world_setting()
        if ws:
            return build_world_context(ws)
    except Exception:
        pass
    return ""


def _get_story_influences() -> str:
    """读取用户聊天中对剧情的影响信息"""
    try:
        from engine.simlife_client import SimLifeClient
        sl = SimLifeClient()
        return sl.get_story_influences()
    except Exception:
        return ""


def _get_world_guide(guide_type: str = "character") -> str:
    """获取世界观的生成引导（character/activity/event）"""
    try:
        from simlife.worlds.world_manager import load_world_setting
        ws = load_world_setting()
        if ws:
            if guide_type == "character":
                from simlife.worlds.world_manager import build_character_guide
                return build_character_guide(ws)
            elif guide_type == "activity":
                from simlife.worlds.world_manager import build_activity_guide
                return build_activity_guide(ws)
            elif guide_type == "event":
                from simlife.worlds.world_manager import build_event_guide
                return build_event_guide(ws)
    except Exception:
        pass
    return ""


def generate_world_setting(
    world_type: str = "fantasy",
    core_theme: str = "",
    character_role: str = "",
) -> dict:
    """
    用 LLM 生成一个完整的世界观设定 JSON。
    返回 world_setting dict 或 None。
    """
    import re

    llm = get_llm_client()

    type_names = {
        "fantasy": "奇幻魔法",
        "scifi": "科幻未来",
        "xianxia": "仙侠修真",
        "post_apocalyptic": "末世废土",
        "modern_power": "现世超武",
        "custom": "自定义",
    }
    type_label = type_names.get(world_type, world_type)

    # 类型特定约束
    type_constraints = ""
    if world_type == "modern_power":
        type_constraints = """
重要：这是一个「现世超武」世界观 — 现代社会背景下存在超能力/武术/异能。
- 社会结构和科技水平与现实世界基本一致（有手机、互联网、城市、公司、学校）
- 但部分人拥有超能力、武道修为、异能觉醒等，形成隐藏的「另一面社会」
- 超能力者有组织（如异能管理局、武道联盟），也有地下势力
- 普通人可能完全不知道超能力者的存在，或者只听说传闻
- 力量体系要接地气：不是飞天遁地，而是有限度的强化（如体术强化、元素操控、精神感应等）
- 势力之间有现实感：有政府机构、有企业财团、有地下组织、有学术研究团体
- 时间跨度要真实：学习一项技能需要数周到数月，修炼提升需要长期投入，不是几天就能速成
- 种族基本是人类，可能有小比例的变异者或觉醒者
"""
    elif world_type in ("fantasy", "xianxia"):
        type_constraints = """
重要：时间跨度要真实可信：
- 学习一项基础技能至少需要2-4周
- 修炼提升一个等级通常需要1-3个月
- 赶路旅行根据距离：相邻城镇1-3天，跨区域5-15天，跨国1-2个月
- 建立关系信任需要数周的互动
- 不是几天就能从新手变高手，成长是长期过程
"""
    elif world_type == "scifi":
        type_constraints = """
重要：时间跨度要真实可信：
- 学习操作一项新设备至少1-2周
- 星际旅行根据距离：近星系数天，远星系数周到数月
- 研究一个课题通常需要数周到数月
- 不是几个小时就能掌握复杂技术
"""

    prompt = f"""你是一个专业的世界观设计师。请创建一个{type_label}类型的世界观设定。
{type_constraints}
核心主题：{core_theme}
角色在这个世界的身份：{character_role or '（未指定）'}

设计要求：
1. 世界观必须自洽：地理、种族、力量体系、势力之间要有合理的因果关系
2. 细节要丰富：每个区域、种族、势力都要有独特性
3. 要有故事潜力：必须有明确的对抗力量和冲突根源，留出悬念
4. 数量适当：区域4-8个，种族3-6个，势力3-5个，副本3-5个
5. 所有名称要有风格统一性
6. 时间跨度要真实：技能学习、修炼提升、旅途赶路都需要合理的时长，不能几天速成

返回完整的 JSON 格式，必须包含以下顶层字段：
world_id（英文小写id）、world_name、world_type、era、communication（device/device_description/narrative_style）、geography（overview/regions数组）、races数组、power_system（name/description/levels数组/description中要包含每个等级的典型修炼时长）、factions数组、history（overview/major_events数组/current_situation）、daily_life、dangers（monster_types/dungeons数组）、character_generation_guide、activity_generation_guide、event_generation_guide

只返回JSON，不要任何其他文字。确保JSON可以直接被解析。"""

    setting = None
    # 首次尝试 + 失败重试（解析失败时用更低 temperature 再试一次）
    for attempt, temp in ((1, 0.8), (2, 0.4)):
        try:
            response = llm.generate(prompt, max_tokens=8000, temperature=temp)
            response = response.strip()
            # 提取 JSON（可能被 markdown 代码块包裹）
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                response = json_match.group(0)

            setting = _safe_json_loads(response)
            if setting:
                break
        except Exception as e:
            print(f"[SimLife] 世界观生成第{attempt}次解析失败: {e}")
            setting = None

    if setting is None:
        raise ValueError("世界观生成失败：多次尝试无法获得有效JSON")

    # 确保 world_id 合法
    if not setting.get("world_id") or setting["world_id"] == "modern":
        import hashlib
        setting["world_id"] = "world_" + hashlib.md5(core_theme.encode()).hexdigest()[:8]

    # 确保 world_type
    if not setting.get("world_type"):
        setting["world_type"] = world_type

    # ── 标准 schema 清洗 + 区域文件化落盘 ──
    try:
        from simlife.backend import world_schema
        from simlife.worlds import world_manager as wm

        world_id = setting.get("world_id", "world")
        # 清洗势力为标准结构
        factions = setting.get("factions", [])
        if factions and isinstance(factions, list):
            setting["factions"] = [world_schema.sanitize_faction(f) for f in factions if isinstance(f, dict)]

        # 拆分区域到独立文件（标准 schema 清洗后落盘）
        regions = setting.get("geography", {}).get("regions", [])
        region_name_map = {}
        if regions and isinstance(regions, list):
            for r in regions:
                if not isinstance(r, dict):
                    continue
                # 补充标准字段：NPC、势力关联在后续由用户/扩展填充，这里先落盘基础
                rid = wm.save_region(world_id, r)
                region_name_map[rid] = r.get("name", rid)
            # 从核心设定中移除已落盘的 regions 明细，避免重复
            setting.get("geography", {}).pop("regions", None)
            setting["geography"]["region_ids"] = list(region_name_map.keys())

        # 生成/清洗跨区域关系文件（势力据点自动推断）
        relations = wm.load_relations(world_id) or {}
        if not relations.get("faction_presence"):
            presence = {}
            for f in setting.get("factions", []):
                fid = f.get("id", "")
                rids = f.get("regions", []) or []
                if fid and rids:
                    presence[fid] = rids
            relations["faction_presence"] = presence
        if not relations.get("storylines"):
            relations["storylines"] = []
        if not relations.get("characters"):
            relations["characters"] = []
        wm.save_relations(world_id, relations)
    except Exception as e:
        print(f"[SimLife] 世界观标准化落盘失败: {e}")

    # ── 区域细化生成：为每个区域补充专属 NPC + 威胁怪物 + 势力据点 ──
    try:
        world_id = setting.get("world_id", "world")
        _refine_region_details(setting, world_id)
    except Exception as e:
        print(f"[SimLife] 区域细化生成失败: {e}")

    return setting


def _refine_region_details(world_setting: dict, world_id: str):
    """区域细化生成：为世界里的每个区域独立调用 LLM，
    生成该区域专属的 NPC、威胁怪物（含战斗数据）和势力据点。
    结果清洗后写入 regions/<id>.json，并更新 relations.json 的势力据点。
    """
    import re
    from simlife.backend import world_schema
    from simlife.worlds import world_manager as wm

    llm = get_llm_client()
    regions = wm.list_regions(world_id)
    if not regions:
        print("[SimLife] 区域细化：无区域文件，跳过")
        return

    factions = world_setting.get("factions", []) or []
    faction_names = "、".join(f.get("name", "") for f in factions[:4] if isinstance(f, dict))

    # 世界概述（作为 LLM 生成时的一致约束）
    geo = world_setting.get("geography", {}) or {}
    world_overview = f"{world_setting.get('world_name','')}（{world_setting.get('world_type','')}）\n{str(geo.get('overview',''))[:200]}"

    # 逐个区域细化
    for rinfo in regions:
        rid = rinfo["id"]
        rname = rinfo["name"]
        rdesc = str(rinfo.get("description", ""))[:150]
        rclimate = str(rinfo.get("climate", ""))[:80]
        key_locs = rinfo.get("key_locations") or []

        prompt = f"""{world_overview}

【当前区域】{rname}
环境：{rdesc}
气候：{rclimate}
关键地点：{'、'.join(key_locs[:4])}

这个世界的主要势力：{faction_names or '（无）'}

请为该区域生成专属的【NPC】和【威胁怪物】，要求完全符合这个世界观和该区域的环境特色。

输出 JSON：
{{
  "npcs": [
    {{"name": "NPC名", "role": "身份（如：村长/铁匠/旅店老板）", "description": "性格/背景（一句话）", "faction_id": "所属势力英文id或空", "is_key": false}}
  ],
  "monsters": [
    {{"name": "怪物名", "level": 等级, "hp": 生命值, "max_hp": 生命值, "attack_power": 攻击力, "defense_power": 防御力, "exp_reward": 经验, "gold_reward": 金币, "type": "normal/elite/boss", "behavior": "行为/攻击特性（供叙事用，一句话）", "skills": ["技能名"]}}
  ],
  "region_faction_ids": ["驻留本区域的势力英文id（从上方势力中选择，最多2个）"]
}}

要求：
- 生成 2-3 个 NPC，1-3 个怪物
- NPC 和怪物必须符合区域环境（如森林区就配森林生物，矿区配矿石生物）
- 等级参考该区域强度（新手村低，深处高）
- 不要输出任何其他文字，只输出JSON"""

        try:
            resp = llm.generate(prompt, max_tokens=1200, temperature=0.8)
            json_match = re.search(r'\{[\s\S]*\}', resp)
            if not json_match:
                print(f"[SimLife] 区域 {rname} 细化生成：未提取到JSON，跳过")
                continue
            data = _safe_json_loads(json_match.group(0))
            if not data:
                continue

            # 读取已有区域文件并补充 NPC/威胁/势力
            region = wm.load_region(world_id, rid) or {"name": rname, "id": rid}

            # NPC
            npcs = data.get("npcs", [])
            if npcs and isinstance(npcs, list):
                region["npcs"] = world_schema.sanitize_region({"npcs": npcs}).get("npcs", [])

            # 威胁怪物 → 存入区域 dangers（monster 数据）+ world_setting.dangers
            monsters = data.get("monsters", [])
            if monsters and isinstance(monsters, list):
                region["monsters"] = monsters
                # 同时更新 dangers.monster_types（供战斗系统引用）
                dangers = world_setting.setdefault("dangers", {})
                mt = dangers.setdefault("monster_types", [])
                existing_names = {m.get("name") for m in mt if isinstance(m, dict)}
                for m in monsters:
                    if isinstance(m, dict) and m.get("name") and m["name"] not in existing_names:
                        mt.append(m)
                        existing_names.add(m["name"])

            # 势力据点
            region_factions = data.get("region_faction_ids", [])
            if region_factions and isinstance(region_factions, list):
                region["factions"] = [f for f in region_factions[:2] if isinstance(f, str)]

            # 保存区域
            wm.save_region(world_id, region)

            # 更新 relations.json 势力据点
            if region_factions and isinstance(region_factions, list):
                relations = wm.load_relations(world_id)
                presence = relations.setdefault("faction_presence", {})
                for fid in region_factions[:2]:
                    if isinstance(fid, str) and fid:
                        rid_list = presence.setdefault(fid, [])
                        if rid not in rid_list:
                            rid_list.append(rid)
                wm.save_relations(world_id, relations)

            print(f"[SimLife] 区域 {rname} 细化完成：{len(npcs)} NPC, {len(monsters)} 怪物")
        except Exception as e:
            print(f"[SimLife] 区域 {rname} 细化失败: {e}")


def get_llm_client(config: dict = None):
    """获取 LLM 客户端实例（从 SimLife 配置或主项目配置）"""
    if config is None:
        config_path = Path(__file__).parent.parent / "data" / "simlife_config.json"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        else:
            config = {}

    import os
    if sys.platform == "win32":
        _cfg_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "AGI-Desktop"
    else:
        _cfg_dir = Path.home() / ".agi-desktop"
    main_config_path = _cfg_dir / "config.json"
    main_cfg = {}
    if main_config_path.exists():
        with open(main_config_path, "r", encoding="utf-8") as f:
            main_cfg = json.load(f)

    provider = config.get("llm_provider", "") or main_cfg.get("api_provider", "deepseek")
    api_key = config.get("llm_api_key", "") or main_cfg.get("api_key", "")
    model = config.get("llm_model", None) or main_cfg.get("llm_model", None)

    return create_client(api_key=api_key, provider=provider, model=model)


def _detect_work_style(occupation: str) -> str:
    """根据职业描述推断工作模式"""
    from .character import detect_work_style
    return detect_work_style(occupation).value


def generate_character_card(anchor: dict, agidpa_personality: dict = None) -> dict:
    """
    根据锚点和人格数据生成完整人物卡。
    根据职业类型自动选择不同的生成模板。
    返回 CharacterCard dict（不含 basic.name，需后续填充）。
    """
    llm = get_llm_client()

    name = anchor.get("character_name", "小AI")
    city = anchor.get("city", "上海")
    occupation = anchor.get("occupation_hint", "UI设计师")
    age = anchor.get("age", 24)
    personality = anchor.get("personality_word", "温柔")

    extra_context = ""
    if agidpa_personality:
        traits = agidpa_personality.get("personality_traits", [])
        style = agidpa_personality.get("speaking_style", "")
        bg = agidpa_personality.get("background_story", "")
        if traits:
            extra_context += f"\n性格标签：{', '.join(traits)}"
        if style:
            extra_context += f"\n说话风格：{style}"
        if bg:
            extra_context += f"\n背景故事：{bg[:100]}"

    work_style = _detect_work_style(occupation)

    if work_style == "freelance":
        prompt = _build_freelance_prompt(name, age, city, occupation, personality, extra_context)
    elif work_style == "student":
        prompt = _build_student_prompt(name, age, city, occupation, personality, extra_context)
    elif work_style == "travel":
        prompt = _build_travel_prompt(name, age, city, occupation, personality, extra_context)
    else:
        prompt = _build_office_prompt(name, age, city, occupation, personality, extra_context)

    # 注入世界观设定（非现代世界时）
    world_ctx = _get_world_context()
    if world_ctx:
        prompt = world_ctx + _get_world_guide("character") + "\n\n" + prompt

    try:
        response = llm.generate(prompt, max_tokens=2500, temperature=0.8)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        card = _safe_json_loads(response)
        card["basic"]["name"] = name
        # 确保有 work_style
        if "work_style" not in card.get("basic", {}):
            card["basic"]["work_style"] = work_style
        else:
            work_style = card["basic"]["work_style"]
        # 确保有 work_location_weights
        if work_style == "freelance" and "work_location_weights" not in card.get("basic", {}):
            card["basic"]["work_location_weights"] = {"home": 50, "cafe": 25, "outdoor": 15, "studio": 10}
        # 确保有 life_goals
        if "life_goals" not in card:
            card["life_goals"] = []
        # 确保有 work_start/work_end
        if "work_start" not in card.get("daily_schedule", {}):
            card["daily_schedule"]["work_start"] = card["daily_schedule"].get("arrive_work", "10:00")
        if "work_end" not in card.get("daily_schedule", {}):
            card["daily_schedule"]["work_end"] = card["daily_schedule"].get("leave_work", "18:00")
        # 兼容旧数据：通勤信息
        if work_style in ("freelance", "remote", "travel") and "commute" not in card:
            card["commute"] = {"method": "", "line": "", "duration_minutes": 0}
        # 旅行博主：确保有 travel_plan
        if work_style == "travel" and "travel_plan" not in card:
            card["travel_plan"] = {"enabled": True, "destinations": []}
        # 兼容旧数据：wardrobe 缺少 travel 字段
        if "travel" not in card.get("wardrobe", {}):
            card.setdefault("wardrobe", {})["travel"] = "轻便旅行装"
            card.setdefault("wardrobe", {})["travel_en"] = "lightweight travel outfit with backpack"
        # ── 自动生成生日：性格→星座→随机日期 ──
        if "birth_date" not in card.get("basic", {}) or not card["basic"].get("birth_date"):
            from .birthday_engine import auto_generate_birthday
            bd_info = auto_generate_birthday(personality, age)
            card["basic"]["birth_date"] = bd_info["birth_date"]
            card["basic"]["zodiac"] = bd_info["zodiac"]
        return card
    except Exception as e:
        print(f"[SimLife] 人物卡生成失败: {e}")
        return None


def _build_office_prompt(name, age, city, occupation, personality, extra_context):
    """上班族生成模板"""
    return f"""为一个名叫"{name}"的虚拟角色生成详细的人物设定卡。

基本信息：
- 年龄：{age}
- 城市：{city}
- 职业：{occupation}（上班族，固定地点工作）
- 性格关键词：{personality}{extra_context}

请生成以下信息，返回JSON格式：
{{
  "basic": {{
    "age": {age},
    "city": "{city}",
    "district": "一个{city}真实的区名",
    "occupation": "{occupation}",
    "work_style": "office",
    "company_name": "一个合理的公司名",
    "company_area": "一个合理的商务区名",
    "work_location_weights": {{"home": 0, "cafe": 0, "outdoor": 0, "studio": 0}},
    "nationality": "国籍/种族（英文，如 chinese, japanese, korean, mixed asian）",
    "hair_color": "发色（英文，如 black, brown, dark brown, blonde）",
    "eye_color": "眼睛颜色（英文，如 brown, dark brown, black）",
    "body_type": "身材描述（英文，如 tall and slender, petite, average height, athletic）"
  }},
  "home": {{
    "type": "合理的户型",
    "description": "30字以内的住处描述，有生活细节",
    "has_roommate": false,
    "pets": "如果没有宠物写空字符串"
  }},
  "family": {{
    "parents_location": "一个合理的城市",
    "contact_frequency": "合理的联系频率",
    "notes": "一个家庭小细节"
  }},
  "daily_schedule": {{
    "wake_up": "07:30",
    "leave_home": "08:45",
    "arrive_work": "09:30",
    "lunch_break_start": "12:00",
    "lunch_break_end": "13:00",
    "leave_work": "18:30",
    "arrive_home": "19:15",
    "sleep": "23:30",
    "work_start": "09:30",
    "work_end": "18:30"
  }},
  "commute": {{
    "method": "地铁/公交/骑车",
    "line": "具体线路",
    "duration_minutes": 30
  }},
  "locations": {{
    "home_address_hint": "一个{city}真实的路名附近",
    "company_landmark": "一个{city}真实的地标",
    "favorite_cafe": "一个真实的咖啡馆名",
    "supermarket": "一个真实的超市名",
    "park": "一个真实的公园名",
    "weekend_hangout": "一个真实的商圈/街道名",
    "frequent_outdoor_spots": ""
  }},
  "habits": {{
    "morning_drink": "早上的饮品",
    "lunch_style": "午餐习惯",
    "evening_routine": "晚上做什么",
    "weekend_morning": "周末早上"
  }},
  "current_context": "最近在忙什么，30字以内",
  "pixel_appearance": {{
    "gender": "male 或 female",
    "hair_color": "#十六进制颜色",
    "hair_style": "发型",
    "default_outfit_color": "#十六进制颜色"
  }},
  "life_goals": [
    {{"category": "事业", "description": "一个职业相关的短期目标", "target_date": "", "progress": 0, "priority": 1}},
    {{"category": "生活", "description": "一个生活相关的目标（如考驾照、学游泳、练肌肉、画油画、种花、学做饭等）", "target_date": "", "progress": 0, "priority": 2}},
    {{"category": "学习", "description": "一个学习成长相关的目标", "target_date": "", "progress": 0, "priority": 3}}
  ],
  "wardrobe": {{
    "home": "在家穿的舒适衣物（中文描述，10字以内）",
    "work": "上班穿的正式或商务休闲装（中文描述）",
    "casual": "日常出门穿的休闲装（中文描述）",
    "outdoor": "户外活动穿的穿搭（中文描述）",
    "formal": "正式场合穿的着装（中文描述）",
    "sport": "运动健身穿的服装（中文描述）",
    "sleep": "睡觉穿的睡衣（中文描述）",
    "home_en": "English description of home outfit for image generation",
    "work_en": "English description of work outfit",
    "casual_en": "English description of casual outfit",
    "outdoor_en": "English description of outdoor outfit",
    "formal_en": "English description of formal outfit",
    "sport_en": "English description of sport outfit",
    "sleep_en": "English description of sleepwear"
  }}
}}

只返回JSON，不要其他内容。所有地点必须是{city}真实存在的。人生目标要具体有趣，不要太空泛。wardrobe 要符合角色的性别、年龄和风格偏好——如果角色是男性，穿着应偏向男性化；如果性格偏运动风，户外和运动装应更具体。"""


def _build_freelance_prompt(name, age, city, occupation, personality, extra_context):
    """自由职业生成模板"""
    return f"""为一个名叫"{name}"的虚拟角色生成详细的人物设定卡。

基本信息：
- 年龄：{age}
- 城市：{city}
- 职业：{occupation}（自由职业/独立工作者，时间地点灵活）
- 性格关键词：{personality}{extra_context}

重要：这是一个自由职业者，没有固定公司，不需要每天通勤。请根据具体职业生成合理的生活节奏。

请生成以下信息，返回JSON格式：
{{
  "basic": {{
    "age": {age},
    "city": "{city}",
    "district": "一个{city}真实的区名",
    "occupation": "{occupation}",
    "work_style": "freelance",
    "company_name": "",
    "company_area": "",
    "work_location_weights": {{
      "home": "在家工作的频率权重（整数0-100）",
      "cafe": "咖啡馆工作的频率权重（整数0-100）",
      "outdoor": "户外工作（拍摄/采访等）的频率权重（整数0-100）",
      "studio": "工作室的频率权重（整数0-100）"
    }},
    "nationality": "国籍/种族（英文，如 chinese, japanese, korean, mixed asian）",
    "hair_color": "发色（英文，如 black, brown, dark brown, blonde）",
    "eye_color": "眼睛颜色（英文，如 brown, dark brown, black）",
    "body_type": "身材描述（英文，如 tall and slender, petite, average height, athletic）"
  }},
  "home": {{
    "type": "合理的户型（自由职业者可能有一间书房或工作区）",
    "description": "30字以内的住处描述，要体现自由职业者的生活气息",
    "has_roommate": false,
    "pets": "如果有宠物会更有生活感，没有写空字符串"
  }},
  "family": {{
    "parents_location": "一个合理的城市",
    "contact_frequency": "合理的联系频率",
    "notes": "家人对这个职业的态度，一个小细节"
  }},
  "daily_schedule": {{
    "wake_up": "合理的起床时间（自由职业者通常比上班族晚）",
    "leave_home": "10:00",
    "arrive_work": "10:30",
    "lunch_break_start": "12:30",
    "lunch_break_end": "14:00",
    "leave_work": "19:00",
    "arrive_home": "19:00",
    "sleep": "合理的睡觉时间（可能比上班族晚）",
    "work_start": "实际开始工作的时间",
    "work_end": "实际结束工作的时间"
  }},
  "commute": {{
    "method": "",
    "line": "",
    "duration_minutes": 0
  }},
  "locations": {{
    "home_address_hint": "一个{city}真实的路名附近",
    "company_landmark": "",
    "favorite_cafe": "常去办公的咖啡馆名",
    "supermarket": "一个真实的超市名",
    "park": "一个真实的公园名（常去放松/找灵感的地方）",
    "weekend_hangout": "一个真实的商圈/街道名",
    "frequent_outdoor_spots": "常去的工作相关户外地点（如拍摄地、采访地点等）"
  }},
  "habits": {{
    "morning_drink": "早上的饮品",
    "lunch_style": "午餐习惯（可能自己做、点外卖或去附近小店）",
    "evening_routine": "晚上的放松方式",
    "weekend_morning": "周末早上的习惯"
  }},
  "current_context": "最近在忙什么项目/创作，30字以内",
  "pixel_appearance": {{
    "gender": "male 或 female",
    "hair_color": "#十六进制颜色",
    "hair_style": "发型",
    "default_outfit_color": "#十六进制颜色"
  }},
  "life_goals": [
    {{"category": "事业", "description": "一个与{occupation}直接相关的目标（如粉丝量、接单量、作品数等）", "target_date": "", "progress": 0, "priority": 1}},
    {{"category": "生活", "description": "一个个人生活目标（从以下选一个或自创：考驾照、学游泳、练肌肉、画油画、种花、学做饭、养猫、旅行计划、学吉他、学跳舞、考个证书等）", "target_date": "", "progress": 0, "priority": 2}},
    {{"category": "健康", "description": "一个健康相关目标（如跑步、健身、早睡、少吃外卖等）", "target_date": "", "progress": 0, "priority": 3}},
    {{"category": "理财", "description": "一个理财目标（如攒钱买设备、月收入达到多少等）", "target_date": "", "progress": 0, "priority": 4}}
  ],
  "wardrobe": {{
    "home": "在家穿的舒适衣物（自由职业者可能一整天穿家居服，中文描述）",
    "work": "见客户或正式工作时的着装（自由职业者不一定穿正装，符合职业风格）",
    "casual": "出门闲逛、去咖啡馆的穿搭",
    "outdoor": "外出拍摄/采访/运动的穿搭（根据具体职业调整）",
    "formal": "正式场合或约会时的着装",
    "sport": "运动健身的服装",
    "sleep": "睡衣",
    "home_en": "English description for image generation",
    "work_en": "English work outfit description",
    "casual_en": "English casual outfit",
    "outdoor_en": "English outdoor outfit",
    "formal_en": "English formal outfit",
    "sport_en": "English sport outfit",
    "sleep_en": "English sleepwear"
  }}
}}

只返回JSON，不要其他内容。所有地点必须是{city}真实存在的。时刻表要符合自由职业者的真实节奏，不要照搬上班族。人生目标要具体有趣、贴合{occupation}这个职业特点。wardrobe 要符合角色的性别、年龄和职业风格。"""


def _build_student_prompt(name, age, city, occupation, personality, extra_context):
    """学生生成模板"""
    return f"""为一个名叫"{name}"的虚拟角色生成详细的人物设定卡。

基本信息：
- 年龄：{age}
- 城市：{city}
- 职业：{occupation}（学生）
- 性格关键词：{personality}{extra_context}

请生成以下信息，返回JSON格式：
{{
  "basic": {{
    "age": {age},
    "city": "{city}",
    "district": "一个{city}真实的区名（大学城附近）",
    "occupation": "{occupation}",
    "work_style": "student",
    "company_name": "所在学校名",
    "company_area": "学校所在区域",
    "work_location_weights": {{"home": 40, "cafe": 25, "outdoor": 5, "studio": 0}},
    "nationality": "国籍/种族（英文，如 chinese, japanese, korean, mixed asian）",
    "hair_color": "发色（英文，如 black, brown, dark brown, blonde）",
    "eye_color": "眼睛颜色（英文，如 brown, dark brown, black）",
    "body_type": "身材描述（英文，如 tall and slender, petite, average height, athletic）"
  }},
  "home": {{
    "type": "宿舍/出租屋",
    "description": "30字以内的住处描述",
    "has_roommate": true,
    "pets": ""
  }},
  "family": {{
    "parents_location": "一个合理的城市",
    "contact_frequency": "合理的联系频率",
    "notes": "一个家庭小细节"
  }},
  "daily_schedule": {{
    "wake_up": "合理的起床时间",
    "leave_home": "上课出发时间",
    "arrive_work": "到教室/图书馆时间",
    "lunch_break_start": "12:00",
    "lunch_break_end": "13:00",
    "leave_work": "下课时间",
    "arrive_home": "回宿舍/家时间",
    "sleep": "合理的睡觉时间",
    "work_start": "开始自习时间",
    "work_end": "结束自习时间"
  }},
  "commute": {{
    "method": "步行/骑车/地铁",
    "line": "具体线路（如有）",
    "duration_minutes": 15
  }},
  "locations": {{
    "home_address_hint": "一个{city}真实的路名附近",
    "company_landmark": "学校名",
    "favorite_cafe": "常去的咖啡馆名",
    "supermarket": "一个真实的超市名",
    "park": "一个真实的公园名",
    "weekend_hangout": "一个真实的商圈/街道名",
    "frequent_outdoor_spots": ""
  }},
  "habits": {{
    "morning_drink": "早上的饮品",
    "lunch_style": "食堂/外卖/校外小店",
    "evening_routine": "晚上的放松方式",
    "weekend_morning": "周末早上"
  }},
  "current_context": "最近在忙什么（如考试、论文、社团等），30字以内",
  "pixel_appearance": {{
    "gender": "male 或 female",
    "hair_color": "#十六进制颜色",
    "hair_style": "发型",
    "default_outfit_color": "#十六进制颜色"
  }},
  "life_goals": [
    {{"category": "学业", "description": "一个学业目标（如考研、考级、GPA等）", "target_date": "", "progress": 0, "priority": 1}},
    {{"category": "生活", "description": "一个生活目标（如学游泳、考驾照、旅行、学乐器等）", "target_date": "", "progress": 0, "priority": 2}},
    {{"category": "社交", "description": "一个社交目标（如参加社团、脱单等）", "target_date": "", "progress": 0, "priority": 3}}
  ],
  "wardrobe": {{
    "home": "在宿舍/出租屋穿的舒适衣物（中文描述）",
    "work": "上课穿的日常服装（学生不需要正装，符合学生风格）",
    "casual": "周末出门穿的休闲装",
    "outdoor": "户外运动或活动的穿搭",
    "formal": "参加活动/面试/正式场合的着装",
    "sport": "运动健身的服装",
    "sleep": "睡衣",
    "home_en": "English description for image generation",
    "work_en": "English daily outfit for class",
    "casual_en": "English casual outfit",
    "outdoor_en": "English outdoor outfit",
    "formal_en": "English formal outfit",
    "sport_en": "English sport outfit",
    "sleep_en": "English sleepwear"
  }}
}}

只返回JSON，不要其他内容。所有地点必须是{city}真实存在的。wardrobe 要符合学生的性别和风格，不要生成过于成熟的职业装。"""


def _build_travel_prompt(name, age, city, occupation, personality, extra_context):
    """旅行博主生成模板"""
    return f"""为一个名叫"{name}"的虚拟角色生成详细的人物设定卡。

基本信息：
- 年龄：{age}
- 基地城市：{city}（旅行出发地和平时居住地）
- 职业：{occupation}（旅行博主/旅游自媒体，常年全世界旅行拍视频）
- 性格关键词：{personality}{extra_context}

重要：这是一个旅行博主，生活节奏不固定，经常在不同城市和国家之间穿梭。
没有固定公司，工作时间就是旅行和拍摄时间。{city}是她的基地城市，不旅行时住在那里。

请生成以下信息，返回JSON格式：
{{
  "basic": {{
    "age": {age},
    "city": "{city}",
    "district": "一个{city}真实的区名",
    "occupation": "{occupation}",
    "work_style": "travel",
    "company_name": "",
    "company_area": "",
    "work_location_weights": {{"home": 20, "cafe": 10, "outdoor": 60, "studio": 10}},
    "nationality": "国籍/种族（英文，如 chinese, japanese, korean, mixed asian）",
    "hair_color": "发色（英文，如 black, brown, dark brown, blonde）",
    "eye_color": "眼睛颜色（英文，如 brown, dark brown, black）",
    "body_type": "身材描述（英文，如 tall and slender, petite, average height, athletic）"
  }},
  "home": {{
    "type": "合理的户型（可能不大，因为大部分时间在外面）",
    "description": "30字以内的住处描述，可以有点凌乱有生活感",
    "has_roommate": false,
    "pets": "如果有的话会更有趣，没有写空字符串"
  }},
  "family": {{
    "parents_location": "一个合理的城市",
    "contact_frequency": "合理的联系频率",
    "notes": "家人对常年旅行这个职业的态度，一个小细节"
  }},
  "daily_schedule": {{
    "wake_up": "合理的起床时间（旅行时可能比平时晚或早起赶行程）",
    "leave_home": "09:00",
    "arrive_work": "10:00",
    "lunch_break_start": "12:00",
    "lunch_break_end": "13:30",
    "leave_work": "18:00",
    "arrive_home": "19:00",
    "sleep": "合理的睡觉时间",
    "work_start": "10:00",
    "work_end": "18:00"
  }},
  "commute": {{
    "method": "",
    "line": "",
    "duration_minutes": 0
  }},
  "locations": {{
    "home_address_hint": "一个{city}真实的路名附近",
    "company_landmark": "",
    "favorite_cafe": "常去的咖啡馆名",
    "supermarket": "一个真实的超市名",
    "park": "一个真实的公园名",
    "weekend_hangout": "一个真实的商圈/街道名",
    "frequent_outdoor_spots": "常去拍摄或取景的地方"
  }},
  "habits": {{
    "morning_drink": "早上的饮品（旅途中可能是当地特色咖啡或茶）",
    "lunch_style": "午餐习惯（旅行时喜欢尝试当地美食）",
    "evening_routine": "晚上的放松方式（整理素材、剪辑视频）",
    "weekend_morning": "不旅行时周末早上的习惯"
  }},
  "current_context": "最近在忙什么旅行项目，30字以内",
  "pixel_appearance": {{
    "gender": "male 或 female",
    "hair_color": "#十六进制颜色",
    "hair_style": "发型",
    "default_outfit_color": "#十六进制颜色"
  }},
  "life_goals": [
    {{"category": "事业", "description": "一个与{occupation}直接相关的目标（如粉丝量、去过多少国家、合作了多少品牌等）", "target_date": "", "progress": 0, "priority": 1}},
    {{"category": "生活", "description": "一个个人生活目标（如学一门新语言、考潜水证、学冲浪等）", "target_date": "", "progress": 0, "priority": 2}},
    {{"category": "健康", "description": "一个健康目标（旅行博主经常作息不规律，可能是调整作息等）", "target_date": "", "progress": 0, "priority": 3}},
    {{"category": "旅行", "description": "一个旅行目标（如去南极、走完丝绸之路、自驾环游等）", "target_date": "", "progress": 0, "priority": 4}}
  ],
  "travel_plan": {{
    "enabled": true,
    "destinations": [
      {{
        "city": "一个真实的旅行目的地城市",
        "city_en": "English city name",
        "country": "国家名",
        "start_date": "从明天开始的一个日期，格式YYYY-MM-DD",
        "end_date": "4-7天后的日期，格式YYYY-MM-DD",
        "spots": ["该城市3-5个真实景点名"],
        "purpose": "这次旅行的目的（拍vlog、探店、体验文化等）",
        "mood_bonus": 15
      }},
      {{
        "city": "另一个不同的国家城市",
        "city_en": "English city name",
        "country": "国家名",
        "start_date": "10-15天后的日期",
        "end_date": "14-18天后的日期",
        "spots": ["该城市3-5个真实景点名"],
        "purpose": "旅行目的",
        "mood_bonus": 18
      }},
      {{
        "city": "第三个目的地",
        "city_en": "English city name",
        "country": "国家名",
        "start_date": "20-25天后的日期",
        "end_date": "24-30天后的日期",
        "spots": ["该城市3-5个真实景点名"],
        "purpose": "旅行目的",
        "mood_bonus": 20
      }}
    ]
  }},
  "wardrobe": {{
    "home": "在基地城市家穿的舒适衣物（中文描述）",
    "work": "见品牌方或正式工作时的着装",
    "casual": "出门闲逛的穿搭",
    "outdoor": "旅行拍摄时的穿搭（防晒、舒适、便于活动）",
    "formal": "品牌活动或正式场合的着装",
    "sport": "运动健身的服装",
    "sleep": "睡衣",
    "travel": "旅行标志性穿搭（如带有摄影师风格：马甲+工装裤+运动鞋）",
    "home_en": "English description for image generation",
    "work_en": "English work outfit description",
    "casual_en": "English casual outfit",
    "outdoor_en": "English travel photography outfit with utility vest and cargo pants",
    "formal_en": "English formal outfit",
    "sport_en": "English sport outfit",
    "sleep_en": "English sleepwear",
    "travel_en": "English travel outfit with camera bag, utility vest, comfortable sneakers and sunglasses"
  }}
}}

只返回JSON，不要其他内容。
- 基地城市{city}的地点必须真实存在。
- travel_plan 里的目的地城市和景点必须是真实存在的。
- 日期从明天开始依次排列，每次旅行4-7天，之间间隔3-5天。
- wardrobe 的 travel 穿搭要体现旅行博主特色（实用、便于拍摄、有辨识度）。
- life_goals 要具体有趣，贴合旅行博主这个职业。"""


def generate_npc_cards(character_card: dict) -> list:
    """根据主角人物卡生成 NPC 网络（根据工作模式调整）"""
    llm = get_llm_client()

    name = character_card.get("basic", {}).get("name", "")
    age = character_card.get("basic", {}).get("age", 24)
    occupation = character_card.get("basic", {}).get("occupation", "")
    city = character_card.get("basic", {}).get("city", "上海")
    district = character_card.get("basic", {}).get("district", "")
    work_style = character_card.get("basic", {}).get("work_style", "office")

    if work_style == "freelance":
        prompt = f"""为主角"{name}"生成一个丰富真实的人际圈。

主角信息：{age}岁，{occupation}（自由职业者），住在{city}{district}。
自由职业者的人际圈不同于上班族，通常有客户、合作者、同行朋友等。

请生成以下NPC，返回JSON数组（必须包含所有角色）：
[
  {{
    "id": "npc_bestfriend",
    "relation": "好友",
    "name": "一个{city}常见名字",
    "age": 25,
    "occupation": "合理的职业（可以是其他自由职业者）",
    "personality_word": "性格词（如开朗、细腻等）",
    "contact_frequency": "见面频率",
    "appear_scenes": ["CAFE", "STREET_WANDERING", "PARK", "FRIEND_HANGOUT", "CAFE_WORKING"],
    "event_pool": ["invite_hangout", "share_good_news"],
    "pixel_variant": "npc_f_01"
  }},
  {{
    "id": "npc_client",
    "relation": "客户",
    "name": "一个常见名字",
    "age": 30,
    "occupation": "合理的行业",
    "personality_word": "性格词",
    "contact_frequency": "项目期间频繁",
    "appear_scenes": ["CAFE_WORKING", "CAFE"],
    "event_pool": ["new_project", "payment_delay"],
    "pixel_variant": "npc_f_02"
  }},
  {{
    "id": "npc_collaborator",
    "relation": "合作者",
    "name": "一个常见名字",
    "age": 27,
    "occupation": "相关行业的自由职业者",
    "personality_word": "性格词",
    "contact_frequency": "偶尔合作",
    "appear_scenes": ["CAFE_WORKING", "CAFE", "HOME_WORKING"],
    "event_pool": ["collaboration_opportunity", "share_resource"],
    "pixel_variant": "npc_m_01"
  }},
  {{
    "id": "npc_mom",
    "relation": "妈妈",
    "name": "不显示",
    "age": {age + random.randint(25, 32)},
    "occupation": "",
    "personality_word": "关心",
    "contact_frequency": "每周视频",
    "appear_scenes": [],
    "event_pool": ["video_call", "send_recipe"],
    "pixel_variant": null
  }},
  {{
    "id": "npc_dad",
    "relation": "爸爸",
    "name": "不显示",
    "age": {age + random.randint(27, 34)},
    "occupation": "",
    "personality_word": "沉稳内敛",
    "contact_frequency": "偶尔视频",
    "appear_scenes": [],
    "event_pool": ["video_call", "send_money"],
    "pixel_variant": null
  }},
  {{
    "id": "npc_roommate",
    "relation": "大学室友",
    "name": "一个{city}常见名字",
    "age": {age},
    "occupation": "合理职业",
    "personality_word": "活泼古怪",
    "contact_frequency": "每月见面",
    "appear_scenes": ["CAFE", "FRIEND_HANGOUT", "STREET_WANDERING"],
    "event_pool": ["invite_hangout", "share_good_news", "catch_up"],
    "pixel_variant": "npc_f_03"
  }},
  {{
    "id": "npc_neighbor",
    "relation": "邻居",
    "name": "一个常见名字",
    "age": {age + random.randint(0, 3)},
    "occupation": "合理的职业",
    "personality_word": "佛系随和",
    "contact_frequency": "偶尔碰面",
    "appear_scenes": ["HOME_MORNING", "HOME_EVENING", "STREET_WANDERING"],
    "event_pool": ["borrow_thing", "share_good_news"],
    "pixel_variant": "npc_f_04"
  }}
]

只返回JSON数组，不要其他内容。人名使用{city}常见名字风格。age 可以适当微调（±2岁）。"""
    else:
        prompt = f"""为主角"{name}"生成一个丰富真实的人际圈。

主角信息：{age}岁，{occupation}，住在{city}{district}。

请生成以下NPC，返回JSON数组（必须包含所有角色）：
[
  {{
    "id": "npc_bestfriend",
    "relation": "好友",
    "name": "一个{city}常见名字",
    "age": {age + random.randint(1, 5)},
    "occupation": "合理的职业",
    "personality_word": "性格词（如开朗、细腻等）",
    "contact_frequency": "见面频率",
    "appear_scenes": ["CAFE", "STREET_WANDERING", "PARK", "FRIEND_HANGOUT"],
    "event_pool": ["invite_hangout", "share_good_news"],
    "pixel_variant": "npc_f_01"
  }},
  {{
    "id": "npc_colleague_a",
    "relation": "同事",
    "name": "一个常见名字",
    "age": {age + random.randint(2, 6)},
    "occupation": "同公司",
    "personality_word": "性格词",
    "contact_frequency": "每天见面",
    "appear_scenes": ["OFFICE_WORKING", "OFFICE_LUNCH"],
    "event_pool": ["lunch_together", "complain_about_work"],
    "pixel_variant": "npc_f_02"
  }},
  {{
    "id": "npc_colleague_b",
    "relation": "同事",
    "name": "一个常见名字",
    "age": {age + random.randint(3, 8)},
    "occupation": "同公司",
    "personality_word": "性格词",
    "contact_frequency": "每天见面",
    "appear_scenes": ["OFFICE_WORKING"],
    "event_pool": ["extra_task_from_boss"],
    "pixel_variant": "npc_m_01"
  }},
  {{
    "id": "npc_mom",
    "relation": "妈妈",
    "name": "不显示",
    "age": {age + random.randint(25, 32)},
    "occupation": "",
    "personality_word": "关心",
    "contact_frequency": "每周视频",
    "appear_scenes": [],
    "event_pool": ["video_call", "send_recipe"],
    "pixel_variant": null
  }},
  {{
    "id": "npc_dad",
    "relation": "爸爸",
    "name": "不显示",
    "age": {age + random.randint(27, 34)},
    "occupation": "",
    "personality_word": "沉稳内敛",
    "contact_frequency": "偶尔视频",
    "appear_scenes": [],
    "event_pool": ["video_call", "send_money"],
    "pixel_variant": null
  }},
  {{
    "id": "npc_roommate",
    "relation": "大学室友",
    "name": "一个{city}常见名字",
    "age": {age},
    "occupation": "合理职业",
    "personality_word": "活泼古怪",
    "contact_frequency": "每月见面",
    "appear_scenes": ["CAFE", "FRIEND_HANGOUT", "STREET_WANDERING"],
    "event_pool": ["invite_hangout", "share_good_news", "catch_up"],
    "pixel_variant": "npc_f_03"
  }},
  {{
    "id": "npc_boss",
    "relation": "直属上司",
    "name": "一个常见名字",
    "age": {age + random.randint(8, 14)},
    "occupation": "合理的职位",
    "personality_word": "干练严厉",
    "contact_frequency": "每天见面",
    "appear_scenes": ["OFFICE_WORKING", "OFFICE_MEETING"],
    "event_pool": ["extra_task_from_boss", "praise_from_boss"],
    "pixel_variant": "npc_m_02"
  }},
  {{
    "id": "npc_neighbor",
    "relation": "邻居",
    "name": "一个常见名字",
    "age": {age + random.randint(0, 3)},
    "occupation": "合理的职业",
    "personality_word": "佛系随和",
    "contact_frequency": "偶尔碰面",
    "appear_scenes": ["HOME_MORNING", "HOME_EVENING", "STREET_WANDERING"],
    "event_pool": ["borrow_thing", "share_good_news"],
    "pixel_variant": "npc_f_04"
  }}
]

只返回JSON数组，不要其他内容。人名使用{city}常见名字风格。age 可以适当微调（±2岁）。"""

    try:
        response = llm.generate(prompt, max_tokens=1500, temperature=0.8)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
        npcs = _safe_json_loads(response)
        # ── 自动为每个 NPC 补充生日 ──
        from .birthday_engine import auto_generate_birthday
        for npc in npcs:
            if not npc.get("birth_date"):
                personality = npc.get("personality_word", "")
                npc_age = npc.get("age", age + 2)
                bd_info = auto_generate_birthday(personality, npc_age)
                npc["birth_date"] = bd_info["birth_date"]
        return npcs
    except Exception as e:
        print(f"[SimLife] NPC生成失败: {e}")
        return None


def generate_activity_description(
    character_card: dict,
    scene: str,
    scene_label: str,
    today_events_summary: str = "",
    mood: int = 70,
) -> str:
    """生成一条口语化的活动描述"""
    llm = get_llm_client()

    from datetime import datetime
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")

    if mood > 80:
        tone = "语气轻快，有小惊喜细节"
    elif mood >= 60:
        tone = "正常语气，平淡但有质感"
    elif mood >= 40:
        tone = "语气带轻微疲惫感"
    else:
        tone = "语气低落，但不夸张"

    prompt = f"""角色名是"{name}"，职业是{occupation}，现在{weekday_names[now.weekday()]} {now.strftime('%H:%M')}。
她/他刚进入"{scene_label}"状态。
今天发生过的事：{today_events_summary or '暂无'}。
{tone}。
用第三人称写一句话描述这个瞬间，口语化，有细节，不超过30字，不要用感叹号。
只返回描述文字，不要引号或其他内容。"""

    # 注入世界观活动引导
    world_guide = _get_world_guide("activity")
    if world_guide:
        prompt = world_guide + "\n\n" + prompt

    try:
        response = llm.generate(prompt, max_tokens=100, temperature=0.9)
        return response.strip().strip('"').strip('"').strip("'").strip()
    except Exception:
        defaults = {
            "HOME_MORNING": "洗漱完在厨房煮咖啡",
            "COMMUTE_TO_WORK": "在去公司的路上",
            "OFFICE_WORKING": "在工位上做事",
            "OFFICE_MEETING": "在会议室里开会",
            "OFFICE_LUNCH": "出来觅食",
            "COMMUTE_TO_HOME": "下班回家的路上",
            "HOME_EVENING": "在家放松",
            "CAFE": "在咖啡馆坐了一会儿",
            "PARK": "在公园散步",
            "HOME_SLEEPING": "睡着了",
            "HOME_WEEKEND_LAZY": "赖在床上不想起来",
            "HOME_WORKING": "在家对着电脑做事",
            "CAFE_WORKING": "在咖啡馆打开了笔记本",
            "OUTDOOR_WORKING": "在外面忙工作的事",
            "STUDIO_WORKING": "在工作室里忙碌",
            "OVERTIME": "还在加班",
            # 旅行场景
            "AIRPORT": "在机场候机",
            "TOURING": "在景点拍素材",
            "HOTEL": "在酒店整理照片",
            "LOCAL_FOOD": "在吃当地美食",
            "TRAIN_STATION": "在火车站等车",
            "SCENIC_DRIVE": "坐在车上拍窗外风景",
            "RESTAURANT_LOCAL": "在当地餐厅吃饭",
        }
        return defaults.get(scene, "在忙自己的事")


def generate_life_arc(character_card: dict, previous_arc: dict = None) -> dict:
    """
    根据世界观 + 角色信息，LLM 推算一个月级别的人生主线。
    可选传入 previous_arc 作为上一段主线的摘要，保证故事连续性。
    返回字典，可直接用于创建 LifeArc 对象。
    """
    llm = get_llm_client()

    # 防御：character_card 可能是异常类型
    if not isinstance(character_card, dict):
        character_card = {}

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")
    personality = character_card.get("basic", {}).get("personality_traits", [])
    traits_str = "、".join(personality[:3]) if personality else "未设定"
    age = character_card.get("basic", {}).get("age", "")

    # 前情提要：上一段主线的摘要
    prev_hint = ""
    prev_threat_level = 0
    # 如果 previous_arc 是 list（异常数据），取第一个 dict 元素
    if isinstance(previous_arc, list):
        previous_arc = previous_arc[0] if previous_arc and isinstance(previous_arc[0], dict) else None
    if previous_arc and isinstance(previous_arc, dict):
        prev_title = previous_arc.get("title", "")
        prev_desc = previous_arc.get("description", "")
        prev_goal = previous_arc.get("main_goal", "")
        prev_antagonist = previous_arc.get("antagonist", "")
        prev_antagonist_motiv = previous_arc.get("antagonist_motivation", "")
        prev_threat_level = previous_arc.get("threat_level", 1)
        prev_consequences = previous_arc.get("consequences", "")
        prev_threads = previous_arc.get("unresolved_threads", [])
        stages = previous_arc.get("stages", [])
        final_stage = stages[-1] if stages else {}
        final_events = "；".join(final_stage.get("key_events", [])[:3])
        if final_stage.get("description"):
            final_events = final_stage["description"] + "。" + final_events

        prev_hint = f"\n\n【前情提要】\n上一条主线：「{prev_title}」\n大目标：{prev_goal}\n概述：{prev_desc}\n"

        if prev_antagonist:
            prev_hint += f"上一个对手：{prev_antagonist}"
            if prev_antagonist_motiv:
                prev_hint += f"（动机：{prev_antagonist_motiv}）"
            prev_hint += "\n"

        prev_hint += f"结局：{final_events}\n"

        if prev_consequences:
            prev_hint += f"此主线造成的后果：{prev_consequences}\n"

        if prev_threads:
            prev_hint += "未解决的伏笔：\n"
            for t in prev_threads[:5]:
                prev_hint += f"  - {t}\n"

        # 历史归档中的主线轨迹
        try:
            hist_path = Path(__file__).parent.parent / "data" / "life_arc_history.json"
            if hist_path.exists():
                with open(hist_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
                if history:
                    arc_titles = " → ".join([h.get("title", "?") for h in history[-5:]])
                    prev_hint += f"\n角色经历过的主线轨迹：{arc_titles}\n"
                    # 提取历史中的反派
                    past_antagonists = [h.get("antagonist", "") for h in history if h.get("antagonist")]
                    if past_antagonists:
                        prev_hint += f"过去的对手：{'、'.join(past_antagonists[-3:])}\n"
        except Exception:
            pass

    # ── 构建世界观硬约束 ──
    world_setting = None
    try:
        from simlife.worlds.world_manager import load_world_setting
        world_setting = load_world_setting()
    except Exception:
        pass

    world_hard_constraints = ""
    if world_setting and isinstance(world_setting, dict):
        ws = world_setting
        wname = ws.get("world_name", "")
        wtype = ws.get("world_type", "")

        # 力量体系 — 剧情中的成长必须贴合这个体系
        ps = ws.get("power_system", {})
        if ps:
            ps_name = ps.get("name", "")
            ps_desc = ps.get("description", "")[:200]
            levels = ps.get("levels", [])
            level_info = ""
            if levels:
                level_info = "、".join([f"{l.get('name','')}({l.get('description','')[:30] if l.get('description') else ''})" for l in levels[:6]])
            world_hard_constraints += f"\n【力量体系硬约束】体系名称：{ps_name}。{ps_desc}\n等级划分：{level_info}\n角色的成长、技能学习、战斗方式必须严格遵循此体系，不得自行发明其他体系。"

        # 势力 — 反派必须从这些势力中选取或与它们密切相关
        factions = ws.get("factions", [])
        if factions:
            faction_details = []
            for f in factions[:5]:
                fd = f"{f.get('name','')}（类型：{f.get('type','')}，立场：{f.get('alignment','')}，描述：{f.get('description','')[:50] if f.get('description') else ''}）"
                faction_details.append(fd)
            world_hard_constraints += f"\n【势力硬约束】世界观中的主要势力：{'；'.join(faction_details)}\n对抗力量（antagonist）必须来自这些势力之一，或与这些势力有直接关联。不得创建世界观中不存在的新势力作为反派。"

        # 当前局势 — 剧情的起因必须从这里发展
        history = ws.get("history", {})
        if history.get("current_situation"):
            world_hard_constraints += f"\n【局势硬约束】当前局势：{history['current_situation'][:300]}\n剧情的起因必须基于此局势发展，不得忽略当前局势另起炉灶。"

        # 种族 — 角色身份必须匹配
        races = ws.get("races", [])
        if races:
            race_names = "、".join([r.get("name", "") for r in races[:6]])
            world_hard_constraints += f"\n【种族硬约束】可选种族：{race_names}。角色和NPC的种族必须来自这些种族。"

        # 地理 — 赶路目的地必须真实存在于世界观中
        regions = ws.get("geography", {}).get("regions", [])
        if regions:
            region_names = "、".join([r.get("name", "") for r in regions[:8]])
            world_hard_constraints += f"\n【地理硬约束】主要区域：{region_names}。旅行目的地、事件发生地必须使用这些真实区域名，不得自行发明世界观中不存在的地方。"

        # 危险/副本 — 可作为冲突来源
        dangers = ws.get("dangers", {})
        monster_types = dangers.get("monster_types", [])
        dungeons = dangers.get("dungeons", [])
        if monster_types or dungeons:
            danger_info = ""
            if monster_types:
                mt_names = [m.get("name", str(m)) if isinstance(m, dict) else str(m) for m in monster_types[:5]]
                danger_info += f"常见威胁：{'、'.join(mt_names)}"
            if dungeons:
                danger_info += f"；副本：{'、'.join([d.get('name','') for d in dungeons[:5]])}"
            world_hard_constraints += f"\n【危险硬约束】{danger_info}。冲突和危险事件必须使用这些已有的威胁类型和副本，不得自行发明新的怪物种类。"

    # 如果没有完整世界设定，仍注入通用 context
    if not world_hard_constraints:
        world_context = _get_world_context()
        if world_context:
            world_hard_constraints = "\n" + world_context

    prompt = f"""你是人生模拟器的叙事系统。请为角色「{name}」（{occupation}，{age}岁，性格：{traits_str}）规划一段人生主线任务。
{prev_hint}
{world_hard_constraints}

## ⚠️ 世界观一致性要求（最高优先级）

剧情必须严格贴合上述世界观设定：
- 对抗力量必须来自世界观中已有的势力或人物，不得凭空创建世界观中不存在的反派组织
- 角色的技能成长必须遵循世界观的力量体系等级，不得跳级或使用体系外的能力
- 旅行目的地必须使用世界观中已有的区域名称
- 危险和冲突必须使用世界观中已有的威胁类型
- NPC的身份、种族、所属势力必须符合世界观设定
- 如果世界观有「当前局势」，剧情的起因必须基于此局势

## 核心设计原则

1. **目标层级**：主线是一个大目标，每个阶段是一个中目标，每个子目标是小目标。大目标拆解为中目标，中目标拆解为小目标
2. **必须有对抗力量**：每条主线都必须有明确的 antagonist（反派/对抗力量）。没有反派的故事没有紧张感。对抗力量可以是：
   - 具体的反派角色（黑魔法师、腐败的领主、宿敌刺客、野心勃勃的异能者）
   - 组织或势力（暗影教会、盗贼公会、侵略军队、跨国犯罪集团）
   - 自然/超自然威胁（瘟疫、远古封印松动、异变魔兽、异能失控事件）
   - 但必须有自己的动机，不是纯粹的"坏人"，要让玩家理解他们为什么这样做
3. **威胁升级**：如果有前情提要，新主线的威胁等级必须高于上一条（threat_level + 1，最高5）。角色在成长，挑战也必须升级。可以是：
   - 之前的对手回来复仇/升级
   - 前一个事件意外引出了更大的威胁
   - 角色的新身份/新能力引来新的敌人
4. **节奏多变**：不要每天都充满戏剧冲突。有些阶段是缓慢的赶路（可能持续3-10天），有些是紧张的决战（2-3天），有些是日常社交铺垫。张弛有度才是好故事
5. **时长真实**：总时长由故事本身决定，不要刻意压缩或拉长。时间跨度必须符合常识：
   - 赶路旅行：相邻地区3-7天，跨区域10-20天，遥远目的地30-60天
   - 学习技能/修炼：基础技能2-4周，进阶技能1-3个月
   - 收集情报：3-10天，取决于情报的复杂程度
   - 建立信任关系：至少数周的互动
   - 准备一场大型行动：7-15天
   - 一个本地事件主线通常15-30天，远行主线通常40-90天
6. **阶段类型**：每个阶段标注类型，用于控制节奏：
   - travel（旅行赶路）：以移动为主，节奏慢，根据距离持续3-20天
   - preparation（准备）：收集情报、整备装备、修炼提升，持续5-15天（修炼类更长）
   - exploration（探索）：调查未知区域、发现线索，持续3-10天
   - social（社交）：与NPC互动、建立关系、获取帮助，持续5-15天
   - conflict（冲突）：对抗、战斗、危机，持续2-5天
   - climax（高潮）：主线最关键的事件，持续1-3天
   - resolution（收尾）：处理后果、休整、为新冒险埋种子，持续5-10天
7. **子目标**：每个阶段拆出2-4个具体可执行的小目标，让角色每天有事可做。子目标的完成时间也要合理
8. **未解伏笔**：给出2-3个本主线结束后仍未解决的伏笔，为下一条主线埋种子
9. **前情延续**：如果有【前情提要】，新主线必须基于前作的后果和未解伏笔自然发展，不是另起炉灶

## 输出要求

返回 JSON，不要其他内容：
{{
  "title": "主线标题（10-20字）",
  "description": "主线概述（80-150字，说明大目标是什么、为什么要做）",
  "main_goal": "主线大目标（一句话概括最终要达成什么）",
  "antagonist": "对抗力量描述（谁/什么在阻止主角，20-40字）",
  "antagonist_motivation": "对抗力量的动机（为什么这样做，20-40字）",
  "threat_level": {prev_threat_level + 1},
  "duration_days": 30,
  "unresolved_threads": ["伏笔1", "伏笔2", "伏笔3"],
  "consequences": "本主线完成后的后果（如果主角成功了会怎样，如果失败了会怎样，30-60字）",
  "stages": [
    {{
      "name": "阶段名（5-10字）",
      "description": "阶段描述（20-50字）",
      "goal": "本阶段目标（一句话，如：抵达矮人王国、找到失踪的商人）",
      "stage_type": "travel",
      "duration_days": 5,
      "key_events": ["事件1", "事件2", "事件3"],
      "sub_goals": ["小目标1", "小目标2", "小目标3"]
    }}
  ]
}}"""

    # 注入用户对剧情的影响
    story_influence = _get_story_influences()
    if story_influence:
        prompt = prompt + "\n\n" + story_influence

    try:
        response = llm.generate(prompt, max_tokens=2000, temperature=0.85)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        # 尝试修复被截断的 JSON：补全未闭合的字符串和括号
        import re as _re
        def _repair_json(s: str) -> str:
            # 提取最外层的 { ... }
            match = _re.search(r'\{[\s\S]*', s)
            if match:
                s = match.group(0)
            # 统计未闭合的括号
            open_curly = s.count('{') - s.count('}')
            open_square = s.count('[') - s.count(']')
            # 检查是否在字符串中间截断（最后一个引号后没有配对）
            # 简单修复：闭合引号
            in_str = False
            escaped = False
            for ch in s:
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == '"':
                    in_str = not in_str
            if in_str:
                s += '"'
            # 补全括号
            s += ']' * max(0, open_square)
            s += '}' * max(0, open_curly)
            return s

        try:
            result = _safe_json_loads(response)
        except json.JSONDecodeError:
            # 尝试修复
            repaired = _repair_json(response)
            try:
                result = _safe_json_loads(repaired)
            except json.JSONDecodeError:
                # 最终尝试：用正则提取 JSON 对象
                json_match = _re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    repaired2 = _repair_json(json_match.group(0))
                    result = _safe_json_loads(repaired2)
                else:
                    raise

        # 如果 LLM 返回数组而非对象，取第一个元素
        if isinstance(result, list):
            if len(result) == 0:
                return _default_life_arc(name)
            result = result[0] if isinstance(result[0], dict) else {}

        if not isinstance(result, dict):
            return _default_life_arc(name)

        # 规范化
        stages_raw = result.get("stages", [])
        total_days = 0
        stages = []
        for s in stages_raw:
            if not isinstance(s, dict):
                continue
            dur = int(s.get("duration_days", 5))
            dur = max(2, min(60, dur))  # 远行主线阶段可达60天
            total_days += dur
            stages.append({
                "name": str(s.get("name", "阶段")),
                "description": str(s.get("description", "")),
                "goal": str(s.get("goal", "")),
                "stage_type": str(s.get("stage_type", "exploration")),
                "duration_days": dur,
                "status": "pending",
                "key_events": [str(e) for e in s.get("key_events", [])[:5]],
                "sub_goals": [str(g) for g in s.get("sub_goals", [])[:4]],
            })

        if not stages:
            return _default_life_arc(name)

        # 激活第一个阶段
        stages[0]["status"] = "active"

        # 威胁等级递增，上限5
        threat_level = int(result.get("threat_level", prev_threat_level + 1))
        threat_level = max(1, min(5, threat_level))

        return {
            "title": str(result.get("title", "日常冒险")),
            "description": str(result.get("description", "")),
            "main_goal": str(result.get("main_goal", "")),
            "antagonist": str(result.get("antagonist", "")),
            "antagonist_motivation": str(result.get("antagonist_motivation", "")),
            "threat_level": threat_level,
            "duration_days": total_days,
            "unresolved_threads": [str(t) for t in result.get("unresolved_threads", [])[:5]],
            "consequences": str(result.get("consequences", "")),
            "stages": stages,
        }

    except Exception as e:
        import traceback
        print(f"[SimLife] 主线生成失败: {e}")
        traceback.print_exc()
        return _default_life_arc(name)


def _default_life_arc(name: str = "角色") -> dict:
    """主线生成失败时的默认值"""
    return {
        "title": "暗影试炼",
        "description": f"{name}发现附近森林的魔兽异常暴动，调查后发现是暗影势力的阴谋",
        "main_goal": "调查并阻止暗影势力的阴谋",
        "antagonist": "暗影教派的残余势力",
        "antagonist_motivation": "试图解封沉睡在地下的暗影魔物",
        "threat_level": 1,
        "duration_days": 30,
        "unresolved_threads": ["暗影教派的真正首领仍未现身", "地下封印的完整结构尚不清楚"],
        "consequences": "如果成功，暗影教派的这一据点被清除；如果失败，暗影魔物可能被释放，周边村庄将遭殃",
        "stages": [
            {"name": "异常初现", "description": "注意到森林魔兽的异常行为", "goal": "收集异常情报", "stage_type": "exploration", "duration_days": 5, "status": "active", "key_events": ["发现异常魔兽", "询问村民", "找到线索"], "sub_goals": ["调查三起魔兽袭击事件", "找到目击者", "确定异常源头方向"]},
            {"name": "深入调查", "description": "进入森林深处调查真相", "goal": "找到暗影教派的据点", "stage_type": "exploration", "duration_days": 7, "status": "pending", "key_events": ["追踪魔兽足迹", "发现祭坛遗迹", "遭遇教徒"], "sub_goals": ["追踪到森林深处", "发现教派的祭坛", "活捉一名教徒审问"]},
            {"name": "备战准备", "description": "回去整备并寻求帮助", "goal": "做好突袭准备", "stage_type": "preparation", "duration_days": 5, "status": "pending", "key_events": ["采购药剂", "招募帮手", "制定计划"], "sub_goals": ["准备解毒药剂", "找到一个帮手", "制定突袭计划"]},
            {"name": "突袭据点", "description": "攻击暗影教派的据点", "goal": "摧毁教派的祭坛", "stage_type": "climax", "duration_days": 5, "status": "pending", "key_events": ["潜入据点", "与守卫战斗", "摧毁祭坛"], "sub_goals": ["潜入不被发现", "击败守卫头目", "摧毁祭坛核心"]},
            {"name": "战后收尾", "description": "处理后续并休整", "goal": "消化收获，警惕未来", "stage_type": "resolution", "duration_days": 8, "status": "pending", "key_events": ["审问俘虏", "整理战利品", "向村庄报告"], "sub_goals": ["审问俘虏获取情报", "整理战利品", "恢复伤势"]},
        ],
    }


def generate_day_plan(
    character_card: dict,
    mood: int = 70,
    yesterday_summary: str = "",
    arc_hint: str = "",
    cast: list = None,
    recent_story_context: str = "",
) -> list:
    """
    为非现代世界生成一天的大纲计划（LLM 一次调用，生成全天安排）。
    返回列表：[{"time":"07:00","scene":"房间","label":"起床","activity":"...","mood_delta":0,"npc":"npc_id或空"}, ...]
    通常 6-10 个节点，覆盖一天的作息。
    """
    from datetime import datetime

    llm = get_llm_client()
    now = datetime.now()
    weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")
    personality = character_card.get("basic", {}).get("personality_traits", [])
    traits_str = "、".join(personality[:3]) if personality else "未设定"

    summary_hint = f"\n昨天的经历：{yesterday_summary}" if yesterday_summary else ""
    arc_hint_text = f"\n\n{arc_hint}" if arc_hint else ""

    # NPC卡司提示
    cast_hint = ""
    if cast:
        npc_brief = "\n".join([f"- {c['name']}（{c['role']}，{c['personality']}）" for c in cast])
        cast_hint = f"\n\n可用NPC卡司：\n{npc_brief}"

    prompt = f"""你是人生模拟器。请为角色「{name}」（{occupation}，性格：{traits_str}）安排今天一整天的大纲计划。

今天是{weekday_names[now.weekday()]}，当前心情{mood}/100。{summary_hint}{arc_hint_text}{cast_hint}

要求：
1. 生成 8-10 个时间节点，从起床到入睡，均匀分布
2. 每个节点包含：time(HH:MM)、scene(2-4字场景名)、label(4-8字标签)、activity(15-30字简短描述)、mood_delta(-5到+5)、npc(可选，NPC的id或空字符串)
3. 活动要符合世界观设定，围绕当前阶段目标推进
4. 不要用感叹号
5. activity 要精简概括，不要展开细节，细节会在到时间后按需展开
6. 一天中至少 1-2 个节点涉及NPC互动

## 时间真实性要求
- 学习技能不能一天速成，如果今天是"修炼/学习"类活动，只能写"开始练习某某技能"或"继续练习某某技能（第X天）"，不要写"学会了"
- 一天的活动安排要符合正常人的精力：不可能从早到晚全在修炼或战斗，要有休息、用餐、闲聊的时间
- travel阶段如果需要赶远路，一天的时间大部分在旅途上，不要安排太多额外事件
- 如果角色在准备阶段（preparation），情报收集、装备筹备等活动要逐步推进，不要一天搞定所有准备

## 节奏要求
- 如果当前阶段是"travel"类型（赶路），大半天应该都在旅途上，不要安排太多事件，赶路本身就是内容
- 如果是"preparation"类型，安排收集情报、采购、修炼等日常准备活动
- 如果是"social"类型，多安排与NPC的互动场景
- 如果是"conflict/climax"类型，安排紧张的事件，但也要有战前准备和战后休整
- 如果是"resolution"类型，节奏要慢，安排整理、反思、休整
- 不要每天都安排大事。有些天就是平淡的日常，这很重要

## 子目标
- 如果提示中给了子目标，今天安排1-2个可以推进的活动，不要一天全做完
- 子目标的推进要自然融入日常，不要生硬地"完成子目标"

返回 JSON 数组，不要其他内容：
[{{"time":"07:00","scene":"房间","label":"晨起","activity":"{name}醒来，简单梳洗",  "mood_delta":1,"npc":""}}, ...]"""

    # 注入世界观引导
    world_context = _get_world_context()
    if world_context:
        prompt = world_context + "\n\n" + prompt
    # 注入用户对剧情的影响
    story_influence = _get_story_influences()
    if story_influence:
        prompt = prompt + "\n\n" + story_influence
    # 注入近期剧情回顾（存档历史）
    if recent_story_context:
        prompt = prompt + "\n\n" + recent_story_context

    try:
        response = llm.generate(prompt, max_tokens=800, temperature=0.85,
                                 response_format={"type": "json_object"})
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        plan = _safe_json_loads(response)
        if not isinstance(plan, list) or len(plan) == 0:
            raise ValueError("空列表")

        # 验证并规范化
        valid_plan = []
        for item in plan:
            if not isinstance(item, dict):
                continue
            valid_plan.append({
                "time": str(item.get("time", "08:00")),
                "scene": str(item.get("scene", "日常")),
                "label": str(item.get("label", "")),
                "activity": str(item.get("activity", "")),
                "mood_delta": int(item.get("mood_delta", 0)),
                "npc": str(item.get("npc", "")),
                "expanded": None,  # 小说展开文本，按需生成
            })
        return valid_plan if valid_plan else _default_day_plan(name)

    except Exception as e:
        print(f"[SimLife] 全天计划 JSON 解析失败，尝试修复: {e}")
        # 尝试修复常见 JSON 格式错误
        try:
            import re as _re
            fixed = response

            # 1. 用正则提取 JSON 数组部分（LLM 可能在首尾附加了其他文本）
            array_match = _re.search(r'\[[\s\S]*\]', fixed)
            if array_match:
                fixed = array_match.group(0)
            # 2. 如果以 , 结尾，去掉
            fixed = _re.sub(r',\s*$', '', fixed.strip())
            # 3. 修复未闭合的引号（Unterminated string）
            in_string = False
            escape_next = False
            for ch in fixed:
                if escape_next:
                    escape_next = False
                    continue
                if ch == '\\':
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
            if in_string:
                fixed += '"'
            # 4. 补全最外层的 ] 或 }（LLM 经常截断）
            open_brackets = fixed.count('[') + fixed.count('{')
            close_brackets = fixed.count(']') + fixed.count('}')
            fixed += ']' * (open_brackets - close_brackets)
            # 5. 尝试用 rjson（对引号缺失更宽容）
            try:
                import rjson
                plan = rjson.loads(fixed)
            except ImportError:
                plan = json.loads(fixed)
            if isinstance(plan, list) and len(plan) > 0:
                valid_plan = []
                for item in plan:
                    if not isinstance(item, dict):
                        continue
                    valid_plan.append({
                        "time": str(item.get("time", "08:00")),
                        "scene": str(item.get("scene", "日常")),
                        "label": str(item.get("label", "")),
                        "activity": str(item.get("activity", "")),
                        "mood_delta": int(item.get("mood_delta", 0)),
                        "npc": str(item.get("npc", "")),
                        "expanded": None,
                    })
                if valid_plan:
                    print(f"[SimLife] JSON 修复成功，得到 {len(valid_plan)} 个节点")
                    return valid_plan
        except Exception as e2:
            print(f"[SimLife] JSON 修复也失败: {e2}")

        # 终极兜底：用正则逐字段提取每个 JSON 对象
        try:
            import re as _re
            objects = _re.findall(r'\{[^{}]*\}', response)
            if objects:
                valid_plan = []
                for obj_str in objects:
                    try:
                        key_values = {}
                        # 提取 mood_delta（数字类型）
                        m = _re.search(r'"mood_delta"\s*:\s*(-?\d+)', obj_str)
                        if m:
                            key_values["mood_delta"] = int(m.group(1))
                        # 提取字符串字段
                        for key in ("time", "scene", "label", "activity", "npc"):
                            m = _re.search(rf'"{key}"\s*:\s*"([^"]*)"', obj_str)
                            if m:
                                key_values[key] = m.group(1)
                        if "time" in key_values and "scene" in key_values:
                            valid_plan.append({
                                "time": key_values.get("time", "08:00"),
                                "scene": key_values.get("scene", "日常"),
                                "label": key_values.get("label", ""),
                                "activity": key_values.get("activity", ""),
                                "mood_delta": int(key_values.get("mood_delta", 0)),
                                "npc": key_values.get("npc", ""),
                                "expanded": None,
                            })
                    except Exception:
                        continue
                if valid_plan:
                    print(f"[SimLife] 正则提取修复成功，得到 {len(valid_plan)} 个节点")
                    return valid_plan
        except Exception:
            pass

        print(f"[SimLife] 全天计划生成失败，使用默认计划")
        return _default_day_plan(name)


def _default_day_plan(name: str = "角色") -> list:
    """生成失败时的默认计划"""
    return [
        {"time": "07:00", "scene": "房间", "label": "起床", "activity": f"{name}从睡梦中醒来", "mood_delta": 1},
        {"time": "08:00", "scene": "日常", "label": "早餐", "activity": f"{name}简单吃了些东西", "mood_delta": 2},
        {"time": "09:00", "scene": "工作", "label": "开始工作", "activity": f"{name}开始了一天的工作", "mood_delta": 0},
        {"time": "12:00", "scene": "日常", "label": "午餐", "activity": f"{name}找了个地方吃饭休息", "mood_delta": 2},
        {"time": "14:00", "scene": "工作", "label": "下午工作", "activity": f"{name}继续忙碌着", "mood_delta": -1},
        {"time": "18:00", "scene": "日常", "label": "晚餐", "activity": f"{name}吃过晚饭，放松下来", "mood_delta": 3},
        {"time": "20:00", "scene": "休闲", "label": "晚间休闲", "activity": f"{name}享受着属于自己的时光", "mood_delta": 2},
        {"time": "22:00", "scene": "房间", "label": "入睡", "activity": f"{name}准备休息了", "mood_delta": 1},
    ]


def generate_story_cast(character_card: dict, arc: dict = None, existing_cast: list = None) -> list:
    """
    为非现代世界生成剧情NPC卡司（3-5个角色）。
    如果传入 arc，会根据主线反派设计加入对应阵营的NPC。
    如果传入 existing_cast，保留部分老NPC以维持关系连续性。
    """
    llm = get_llm_client()

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")
    age = character_card.get("basic", {}).get("age", 24)
    personality = character_card.get("basic", {}).get("personality_traits", [])
    traits_str = "、".join(personality[:3]) if personality else "未设定"

    # 主线反派信息
    arc_hint = ""
    if arc:
        antagonist = arc.get("antagonist", "")
        antagonist_motiv = arc.get("antagonist_motivation", "")
        arc_title = arc.get("title", "")
        arc_goal = arc.get("main_goal", "")
        arc_hint = f"\n当前主线：「{arc_title}」\n主线目标：{arc_goal}\n"
        if antagonist:
            arc_hint += f"对抗力量：{antagonist}"
            if antagonist_motiv:
                arc_hint += f"（动机：{antagonist_motiv}）"
            arc_hint += "\n卡司中必须包含1-2个与对抗力量相关的NPC（可以是反派阵营的人、被反派胁迫的人、或反对反派的盟友）\n"

    # 老NPC信息（保持关系连续性）
    old_cast_hint = ""
    if existing_cast:
        old_brief = "\n".join([f"- {c.get('name', '?')}（{c.get('role', '?')}，信任度{c.get('trust', 50)}）" for c in existing_cast[:5]])
        old_cast_hint = f"\n\n角色已有的社交关系：\n{old_brief}\n可以保留1-2个关系最深的老面孔，其余换新。\n"

    # 注入世界观硬约束（NPC种族、势力必须符合世界观）
    world_setting = None
    try:
        from simlife.worlds.world_manager import load_world_setting
        world_setting = load_world_setting()
    except Exception:
        pass

    ws_constraints = ""
    if world_setting:
        races = world_setting.get("races", [])
        factions = world_setting.get("factions", [])
        if races:
            ws_constraints += f"\n可用种族：{'、'.join([r.get('name','') for r in races[:6]])}"
        if factions:
            faction_info = "；".join([f"{f.get('name','')}（{f.get('type','')}）" for f in factions[:5]])
            ws_constraints += f"\n已有势力：{faction_info}\nNPC的所属势力必须来自这些已有势力。"
        ws_constraints = "\n【世界观约束】" + ws_constraints

    prompt = f"""你是人生模拟器的叙事系统。请为角色「{name}」（{occupation}，{age}岁，性格：{traits_str}）生成一组剧情NPC卡司。{arc_hint}{old_cast_hint}{ws_constraints}

要求：
1. 生成 4-6 个NPC，他们将在剧情中反复出现
2. NPC类型要多样：同伴、对手、导师、神秘人、交易伙伴等
3. 如果有当前主线，必须包含1-2个与对抗力量相关的NPC
4. 每个NPC要有独特的性格和说话风格，让对话有辨识度
5. 每个NPC要有一个秘密或隐藏身份，为后续剧情埋伏笔
6. NPC要完全符合世界观设定，种族和势力必须来自世界观中已有的
7. 如果有已有社交关系，保留1-2个老面孔，维持关系连续性

返回 JSON 数组，不要其他内容：
[
  {{
    "id": "npc_角色英文id",
    "name": "角色名",
    "role": "在故事中的角色（如：冒险同伴、图书馆管理员、对头、导师的旧友等）",
    "personality": "性格描述（30字以内）",
    "appearance": "外貌描述（30字以内）",
    "secret": "一个秘密或隐藏身份（20字以内）",
    "voice_style": "说话风格（15字以内，如：喜欢用反问句、说话慢条斯理、口头禅是什么等）",
    "first_encounter": "与主角初次相遇的场景描述（30字以内）"
  }}
]"""

    world_context = _get_world_context()
    if world_context:
        prompt = world_context + "\n\n" + prompt
    story_influence = _get_story_influences()
    if story_influence:
        prompt = prompt + "\n\n" + story_influence

    try:
        response = llm.generate(prompt, max_tokens=1500, temperature=0.85)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        cast = _safe_json_loads(response)
        if not isinstance(cast, list) or len(cast) == 0:
            return _default_story_cast(name)

        valid_cast = []
        for item in cast:
            if not isinstance(item, dict):
                continue
            valid_cast.append({
                "id": str(item.get("id", "")),
                "name": str(item.get("name", "")),
                "role": str(item.get("role", "")),
                "personality": str(item.get("personality", "")),
                "appearance": str(item.get("appearance", "")),
                "secret": str(item.get("secret", "")),
                "voice_style": str(item.get("voice_style", "")),
                "first_encounter": str(item.get("first_encounter", "")),
                "trust": 50,       # 初始信任度 0-100
                "encountered": False,
            })
        return valid_cast if valid_cast else _default_story_cast(name)
    except Exception as e:
        print(f"[SimLife] NPC卡司生成失败: {e}")
        return _default_story_cast(name)


def _default_story_cast(name: str = "角色") -> list:
    """卡司生成失败时的默认值"""
    return [
        {"id": "npc_companion", "name": "旅行者", "role": "偶然相遇的同行者",
         "personality": "话多但心善", "appearance": "穿着斗篷看不清面容",
         "secret": "其实是在逃亡", "voice_style": "喜欢用夸张的比喻",
         "first_encounter": "在路边休息时被搭话", "trust": 50, "encountered": False},
        {"id": "npc_mentor", "name": "老者", "role": "神秘的引导者",
         "personality": "沉默寡言但关键时刻指点迷津", "appearance": "白发苍苍，眼神深邃",
         "secret": "与主角的导师有旧交", "voice_style": "说话简短有力",
         "first_encounter": "在图书馆角落偶遇", "trust": 50, "encountered": False},
        {"id": "npc_rival", "name": "竞争者", "role": "目标相同的对手",
         "personality": "表面友善内心算计", "appearance": "衣着整洁，面带微笑",
         "secret": "为某个组织效力", "voice_style": "语气温和但暗藏锋芒",
         "first_encounter": "在任务发布处争抢同一个委托", "trust": 30, "encountered": False},
    ]


def expand_node(character_card: dict, node: dict, cast: list = None,
                arc_context: str = "", prev_nodes: list = None) -> str:
    """
    将 day_plan 的一个节点展开为 200-500 字的小说段落。
    包含场景描写、动作细节、内心独白、NPC对话。
    """
    llm = get_llm_client()

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")

    # 构建 NPC 上下文
    cast_info = ""
    if cast and node.get("npc"):
        npc_id = node.get("npc", "")
        for c in cast:
            if c.get("id") == npc_id:
                cast_info = (
                    f"\n互动NPC：{c['name']}（{c['role']}）\n"
                    f"性格：{c['personality']}\n"
                    f"说话风格：{c['voice_style']}\n"
                    f"秘密：{c['secret']}"
                )
                break
        if not cast_info and cast:
            # 如果没找到具体NPC，把所有卡司简要列出
            brief = "; ".join([f"{c['name']}({c['role']})" for c in cast[:4]])
            cast_info = f"\n可用NPC：{brief}"

    # 构建上文衔接
    prev_context = ""
    if prev_nodes and len(prev_nodes) > 0:
        last = prev_nodes[-1]
        prev_context = f"\n上一个节点：{last.get('time', '')} {last.get('label', '')} - {last.get('activity', '')}"

    arc_hint = f"\n\n{arc_context}" if arc_context else ""

    prompt = f"""你是人生模拟器的小说叙事系统。请将以下日程节点展开为一段生动的小说段落。

角色：{name}（{occupation}）
当前节点：{node.get('time', '')} {node.get('label', '')} - {node.get('scene', '')}
活动概要：{node.get('activity', '')}{cast_info}{prev_context}{arc_hint}

写作要求：
1. 字数 200-500 字
2. 包含场景描写（环境、氛围、五感）
3. 包含动作细节（微表情、小动作）
4. 如果有互动NPC，必须包含对话（要有性格辨识度）
5. 可以包含角色内心独白
6. 第三人称叙事，语气自然流畅
7. 不要用感叹号
8. 严格符合世界观设定

只返回小说正文，不要其他内容。"""

    world_context = _get_world_context()
    if world_context:
        prompt = world_context + "\n\n" + prompt
    story_influence = _get_story_influences()
    if story_influence:
        prompt = prompt + "\n\n" + story_influence

    try:
        response = llm.generate(prompt, max_tokens=600, temperature=0.9)
        return response.strip()
    except Exception as e:
        print(f"[SimLife] 节点展开失败: {e}")
        return node.get("activity", "")


def generate_future_events(
    character_card: dict,
    recent_events: list,
    days: int = 3,
) -> list:
    """生成未来N天的随机事件队列"""
    llm = get_llm_client()

    name = character_card.get("basic", {}).get("name", "")
    occupation = character_card.get("basic", {}).get("occupation", "")
    work_style = character_card.get("basic", {}).get("work_style", "office")
    recent = "、".join([e.get("label", "") for e in recent_events[-5:]]) if recent_events else "暂无"

    style_hint = ""
    if work_style == "freelance":
        style_hint = "她是自由职业者，事件可能涉及找灵感、客户沟通、作品创作、自我提升等。"
    elif work_style == "student":
        style_hint = "她是学生，事件可能涉及考试、社团、作业、同学社交等。"
    elif work_style == "travel":
        style_hint = "她是旅行博主，事件可能涉及航班变化、拍摄素材、当地见闻、品牌合作、粉丝互动等。"
    else:
        style_hint = "她是上班族，事件可能涉及工作项目、同事关系、加班、通勤等。"

    prompt = f"""角色"{name}"，{occupation}。最近发生过：{recent}。
{style_hint}
帮她/他生成接下来{days}天可能发生的生活小事，
每天0-2条，带发生时间段（如"19:00-20:00"）和心情影响值（-30到+30）。
返回JSON数组格式：
[
  {{"event_id": "自定义英文id", "label": "事件描述", "scheduled_date": "YYYY-MM-DD", "scheduled_time_range": "HH:MM-HH:MM", "mood_delta": 10, "source": "llm_generated"}}
]
从明天开始。只返回JSON数组。"""

    # 注入世界观事件引导
    world_guide = _get_world_guide("event")
    if world_guide:
        prompt = world_guide + "\n\n" + prompt

    try:
        from datetime import datetime, timedelta
        response = llm.generate(prompt, max_tokens=1000, temperature=0.8)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
        events = _safe_json_loads(response)
        # 如果返回的是 dict 而非 list，尝试提取
        if isinstance(events, dict):
            events = events.get("events", events.get("event_list", [events]))
        if not isinstance(events, list):
            events = [events]

        tomorrow = (datetime.now() + timedelta(days=1)).date()
        for i, evt in enumerate(events):
            date_str = evt.get("scheduled_date", "")
            try:
                d = __import__("datetime").date.fromisoformat(date_str)
            except Exception:
                d = tomorrow + timedelta(days=i // 2)

        return events
    except Exception as e:
        print(f"[SimLife] 未来事件生成失败: {e}")
        return []
