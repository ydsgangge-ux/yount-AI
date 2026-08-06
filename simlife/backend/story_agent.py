"""
场景故事反馈 Agent — 分段生成剧情，用户选择后才推进

核心设计：
- 不预生成全天计划，而是根据用户选择逐段推进
- 每段生成：场景描述 + 2-4个选项
- 用户选择后：LLM 叙事 + 数值系统判定结果
- 支持自由输入行动（不只限于预设选项）
"""
import json
import re
from typing import Dict, List, Optional


class StoryAgent:
    """场景故事反馈 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client

    def _build_world_context(self, state: Dict) -> str:
        """构建世界观约束 — 区域驱动：
        先注入全局核心设定（世界背景），再注入玩家当前所在区域的完整本地设定。
        数据源优先级：
          1) world_manager 的区域独立文件（<world_id>/regions/<region>.json）
          2) 跨区域关系文件（<world_id>/relations.json）
          3) 兼容旧结构（world_setting.geography.regions 内嵌）
        """
        ws = state.get("world_setting", {})
        if not ws or not isinstance(ws, dict):
            return ""

        parts = []
        parts.append(f"世界：{ws.get('world_name', '未知')}（{ws.get('world_type', '未知')}）")

        # ── 1. 尝试从区域文件加载（新架构优先）──
        region_ctx, relations_ctx = "", ""
        try:
            from simlife.worlds import world_manager as wm
            world_id = ws.get("world_id", "")
            if world_id:
                # 确定当前区域
                region_name = self._get_current_region_name(state, ws)
                if region_name:
                    region = wm.load_region(world_id, region_name)
                    if region:
                        region_ctx = wm.build_region_context(region, ws)
                        # 注入跨区域关系
                        relations = wm.load_relations(world_id)
                        cur_rid = region.get("id", "")
                        relations_ctx = wm.build_relations_context(relations, cur_rid)
        except Exception:
            region_ctx, relations_ctx = "", ""

        # ── 2. 区域文件未命中时，从 world_map 中获取区域数据 ──
        if not region_ctx:
            # 优先从 world_map 的区域数据构建上下文
            wm_data = state.get("world_map", {})
            wm_regions = wm_data.get("regions", {})
            cur_region_id = wm_data.get("current_region_id", "")
            cur_location = state.get("story", {}).get("current_location", "")
            # 尝试匹配当前区域
            region_data = None
            for rid, rdata in wm_regions.items():
                if rid == cur_region_id or rid == cur_location or rdata.get("name") == cur_location:
                    region_data = rdata
                    break
            if region_data:
                r_name = region_data.get("name", cur_location or "未知")
                r_desc = region_data.get("description", "")
                r_type = region_data.get("region_type", "")
                r_danger = region_data.get("danger_level", 0)
                type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城", "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(r_type, r_type)
                region_ctx = f"【当前区域】{r_name}（{type_label}，危险等级{r_danger}）\n{r_desc}"
            else:
                # 最终回退到内嵌 regions
                current_region = self._resolve_current_region(state, ws)
                if current_region:
                    region_ctx = self._build_region_context(current_region, ws)
                else:
                    regions = ws.get("geography", {}).get("regions", [])
                    if regions:
                        names = [r.get("name", "") for r in regions[:6] if isinstance(r, dict)]
                        region_ctx = f"已知区域：{'、'.join(names)}"

        # ── 3. 世界地理概述 ──
        geo_overview = ws.get("geography", {}).get("overview", "")
        if geo_overview:
            parts.append(f"【世界地理】{geo_overview[:200]}")

        # ── 4. 当前区域本地设定 + 跨区域关系 ──
        if region_ctx:
            parts.append(region_ctx)
        if relations_ctx:
            parts.append(relations_ctx)

        return "\n".join(parts)

    def _get_current_region_name(self, state: Dict, ws: Dict) -> str:
        """获取当前所在区域名（候选：地点名/区域id/地图当前区域）"""
        candidates = [
            state.get("story", {}).get("current_location", ""),
            state.get("world_map", {}).get("current_region", ""),
            state.get("world_map", {}).get("current_region_id", ""),
        ]
        for c in candidates:
            if c:
                c = str(c).strip()
                if c:
                    return c
        return ""

    def _resolve_current_region(self, state: Dict, ws: Dict):
        """根据当前状态解析玩家所在区域对象（优先匹配区域名）"""
        regions = ws.get("geography", {}).get("regions", [])
        if not regions or not isinstance(regions, list):
            return None
        regions = [r for r in regions if isinstance(r, dict)]

        # 候选：当前地点名、区域id、地图当前区域名
        candidates = []
        cur_loc = state.get("story", {}).get("current_location", "")
        region_id = state.get("world_map", {}).get("current_region_id", "")
        cur_region_name = state.get("world_map", {}).get("current_region", "")

        for c in (cur_loc, cur_region_name, region_id):
            if c:
                candidates.append(str(c).strip())

        # 精确匹配区域名
        for name in candidates:
            for r in regions:
                if r.get("name") and r.get("name").lower() == name.lower():
                    return r
        # 模糊匹配（区域名含在地点里，或反之）
        for name in candidates:
            for r in regions:
                rn = (r.get("name") or "").lower()
                if rn and (rn in name.lower() or name.lower() in rn):
                    return r
        return None

    def _build_region_context(self, region: Dict, ws: Dict) -> str:
        """构建当前区域的完整本地设定（地理/气候/地点/危险/势力/NPC）"""
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

        # 区域危险/怪物（带特性）
        region_dangers = region.get("dangers", [])
        monster_types = ws.get("dangers", {}).get("monster_types", [])
        if region_dangers:
            parts.append(f"本区危险：{'、'.join(region_dangers[:5])}")
        elif monster_types:
            names = [m.get("name", str(m)) for m in monster_types[:4] if isinstance(m, dict)]
            parts.append(f"常见怪物：{'、'.join(names)}")

        # ── 本区驻留势力（大势力跨区域，注入理念/领袖/立场）──
        factions = ws.get("factions", [])
        active_factions = []
        if factions:
            for f in factions[:3]:
                if isinstance(f, dict):
                    parts.append(
                        f"势力『{f.get('name','?')}』：{str(f.get('ideology') or f.get('description') or '')[:120]}"
                        f"{'，领袖：' + str(f.get('leader')) if f.get('leader') else ''}"
                    )
            active_factions = [f.get("name", "") for f in factions[:3] if isinstance(f, dict)]

        # ── 本区可交互 NPC（由势力/区域派生，保证与世界观一致）──
        npcs = self._derive_region_npcs(region, active_factions)
        if npcs:
            parts.append(f"本区人物：{'；'.join(npcs)}")

        return "\n".join(parts)

    def _derive_region_npcs(self, region: Dict, active_factions: list) -> list:
        """基于区域和势力派生本区NPC（规则化，不额外调LLM）"""
        rname = (region.get("name") or "").lower()
        key_locs = region.get("key_locations", [])
        locs_str = "，".join(key_locs[:3]) if key_locs else rname

        npcs = []
        # 取主要势力名（大势力在此区域的代表）
        main_faction = active_factions[0] if active_factions else "当地势力"

        # 通用但贴合区域的NPC类型
        if "forest" in rname or "wood" in rname or "magic" in rname:
            npcs.append(f"{main_faction}在此镇守的队长")
            npcs.append(f"{locs_str}的本地猎人/药师")
        elif "water" in rname or "lake" in rname or "river" in rname or "iron" in rname:
            npcs.append(f"{main_faction}在港口/矿区的管事")
            npcs.append(f"{locs_str}的船夫/矿工")
        elif "high" in rname or "wind" in rname or "sky" in rname:
            npcs.append(f"{main_faction}在高空据点的观察员")
            npcs.append(f"{locs_str}的风向导航员")
        elif "shadow" in rname or "dark" in rname or "tenebr" in rname:
            npcs.append(f"{main_faction}潜伏在此的密探")
            npcs.append(f"{locs_str}的守夜人")
        else:
            npcs.append(f"{locs_str}的{main_faction}联络人")
            npcs.append(f"{locs_str}的本地旅店老板")

        # 若区域有首领/守护者描述，补充
        return npcs[:3]

    def _build_character_context(self, state: Dict) -> str:
        """构建角色状态（含用户同伴角色）"""
        char = state.get("character", {})
        stats = char.get("stats", {})

        parts = [
            f"角色：{char.get('name', '无名')}（{char.get('class_name', '战士')} Lv.{char.get('level', 1)}）",
            f"HP: {char.get('hp', 0)}/{char.get('max_hp', 0)}",
            f"MP: {char.get('mp', 0)}/{char.get('max_mp', 0)}",
            f"属性：力量{stats.get('strength',5)} 敏捷{stats.get('agility',5)} 智力{stats.get('intelligence',5)} 体质{stats.get('vitality',5)} 运气{stats.get('luck',5)}",
            f"技能：{'、'.join(char.get('skills', [])) or '无'}",
            f"装备：{'、'.join([e.get('name','') for e in char.get('equipment', [])]) or '无'}",
            f"金币：{char.get('gold', 0)}",
        ]

        # 用户同伴角色（重要：让LLM知道有两个主角一起冒险）
        user_char = state.get("user_character", {})
        if user_char.get("class_name") or user_char.get("name"):
            u_stats = user_char.get("stats", {})
            parts.append("")
            parts.append(f"同伴：{user_char.get('name', '用户')}（{user_char.get('class_name', '冒险者')} Lv.{user_char.get('level', 1)}）")
            parts.append(f"同伴HP: {user_char.get('hp', 0)}/{user_char.get('max_hp', 0)}")
            parts.append(f"同伴MP: {user_char.get('mp', 0)}/{user_char.get('max_mp', 0)}")
            parts.append(f"同伴属性：力量{u_stats.get('strength',5)} 敏捷{u_stats.get('agility',5)} 智力{u_stats.get('intelligence',5)} 体质{u_stats.get('vitality',5)} 运气{u_stats.get('luck',5)}")
            parts.append(f"同伴技能：{'、'.join(user_char.get('skills', [])) or '无'}")
            parts.append(f"同伴装备：{'、'.join([e.get('name','') for e in user_char.get('equipment', [])]) or '无'}")
            parts.append(f"（{char.get('name', 'AI')} 与 {user_char.get('name', '用户')} 是一起冒险的同伴，行动中提到「两人」「我们」「他俩」时，默认就是指他们俩，不要写成其他NPC）")

        # 战斗状态（让 LLM 知道当前是否在战斗中）
        in_combat = state.get("in_combat", False)
        enemies = state.get("enemies", [])
        if in_combat and enemies:
            alive = [e for e in enemies if e.get("hp", 0) > 0]
            if alive:
                _enemy_descs = [f"{e.get('name','?')}(HP:{e.get('hp',0)})" for e in alive]
                parts.append("")
                parts.append(f"【战斗中】当前敌人：{', '.join(_enemy_descs)}")
                parts.append("战斗正在进行，叙事应描述交锋过程，不要生成新敌人或切换地点。")
            else:
                parts.append("")
                parts.append("【战斗中】所有敌人已被击败，战斗即将结束。")
        return "\n".join(parts)

    def _build_story_context(self, state: Dict) -> str:
        """构建故事上下文（最近5段，含行动和结果 + 未解决的剧情钩子）"""
        history = state.get("story", {}).get("history", [])
        if not history:
            return "（故事刚刚开始）"

        # 检查最近一条历史是否有战斗胜利，如有则在上下文最前面突出警告
        combat_warning = ""
        last_h = history[-1] if history else {}
        if last_h.get('combat_result') and last_h['combat_result'].get('victory'):
            _defeated = last_h['combat_result'].get('enemies_defeated', [])
            _defeated_str = "、".join(_defeated) if _defeated else "所有敌人"
            combat_warning = f"⚠️【重要·最近战斗结果】{_defeated_str} 已在上一回合被全部击败并死亡。叙事中绝不能让这些已死亡的敌人再次出现或还活着，应描述战后的场景（清理战场、休整、推进剧情）。\n\n"

        recent = history[-5:]
        parts = []
        for h in recent:
            chapter = h.get('chapter', 1)
            action = h.get('action', '')
            summary = h.get('summary', '')
            outcome = h.get('outcome', '')
            # 显示战斗结果
            combat_info = ""
            if h.get('combat_result'):
                cr = h['combat_result']
                if cr.get('victory'):
                    defeated = ', '.join(cr.get('enemies_defeated', []))
                    combat_info = f" [战斗胜利：击败{defeated}]"
                else:
                    combat_info = f" [战斗进行中：{cr.get('combat_summary', '')}]"
            if action:
                parts.append(f"[第{chapter}章] 行动：{action}\n结果：{summary}（{outcome}）{combat_info}")
            else:
                parts.append(f"[第{chapter}章] {summary}{combat_info}")
        text = combat_warning + "\n".join(parts)

        # 附加未解决的剧情钩子（LLM 上一段返回的，必须承接）
        hooks = state.get("story", {}).get("unresolved_hooks", [])
        if hooks:
            text += "\n\n【必须承接的剧情钩子】（叙事必须呼应这些未解决的悬念）"
            for hook in hooks[-4:]:  # 最近 4 个钩子
                text += f"\n- {hook}"
        return text

    def generate_scene(self, state: Dict, map_context: str = "") -> Dict:
        """
        生成新场景：场景描述 + 2-4个选项。
        不预生成后续内容，等用户选择后再推进。
        map_context: 地图上下文信息（区域、怪物、NPC等）
        """
        char = state.get("character", {})
        world_ctx = self._build_world_context(state)
        char_ctx = self._build_character_context(state)
        story_ctx = self._build_story_context(state)
        chapter = state.get("story", {}).get("current_chapter", 1)
        day = state.get("play_time_days", 1)

        # 当前场景提示
        current_scene = state.get("story", {}).get("scene_description", "")
        current_location = state.get("story", {}).get("current_location", "")

        # ── 隐藏结局方向提示（仅系统可见，不透露结局）──
        ending_hint = ""
        ending_region_hint = ""
        try:
            ending_data = state.get("hidden_ending")
            if ending_data and not ending_data.get("triggered", False):
                from simlife.backend.ending_system import HiddenEnding
                ending = HiddenEnding.from_dict(ending_data)
                hint = ending.get_stage_hint()
                if hint:
                    ending_hint = f"【世界暗流】{hint}"
                # 如果当前阶段是区域相关，额外引导生成前往该区域的选项
                stage = ending.get_current_stage()
                if stage:
                    stage_type = stage.get("type", "")
                    conditions = stage.get("conditions", {})
                    if stage_type == "arrival":
                        target_region = conditions.get("region_id", "")
                        if target_region:
                            ending_region_hint = f"（暗中引导：角色的探索方向应逐步指向『{target_region}』，但不是强制的）"
                    elif stage_type == "explore":
                        target_type = conditions.get("region_type", "")
                        type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城", "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(target_type, target_type)
                        if target_type:
                            ending_region_hint = f"（暗中引导：角色应逐步前往未探索的{type_label}区域探索）"
        except Exception:
            pass

        prompt = f"""你是死亡模式人生模拟器的叙事Agent。请为角色生成下一段场景。

