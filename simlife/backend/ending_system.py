"""
隐藏结局系统 — 在世界生成时预设结局，通过多段任务链推动剧情走向终点

核心设计：
- 结局在生成世界观时一起生成，对用户和系统角色完全隐藏
- 结局由多个阶段(stage)组成，每个阶段对应一个区域或关键事件
- 阶段按顺序推进，利用现有 WorldMap 的区域系统（boss_lair 区域是最终决战地）
- 进度检查在每次行动后自动触发
- 结局信息仅系统可见，不暴露给用户或AI角色
"""
import json
import random
from typing import Dict, List, Optional, Tuple


# ── 结局阶段类型 ──
STAGE_ARRIVAL = "arrival"       # 抵达某个区域
STAGE_EXPLORE = "explore"       # 探索类（造访某类区域）
STAGE_COMBAT = "combat"         # 击败特定类型敌人
STAGE_COLLECT = "collect"       # 收集关键物品
STAGE_ALLIANCE = "alliance"     # 联合势力
STAGE_TASK = "task"             # 完成特定任务链（与任务系统联动）
STAGE_CLIMAX = "climax"        # 最终决战
STAGE_RESOLUTION = "resolution" # 结局收尾


class HiddenEnding:
    """隐藏结局 — 不暴露给玩家和AI角色"""

    def __init__(self, data: dict):
        self.ending_id: str = data.get("ending_id", "")
        self.title: str = data.get("title", "")          # 结局标题（仅系统可见）
        self.description: str = data.get("description", "")  # 结局描述
        self.final_goal: str = data.get("final_goal", "")    # 最终目标
        self.stages: List[dict] = data.get("stages", [])     # 阶段列表
        self.current_stage: int = data.get("current_stage", 0)  # 当前阶段索引
        self.triggered: bool = data.get("triggered", False)   # 是否已触发结局
        self.completed: bool = data.get("completed", False)   # 是否已完成

    def to_dict(self) -> dict:
        return {
            "ending_id": self.ending_id,
            "title": self.title,
            "description": self.description,
            "final_goal": self.final_goal,
            "stages": self.stages,
            "current_stage": self.current_stage,
            "triggered": self.triggered,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HiddenEnding":
        return cls(data)

    def get_current_stage(self) -> Optional[dict]:
        """获取当前阶段"""
        if 0 <= self.current_stage < len(self.stages):
            return self.stages[self.current_stage]
        return None

    def get_stage_hint(self) -> str:
        """
        获取当前阶段的方向提示（供 story_agent 使用）
        不透露结局，只给方向线索
        增强：根据阶段类型添加区域引导信息
        """
        stage = self.get_current_stage()
        if not stage:
            return ""
        hint = stage.get("hint", "")
        stage_type = stage.get("type", "")
        conditions = stage.get("conditions", {})

        # 根据阶段类型，附加更明确的引导信息
        extra = ""
        if stage_type == STAGE_ARRIVAL:
            region_id = conditions.get("region_id", "")
            if region_id:
                extra = f"（命运的线索指向『{region_id}』）"
        elif stage_type == STAGE_EXPLORE:
            region_type = conditions.get("region_type", "")
            type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城", "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(region_type, region_type)
            if region_type:
                extra = f"（探索未知的{type_label}，那里藏着关键的线索）"
        elif stage_type == STAGE_TASK:
            task_hint = conditions.get("task_hint", "")
            if task_hint:
                extra = f"（{task_hint}）"

        if hint and extra:
            return f"{hint} {extra}"
        return hint or extra

    def get_stage_hint_for_quest(self) -> str:
        """
        获取当前阶段的方向提示（供任务系统生成任务链时使用）
        返回更丰富的上下文，用于引导LLM生成匹配结局方向的任务
        """
        stage = self.get_current_stage()
        if not stage:
            return ""
        stage_type = stage.get("type", "")
        hint = stage.get("hint", "")
        conditions = stage.get("conditions", {})
        final_goal = self.final_goal

        # 构建任务生成上下文
        parts = []
        parts.append(f"世界命运的暗流正在涌动，最终目标：{final_goal}")

        if stage_type == STAGE_ARRIVAL:
            region_id = conditions.get("region_id", "")
            parts.append(f"当前需要前往『{region_id}』，那里有关键的线索等待发现")
        elif stage_type == STAGE_EXPLORE:
            region_type = conditions.get("region_type", "")
            type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城", "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(region_type, region_type)
            parts.append(f"当前需要深入探索{type_label}区域，寻找隐藏的真相")
        elif stage_type == STAGE_COMBAT:
            enemy_kw = conditions.get("enemy_keyword", "")
            count = conditions.get("count", 1)
            parts.append(f"当前需要击败{count}个{enemy_kw}类型的敌人，削弱暗中的威胁")
        elif stage_type == STAGE_COLLECT:
            item_kw = conditions.get("item_keyword", "")
            count = conditions.get("count", 1)
            parts.append(f"当前需要收集{count}个{item_kw}，这些是解锁关键线索的必需品")
        elif stage_type == STAGE_TASK:
            task_hint = conditions.get("task_hint", "")
            if task_hint:
                parts.append(task_hint)
        elif stage_type == STAGE_CLIMAX:
            parts.append("最终决战临近，需要为终极一战做好准备")

        if hint:
            parts.append(f"暗流提示：{hint}")

        return " | ".join(parts)

    def get_all_stages_hints(self) -> str:
        """
        获取所有阶段的线性方向提示（供 story_agent 完整上下文使用）
        不透露结局，只给一条模糊的方向线索链
        """
        if not self.stages:
            return ""
        hints = []
        for s in self.stages:
            h = s.get("hint", "")
            if h:
                hints.append(h)
        if not hints:
            return ""
        return "世界暗流涌动，命运的线索渐次浮现：\n" + "\n".join(f"· {h}" for h in hints[:3])

    def check_progress(self, state: dict) -> dict:
        """
        检查当前阶段是否完成。
        返回进度更新信息：{"stage_advanced": bool, "new_stage": int, "message": str}
        """
        if self.completed or self.triggered:
            return {"stage_advanced": False, "new_stage": self.current_stage, "message": ""}

        stage = self.get_current_stage()
        if not stage:
            return {"stage_advanced": False, "new_stage": self.current_stage, "message": ""}

        stage_type = stage.get("type", STAGE_EXPLORE)
        conditions = stage.get("conditions", {})
        completed = self._check_stage_conditions(stage_type, conditions, state)

        if completed:
            self.current_stage += 1
            msg = stage.get("completion_message", "")
            # 检查是否所有阶段完成
            if self.current_stage >= len(self.stages):
                self.triggered = True
                return {
                    "stage_advanced": True,
                    "new_stage": self.current_stage,
                    "message": msg,
                    "ending_ready": True,
                }
            return {
                "stage_advanced": True,
                "new_stage": self.current_stage,
                "message": msg,
                "ending_ready": False,
            }

        return {"stage_advanced": False, "new_stage": self.current_stage, "message": ""}

    def _check_stage_conditions(self, stage_type: str, conditions: dict, state: dict) -> bool:
        """检查阶段条件是否满足"""
        if stage_type == STAGE_ARRIVAL:
            # 抵达特定区域
            target_region = conditions.get("region_id", "")
            current_region = state.get("world_map", {}).get("current_region_id", "")
            if current_region and target_region and current_region == target_region:
                return True
            # 也检查区域名匹配
            current_name = state.get("story", {}).get("current_location", "")
            if current_name and target_region and target_region in current_name:
                return True
            # 检查world_map区域名
            regions = state.get("world_map", {}).get("regions", {})
            for rid, rdata in regions.items():
                if rid == target_region or rdata.get("name", "") == target_region:
                    # 玩家当前区域是否等于目标区域
                    cur_rid = state.get("world_map", {}).get("current_region_id", "")
                    if cur_rid == rid:
                        return True
                    # 或者当前地点名包含目标区域名
                    if current_name and target_region in current_name:
                        return True
                    # 或者目标区域名包含在当前地点名中
                    if current_name and rdata.get("name", "") in current_name:
                        return True
            return False

        elif stage_type == STAGE_EXPLORE:
            # 探索了某类区域（如所有wild区域）
            target_type = conditions.get("region_type", "")
            if not target_type:
                return True
            regions = state.get("world_map", {}).get("regions", {})
            for rid, rdata in regions.items():
                if rdata.get("region_type") == target_type and not rdata.get("explored", False):
                    return False
            return True

        elif stage_type == STAGE_COMBAT:
            # 击败特定敌人类型
            target_keyword = conditions.get("enemy_keyword", "").lower()
            target_count = conditions.get("count", 1)
            # 从战斗历史中统计
            defeated = state.get("combat_history", {}).get("defeated_enemies", [])
            count = sum(1 for e in defeated if target_keyword in e.lower())
            return count >= target_count

        elif stage_type == STAGE_COLLECT:
            # 收集关键物品
            item_keyword = conditions.get("item_keyword", "")
            item_count = conditions.get("count", 1)
            # 从背包中检查
            inventory = state.get("character", {}).get("inventory", [])
            # 如果是shared_inventory
            shared = state.get("shared_inventory", [])
            all_items = inventory + shared
            count = 0
            for item in all_items:
                name = item.get("name", "") if isinstance(item, dict) else str(item)
                if item_keyword.lower() in name.lower():
                    count += 1
            return count >= item_count

        elif stage_type == STAGE_ALLIANCE:
            # 联合势力（通过play_time_days判断，简单处理）
            min_days = conditions.get("min_days", 7)
            return state.get("play_time_days", 0) >= min_days

        elif stage_type == STAGE_TASK:
            # 完成任务链：检查特定系列任务是否已全部完成
            series_id = conditions.get("series_id", "")
            task_ids = conditions.get("task_ids", [])
            if series_id:
                # 从任务系统中检查该系列任务是否全部完成
                quests = state.get("quests", {})
                turned_in = quests.get("turned_in_ids", [])
                # 检查该系列下所有任务是否都已交付
                from simlife.backend.quest_system import QuestSystem
                series_quests = QuestSystem.get_quests_by_series(state, series_id)
                if series_quests:
                    all_done = all(q.get("id") in turned_in for q in series_quests)
                    if all_done:
                        return True
            if task_ids:
                quests = state.get("quests", {})
                turned_in = quests.get("turned_in_ids", [])
                return all(tid in turned_in for tid in task_ids)
            # 简单模式：完成任意 active 任务也算
            min_count = conditions.get("min_completed", 0)
            if min_count > 0:
                completed_count = len(quests.get("turned_in_ids", []))
                return completed_count >= min_count
            return False

        elif stage_type == STAGE_CLIMAX:
            # 最终决战：已击败BOSS或抵达final_boss_lair
            boss_lair_defeated = conditions.get("boss_lair_defeated", False)
            if boss_lair_defeated:
                # 检查boss_lair区域是否已击败BOSS
                regions = state.get("world_map", {}).get("regions", {})
                for rid, rdata in regions.items():
                    if rdata.get("region_type") == "boss_lair" and rdata.get("boss_defeated", False):
                        return True
                return False
            # 或者 play_time_days 达到阈值
            min_days = conditions.get("min_days", 30)
            return state.get("play_time_days", 0) >= min_days

        elif stage_type == STAGE_RESOLUTION:
            # 结局收尾：play_time_days 达到或 climax 已完成
            return True

        return False

    def get_ending_narrative_prompt(self, state: dict) -> str:
        """
        获取结局叙事提示（当结局触发时调用）
        用于 story_agent 生成最终结局场景
        """
        if not self.triggered:
            return ""
        last_stage = self.stages[-1] if self.stages else {}
        return f"""【命运终局】
这个世界的故事即将迎来终章。
最终目标：{self.final_goal}
结局描述：{self.description}

请生成一段结局叙事，展现这个世界的命运如何尘埃落定。
不要直接说明"结局"二字，让故事自然走向终点。
"""


def generate_hidden_ending(world_setting: dict, llm_client, world_map=None) -> Optional[HiddenEnding]:
    """
    用LLM为世界观生成一个隐藏结局。
    结局包含：
    - 结局标题和最终目标（仅系统可见）
    - 3-5个阶段，每个阶段有条件和完成提示
    - 阶段类型对应：arrival/explore/combat/collect/alliance/climax/resolution
    - 最终阶段是climax，对应boss_lair区域
    """
    world_name = world_setting.get("world_name", "未知世界")
    world_type = world_setting.get("world_type", "fantasy")
    history = world_setting.get("history", {})
    current_situation = history.get("current_situation", "")[:300]
    factions = world_setting.get("factions", [])
    faction_names = "、".join(f.get("name", "") for f in factions[:4] if isinstance(f, dict))

    # 从world_map获取区域信息（决定结局的阶段对应哪些区域）
    region_info = ""
    boss_lair_name = ""
    if world_map:
        regions = []
        for rid, r in world_map.regions.items():
            regions.append(f"{r.name}({r.region_type})")
        region_info = "区域：" + "、".join(regions)
        # 找到boss_lair
        for rid, r in world_map.regions.items():
            if r.region_type == "boss_lair":
                boss_lair_name = r.name
                break

    prompt = f"""你是一个隐藏在世界观背后的「命运编织者」。请为以下世界设计一个隐藏结局。

世界：{world_name}（{world_type}）
当前局势：{current_situation}
主要势力：{faction_names}
{region_info}

设计要求：
1. 结局必须贴合世界观设定，是当前局势和冲突的自然发展
2. 结局**不能透露给玩家和系统角色**，是系统后台的隐藏信息
3. 结局分3-5个阶段逐步推进，每个阶段对应一个区域或事件
4. 最终阶段(climax)发生在{boss_lair_name or '最终BOSS区域'}
5. 阶段之间是线性关系，前一个完成才能推进到下一个
6. 每个阶段提供一条"方向提示"(hint)，供系统暗中引导剧情走向
7. hint不能透露结局，只给模糊的方向指引（如"暗影中的线索指向北方"）
8. 每个阶段设置完成条件，参考区域类型：
   - arrival: 抵达某区域，设置region_id（对应world_map中的区域id或区域名）
   - explore: 探索某类区域，设置region_type（如wild/dungeon/town）
   - combat: 击败某类敌人，设置enemy_keyword和count
   - collect: 收集关键物品，设置item_keyword和count
   - alliance: 联合势力，设置min_days
   - task: 完成特定任务链，设置series_id或task_hint（任务系统会自动生成匹配的任务）
   - climax: 最终决战，设置min_days或boss_lair_defeated
   - resolution: 结局收尾

输出JSON（只返回JSON，不要其他文字）：
{{
  "title": "结局标题（4-12字，如"暗影终焉"、"王朝覆灭"、"星辰归位"）",
  "description": "结局描述（30-80字，说明最终会发生什么）",
  "final_goal": "最终目标（一句话，如：推翻暴政、封印深渊、统一大陆）",
  "stages": [
    {{
      "hint": "方向提示（不透露结局，15-30字）",
      "type": "arrival/explore/combat/collect/alliance/task/climax/resolution",
      "conditions": {{"region_id": "..."}} 或 {{"region_type": "..."}} 或 {{"enemy_keyword": "...", "count": 3}} 或 {{"task_hint": "..."}} 等，
      "completion_message": "阶段完成时系统可记录的消息（仅系统日志，不展示给用户）"
    }}
  ]
}}"""

    try:
        response = llm_client.generate(prompt, max_tokens=1500, temperature=0.8, thinking=False)
        # 清理markdown
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines).strip()

        # 提取JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            response = json_match.group(0)

        data = json.loads(response)

        # 验证
        stages = data.get("stages", [])
        if not stages or len(stages) < 3:
            print(f"[HiddenEnding] 阶段数不足({len(stages)})，使用默认结局")
            return _default_ending(world_setting, boss_lair_name)

        # 确保最终阶段是climax
        if stages[-1].get("type") != "climax":
            stages[-1]["type"] = "climax"
            stages[-1]["conditions"] = stages[-1].get("conditions", {"min_days": 30})

        # 添加resolution阶段
        stages.append({
            "hint": "一切尘埃落定，命运之轮转到了终点",
            "type": "resolution",
            "conditions": {},
            "completion_message": "结局完成"
        })

        # 生成ending_id
        ending_id = "ending_" + "".join(c for c in data.get("title", "default") if c.isalnum())[:10].lower()

        result = {
            "ending_id": ending_id,
            "title": data.get("title", "命运终局"),
            "description": data.get("description", ""),
            "final_goal": data.get("final_goal", ""),
            "stages": stages,
            "current_stage": 0,
            "triggered": False,
            "completed": False,
        }
        print(f"[HiddenEnding] 生成成功：{result['title']}（{len(stages)}个阶段）")
        return HiddenEnding(result)

    except Exception as e:
        print(f"[HiddenEnding] 生成失败: {e}")
        return _default_ending(world_setting, boss_lair_name)


