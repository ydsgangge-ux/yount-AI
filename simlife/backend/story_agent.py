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
        """构建世界观约束"""
        ws = state.get("world_setting", {})
        if not ws or not isinstance(ws, dict):
            return ""

        parts = []
        parts.append(f"世界：{ws.get('world_name', '未知')}")
        parts.append(f"类型：{ws.get('world_type', '未知')}")

        ps = ws.get("power_system", {})
        if ps and isinstance(ps, dict):
            parts.append(f"力量体系：{ps.get('name', '未知')}")

        factions = ws.get("factions", [])
        if factions and isinstance(factions, list):
            faction_names = [f.get("name", "") for f in factions[:4] if isinstance(f, dict)]
            parts.append(f"主要势力：{'、'.join(faction_names)}")

        dangers = ws.get("dangers", {})
        monster_types = dangers.get("monster_types", [])
        if monster_types:
            mt_names = []
            for m in monster_types[:5]:
                if isinstance(m, dict):
                    mt_names.append(m.get("name", str(m)))
                else:
                    mt_names.append(str(m))
            parts.append(f"常见威胁：{'、'.join(mt_names)}")

        regions = ws.get("geography", {}).get("regions", [])
        if regions and isinstance(regions, list):
            region_names = [r.get("name", "") for r in regions[:6] if isinstance(r, dict)]
            parts.append(f"区域：{'、'.join(region_names)}")

        return "\n".join(parts)

    def _build_character_context(self, state: Dict) -> str:
        """构建角色状态"""
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
        return "\n".join(parts)

    def _build_story_context(self, state: Dict) -> str:
        """构建故事上下文（最近3段）"""
        history = state.get("story", {}).get("history", [])
        if not history:
            return "（故事刚刚开始）"

        recent = history[-3:]
        parts = []
        for h in recent:
            parts.append(f"[第{h.get('chapter',1)}章] {h.get('summary', '')}")
        return "\n".join(parts)

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

        prompt = f"""你是死亡模式人生模拟器的叙事Agent。请为角色生成下一段场景。

【世界观】
{world_ctx}

【角色状态】
{char_ctx}

【故事背景】
{story_ctx}
当前：第{chapter}章 · 第{day}天
当前地点：{current_location or '未知（刚开始冒险）'}

【地图信息】
{map_context or '（无地图信息）'}

【设计原则】
1. 场景必须有明确的地点名称，地点要在世界观范围内，不能随意跳跃
2. 场景要有紧张感和危险可能，但不一定每场都战斗
3. 选项要有策略性：不同选项对应不同风险/收益
4. 选项中至少包含一个"冒险"选项和一个"保守"选项
5. 场景描述要沉浸，2-4句话描述环境和氛围，必须提到角色所在的地点
6. 不要透露选项背后的具体数值后果，保持信息不对称
7. 严格贴合世界观，不出现世界观外的元素
8. 场景可以是：探索、遭遇战、NPC互动、陷阱、休息点、宝箱等
9. 地点连续性：如果上一场景在某地，新场景应该与该地点有关联（同区域、相邻区域、或合理的移动）
10. 如果地图信息中有NPC，场景中可以包含与NPC互动的选项
11. 如果地图信息中有怪物，场景中可以包含战斗或躲避的选项
12. 如果地图信息中有BOSS，高风险选项可以触发BOSS战

返回JSON格式：
{{
  "scene_id": "scene_唯一英文id",
  "location": "具体地点名称（如：暗影森林深处、废弃神殿入口、城镇集市等）",
  "description": "场景描述（2-4句，沉浸式，必须包含地点信息）",
  "choices": [
    {{"id": "A", "text": "选项描述", "risk": "low/medium/high", "type": "combat/explore/social/escape/rest/trade"}},
    {{"id": "B", "text": "选项描述", "risk": "low/medium/high", "type": "combat/explore/social/escape/rest/trade"}},
    ...
  ]
}}

只返回JSON，不要其他文字。"""

        try:
            response = self.llm.generate(prompt, max_tokens=800, temperature=0.85)
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:])
                if response.endswith("```"):
                    response = response[:-3]
                response = response.strip()

            result = json.loads(response)

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

    def process_action(self, state: Dict, action: str, action_type: str = "choice") -> Dict:
        """
        处理用户行动，生成叙事结果。
        action: 用户选择的选项ID 或 自由输入的行动描述
        action_type: "choice" (选择预设选项) / "free" (自由输入)
        返回: {"narrative": "叙事文本", "outcome": "...", "combat_triggered": bool}
        """
        char = state.get("character", {})
        world_ctx = self._build_world_context(state)
        char_ctx = self._build_character_context(state)
        current_scene = state.get("story", {}).get("scene_description", "")
        choices = state.get("story", {}).get("choices", [])

        # 如果是选择预设选项，找到对应的选项描述
        action_desc = action
        if action_type == "choice":
            for c in choices:
                if c.get("id") == action:
                    action_desc = c.get("text", action)
                    break

        prompt = f"""你是死亡模式人生模拟器的叙事Agent。角色做出了行动，请生成结果叙事。

【世界观】
{world_ctx}

【角色状态】
{char_ctx}

【当前场景】
{current_scene}

【角色行动】
{action_desc}

【设计原则】
1. 叙事要简短有力（3-5句话），描述行动的结果
2. 不要替数值系统做判定（不要说"你赢了"或"你死了"），只描述过程
3. 如果是战斗行动，描述交锋过程，不要写最终结果
4. 如果是探索行动，描述发现了什么或触发了什么
5. 如果是社交行动，描述对方反应
6. 保持紧张感，但不透露具体数值
7. 结尾留下"接下来会发生什么"的悬念

返回JSON格式：
{{
  "narrative": "结果叙事（3-5句）",
  "outcome_type": "combat_success/combat_fail/discovery/social_response/trap/escape/rest/nothing",
  "next_tension": "low/medium/high"  // 下一段的紧张度暗示
}}

只返回JSON，不要其他文字。"""

        try:
            response = self.llm.generate(prompt, max_tokens=500, temperature=0.8)
            response = response.strip()
            if response.startswith("```"):
                lines = response.split("\n")
                response = "\n".join(lines[1:])
                if response.endswith("```"):
                    response = response[:-3]
                response = response.strip()

            result = json.loads(response)

            if isinstance(result, list):
                result = result[0] if result and isinstance(result[0], dict) else {}

            if not isinstance(result, dict):
                return {"narrative": "行动执行完毕。", "outcome_type": "nothing", "next_tension": "medium"}

            return {
                "narrative": str(result.get("narrative", "行动执行完毕。")),
                "outcome_type": str(result.get("outcome_type", "nothing")),
                "next_tension": str(result.get("next_tension", "medium")),
            }
        except Exception as e:
            print(f"[DeathMode] 行动处理失败: {e}")
            return {"narrative": "行动执行完毕，但结果未知。", "outcome_type": "nothing", "next_tension": "medium"}

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
            response = self.llm.generate(prompt, max_tokens=200, temperature=0.7)
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