【世界观】
{world_ctx}

【角色状态】
{char_ctx}

【故事背景】（最近行动记录）
{story_ctx}
当前：第{chapter}章 · 第{day}天
当前地点：{current_location or '未知（刚开始冒险）'}

【地图信息】
{map_context or '（无地图信息）'}

{ending_hint}

{ending_region_hint}

【设计原则】
1. 场景必须有明确的地点名称，地点要在世界观范围内，不能随意跳跃
2. 场景要有紧张感和危险可能，但不一定每场都战斗
3. 选项要有策略性：不同选项对应不同风险/收益
4. 选项中至少包含一个"冒险"选项和一个"保守"选项
5. 场景描述要沉浸，2-4句话描述环境和氛围，必须提到角色所在的地点
6. 不要透露选项背后的具体数值后果，保持信息不对称
7. 严格贴合世界观，不出现世界观外的元素
8. 场景可以是：探索、遭遇战、NPC互动、陷阱、休息点、宝箱等
9. 【地点连续性·最重要】新场景必须承接上一段行动的结果。如果上一段行动在某个地点发生，新场景必须在同一地点或合理延伸的相邻地点。绝不能凭空跳转到与上一段行动无关的地点。
9a.【区域一致性·最重要】玩家当前区域已在【世界观】的"【当前区域】"列出。所有场景必须在当前区域的真实设定范围内发生：只能使用该区域的【关键地点】【本区危险】【本区人物】【驻留势力】，绝不能凭空发明该区域不存在的地点、势力或生物。
10. 如果故事背景中显示角色刚到达某处，新场景应描述该处的环境，而非其他地方
11. 如果地图信息中有NPC，场景中可以包含与NPC互动的选项
12. 如果地图信息中有怪物，场景中可以包含战斗或躲避的选项
13. 如果地图信息中有BOSS，高风险选项可以触发BOSS战