def _default_ending(world_setting: dict, boss_lair_name: str = "") -> HiddenEnding:
    """生成失败时的默认结局"""
    world_name = world_setting.get("world_name", "未知世界")
    world_type = world_setting.get("world_type", "fantasy")

    default_endings = {
        "fantasy": {
            "title": "暗影终焉",
            "description": f"盘踞在{boss_lair_name or '暗黑城堡'}的邪恶势力终被击败，{world_name}迎来久违的和平。",
            "final_goal": "击败最终BOSS，恢复世界的和平",
        },
        "xianxia": {
            "title": "飞升之路",
            "description": f"历经千辛万苦，终于突破{boss_lair_name or '魔域深渊'}的终极试炼，踏上飞升之路。",
            "final_goal": "突破最终试炼，证道飞升",
        },
        "post_apocalyptic": {
            "title": "新纪元",
            "description": f"在{boss_lair_name or '虫巢母穴'}消灭了灾变源头，人类文明看到了重建的曙光。",
            "final_goal": "消灭灾变源头，为文明重建赢得希望",
        },
        "modern_power": {
            "title": "暗流平息",
            "description": f"捣毁{boss_lair_name or '魔门总坛'}后，暗势力土崩瓦解，世界恢复了表面的平静。",
            "final_goal": "摧毁暗势力的核心，终结这场暗战",
        },
        "scifi": {
            "title": "深空回响",
            "description": f"夺回{boss_lair_name or '指挥舰桥'}的控制权，叛变AI被清除，太空站重返人类掌控。",
            "final_goal": "清除叛变AI，夺回太空站控制权",
        },
    }

    ending_info = default_endings.get(world_type, default_endings["fantasy"])

    stages = [
        {
            "hint": "世界暗流涌动，深渊的低语隐约可闻",
            "type": "explore",
            "conditions": {"region_type": "wild"},
            "completion_message": "初步探索完成，世界的轮廓逐渐清晰",
        },
        {
            "hint": "古老的线索指向更深处的黑暗",
            "type": "explore",
            "conditions": {"region_type": "dungeon"},
            "completion_message": "深入地下城，发现了隐藏的真相碎片",
        },
        {
            "hint": "所有的道路都指向一个最终的目的地",
            "type": "climax",
            "conditions": {"min_days": 20},
            "completion_message": "最终决战的条件已成熟",
        },
        {
            "hint": "一切尘埃落定",
            "type": "resolution",
            "conditions": {},
            "completion_message": "结局完成",
        },
    ]

    return HiddenEnding({
        "ending_id": "ending_default",
        "title": ending_info["title"],
        "description": ending_info["description"],
        "final_goal": ending_info["final_goal"],
        "stages": stages,
        "current_stage": 0,
        "triggered": False,
        "completed": False,
    })