返回JSON格式：
{{
  "scene_id": "scene_唯一英文id",
  "location": "具体地点名称（必须与上一段行动的地点一致或相邻）",
  "description": "场景描述（2-4句，沉浸式，必须包含地点信息，必须承接上一段行动的结果）",
  "choices": [
    {{"id": "A", "text": "选项描述", "risk": "low/medium/high", "type": "combat/explore/social/escape/rest/trade"}},
    {{"id": "B", "text": "选项描述", "risk": "low/medium/high", "type": "combat/explore/social/escape/rest/trade"}},
    ...
  ]
}}

只返回JSON，不要其他文字。"""

        try:
            response = self.llm.generate(prompt, max_tokens=800, temperature=0.85, thinking=False)
            response = response.strip()
            # 清理 LLM 输出：提取 JSON
            result = self._extract_json(response)

            # 如果返回数组，取第一个
            if isinstance(result, list):
                result = result[0] if result and isinstance(result[0], dict) else {}

            if not isinstance(result, dict):
                return self._default_scene(chapter, day)

            return {
                "scene_id": str(result.get("scene_id", f"scene_{chapter}_{day}")),
                "location": str(result.get("location", "")),
                "description": str(result.get("description", "")),
                "choices": [
                    {
                        "id": str(c.get("id", chr(65 + i))),
                        "text": str(c.get("text", "")),
                        "risk": str(c.get("risk", "medium")),
                        "type": str(c.get("type", "explore")),
                    }
                    for i, c in enumerate(result.get("choices", [])[:4])
                    if isinstance(c, dict)
                ],
            }
        except Exception as e:
            print(f"[DeathMode] 场景生成失败: {e}")
            return self._default_scene(chapter, day)

    def process_action(self, state: Dict, action: str, action_type: str = "choice", sender: str = "user") -> Dict:
        """
        处理用户行动，生成叙事结果。
        action: 用户选择的选项ID 或 自由输入的行动描述
        action_type: "choice" (选择预设选项) / "free" (自由输入)
        sender: "user"（用户发的指令）或 "ai"（系统角色发的指令，行动中的「我」指AI角色）
        返回: {"narrative": "叙事文本", "outcome": "...", "combat_triggered": bool}
        """
        char = state.get("character", {})
        user_char = state.get("user_character", {})
        world_ctx = self._build_world_context(state)
        char_ctx = self._build_character_context(state)
        current_scene = state.get("story", {}).get("scene_description", "")
        current_location = state.get("story", {}).get("current_location", "")
        choices = state.get("story", {}).get("choices", [])

        # ── 构建最近行动历史（让LLM知道之前发生了什么）──
        history = state.get("story", {}).get("history", [])
        recent_history = history[-5:] if history else []  # 最近5条
        history_ctx = ""
        if recent_history:
            history_lines = []
            for h in recent_history:
                _act = h.get("action", "")
                _sum = h.get("summary", "")
                _loc = h.get("location", "")
                _combat = h.get("combat_result")
                _combat_info = ""
                if _combat:
                    if _combat.get("victory"):
                        _defeated = "、".join(_combat.get("enemies_defeated", [])) or "所有敌人"
                        _combat_info = f" [✅战斗胜利：{_defeated}已被全部击败并死亡，不能再出现]"
                    else:
                        _combat_info = f" [⚔️战斗中：{_combat.get('combat_summary', '')}]"
                if _act and _sum:
                    history_lines.append(f"  • 行动：{_act}\n    结果：{_sum[:120]}{_combat_info}" + (f"（地点：{_loc}）" if _loc else ""))
            if history_lines:
                history_ctx = "【最近行动记录】（必须保持连续性，不能与以下内容矛盾）\n" + "\n".join(history_lines) + "\n"

            # 如果最近一条是战斗胜利，在history_ctx最前面加醒目警告
            _last = recent_history[-1] if recent_history else {}
            if _last.get("combat_result") and _last["combat_result"].get("victory"):
                _defeated = "、".join(_last["combat_result"].get("enemies_defeated", [])) or "所有敌人"
                history_ctx = f"⚠️【重要·上一回合战斗结果】{_defeated} 已在上一回合被全部击败并死亡。叙事中绝不能让这些已死亡的敌人再次出现或还活着，应描述战后的场景（清理战场、休整、推进剧情、引出新威胁）。\n\n" + history_ctx

        # 未解决的剧情钩子
        hooks = state.get("story", {}).get("unresolved_hooks", [])
        hooks_ctx = ""
        if hooks:
            hooks_ctx = "【必须承接的剧情钩子】\n" + "\n".join(f"  - {h}" for h in hooks) + "\n"

        # 已击败的敌人列表（防止LLM复活死去的敌人）
        defeated_enemies = state.get("defeated_enemies", [])
        defeated_ctx = ""
        if defeated_enemies:
            recent_defeated = defeated_enemies[-10:]  # 最近10个
            defeated_ctx = f"【已击败的敌人·绝不能复活】以下敌人已被击败并死亡，叙事中绝不能让它们再次出现、还活着或重新战斗：{', '.join(recent_defeated)}\n"

        # ── 识别行动主角 ──
        # sender="ai"：行动由 A层（系统角色）发起，行动中的「我」指 AI角色
        # sender="user"：行动由用户发起，行动中的「我」指用户角色
        _ai_name = char.get("name", "焕灵")
        _user_name = user_char.get("name", "你") if user_char.get("class_name") else ""
        _action_lower = (action or "").strip()

        # 默认主角由 sender 决定
        if sender == "ai":
            _subject = _ai_name or "AI角色"
            _default_actor = _ai_name
        else:
            _subject = _user_name or "你"
            _default_actor = _user_name

        # 行动中明确提到对方名字 → 可切换主角（但群体行动仍以发起者为主）
        _ai_mentioned = bool(_ai_name and _ai_name in _action_lower)
        _user_mentioned = bool(_user_name and _user_name in _action_lower)
        if _ai_mentioned and not _user_mentioned and sender == "user":
            # 用户明确提到 AI角色 → 由 AI角色执行
            _subject = _ai_name

        # 群体指代检测：「两人/我们/俩/双」表示两人一起在场
        # 注意：群体指代只表示两人都在场，不改变行动主体（发起者仍是主角）
        _group_keywords = ["两人", "我们", "我俩", "俩", "双人", "两人一起", "他俩"]
        _is_group_action = any(k in _action_lower for k in _group_keywords)
        if _is_group_action and _ai_name and _user_name:
            _subject_hint = (
                f"【行动主角】本行动由『{_subject}』发起执行（行动中的「我」就是{_subject}）。"
                f"叙事必须以『{_subject}』为主语，用其名字称呼。"
                f"重要：『{_ai_name}』和『{_user_name}』是一起冒险的同伴，两人都在场。"
                f"行动中出现的「两人/我们/我俩」就是指{_ai_name}和{_user_name}两人，绝不能写成其他NPC。"
                f"场景中其他NPC（如艾德蒙、旅店老板等）只能作为配角出现，不能替换掉这两人中的任何一个。"
            )
        else:
            _subject_hint = (
                f"【行动主角】本行动由『{_subject}』执行（行动中的「我」就是{_subject}）。"
                f"叙事必须以此角色为主语（用其名字），不要写成其他角色。"
            )

        # 如果是选择预设选项，找到对应的选项描述
        action_desc = action
        if action_type == "choice":
            for c in choices:
                if c.get("id") == action:
                    action_desc = c.get("text", action)
                    break

        # 任务系统上下文：当前进行中任务 + 已有委托 offer 数量
        from simlife.backend.quest_system import QuestSystem
        quest_summary = QuestSystem.get_active_quests_summary(state)
        offers_count = len(QuestSystem.get_available_offers(state))

        # ── 隐藏结局方向提示（仅系统可见，不透露结局）──
        ending_hint = ""
        ending_region_hint = ""
        try:
            ending_data = state.get("hidden_ending")
            if ending_data and not ending_data.get("triggered", False):
                from simlife.backend.ending_system import HiddenEnding
                ending = HiddenEnding.from_dict(ending_data)
                hint = ending.get_stage_hint()
                if hint:
                    ending_hint = f"\n【世界暗流】{hint}\n"
                # 区域引导
                stage = ending.get_current_stage()
                if stage:
                    stage_type = stage.get("type", "")
                    conditions = stage.get("conditions", {})
                    if stage_type == "arrival":
                        target_region = conditions.get("region_id", "")
                        if target_region:
                            ending_region_hint = f"\n【命运指向】暗中的线索指向『{target_region}』，那里可能有重要的发现。\n"
                    elif stage_type == "explore":
                        target_type = conditions.get("region_type", "")
                        type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城", "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(target_type, target_type)
                        if target_type:
                            ending_region_hint = f"\n【命运指向】未探索的{type_label}区域中隐藏着关键线索。\n"
        except Exception:
            pass
        # 玩家等级影响难度
        char_level = char.get("level", 1)
        # 玩家最近是否在和 NPC 对话 / 看告示板 / 听传闻
        action_lower = (action_desc or "").lower()
        quest_trigger_hints = any(k in action_lower for k in [
            "酒馆", "老板", "委托", "任务", "告示", "传闻", "打听", "聊天",
            "对话", "问", "找", "见面", "商人", "铁匠", "村长", "长老",
            "tavern", "quest", "notice", "talk", "ask", "chat", "rumor",
        ])

        prompt = f"""你是死亡模式人生模拟器的叙事Agent。角色做出了行动，请生成结果叙事。

【世界观】
{world_ctx}

【角色状态】
{char_ctx}

{history_ctx}
{hooks_ctx}{defeated_ctx}
【当前场景】
当前地点：{current_location or '未知'}
场景描述：{current_scene or '（无特定场景，参考最近行动记录）'}

【角色行动】
{action_desc}

{_subject_hint}

{("【当前任务】" + chr(10) + quest_summary) if quest_summary else ""}
【已有待接任务委托】{offers_count} 个
{ending_hint}{ending_region_hint}
【设计原则】
1. 叙事要简短有力（3-5句话），描述行动的结果
2. 不要替数值系统做判定（不要说"你赢了"或"你死了"），只描述过程
3. 如果是战斗行动，描述交锋过程，不要写最终结果
4. 如果是探索行动，描述发现了什么或触发了什么
5. 如果是社交行动，描述对方反应
6. 保持紧张感，但不透露具体数值
7. 结尾留下"接下来会发生什么"的悬念
8. 【地点连续性·最严格】叙事地点必须等于当前地点（{current_location or '未知'}）。除非玩家明确说"前往XX/离开这里/去XX"，否则 new_location 必须填 null，叙事地点不得改变。绝不可在玩家只说"查看/清掉/攻击"等原地行动时擅自切换地点。
9. 如果行动涉及移动（如"前往XX"、"探索XX"），叙事应描述到达该处或移动过程，并在new_location中填写新地点
10. 如果行动不涉及移动，new_location填null（保持原地）
11. 【剧情钩子承接】如果上方"必须承接的剧情钩子"列表非空，叙事必须显式呼应其中至少一个钩子（描述其后续），不得装作没看到
12. 【区域一致性·最严格】当前区域和设定已在【世界观】的"【当前区域】"给出。叙事只能用当前区域真实的【关键地点】【本区危险】【本区人物】【驻留势力】。绝不能凭空发明该区域不存在的地点、势力、NPC或生物。若行动涉及进入新区域（如"进入地下城""前往XX层"），必须在描述中体现该区域的独特设定（环境/危险/势力），new_location 填新地点。
13. 【势力一致性】叙事涉及势力时，必须贴合该势力的理念与立场（已在【当前区域】列出），如暗黑公会的杀戮掠夺、法师议会的求索、解放军的纪律等。NPC 的言行要符合其所属势力的立场。
14. 【行动连续性·最重要】必须参考【最近行动记录】，当前行动是之前行动的延续。NPC名字、地点、对话内容必须与之前一致。如果之前在跟某个NPC对话，当前必须还是那个NPC。如果之前在某个地点，当前必须还在那个地点（除非行动明确涉及移动）。
15. 【战斗状态感知·关键】如果【角色状态】中标注了【战斗中】，说明战斗正在进行：叙事必须描述战斗交锋过程，绝不能生成新敌人（spotted_enemies 填 null），绝不能切换地点（new_location 填 null）。如果【最近行动记录】中有[战斗胜利]，说明战斗刚结束：叙事应描述战后的短暂喘息或清理战场，不要假装敌人还活着。
16. 【角色名约束·最严格】叙事中只能使用以下角色名：{char.get('name', 'AI')}（系统角色）和{user_char.get('name', '用户')}（用户角色）。绝不能编造其他角色名（如 turent、张三等），绝不能把技能或攻击归属到不存在的角色身上。

【任务系统联动·重要】
当角色的行动符合以下情况之一时，应生成 quest_offers（任务委托）：
- 与 NPC 对话（酒馆老板、村长、商人、铁匠、长老等）
- 查看告示板、打听消息、听传闻
- 探索时发现需要帮助的场景
- 当前已有任务完成，NPC 提出后续委托

任务难度根据角色等级（Lv.{char_level}）决定：
- 简单 (easy)：单一目标，如"杀3只史莱姆"——适合低等级
- 普通 (normal)：2-3个目标，如"杀怪+收集"——适合中等级
- 困难 (hard)：系列任务，多个 offer 共享同一个 series_id，按 series_order 递增（1,2,3...）——适合高等级或剧情节点

限制规则：
- 当前若已有 {offers_count} 个待接委托，且 ≥ 3 个，则不要再生成新委托（填 null）
- 任务目标关键词必须是游戏内可触发的：kill（击杀敌人）, collect（获得物品）, visit_location（进入地点）, talk_npc（对话NPC）
- rewards 要合理：easy 给 exp 20-40 / gold 10-30；normal 给 exp 40-80 / gold 30-60；hard 给 exp 80-200 / gold 50-150
- 系列任务时，series_id 用英文蛇形命名（如 "series_dark_guild_probe"），series_title 给中文名

返回JSON格式（重要：narrative控制在150字以内，确保outcome_type等后续字段能完整输出）：
{{
  "narrative": "结果叙事（2-3句，不超过150字）",
  "outcome_type": "combat_success/combat_fail/discovery/social_response/trap/escape/rest/trade/nothing",
  "next_tension": "low/medium/high",
  "new_location": "新地点名称" 或 null,
  "items_gained": ["物品名1", "物品名2"] 或 null,
  "gold_spent": 0 或 null,
  "gold_gained": 0 或 null,
  "hp_change": 0 或 null,
  "mp_change": 0 或 null,
  "quest_offers": [
    {{
      "title": "任务标题（中文）",
      "description": "任务描述（NPC说的话或委托内容）",
      "quest_giver": "委托人名（如：酒馆老板）",
      "location_hint": "任务地点提示（可选）",
      "difficulty": "easy/normal/hard",
      "series_id": "系列ID（仅系列任务填，否则 null）",
      "series_order": 1,
      "series_title": "系列名（仅系列任务首条填）",
      "series_description": "系列简介（仅系列任务首条填）",
      "objectives": [
        {{"type": "kill/collect/visit_location/talk_npc", "target_keyword": "英文关键词（如 slime）", "count": 3}}
      ],
      "rewards": {{"exp": 40, "gold": 25}},
      "auto_complete": true
    }}
  ] 或 null,
  "spotted_enemies": [
    {{"name": "敌人名（英文，如 Elemental Slime）", "count": 3}}
  ] 或 null,
  "unresolved_hooks": ["本段叙事留下的悬念1（一句话）", "悬念2"] 或 null
}}

物品/金币规则：
- 如果角色购买了物品，必须在items_gained中列出物品名，在gold_spent中填写花费金额
- 如果角色出售了物品，在gold_gained中填写获得金额
- 如果角色使用了药水/食物恢复，在hp_change/mp_change中填写恢复量
- 战斗伤害不要填在hp_change里，战斗系统会自动处理
- 如果没有任何物品/金币变动，对应字段填null

任务生成规则：
- 仅在角色行动合理触发时才生成 quest_offers，否则填 null
- 一次可生成 1-3 个 offer（系列任务时多个）
- 不要重复生成已存在的委托（参考"已有待接任务委托"数量）

spotted_enemies 规则（关键！）：
- 当叙事描述中出现了具体的敌人（如"三只史莱姆吸附在岩壁上"），必须在 spotted_enemies 里列出这些敌人
- name 用英文（如 Elemental Slime, Goblin Scout, Tidal Wraith），与叙事描述对应
- count 是叙事中提到的数量
- 玩家下回合说"清掉这些怪/扫荡小怪"时，战斗系统会用这些敌人，不会随机生成
- 如果叙事没有提到具体敌人，填 null

unresolved_hooks 规则：
- 这段叙事留下的悬念，例如"地精独眼闪烁危险光芒"、"身后传来非人呼吸声"
- 一句话一条，简短描述
- 最多 2 条
- 后续叙事必须承接这些钩子，不能装作没看到
- 如果叙事没有留下悬念，填 null

只返回JSON，不要其他文字。"""

        try:
            response = self.llm.generate(prompt, max_tokens=1200, temperature=0.8, thinking=False)
            response = response.strip()
            # 清理 LLM 输出：提取 JSON
            result = self._extract_json(response)

            if isinstance(result, list):
                result = result[0] if result and isinstance(result[0], dict) else {}

            if not isinstance(result, dict):
                return {"narrative": "行动执行完毕。", "outcome_type": "nothing", "next_tension": "medium"}

            return {
                "narrative": str(result.get("narrative", "行动执行完毕。")),
                "outcome_type": str(result.get("outcome_type", "nothing")),
                "next_tension": str(result.get("next_tension", "medium")),
                "new_location": result.get("new_location"),
                "items_gained": result.get("items_gained"),
                "gold_spent": result.get("gold_spent"),
                "gold_gained": result.get("gold_gained"),
                "hp_change": result.get("hp_change"),
                "mp_change": result.get("mp_change"),
                "quest_offers": result.get("quest_offers"),
                # 叙事中提到的敌人（玩家"清掉这些怪"时用这些，不再随机生成）
                "spotted_enemies": result.get("spotted_enemies"),
                # 这段叙事留下的未解决钩子（后续必须承接）
                "unresolved_hooks": result.get("unresolved_hooks"),
            }
        except Exception as e:
            print(f"[DeathMode] 行动处理失败: {e}")
            return {"narrative": "行动执行完毕，但结果未知。", "outcome_type": "nothing", "next_tension": "medium"}

    def generate_quick_combat_narrative(self, state: Dict, combat_summary: Dict) -> str:
        """
        快速战斗（扫荡）的总结叙事。
        combat_summary: {
            "rounds": 回合数,
            "enemies_defeated": ["敌人1名", "敌人2名"],
            "total_damage_taken": 总受伤,
            "total_damage_dealt": 总伤害,
            "drops": [{"name": "xxx", "rarity_name": "普通"}],
            "exp_gained": 经验,
            "gold_gained": 金币,
            "key_events": ["第3回合：焕灵暴击击杀史莱姆2", ...]  # 关键事件摘要
        }
        只调用一次LLM，生成一段简短的扫荡总结叙事。
        """
        char = state.get("character", {})
        user_char = state.get("user_character", {})
        enemies = combat_summary.get("enemies_defeated", [])
        rounds = combat_summary.get("rounds", 1)
        dmg_taken = combat_summary.get("total_damage_taken", 0)
        dmg_dealt = combat_summary.get("total_damage_dealt", 0)
        drops = combat_summary.get("drops", [])
        key_events = combat_summary.get("key_events", [])
        exp = combat_summary.get("exp_gained", 0)
        gold = combat_summary.get("gold_gained", 0)

        # 构建关键事件摘要
        events_text = "\n".join(key_events[:5]) if key_events else "（常规扫荡，无特殊事件）"

        # 掉落物品摘要
        drops_text = ""
        if drops:
            drops_text = "掉落：" + "、".join(f"{d.get('name','?')}({d.get('rarity_name','普通')})" for d in drops[:6])

        # 参战角色名
        char_name = char.get("name", "无名")
        user_name = user_char.get("name", "") if user_char.get("class_name") else ""

        prompt = f"""你是死亡模式人生模拟器的叙事Agent。角色刚刚完成了一次快速扫荡战斗，请生成简短的战斗总结叙事。

【角色】
{char_name}（{char.get('class_name', '战士')} Lv.{char.get('level', 1)}）{f'、{user_name}（{user_char.get('class_name', '')} Lv.{user_char.get('level', 1)}）' if user_name else ''}
当前HP: {char.get('hp', 0)}/{char.get('max_hp', 0)}

【战斗地点】（叙事必须围绕此地点，不得跳转）
{state.get('story', {}).get('current_location', '未知地点')}

【战斗数据】
敌人：{'、'.join(enemies) if enemies else '无'}
回合数：{rounds}
总伤害输出：{dmg_dealt}
总受伤：{dmg_taken}
{drops_text if drops_text else ''}
经验+{exp}  金币+{gold}

【关键事件】
{events_text}

【要求】
1. 2-4句话，简洁有力，像战斗日志的结尾叙述
2. 描述战斗的整体过程和结果，不要逐回合描述
3. 如果受伤较多，提一句伤势
4. 如果有掉落好装备，提一句收获
5. 结尾暗示接下来可能发生的事
6. 不要过于冗长，这是扫荡总结，不是详细战斗叙事
7. 【地点严格约束】叙事场景必须围绕上述战斗地点描述，绝不可跳转到无关场景（如矿脉中战斗不得出现"海岸/礁石/海浪"等无关元素）

只返回叙事文本，不要JSON。"""

        try:
            response = self.llm.generate(prompt, max_tokens=300, temperature=0.7, thinking=False)
            return response.strip()
        except Exception as e:
            print(f"[StoryAgent] 快速战斗叙事生成失败: {e}")
            enemy_names = "、".join(enemies) if enemies else "敌人"
            return f"经过{rounds}回合的战斗，{char_name}{'和' + user_name if user_name else ''}扫荡了{enemy_names}。战斗结束，损失{dmg_taken}点生命值，获得{exp}经验和{gold}金币。"

    def generate_death_description(self, state: Dict, death_cause: str) -> str:
        """生成死亡描述"""
        char = state.get("character", {})
        story_ctx = self._build_story_context(state)

        prompt = f"""角色在死亡模式中阵亡了，请写一段简短的死亡描述。

角色：{char.get('name', '无名')}（{char.get('class_name', '战士')} Lv.{char.get('level', 1)}）
死亡原因：{death_cause}
故事背景：{story_ctx}

要求：
1. 2-3句话，有史诗感
2. 不要过于血腥，但要庄重
3. 可以提到角色最后的想法或遗言

只返回描述文本，不要JSON。"""

        try:
            response = self.llm.generate(prompt, max_tokens=200, temperature=0.7, thinking=False)
            return response.strip()
        except Exception:
            return f"{char.get('name', '无名')}在冒险中倒下了，再也无法站起来。"

    def _default_scene(self, chapter: int, day: int) -> Dict:
        """默认场景（LLM失败时）"""
        return {
            "scene_id": f"scene_{chapter}_{day}",
            "description": "你来到了一处陌生的环境，空气中弥漫着不安的气息。",
            "choices": [
                {"id": "A", "text": "小心探索周围", "risk": "medium", "type": "explore"},
                {"id": "B", "text": "寻找掩体观察", "risk": "low", "type": "rest"},
                {"id": "C", "text": "直接前进", "risk": "high", "type": "explore"},
            ],
        }

    @staticmethod
    def _extract_json(text: str):
        """从 LLM 输出中提取 JSON，处理常见格式问题"""
        # 去除 markdown 代码块包裹
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉第一行（```json 或 ```）和最后一行（```）
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 去除 JSON 中的注释（// 和 /* */）
        text = re.sub(r'//.*?$', '', text, flags=re.MULTILINE)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)

        # 去除尾随逗号（, } 或 , ] 中的逗号）
        text = re.sub(r',\s*([}\]])', r'\1', text)

        # 尝试提取 { } 包裹的部分
        brace_start = text.find('{')
        bracket_start = text.find('[')
        if brace_start >= 0 or bracket_start >= 0:
            # 优先从第一个 { 或 [ 开始
            if brace_start >= 0 and (bracket_start < 0 or brace_start <= bracket_start):
                start = brace_start
                # 找到匹配的 }
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start:i+1])
                            except json.JSONDecodeError:
                                break
            elif bracket_start >= 0:
                start = bracket_start
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == '[':
                        depth += 1
                    elif text[i] == ']':
                        depth -= 1
                        if depth == 0:
                            try:
                                return json.loads(text[start:i+1])
                            except json.JSONDecodeError:
                                break

        # 最后再试一次整段
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 全部失败，尝试从截断的 JSON 中提取已有字段（narrative 等）
        _partial = StoryAgent._extract_partial_json(text)
        if _partial:
            return _partial

        print(f"[StoryAgent] JSON提取失败，原始文本: {text[:200]}")
        return None

    @staticmethod
    def _extract_partial_json(text: str):
        """从截断的 JSON 中提取已有字段（LLM token 耗尽时的兜底）
        例如 LLM 只返回了 {"narrative": "很长的叙事..." 就截断了
        会尝试提取 narrative / outcome_type / spotted_enemies 等已完整输出的字段
        """
        if not text or '{' not in text:
            return None

        result = {}
        # 用正则提取已完成的 "key": "value" 或 "key": [...] 或 "key": null
        # 字符串值
        for m in re.finditer(r'"(narrative|outcome_type|next_tension|new_location)"\s*:\s*"((?:[^"\\]|\\.)*)"', text):
            result[m.group(1)] = m.group(2).encode().decode('unicode_escape')
        # null 值
        for m in re.finditer(r'"(new_location|spotted_enemies|unresolved_hooks|items_gained|quest_offers)"\s*:\s*(null)', text):
            result[m.group(1)] = None
        # 数值
        for m in re.finditer(r'"(gold_spent|gold_gained|hp_change|mp_change)"\s*:\s*(-?\d+)', text):
            result[m.group(1)] = int(m.group(2))

        if result.get("narrative"):
            # 确保有 outcome_type，默认 nothing
            result.setdefault("outcome_type", "nothing")
            result.setdefault("next_tension", "medium")
            print(f"[StoryAgent] 从截断JSON中提取到部分字段: {list(result.keys())}")
            return result

        return None
