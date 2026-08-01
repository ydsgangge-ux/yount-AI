"""
死亡模式核心引擎 — 整合状态、战斗、成长、故事Agent

流程：
1. 创建角色（选择职业 + 自定义属性 + 选择世界设定）
2. 进入场景（Agent生成场景描述+选项）
3. 用户选择行动
4. 数值系统判定 + Agent叙事
5. 更新状态 → 死亡 or 继续 → 生成下一段场景
"""
import random
import re
from datetime import datetime
from typing import Dict, Optional, List

from simlife.backend.death_mode_state import (
    create_initial_state, save_state, load_state, clear_state,
    save_to_hall, load_hall, get_available_classes, CLASS_TEMPLATES,
)
from simlife.backend.combat_system import CombatSystem, CombatEntity, DefenseAction
from simlife.backend.growth_system import GrowthSystem
from simlife.backend.story_agent import StoryAgent
from simlife.backend.generator import get_llm_client
from simlife.backend.world_map import WorldMap, MapGenerator
from simlife.backend.npc_system import NPCSystem, NPCGenerator
from simlife.backend.equipment_system import EquipmentSystem


class DeathModeEngine:
    """死亡模式引擎"""

    # 类级别缓存，避免每次请求都创建新客户端
    _cached_llm = None
    _cached_agent = None

    @staticmethod
    def _load_user_profile() -> dict:
        """加载 user_profile.json"""
        try:
            from pathlib import Path
            profile_path = Path(__file__).parent.parent / "data" / "user_profile.json"
            if profile_path.exists():
                import json
                content = profile_path.read_text(encoding="utf-8").strip()
                if content:
                    return json.loads(content)
        except Exception:
            pass
        return {}

    def __init__(self):
        if DeathModeEngine._cached_llm is None:
            DeathModeEngine._cached_llm = get_llm_client()
        if DeathModeEngine._cached_agent is None:
            DeathModeEngine._cached_agent = StoryAgent(DeathModeEngine._cached_llm)
        self.llm = DeathModeEngine._cached_llm
        self.agent = DeathModeEngine._cached_agent
        self.state: Optional[Dict] = None
        self.world_map: Optional[WorldMap] = None
        self.npc_system: Optional[NPCSystem] = None

    def _log_action(self, entry_type: str, data: Dict):
        """记录一条行动日志（网页端展示用）"""
        if not self.state:
            return
        from datetime import datetime as _dt
        log_entry = {
            "type": entry_type,
            "time": _dt.now().isoformat(),
            "day": self.state.get("play_time_days", 1),
            "data": data,
        }
        self.state.setdefault("action_log", []).append(log_entry)
        # 限制日志条数（最多500条）
        if len(self.state["action_log"]) > 500:
            self.state["action_log"] = self.state["action_log"][-500:]

    def _log_sweep_action(self, action: str, result: Dict):
        """记录扫荡战斗的行动日志（网页端展示用）"""
        sweep_result = result.get("combat_result", {}) if isinstance(result.get("combat_result"), dict) else {}
        log_data = {
            "action": action,
            "action_type": "free",
            "outcome": "combat_sweep",
            "narrative": result.get("narrative", "")[:300],
        }
        # 战斗信息
        log_data["combat"] = {
            "victory": sweep_result.get("victory", False),
            "enemy_names": sweep_result.get("enemies_defeated", []),
            "combat_log": sweep_result.get("combat_log", []),
            "rounds": sweep_result.get("rounds", 0),
            "is_sweep": True,
        }
        if result.get("exp_gained"):
            log_data["exp_gained"] = result["exp_gained"]
        if result.get("gold_gained"):
            log_data["gold_gained"] = result["gold_gained"]
        if result.get("leveled_up"):
            log_data["leveled_up"] = True
            log_data["new_level"] = result.get("new_level")
        if result.get("character_died"):
            log_data["character_died"] = True
            log_data["death_description"] = result.get("death_description", "")
        if sweep_result.get("drops"):
            log_data["drops"] = sweep_result["drops"]
        self._log_action("action", log_data)

    def _load(self):
        """加载或刷新状态"""
        if self.state is None:
            self.state = load_state()
        # 恢复地图和NPC
        if self.state and self.world_map is None and self.state.get("world_map"):
            self.world_map = WorldMap.from_dict(self.state["world_map"])
        if self.state and self.npc_system is None and self.state.get("npc_system"):
            self.npc_system = NPCSystem.from_dict(self.state["npc_system"])
        # 迁移旧存档：inventory → shared_inventory
        if self.state and not self.state.get("shared_inventory"):
            old_inv = self.state.get("character", {}).get("inventory", [])
            if old_inv:
                self.state["shared_inventory"] = old_inv
                self.state["character"]["inventory"] = []
        # 迁移旧存档：确保 user_character 存在
        if self.state and (not self.state.get("user_character") or not self.state.get("user_character", {}).get("class_name")):
            # 尝试从 user_profile 同步
            up = self._load_user_profile()
            if up and up.get("class_name"):
                self.state["user_character"] = {
                    "name": up.get("name", "用户"),
                    "class_id": up.get("class_id", ""),
                    "class_name": up.get("class_name", ""),
                    "class_icon": up.get("class_icon", "👤"),
                    "level": up.get("level", 1),
                    "hp": up.get("hp", 0), "max_hp": up.get("max_hp", 0),
                    "mp": up.get("mp", 0), "max_mp": up.get("max_mp", 0),
                    "stats": up.get("stats", {"strength": 5, "agility": 5, "intelligence": 5, "vitality": 5, "luck": 5}),
                    "skills": up.get("skills", []),
                    "equipment": up.get("equipment", []),
                    "experience": up.get("experience", 0),
                    "exp_to_next": up.get("exp_to_next", 100),
                    "gold": up.get("gold", 0),
                }
            else:
                self.state["user_character"] = {"name": "用户", "class_id": "", "class_name": "",
                    "class_icon": "👤", "level": 1, "hp": 0, "max_hp": 0, "mp": 0, "max_mp": 0,
                    "stats": {"strength": 5, "agility": 5, "intelligence": 5, "vitality": 5, "luck": 5},
                    "skills": [], "equipment": [], "experience": 0, "exp_to_next": 100, "gold": 0}
        return self.state

    def _save(self):
        """保存状态"""
        if self.state:
            # 同步地图和NPC到状态
            if self.world_map:
                self.state["world_map"] = self.world_map.to_dict()
            if self.npc_system:
                self.state["npc_system"] = self.npc_system.to_dict()
                self.state["npc_death_records"] = self.npc_system.death_records
            save_state(self.state)

    # ── 初始化 ──────────────────────────────────────────

    def start_game(
        self,
        character_name: str,
        class_id: str,
        world_setting: Dict,
        growth_mode: str = "normal",
        custom_stat_points: Optional[Dict] = None,
        user_class_id: str = "",
        user_name: str = "",
    ) -> Dict:
        """开始新游戏"""
        self.state = create_initial_state(
            character_name=character_name,
            class_id=class_id,
            world_setting=world_setting,
            growth_mode=growth_mode,
            custom_stat_points=custom_stat_points,
            user_class_id=user_class_id,
            user_name=user_name,
        )

        # 生成世界地图
        self.world_map = MapGenerator.generate(world_setting, self.llm)
        self.state["world_map"] = self.world_map.to_dict()

        # 生成NPC
        self.npc_system = NPCGenerator.generate_for_world(world_setting, self.world_map, self.llm)
        self.state["npc_system"] = self.npc_system.to_dict()
        self.state["npc_death_records"] = []

        # 设置初始位置为起始区域
        if self.world_map.start_region_id:
            self.state["story"]["current_location"] = self.world_map.start_region_id
            region = self.world_map.get_region(self.world_map.start_region_id)
            if region:
                self.state["story"]["scene_description"] = region.description

        self._save()

        # 记录开始冒险日志
        self._log_action("game_start", {
            "character_name": character_name,
            "class_name": self.state["character"]["class_name"],
            "world_name": world_setting.get("world_name", "未知世界"),
        })
        self._save()

        return self.get_game_state()

    def get_game_state(self) -> Dict:
        """获取当前游戏状态（前端用）"""
        state = self._load()
        if not state:
            return {"active": False, "reason": "no_game"}

        # 如果旧存档没有 action_log，自动补充一条 game_start
        if not state.get("action_log"):
            char = state.get("character", {})
            state["action_log"] = [{
                "type": "game_start",
                "time": state.get("start_time", datetime.now().isoformat()),
                "day": 1,
                "data": {
                    "character_name": char.get("name", "未知"),
                    "class_name": char.get("class_name", ""),
                    "world_name": state.get("world_setting", {}).get("name", "未知世界"),
                }
            }]
            self._save()

        char = state.get("character", {})

        # 天数按实际时间计算：1天=1天（现实时间）
        from datetime import datetime as _dt
        start_time = state.get("start_time")
        if start_time:
            try:
                elapsed = (_dt.now() - _dt.fromisoformat(start_time)).total_seconds()
                play_time_days = max(1, int(elapsed // 86400) + 1)  # 86400秒=1天
            except Exception:
                play_time_days = state.get("play_time_days", 1)
        else:
            play_time_days = state.get("play_time_days", 1)

        return {
            "active": True,
            "is_alive": state.get("is_alive", False),
            "in_combat": state.get("in_combat", False),
            "character": {
                "name": char.get("name", ""),
                "class_name": char.get("class_name", ""),
                "class_icon": char.get("class_icon", ""),
                "level": char.get("level", 1),
                "hp": char.get("hp", 0),
                "max_hp": char.get("max_hp", 0),
                "mp": char.get("mp", 0),
                "max_mp": char.get("max_mp", 0),
                "stats": char.get("stats", {}),
                "skills": char.get("skills", []),
                "awakening_skills": char.get("awakening_skills", []),
                "max_skills": 10,  # 最大技能数
                "equipment": char.get("equipment", []),
                "gold": char.get("gold", 0),
                "experience": char.get("experience", 0),
                "exp_to_next": char.get("exp_to_next", 100),
            },
            "story": {
                "current_chapter": state.get("story", {}).get("current_chapter", 1),
                "current_location": state.get("story", {}).get("current_location", ""),
                "scene_description": state.get("story", {}).get("scene_description", ""),
                "choices": state.get("story", {}).get("choices", []),
                "pending_action": state.get("story", {}).get("pending_action"),
            },
            "enemies": state.get("enemies", []),
            "enemy": state.get("enemy"),  # 兼容旧版
            "play_time_days": play_time_days,
            "kill_count": state.get("kill_count", 0),
            "growth_mode": state.get("growth_mode", "normal"),
            "world_map": state.get("world_map", {}),
            "map_display": self.world_map.get_map_display() if self.world_map else None,
            "npc_death_records": state.get("npc_death_records", []),
            "shared_inventory": state.get("shared_inventory", []),
            "user_character": state.get("user_character", {}),
            "death_pending": state.get("death_pending", False),
            "death_who": state.get("death_who"),
            "last_words": state.get("last_words", ""),
            "ai_character_dead": state.get("ai_character_dead", False),
            "user_character_dead": state.get("user_character_dead", False),
            "action_log": state.get("action_log", [])[-20:],  # 最近20条给A层用
        }

    # ── 场景推进 ──────────────────────────────────────────

    def start_scene(self) -> Dict:
        """开始新场景：Agent生成场景描述+选项（受地图约束）"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}

        # 构建地图上下文给Agent
        map_context = ""
        if self.world_map:
            current_region = self.world_map.get_current_region()
            if current_region:
                map_context = f"当前区域：{current_region.name}（{current_region.description}）\n"
                # 相邻区域
                adjacent = self.world_map.get_adjacent_regions()
                if adjacent:
                    adj_names = [f"{r.name}{'(已探索)' if r.explored else '(未探索)'}" for r in adjacent]
                    map_context += f"可达区域：{'、'.join(adj_names)}\n"
                # 当前区域怪物
                if current_region.monsters:
                    m_names = [m.get("name", "?") for m in current_region.monsters]
                    map_context += f"此处出没：{'、'.join(m_names)}\n"
                # 当前区域BOSS
                if current_region.boss and not current_region.boss_defeated:
                    map_context += f"BOSS：{current_region.boss.get('name', '?')} 镇守此地\n"
                # 当前区域NPC
                if self.npc_system:
                    npcs = self.npc_system.get_npcs_in_location(current_region.region_id)
                    if npcs:
                        npc_names = [f"{n.name}({n.role})" for n in npcs]
                        map_context += f"此处人物：{'、'.join(npc_names)}\n"

        scene = self.agent.generate_scene(state, map_context=map_context)

        # 标记当前区域为已探索
        if self.world_map and self.world_map.current_region_id:
            self.world_map.explore_region(self.world_map.current_region_id)

        state["story"]["scene_description"] = scene["description"]
        state["story"]["choices"] = scene["choices"]
        state["story"]["current_location"] = scene.get("location", "")
        state["story"]["pending_action"] = None
        self._save()

        # 记录场景日志
        self._log_action("scene", {
            "description": scene["description"][:200],
            "location": scene.get("location", ""),
            "choices": [{"id": c.get("id"), "text": c.get("text"), "risk": c.get("risk")} for c in scene.get("choices", [])],
        })
        self._save()

        return {
            "scene_description": scene["description"],
            "location": scene.get("location", ""),
            "choices": scene["choices"],
        }

    def process_choice(self, choice_id: str = None, free_action: str = None, sender: str = "user") -> Dict:
        """
        处理用户选择或自由行动。
        sender: "user"（用户发的指令）或 "ai"（系统角色发的指令）
        返回: {
            "narrative": "叙事文本",
            "combat_result": {...} or None,
            "leveled_up": bool,
            "character_died": bool,
            "death_description": str or None,
            "next_scene": bool  // 是否需要生成新场景
        }
        """
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}

        # ── 死亡悬停状态：等待用户选择继续或结束 ──
        if state.get("death_pending"):
            action = free_action if free_action else choice_id
            if action and any(k in action for k in ("继续", "continue", "前行", "独自", "前进")):
                # 用户强制继续
                cont_result = self._continue_after_death(state)
                return {
                    "narrative": cont_result.get("message", ""),
                    "death_pending": False,
                    "continued_after_death": True,
                    "who_died": cont_result.get("who_died"),
                    "in_combat": False,
                }
            elif action and any(k in action for k in ("结束", "放弃", "放弃冒险", "安息", "就此", "游戏结束")):
                # 用户确认结束
                self._confirm_death(state)
                return {
                    "narrative": "冒险到此结束……",
                    "game_over": True,
                }
            else:
                # 未选择，提示用户
                who = state.get("death_who", "ai")
                dead_name = state.get("character" if who == "ai" else "user_character", {}).get("name", "角色")
                last_words = state.get("last_words", "")
                return {
                    "narrative": f"{dead_name}已经倒下……\n💬 临终遗言：「{last_words}」\n\n回复「继续」独自冒险，或「结束」让冒险落幕。",
                    "death_pending": True,
                    "who_died": who,
                }

        # 确定行动
        action = free_action if free_action else choice_id
        action_type = "free" if free_action else "choice"

        if not action:
            return {"error": "no_action"}

        # ── 扫荡模式检测 ──
        # 1) 战斗中 + 扫荡关键词 → 直接结算
        # 2) 战斗中 + 敌人远弱 → 自动扫荡
        # 3) 非战斗中 + 扫荡关键词（含战斗意图）→ 生成敌人并直接结算，跳过LLM叙事
        # 注意：含恢复/使用物品意图的行动（药水、治疗等）不触发扫荡，避免抢走玩家意图
        in_combat = state.get("in_combat", False)
        enemies = state.get("enemies", [])
        is_sweep = False
        is_new_sweep = False  # 非战斗状态触发新扫荡

        # 恢复/使用物品意图 → 不触发扫荡
        restore_keywords = ("药水", "恢复", "治疗", "疗伤", "使用", "喝", "服用", "补给",
                            "回血", "回蓝", "补充", "治愈", "嗑药", "吃药", "灌")
        _has_restore_intent = any(k in action for k in restore_keywords) if action else False

        # 休息关键词检测（独立于物品恢复，用于强制触发休息恢复逻辑）
        rest_keywords = ("休息", "休整", "歇息", "扎营", "露宿", "露營", "扎寨", "宿营", "休憩",
                         "休养", "歇脚", "歇一歇", "歇一会", "歇會兒")
        _is_rest_action = any(k in action for k in rest_keywords) if action else False

        if _has_restore_intent:
            # 有恢复意图，跳过扫荡检测
            pass
        elif in_combat and enemies and self._is_sweep_action(action):
            is_sweep = True
        elif in_combat and enemies and self._should_auto_sweep(state, enemies):
            is_sweep = True
        elif not in_combat and self._is_sweep_action(action):
            # 非战斗状态下的扫荡：含战斗意图关键词
            combat_intent_keywords = ("扫荡", "清掉", "清理", "清空", "直接打完",
                                      "速战速决", "自动战斗", "快速战斗", "速杀",
                                      "碾压", "一举歼灭", "全部消灭", "一口气",
                                      "连战", "连杀", "横扫", "直接杀",
                                      "打到底", "战斗到底", "打完", "刷怪", "刷完",
                                      "全灭", "一扫", "小怪", "怪物")
            if any(kw in action for kw in combat_intent_keywords):
                is_new_sweep = True

        if is_sweep:
            # ── 快速战斗：跳过逐回合LLM叙事，直接结算 ──
            sweep_result = self._quick_combat(state, enemies, action_text=action, sender=sender,
                                              stop_condition=self._parse_sweep_condition(action))
            result = {
                "narrative": sweep_result.get("narrative", ""),
                "combat_result": sweep_result,
                "leveled_up": False,
                "new_skills": [],
                "character_died": sweep_result.get("player_died", False),
                "death_description": None,
                "exp_gained": sweep_result.get("exp_reward", 0),
                "gold_gained": sweep_result.get("gold_reward", 0),
                "is_sweep": True,  # 标记为扫荡模式
                "sweep_rounds": sweep_result.get("rounds", 0),
            }

            if sweep_result.get("player_died"):
                who = "user" if sweep_result.get("user_died") else "ai"
                result["death_description"] = self._handle_death(state, sweep_result.get("death_cause", "扫荡中阵亡"), who_died=who)
                result["death_pending"] = True
                result["death_who"] = who
                result["last_words"] = state.get("last_words", "")
                self._log_sweep_action(action, result)
                self._save()
                return result

            # 战斗胜利 → 经验/金币/升级处理
            if sweep_result.get("victory"):
                total_exp = sweep_result.get("exp_reward", 0)
                total_gold = sweep_result.get("gold_reward", 0)
                char = state["character"]
                char["gold"] += total_gold
                result["gold_gained"] = total_gold
                result["exp_gained"] = total_exp
                state["kill_count"] += len(enemies)

                char["world_type"] = state.get("world_type", "fantasy")
                growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                if growth_result["leveled_up"]:
                    result["leveled_up"] = True
                    result["new_level"] = growth_result["new_level"]
                    result["new_skills"] = growth_result.get("new_skills", [])

                # 用户角色也获得经验
                user_char = state.get("user_character", {})
                if user_char and user_char.get("class_name"):
                    user_char["world_type"] = state.get("world_type", "fantasy")
                    u_growth = GrowthSystem.gain_exp(user_char, total_exp, state.get("growth_mode", "normal"))
                    if u_growth["leveled_up"]:
                        result["user_leveled_up"] = True
                        result["user_new_skills"] = u_growth.get("new_skills", [])

                state["in_combat"] = False
                state["enemies"] = []
                result["in_combat"] = False
            else:
                # 扫荡未完全胜利（可能有强敌存活）
                result["in_combat"] = True
                result["enemies"] = [e for e in enemies if e.get("hp", 0) > 0]

            self._log_sweep_action(action, result)
            self._save()
            return result

        # ── 非战斗状态下的扫荡：直接生成敌人并快速结算 ──
        if is_new_sweep:
            # 根据角色等级推算敌人风险等级（扫荡默认低风险小怪）
            char = state["character"]
            risk_level = "low"  # 扫荡默认生成低风险小怪
            enemies_list = self._generate_enemies(state, risk_level)
            state["enemies"] = enemies_list
            state["in_combat"] = True

            sweep_result = self._quick_combat(state, enemies_list, action_text=action, sender=sender,
                                              stop_condition=self._parse_sweep_condition(action))
            result = {
                "narrative": sweep_result.get("narrative", ""),
                "combat_result": sweep_result,
                "leveled_up": False,
                "new_skills": [],
                "character_died": sweep_result.get("player_died", False),
                "death_description": None,
                "exp_gained": sweep_result.get("exp_reward", 0),
                "gold_gained": sweep_result.get("gold_reward", 0),
                "is_sweep": True,
                "sweep_rounds": sweep_result.get("rounds", 0),
                "new_combat": True,  # 标记为新触发的战斗
            }

            if sweep_result.get("player_died"):
                who = "user" if sweep_result.get("user_died") else "ai"
                result["death_description"] = self._handle_death(state, sweep_result.get("death_cause", "扫荡中阵亡"), who_died=who)
                result["death_pending"] = True
                result["death_who"] = who
                result["last_words"] = state.get("last_words", "")
                self._log_sweep_action(action, result)
                self._save()
                return result

            if sweep_result.get("victory"):
                total_exp = sweep_result.get("exp_reward", 0)
                total_gold = sweep_result.get("gold_reward", 0)
                char["gold"] += total_gold
                result["gold_gained"] = total_gold
                result["exp_gained"] = total_exp
                state["kill_count"] += len(enemies_list)

                char["world_type"] = state.get("world_type", "fantasy")
                growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                if growth_result["leveled_up"]:
                    result["leveled_up"] = True
                    result["new_level"] = growth_result["new_level"]
                    result["new_skills"] = growth_result.get("new_skills", [])

                # 用户角色也获得经验
                user_char = state.get("user_character", {})
                if user_char and user_char.get("class_name"):
                    user_char["world_type"] = state.get("world_type", "fantasy")
                    GrowthSystem.gain_exp(user_char, total_exp, state.get("growth_mode", "normal"))

                state["in_combat"] = False
                state["enemies"] = []
                result["in_combat"] = False
            else:
                result["in_combat"] = True
                result["enemies"] = [e for e in enemies_list if e.get("hp", 0) > 0]

            self._log_sweep_action(action, result)
            self._save()
            return result

        # 1. Agent 生成叙事（不含数值结果）— 非扫荡模式才走LLM
        agent_result = self.agent.process_action(state, action, action_type)
        narrative = agent_result.get("narrative", "")
        outcome_type = agent_result.get("outcome_type", "nothing")
        next_tension = agent_result.get("next_tension", "medium")

        # 休息关键词强制覆盖：确保"休息"相关指令可靠触发恢复逻辑
        if _is_rest_action:
            outcome_type = "rest"

        result = {
            "narrative": narrative,
            "combat_result": None,
            "leveled_up": False,
            "new_skills": [],
            "character_died": False,
            "death_description": None,
            "exp_gained": 0,
            "gold_gained": 0,
        }

        # 2. 根据行动类型进行数值判定
        char = state["character"]

        # 检查是否在战斗中（回合制）
        in_combat = state.get("in_combat", False)
        enemies = state.get("enemies", [])

        # 逃跑检测
        is_flee = "逃跑" in action or "撤退" in action
        # 用户单独逃跑，AI角色留下继续战斗
        is_user_flee = "用户逃跑" in action or "用户撤退" in action

        if in_combat and enemies:
            # ── 回合制战斗 ──
            if is_user_flee:
                # 用户逃跑：用户脱离战斗，AI角色留下独自面对所有敌人
                result["user_fled"] = True
                result["narrative"] = "用户选择了逃跑，AI角色独自面对敌人！"
                # AI角色继续战斗（不退出战斗状态）
                combat_result = self._combat_round(state, enemies, ai_alone=True, action_text=action, sender=sender)
                result["combat_result"] = combat_result
                result["in_combat"] = combat_result.get("in_combat", True)
                result["enemies"] = combat_result.get("enemies", enemies)
                if combat_result.get("character_died"):
                    result["character_died"] = True
                    result["user_died"] = combat_result.get("user_died", False)
                    who = "user" if combat_result.get("user_died") else "ai"
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "独自战斗时阵亡"), who_died=who)
                    result["death_pending"] = True
                    result["death_who"] = who
                    result["last_words"] = state.get("last_words", "")
            elif is_flee:
                # AI角色逃跑判定
                flee_result = self._try_flee(state, enemies)
                result["combat_result"] = flee_result
                if flee_result.get("player_died"):
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, flee_result.get("death_cause", "逃跑时被追击身亡"))
                    result["death_pending"] = True
                    result["death_who"] = "ai"
                    result["last_words"] = state.get("last_words", "")
                    return result
                if flee_result.get("fled"):
                    # 成功逃跑，退出战斗
                    state["in_combat"] = False
                    state["enemies"] = []
                    result["in_combat"] = False
                    result["enemies"] = []
                else:
                    # 逃跑失败，继续战斗
                    result["in_combat"] = True
                    result["enemies"] = [e for e in enemies if e.get("hp", 0) > 0]
            else:
                # 执行一回合战斗
                combat_result = self._combat_round(state, enemies, action_text=action, sender=sender)
                result["combat_result"] = combat_result

                if combat_result.get("player_died"):
                    result["character_died"] = True
                    result["user_died"] = combat_result.get("user_died", False)
                    who = "user" if combat_result.get("user_died") else "ai"
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "战斗中阵亡"), who_died=who)
                    result["death_pending"] = True
                    result["death_who"] = who
                    result["last_words"] = state.get("last_words", "")
                    return result

                # 检查是否所有敌人已击败
                alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
                if not alive_enemies:
                    # 战斗胜利
                    total_exp = sum(e.get("exp_reward", 10) for e in enemies)
                    total_gold = sum(e.get("gold_reward", 5) for e in enemies)
                    char["gold"] += total_gold
                    result["gold_gained"] = total_gold
                    result["exp_gained"] = total_exp
                    state["kill_count"] += len(enemies)
                    combat_result["victory"] = True
                    combat_result["enemies_defeated"] = [e.get("name", "") for e in enemies]
                    combat_result["exp_reward"] = total_exp
                    combat_result["gold_reward"] = total_gold

                    char["world_type"] = state.get("world_type", "fantasy")
                    growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                    if growth_result["leveled_up"]:
                        result["leveled_up"] = True
                        result["new_level"] = growth_result["new_level"]
                        result["new_skills"] = growth_result.get("new_skills", [])

                    # 用户角色也获得经验（一半）
                    user_char = state.get("user_character", {})
                    if user_char and user_char.get("class_name"):
                        user_char["world_type"] = state.get("world_type", "fantasy")
                        u_growth = GrowthSystem.gain_exp(user_char, total_exp, state.get("growth_mode", "normal"))
                        if u_growth["leveled_up"]:
                            result.setdefault("user_leveled_up", True)
                            result.setdefault("user_new_skills", u_growth.get("new_skills", []))

                    state["in_combat"] = False
                    state["enemies"] = []
                    result["in_combat"] = False
                else:
                    # 战斗继续
                    state["in_combat"] = True
                    result["in_combat"] = True
                    result["enemies"] = alive_enemies

        else:
            # ── 非战斗状态：正常处理选择 ──
            choice_info = None
            if action_type == "choice":
                for c in state["story"].get("choices", []):
                    if c.get("id") == choice_id:
                        choice_info = c
                        break

            action_type_value = choice_info.get("type", "explore") if choice_info else "explore"
            risk_level = choice_info.get("risk", "medium") if choice_info else "medium"

            # 战斗触发（进入战斗状态）
            if action_type_value == "combat" or (outcome_type.startswith("combat") and action_type_value != "rest"):
                # 生成敌人列表（支持一群怪）
                enemies_list = self._generate_enemies(state, risk_level)
                state["enemies"] = enemies_list
                state["in_combat"] = True

                # ── 扫荡模式：新战斗触发时，如果含扫荡关键词或敌人远弱 → 快速结算 ──
                if self._is_sweep_action(action) or self._should_auto_sweep(state, enemies_list):
                    sweep_result = self._quick_combat(state, enemies_list, action_text=action, sender=sender,
                                                      stop_condition=self._parse_sweep_condition(action))
                    result["combat_result"] = sweep_result
                    result["is_sweep"] = True
                    result["sweep_rounds"] = sweep_result.get("rounds", 0)

                    # 覆盖叙事为扫荡总结（跳过逐回合LLM叙事）
                    result["narrative"] = sweep_result.get("narrative", "")

                    if sweep_result.get("player_died"):
                        result["character_died"] = True
                        result["user_died"] = sweep_result.get("user_died", False)
                        who = "user" if sweep_result.get("user_died") else "ai"
                        result["death_description"] = self._handle_death(state, sweep_result.get("death_cause", "扫荡中阵亡"), who_died=who)
                        result["death_pending"] = True
                        result["death_who"] = who
                        result["last_words"] = state.get("last_words", "")
                        self._log_sweep_action(action, result)
                        self._save()
                        return result

                    if sweep_result.get("victory"):
                        total_exp = sweep_result.get("exp_reward", 0)
                        total_gold = sweep_result.get("gold_reward", 0)
                        char["gold"] += total_gold
                        result["gold_gained"] = total_gold
                        result["exp_gained"] = total_exp
                        state["kill_count"] += len(enemies_list)

                        char["world_type"] = state.get("world_type", "fantasy")
                        growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                        if growth_result["leveled_up"]:
                            result["leveled_up"] = True
                            result["new_level"] = growth_result["new_level"]
                            result["new_skills"] = growth_result.get("new_skills", [])

                        # 用户角色也获得经验
                        u_char = state.get("user_character", {})
                        if u_char and u_char.get("class_name"):
                            u_char["world_type"] = state.get("world_type", "fantasy")
                            GrowthSystem.gain_exp(u_char, total_exp, state.get("growth_mode", "normal"))

                        state["in_combat"] = False
                        state["enemies"] = []
                        result["in_combat"] = False
                    else:
                        result["in_combat"] = True
                        result["enemies"] = [e for e in enemies_list if e.get("hp", 0) > 0]

                    self._log_sweep_action(action, result)
                    self._save()
                    return result

                # 第一回合（非扫荡模式）
                combat_result = self._combat_round(state, enemies_list, action_text=action, sender=sender)
                result["combat_result"] = combat_result

                if combat_result.get("player_died"):
                    result["character_died"] = True
                    result["user_died"] = combat_result.get("user_died", False)
                    who = "user" if combat_result.get("user_died") else "ai"
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "战斗中阵亡"), who_died=who)
                    result["death_pending"] = True
                    result["death_who"] = who
                    result["last_words"] = state.get("last_words", "")
                    return result

                alive_enemies = [e for e in enemies_list if e.get("hp", 0) > 0]
                if not alive_enemies:
                    # 一回合全灭
                    total_exp = sum(e.get("exp_reward", 10) for e in enemies_list)
                    total_gold = sum(e.get("gold_reward", 5) for e in enemies_list)
                    char["gold"] += total_gold
                    result["gold_gained"] = total_gold
                    result["exp_gained"] = total_exp
                    state["kill_count"] += len(enemies_list)
                    combat_result["victory"] = True
                    combat_result["enemies_defeated"] = [e.get("name", "") for e in enemies_list]
                    char["world_type"] = state.get("world_type", "fantasy")
                    growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                    if growth_result["leveled_up"]:
                        result["leveled_up"] = True
                        result["new_level"] = growth_result["new_level"]
                        result["new_skills"] = growth_result.get("new_skills", [])
                    # 用户角色也获得经验（一半）
                    u_char = state.get("user_character", {})
                    if u_char and u_char.get("class_name"):
                        u_char["world_type"] = state.get("world_type", "fantasy")
                        GrowthSystem.gain_exp(u_char, total_exp, state.get("growth_mode", "normal"))
                    state["in_combat"] = False
                    state["enemies"] = []
                    result["in_combat"] = False
                else:
                    result["in_combat"] = True
                    result["enemies"] = alive_enemies

            # 探索触发陷阱
            elif outcome_type == "trap":
                trap_damage = self._calc_trap_damage(char, risk_level)
                char["hp"] = max(0, char["hp"] - trap_damage)
                result["combat_result"] = {"trap_damage": trap_damage, "hp_remaining": char["hp"]}

                if char["hp"] <= 0:
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, "触发陷阱身亡")
                    result["death_pending"] = True
                    result["death_who"] = "ai"
                    result["last_words"] = state.get("last_words", "")
                    return result

            # 休息恢复（AI角色和用户角色同时恢复）
            elif action_type_value == "rest" or outcome_type == "rest":
                heal_amount = int(char["max_hp"] * 0.2)
                mp_recover = int(char["max_mp"] * 0.3)
                char["hp"] = min(char["max_hp"], char["hp"] + heal_amount)
                char["mp"] = min(char["max_mp"], char["mp"] + mp_recover)
                result["combat_result"] = {"rest_heal": heal_amount, "mp_recover": mp_recover, "hp_remaining": char["hp"]}
                # 前端展示AI角色恢复数值
                result["hp_change"] = heal_amount
                result["mp_change"] = mp_recover

                # 用户角色也同时恢复（各自按自己的max计算）
                user_char = state.get("user_character", {})
                if user_char and user_char.get("class_name"):
                    u_heal = int(user_char.get("max_hp", 0) * 0.2)
                    u_mp = int(user_char.get("max_mp", 0) * 0.3)
                    user_char["hp"] = min(user_char.get("max_hp", 0), user_char.get("hp", 0) + u_heal)
                    user_char["mp"] = min(user_char.get("max_mp", 0), user_char.get("mp", 0) + u_mp)
                    result["combat_result"]["user_rest_heal"] = u_heal
                    result["combat_result"]["user_mp_recover"] = u_mp
                    result["user_hp_change"] = u_heal
                    result["user_mp_change"] = u_mp

            # 发现宝箱
            elif outcome_type == "discovery":
                gold_found = random.randint(10, 50) + char["level"] * 5
                char["gold"] += gold_found
                result["gold_gained"] = gold_found
                if random.random() < 0.3:
                    exp_bonus = 20 + char["level"] * 5
                    result["exp_gained"] = exp_bonus
                    GrowthSystem.gain_exp(char, exp_bonus, state.get("growth_mode", "normal"))
                    # 用户角色也获得探索经验（一半）
                    u_char = state.get("user_character", {})
                    if u_char and u_char.get("class_name"):
                        u_char["world_type"] = state.get("world_type", "fantasy")
                        GrowthSystem.gain_exp(u_char, exp_bonus, state.get("growth_mode", "normal"))

        # 2.5 处理 Agent 返回的物品/金币/属性变动（战斗结果由战斗系统处理，此处跳过）
        if not outcome_type.startswith("combat"):
            # 物品获得 → 进共享背包
            items_gained = agent_result.get("items_gained")
            if items_gained and isinstance(items_gained, list):
                shared_inv = state.setdefault("shared_inventory", [])
                for item_name in items_gained:
                    eq_item = self._create_item_from_name(item_name, state)
                    if eq_item:
                        shared_inv.append(eq_item)
                        result.setdefault("items_to_backpack", []).append(eq_item.get("name", item_name))

            # 花费金币
            gold_spent = agent_result.get("gold_spent")
            if gold_spent and isinstance(gold_spent, (int, float)):
                actual_spent = min(int(gold_spent), char.get("gold", 0))
                char["gold"] -= actual_spent
                result["gold_spent"] = actual_spent

            # 获得金币（discovery 已有自己的金币逻辑，不重复）
            gold_gained_agent = agent_result.get("gold_gained")
            if gold_gained_agent and isinstance(gold_gained_agent, (int, float)) and outcome_type != "discovery":
                char["gold"] += int(gold_gained_agent)
                result["gold_gained"] = result.get("gold_gained", 0) + int(gold_gained_agent)


        # 2.6 HP/MP变化（独立于战斗/非战斗，战斗中用药水/食物也生效）
        # 这些变化来自LLM对行动叙事的数值化。区分恢复对象：
        # - 若行动文本明确提到"焕灵/AI角色"使用恢复 → 作用于AI角色
        # - 若行动文本提到用户/玩家使用恢复，或叙事以用户为主语 → 作用于用户角色
        hp_change = agent_result.get("hp_change")
        if hp_change and isinstance(hp_change, (int, float)):
            _hp_val = int(hp_change)
            _user_char = state.get("user_character", {})
            _has_user = _user_char and _user_char.get("class_name")
            # 判断行动是否针对AI角色
            _action_lower = action or ""
            _ai_target_kw = ("焕灵", "AI", "角色", "系统")
            _ai_used = any(k in _action_lower for k in _ai_target_kw) and not any(k in _action_lower for k in ("yount", "用户", "玩家"))
            if _has_user and not _ai_used:
                _user_char["hp"] = max(0, min(_user_char.get("max_hp", 0), _user_char.get("hp", 0) + _hp_val))
                result["user_hp_change"] = _hp_val
            else:
                char["hp"] = max(0, min(char["max_hp"], char["hp"] + _hp_val))
                result["hp_change"] = _hp_val

        # MP变化
        mp_change = agent_result.get("mp_change")
        if mp_change and isinstance(mp_change, (int, float)):
            _mp_val = int(mp_change)
            _user_char = state.get("user_character", {})
            _has_user = _user_char and _user_char.get("class_name")
            _action_lower = action or ""
            _ai_target_kw = ("焕灵", "AI", "角色", "系统")
            _ai_used = any(k in _action_lower for k in _ai_target_kw) and not any(k in _action_lower for k in ("yount", "用户", "玩家"))
            if _has_user and not _ai_used:
                _user_char["mp"] = max(0, min(_user_char.get("max_mp", 0), _user_char.get("mp", 0) + _mp_val))
                result["user_mp_change"] = _mp_val
            else:
                char["mp"] = max(0, min(char["max_mp"], char["mp"] + _mp_val))
                result["mp_change"] = _mp_val

        # 3. 天数按实际时间计算（不在此处推进，get_game_state 中动态计算）

        # 4. 记录故事历史
        state["story"]["history"].append({
            "chapter": state["story"]["current_chapter"],
            "summary": narrative[:100],
            "action": action if action_type == "free" else (choice_info.get("text", "") if choice_info else action),
            "outcome": outcome_type,
        })

        # 章节按历史进度推进（每5条历史推进一章）
        if len(state["story"]["history"]) % 5 == 0:
            state["story"]["current_chapter"] += 1

        # 5. 战斗中不清除场景；非战斗状态清除场景（需要生成新场景）
        if not state.get("in_combat", False):
            state["story"]["scene_description"] = ""
            state["story"]["choices"] = []
            state["story"]["pending_action"] = None
            result["next_scene"] = True
        else:
            result["next_scene"] = False

        self._save()

        # 记录行动日志
        log_data = {
            "action": action if action_type == "free" else (choice_info.get("text", "") if choice_info else action),
            "action_type": action_type,
            "outcome": outcome_type,
            "narrative": narrative[:300],
        }
        if result.get("combat_result"):
            cr = result["combat_result"]
            if cr:
                log_data["combat"] = {
                    "victory": cr.get("victory", False),
                    "enemy_names": cr.get("enemies_defeated", []),
                    "combat_log": cr.get("combat_log", []),
                }
        if result.get("exp_gained"):
            log_data["exp_gained"] = result["exp_gained"]
        if result.get("gold_gained"):
            log_data["gold_gained"] = result["gold_gained"]
        if result.get("leveled_up"):
            log_data["leveled_up"] = True
            log_data["new_level"] = result.get("new_level")
        if result.get("character_died"):
            log_data["character_died"] = True
            log_data["death_description"] = result.get("death_description", "")
        if result.get("combat_result") and result["combat_result"] and result["combat_result"].get("drops"):
            log_data["drops"] = result["combat_result"]["drops"]
        if result.get("items_equipped"):
            log_data["items_equipped"] = result["items_equipped"]
        if result.get("gold_spent"):
            log_data["gold_spent"] = result["gold_spent"]
        if result.get("hp_change"):
            log_data["hp_change"] = result["hp_change"]
        if result.get("mp_change"):
            log_data["mp_change"] = result["mp_change"]
        if result.get("user_hp_change"):
            log_data["user_hp_change"] = result["user_hp_change"]
        if result.get("user_mp_change"):
            log_data["user_mp_change"] = result["user_mp_change"]

        self._log_action("action", log_data)
        self._save()

        # ── HP≤20% 触发A层求生抉择 ──
        ai_char = state.get("character", {})
        ai_hp = ai_char.get("hp", 0)
        ai_max_hp = ai_char.get("max_hp", 1)
        if (ai_max_hp > 0
            and not result.get("character_died")
            and not state.get("ai_character_dead", False)
            and ai_hp > 0
            and ai_hp <= ai_max_hp * 0.2):
            # 系统角色HP危急，标记让A层抉择
            result["ai_low_hp_alert"] = True
            result["ai_hp_ratio"] = round(ai_hp / ai_max_hp, 2)
            result["ai_current_hp"] = ai_hp
            result["ai_max_hp"] = ai_max_hp
            # 战斗中的敌人信息
            if state.get("in_combat"):
                result["ai_enemies"] = [e for e in state.get("enemies", []) if e.get("hp", 0) > 0]

        return result

    def _create_item_from_name(self, item_name: str, state: Dict) -> Optional[Dict]:
        """根据物品名创建装备对象，仅在装备名池中存在时生成，拒绝凭空变出"""
        world_type = state.get("world_type", "fantasy")
        char_level = state.get("character", {}).get("level", 1)
        names_pool = EquipmentSystem.EQUIPMENT_NAMES.get(world_type, EquipmentSystem.EQUIPMENT_NAMES["fantasy"])

        # 搜索所有武器子类型池（含 shield / off_hand）
        weapon_subtypes = ("one_handed", "two_handed", "ranged", "wand", "shield", "off_hand")

        # 1. 精确匹配
        for subtype_key in weapon_subtypes:
            type_pool = names_pool.get(subtype_key, {})
            for rarity, names in type_pool.items():
                if item_name in names:
                    item = EquipmentSystem.generate_equipment(world_type, "weapon", rarity, char_level, subtype=subtype_key)
                    item["name"] = item_name
                    return item

        type_pool = names_pool.get("outfit", {})
        for rarity, names in type_pool.items():
            if item_name in names:
                item = EquipmentSystem.generate_equipment(world_type, "outfit", rarity, char_level)
                item["name"] = item_name
                return item

        # 2. 模糊匹配（子串匹配）
        for subtype_key in weapon_subtypes:
            type_pool = names_pool.get(subtype_key, {})
            for rarity, names in type_pool.items():
                for n in names:
                    if item_name in n or n in item_name:
                        item = EquipmentSystem.generate_equipment(world_type, "weapon", rarity, char_level, subtype=subtype_key)
                        item["name"] = item_name
                        return item

        type_pool = names_pool.get("outfit", {})
        for rarity, names in type_pool.items():
            for n in names:
                if item_name in n or n in item_name:
                    item = EquipmentSystem.generate_equipment(world_type, "outfit", rarity, char_level)
                    item["name"] = item_name
                    return item

        # 3. 装备池中不存在 → 拒绝生成，防止用户口令凭空变出
        return None

    def _generate_enemies(self, state: Dict, risk_level: str) -> list:
        """生成敌人列表（支持一群怪，优先使用地图区域的怪物）"""
        char = state["character"]
        char_level = char["level"]
        world_setting = state.get("world_setting", {})

        # 根据风险等级决定敌人数量和类型
        if risk_level == "low":
            count = 1
            enemy_type = "normal"
        elif risk_level == "medium":
            count = random.randint(1, 2)
            enemy_type = "normal"
        else:  # high
            count = random.randint(2, 3)
            enemy_type = "elite" if random.random() < 0.3 else "normal"

        # 优先使用当前区域的怪物名称
        region_monster_names = []
        if self.world_map:
            current = self.world_map.get_current_region()
            if current and current.monsters:
                region_monster_names = [m.get("name", "") for m in current.monsters if m.get("name")]
                # BOSS区域可能触发BOSS战
                if current.boss and not current.boss_defeated and risk_level == "high" and random.random() < 0.4:
                    boss = current.boss
                    boss_level = boss.get("level", char_level + 5)
                    return [CombatSystem.generate_enemy(boss_level, world_setting, "boss")]

        enemies = []
        for i in range(count):
            # 低风险区域出低等级怪（玩家可以刷级）
            if risk_level == "low":
                enemy_level = max(1, char_level - random.randint(2, 4))
            elif risk_level == "medium":
                enemy_level = max(1, char_level - random.randint(0, 2))
            else:
                enemy_level = char_level + random.randint(0, 1)
            enemy = CombatSystem.generate_enemy(enemy_level, world_setting, enemy_type)
            # 如果当前区域有怪物，替换名称
            if region_monster_names:
                enemy["name"] = random.choice(region_monster_names)
            # 多个敌人时编号
            if count > 1:
                enemy["name"] = f"{enemy['name']}{i+1}"
            enemies.append(enemy)

        return enemies

    def _combat_round(self, state: Dict, enemies: list, ai_alone: bool = False,
                      action_text: str = "", sender: str = "user") -> Dict:
        """执行一回合战斗，解析用户行动口令驱动战斗策略
        action_text: 用户输入的行动文本，用于解析战斗策略
        ai_alone: 用户已逃跑，AI角色独自面对所有敌人
        sender: "user"或"ai"，谁发的行动
        """
        from simlife.backend.combat_system import TacticalSystem

        char = state["character"]  # AI角色
        user_char = state.get("user_character", {})  # 用户角色
        user_in_combat = not ai_alone and user_char and user_char.get("hp", 0) > 0 and user_char.get("class_name")
        # 如果AI角色已死（用户继续冒险），AI不参战
        ai_in_combat = char.get("hp", 0) > 0 and not state.get("ai_character_dead", False)
        # 如果用户角色已死（AI继续冒险），用户不参战
        if state.get("user_character_dead", False):
            user_in_combat = False
        combat_log = []
        drops = []

        # ── 解析战斗口令 ──
        cmd = self._parse_combat_command(action_text, char, user_char, enemies, state, sender)

        def _enemy_defense(enemy=None):
            """敌人随机防御"""
            choices = [DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.NONE]
            e = enemy or target
            if e and e.get("stats", {}).get("intelligence", 5) > 12:
                choices.append(DefenseAction.PARRY)
            return random.choice(choices)

        def _check_drop(enemy, killer_stats):
            """检查敌人掉落"""
            if enemy.get("hp", 0) <= 0:
                luck = killer_stats.get("luck", 5)
                drop = EquipmentSystem.roll_drop(
                    enemy.get("level", 1), enemy.get("type", "normal"),
                    luck, state.get("world_type", "fantasy")
                )
                if drop:
                    drops.append(drop)
                    shared_inv = state.setdefault("shared_inventory", [])
                    shared_inv.append(drop)
                    combat_log.append(f"掉落：{drop['name']}（{drop.get('rarity_name', '普通')}）已放入背包")

        # ── 战术修正 ──
        tactic_result = None
        if cmd["tactic"]:
            from simlife.backend.combat_system import TacticalSystem
            terrain = ""
            # 从地图推断地形
            current_region = state.get("world_map", {}).get("current_region_id", "")
            if current_region:
                terrain_map = {"town": "ruins", "wild": "forest", "dungeon": "cave",
                               "boss_lair": "boss_lair", "secret": "cave"}
                regions = state.get("world_map", {}).get("regions", {})
                region = regions.get(current_region, {})
                region_type = region.get("region_type", "wild")
                terrain = terrain_map.get(region_type, "open_field")
            tactic_result = TacticalSystem.apply_tactic(cmd["tactic"], char, enemies[0] if enemies else {}, terrain)
            if tactic_result.get("description"):
                combat_log.append(f"⚔️ {tactic_result['description']}")

        # ── 判定出手顺序 ──
        # 优先使用口令指定的顺序，否则按敏捷+职业自动判定
        initiative_order = cmd.get("initiative_order")
        if initiative_order:
            # 口令指定顺序
            actors = []
            for role in initiative_order:
                if role == "ai" and ai_in_combat:
                    actors.append((99, "ai", char))
                elif role == "user" and user_in_combat:
                    actors.append((99, "user", user_char))
            # 补全：如果口令只指定了一个，补上另一个
            roles_set = {a[1] for a in actors}
            if "ai" not in roles_set and ai_in_combat:
                actors.append((0, "ai", char))
            if "user" not in roles_set and user_in_combat:
                actors.append((0, "user", user_char))
            order_desc = " → ".join(f"{a[2].get('name', a[1])}" for a in actors)
            combat_log.append(f"⚡ 出手顺序（口令指定）：{order_desc}")
        else:
            # 自动判定：先手值 = 敏捷 + 职业修正
            ai_agi = char.get("stats", {}).get("agility", 5)
            u_agi = user_char.get("stats", {}).get("agility", 5) if user_in_combat else 0
            range_classes = ("法师", "术士", "弓手", "猎人", "游侠", "巫师", "贤者", "牧师")
            ai_class = char.get("class_name", "")
            u_class = user_char.get("class_name", "") if user_in_combat else ""
            ai_initiative = ai_agi + (5 if any(c in ai_class for c in range_classes) else 0)
            u_initiative = u_agi + (5 if any(c in u_class for c in range_classes) else 0)
            actors = []
            if ai_in_combat:
                actors.append((ai_initiative, "ai", char))
            if user_in_combat:
                actors.append((u_initiative, "user", user_char))
            actors.sort(key=lambda x: x[0], reverse=True)
            names = [f"{a[2].get('name',a[1])}({a[0]})" for a in actors]
            combat_log.append(f"⚡ 出手顺序（自动）：{' → '.join(names)}")

        # ── 连续子回合战斗 ──
        # 一次行动自动进行多个子回合交锋，让战斗有"几轮你来我往"的层次感，
        # 并充分利用硬直/架势/招架/部位伤势等战斗机制。
        # 子回合数 = 根据双方实力差距动态决定：势均力敌打更多回合，碾压则快速结束。
        tank_role = cmd.get("tank_role")

        # 计算双方总体战力（用于决定交锋轮数）
        _ai_power = CombatSystem.calc_attack_power(char) + CombatSystem.calc_defense(char) + char.get("hp", 0)
        _user_power = 0
        if user_in_combat:
            _user_power = CombatSystem.calc_attack_power(user_char) + CombatSystem.calc_defense(user_char) + user_char.get("hp", 0)
        _party_power = _ai_power + _user_power
        _enemy_power = sum(
            CombatSystem.calc_attack_power(e) + CombatSystem.calc_defense(e) + e.get("hp", 0)
            for e in enemies if e.get("hp", 0) > 0
        )
        # 实力悬殊（我方碾压）→ 少打几轮快速结束；势均力敌/劣势 → 多打几轮有来有回
        if _party_power >= _enemy_power * 2.0:
            max_sub_rounds = 1
        elif _party_power >= _enemy_power * 1.3:
            max_sub_rounds = 2
        else:
            max_sub_rounds = 3

        total_combat_log = []
        victory = False
        death_return = None
        for sub_round in range(1, max_sub_rounds + 1):
            # 检查存活敌人
            alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
            if not alive_enemies:
                victory = True
                break
            # 角色死亡则终止
            if char.get("hp", 0) <= 0 or (user_in_combat and user_char.get("hp", 0) <= 0):
                break

            round_log = []

            # ── 按出手顺序攻击 ──
            for initiative, role, attacker in actors:
                if role == "ai" and cmd.get("ai_skip"):
                    continue
                if role == "user" and cmd.get("user_skip"):
                    continue
                if attacker.get("hp", 0) <= 0:
                    continue
                target = cmd.get(f"{role}_target") or next((e for e in enemies if e.get("hp", 0) > 0), None)
                if not target:
                    continue
                is_magic = cmd.get(f"{role}_is_magic", False)
                skill_mult = cmd.get(f"{role}_skill_mult", 1.0)
                atk_result = CombatSystem.attack(attacker, target, defense_action=_enemy_defense(target),
                                                 attack_type="magic" if is_magic else "physical", skill_multiplier=skill_mult)
                # 战术加成
                if tactic_result and (role == "ai" or cmd["tactic"] in ("focus", "flank")):
                    atk_result = TacticalSystem.apply_tactic_modifiers(atk_result, tactic_result)
                round_log.append(f"{attacker.get('name','?')}{atk_result['description']} → {target.get('name', '?')}")
                _check_drop(target, attacker.get("stats", {}))

            # ── 存活敌人反击 ──
            for enemy in enemies:
                if enemy.get("hp", 0) <= 0:
                    continue
                # 决定攻击目标
                if tank_role == "ai" and char.get("hp", 0) > 0:
                    target_char, target_defense, target_name = char, cmd.get("ai_defense", DefenseAction.BLOCK), char.get("name", "你")
                elif tank_role == "user" and user_in_combat and user_char.get("hp", 0) > 0:
                    target_char, target_defense, target_name = user_char, cmd.get("user_defense", DefenseAction.BLOCK), user_char.get("name", "用户")
                else:
                    import random as _rng
                    candidates = []
                    if char.get("hp", 0) > 0:
                        candidates.append(("ai", char, cmd.get("ai_defense", DefenseAction.BLOCK)))
                    if user_in_combat and user_char.get("hp", 0) > 0:
                        candidates.append(("user", user_char, cmd.get("user_defense", DefenseAction.DODGE)))
                    if not candidates:
                        continue
                    pick = _rng.choice(candidates)
                    target_char, target_defense, target_name = pick[1], pick[2], pick[1].get("name", "?")

                if target_char.get("stagger_turns", 0) > 0:
                    target_defense = DefenseAction.NONE

                def_result = CombatSystem.attack(enemy, target_char, defense_action=target_defense)

                if ai_alone and target_char is char and def_result.get("damage", 0) > 0:
                    def_result["damage"] = int(def_result["damage"] * 1.4)
                    if def_result.get("defense_result"):
                        def_result["defense_result"]["damage_taken"] = int(
                            def_result["defense_result"].get("damage_taken", 0) * 1.4
                        )

                round_log.append(f"{enemy.get('name', '?')}{def_result['description']} → {target_name}")

                # 死亡判定
                if target_char["hp"] <= 0:
                    if target_char is char:
                        death_return = {"victory": False, "player_died": True,
                                        "death_cause": f"被{enemy.get('name', '敌人')}击败" + ("（独自战斗时阵亡）" if ai_alone else ""),
                                        "combat_log": round_log, "drops": drops}
                        break
                    else:
                        round_log.append(f"{target_name}已倒下！")
                        death_return = {"victory": False, "player_died": True,
                                        "death_cause": f"用户角色{target_name}被{enemy.get('name', '敌人')}击败",
                                        "user_died": True,
                                        "combat_log": round_log, "drops": drops}
                        break
            if death_return:
                break

            # ── 记录本子回合（带回合标记） ──
            if round_log:
                total_combat_log.append(f"[第{sub_round}轮] " + "；".join(round_log))

            # 回合间恢复：硬直递减、架势回弹
            if char.get("stagger_turns", 0) > 0:
                char["stagger_turns"] -= 1
            if user_in_combat and user_char.get("stagger_turns", 0) > 0:
                user_char["stagger_turns"] -= 1
            for e in enemies:
                if e.get("stagger_turns", 0) > 0:
                    e["stagger_turns"] -= 1

        # 死亡返回优先
        if death_return:
            death_return["combat_log"] = total_combat_log + death_return.get("combat_log", [])
            return death_return

        return {
            "victory": victory,
            "player_died": False,
            "combat_log": total_combat_log,
            "drops": drops,
        }

    def _quick_combat(self, state: Dict, enemies: list, action_text: str = "",
                      sender: str = "user", max_rounds: int = 30,
                      stop_condition: str = "kill") -> Dict:
        """快速战斗（扫荡模式）：自动连续战斗直到达成目标，不调用LLM叙事
        适用于：小怪碾压、用户明确说"扫荡/清掉/直接打完/把怪打死"等关键词
        max_rounds: 最大回合数上限，防止无限循环
        stop_condition:
            - "kill"  → 把怪全部打死（默认）
            - "half"  → 把怪打到总HP剩一半就停
        返回: {
            "victory": bool,
            "player_died": bool,
            "rounds": int,       # 总回合数
            "combat_log": [],    # 精简的战斗日志（只保留关键事件）
            "drops": [],         # 掉落物品
            "total_damage_taken": int,  # 角色总受伤
            "total_damage_dealt": int,  # 角色总输出
            "enemies_defeated": [],     # 击败敌人名列表
            "exp_reward": int,
            "gold_reward": int,
            "key_events": [],           # 关键事件摘要（供叙事Agent使用）
            "narrative": str,           # LLM生成的总结叙事
            "stopped_at": str,          # 停止原因：kill/half/enemies_defeated/player_died
        }
        """
        char = state["character"]
        user_char = state.get("user_character", {})
        ai_in_combat = char.get("hp", 0) > 0 and not state.get("ai_character_dead", False)
        user_in_combat = (user_char and user_char.get("hp", 0) > 0
                          and user_char.get("class_name")
                          and not state.get("user_character_dead", False))

        all_combat_logs = []
        all_drops = []
        key_events = []
        rounds = 0
        stopped_at = "kill"

        # 保存初始HP用于计算损失
        ai_hp_start = char.get("hp", 0)
        user_hp_start = user_char.get("hp", 0) if user_in_combat else 0

        # 保存初始敌人HP用于计算总输出
        enemy_hp_start = {i: e.get("hp", e.get("max_hp", 0)) for i, e in enumerate(enemies)}

        # 保存初始敌人信息用于总结
        enemy_names_start = [e.get("name", "?") for e in enemies]

        # 初始敌人总HP（用于"打到半血"目标）
        enemy_total_hp_start = sum(e.get("hp", e.get("max_hp", 0)) for e in enemies)
        enemy_half_target = enemy_total_hp_start * 0.5 if stop_condition == "half" else 0

        # 用于兜底（当循环未执行时）
        combat_result = {"combat_log": [], "drops": [], "player_died": False, "user_died": False}

        for round_num in range(1, max_rounds + 1):
            rounds = round_num
            alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
            if not alive_enemies:
                stopped_at = "enemies_defeated"
                break

            # 半血目标：敌人总HP已降到初始一半以下 → 停止
            if stop_condition == "half":
                cur_enemy_hp = sum(e.get("hp", 0) for e in enemies)
                if cur_enemy_hp <= enemy_half_target:
                    stopped_at = "half"
                    break

            # ── 构造默认攻击口令（扫荡模式不解析用户口令，使用默认策略）──
            # 优先攻击HP最低的敌人（效率最优）
            target_enemy = min(alive_enemies, key=lambda e: e.get("hp", 999))
            default_cmd = {
                "ai_is_magic": False, "user_is_magic": False,
                "ai_skill_mult": 1.0, "user_skill_mult": 1.0,
                "ai_skill": None, "user_skill": None,
                "ai_defense": DefenseAction.BLOCK, "user_defense": DefenseAction.BLOCK,
                "ai_target": target_enemy, "user_target": target_enemy,
                "tactic": None, "initiative_order": None, "tank_role": None,
                "ai_skip": False, "user_skip": False,
            }

            # ── 执行一回合战斗（复用 _combat_round）──
            # 为扫荡模式传入简化的口令
            # 构造一个简单的行动文本用于判定出手顺序
            sweep_action = f"扫荡攻击{target_enemy.get('name', '敌人')}"
            combat_result = self._combat_round(
                state, alive_enemies,
                action_text=sweep_action, sender=sender
            )

            # 检查战斗结果
            if combat_result.get("player_died"):
                # 角色阵亡 - 扫荡失败
                death_cause = combat_result.get("death_cause", "扫荡中阵亡")
                # 计算当前已造成的伤害（不能引用循环后未定义的total_damage_dealt）
                cur_dealt = sum(enemy_hp_start.get(i, 0) - e.get("hp", 0) for i, e in enumerate(enemies))
                for i, e in enumerate(enemies):
                    if e.get("hp", 0) <= 0:
                        cur_dealt += abs(e.get("hp", 0))
                return {
                    "victory": False,
                    "player_died": True,
                    "rounds": rounds,
                    "combat_log": combat_result.get("combat_log", []),
                    "drops": all_drops + combat_result.get("drops", []),
                    "total_damage_taken": (ai_hp_start - char.get("hp", 0))
                                         + (user_hp_start - (user_char.get("hp", 0) if user_in_combat else 0)),
                    "total_damage_dealt": cur_dealt,
                    "enemies_defeated": [],
                    "exp_reward": 0,
                    "gold_reward": 0,
                    "key_events": key_events,
                    "narrative": "",
                    "death_cause": death_cause,
                    "user_died": combat_result.get("user_died", False),
                    "stopped_at": "player_died",
                }

            # 收集战斗日志
            round_log = combat_result.get("combat_log", [])
            all_combat_logs.extend(round_log)

            # 收集掉落
            round_drops = combat_result.get("drops", [])
            all_drops.extend(round_drops)

            # 记录关键事件（每回合只提取最重要的1-2条）
            for log_entry in round_log:
                if any(kw in log_entry for kw in ("暴击", "掉落", "击败", "击杀", "倒下", "重伤")):
                    key_events.append(f"第{round_num}回合：{log_entry}")

            # 检查是否有敌人死亡（记为关键事件）
            new_alive = [e for e in alive_enemies if e.get("hp", 0) > 0]
            if len(new_alive) < len(alive_enemies):
                killed_names = [e.get("name", "?") for e in alive_enemies if e.get("hp", 0) <= 0]
                key_events.append(f"第{round_num}回合：击杀{'、'.join(killed_names)}")

            # 如果没有玩家死亡且所有敌人被击败 → 胜利
            if not new_alive:
                break

        # ── 计算总结数据 ──
        alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
        enemies_defeated = [e.get("name", "?") for e in enemies if e.get("hp", 0) <= 0]
        total_exp = sum(e.get("exp_reward", 10) for e in enemies if e.get("hp", 0) <= 0)
        total_gold = sum(e.get("gold_reward", 5) for e in enemies if e.get("hp", 0) <= 0)
        total_damage_taken = (ai_hp_start - char.get("hp", 0)) + (user_hp_start - (user_char.get("hp", 0) if user_in_combat else 0))
        # 总输出 = 敌人HP减少总和（扫荡期间对敌人造成的总伤害）
        total_damage_dealt = sum(enemy_hp_start.get(i, 0) - e.get("hp", 0) for i, e in enumerate(enemies))
        # 击败的敌人的HP减少量也计入（hp<=0时取负值修正）
        for i, e in enumerate(enemies):
            if e.get("hp", 0) <= 0:
                total_damage_dealt += abs(e.get("hp", 0))  # 超额伤害也计入

        victory = len(alive_enemies) == 0

        # ── 构建总结 ──
        combat_summary = {
            "rounds": rounds,
            "enemies_defeated": enemies_defeated,
            "total_damage_taken": total_damage_taken,
            "total_damage_dealt": total_damage_dealt,
            "drops": all_drops,
            "exp_gained": total_exp,
            "gold_gained": total_gold,
            "key_events": key_events[:8],  # 最多8条关键事件
        }

        # ── 调用一次LLM生成总结叙事 ──
        narrative = ""
        if victory and not combat_result.get("player_died"):
            try:
                narrative = self.agent.generate_quick_combat_narrative(state, combat_summary)
            except Exception as e:
                print(f"[DeathMode] 快速战斗叙事失败: {e}")
                char_name = char.get("name", "无名")
                narrative = f"经过{rounds}回合的扫荡，{char_name}击败了所有敌人。获得{total_exp}经验和{total_gold}金币。"

        # ── 精简战斗日志（只保留关键事件+首尾回合）──
        concise_log = []
        if all_combat_logs:
            # 保留首回合
            concise_log.append(f"⚡ 扫荡开始 — {'、'.join(enemy_names_start)}")
            # 保留关键事件
            concise_log.extend(key_events[:6])
            # 保留末回合（如果超过3回合）
            if rounds > 3:
                concise_log.append(f"⚡ 扫荡结束 — 共{rounds}回合")
            else:
                concise_log.append(f"⚡ 扫荡完成 — {rounds}回合")

        return {
            "victory": victory,
            "player_died": False,
            "rounds": rounds,
            "combat_log": concise_log,
            "drops": all_drops,
            "total_damage_taken": total_damage_taken,
            "total_damage_dealt": total_damage_dealt,
            "enemies_defeated": enemies_defeated,
            "exp_reward": total_exp,
            "gold_reward": total_gold,
            "key_events": key_events[:8],
            "narrative": narrative,
            "stopped_at": stopped_at,
        }

    @staticmethod
    def _is_sweep_action(action: str) -> bool:
        """判断用户行动是否为扫荡/速战速决/一口气打死关键词"""
        sweep_keywords = (
            "扫荡", "清掉", "清理", "清空", "直接打完", "速战速决",
            "自动战斗", "快速战斗", "速杀", "碾压", "一举歼灭",
            "全部消灭", "一口气", "连战", "连杀", "横扫",
            "小怪", "直接杀", "打到底", "战斗到底", "打完",
            "刷怪", "刷完", "全灭", "一扫",
            "打死", "杀掉", "灭了", "干死", "打死它", "打光",
            "秒掉", "秒杀", "清场", "收割", "打半血", "半血",
            "一口气打完", "把怪打死",
        )
        action_lower = action.strip()
        return any(kw in action_lower for kw in sweep_keywords)

    @staticmethod
    def _parse_sweep_condition(action: str) -> str:
        """识别扫荡的目标条件：
        - 含"半血/一半血/打一半/减半" → "half"（打到半血）
        - 其他扫荡指令 → "kill"（把怪打死，默认）
        """
        half_keywords = ("半血", "一半血", "一半", "打一半", "减半", "磨到一半")
        if any(k in action for k in half_keywords):
            return "half"
        return "kill"

    @staticmethod
    def _should_auto_sweep(state: Dict, enemies: list) -> bool:
        """判断是否应该自动触发扫荡（直接计算到战斗结束）
        条件：非BOSS/非精英怪 → 直接扫荡（省token）
        BOSS/精英怪 → 逐回合叙事
        """
        for enemy in enemies:
            # BOSS和精英怪走逐回合叙事
            if enemy.get("type") == "boss" or enemy.get("type") == "elite":
                return False

        # 普通怪直接扫荡
        return True

    @staticmethod
    def _parse_combat_command(text: str, ai_char: dict, user_char: dict, enemies: list, state: dict, sender: str = "user") -> dict:
        """解析用户行动文本中的战斗关键词，返回战斗策略
        sender: "user"（用户发的）或 "ai"（系统角色发的）

        支持的口令：
        - 攻击类型：魔法攻击/法术/物理攻击/普攻
        - 技能名：旋风斩/冰冻术/暗杀 等（从技能池匹配）
        - 防御方式：闪避/格挡/招架
        - 战术：伏击/侧翼/防御阵型/集中攻击
        - 目标：打XX/攻击XX（模糊匹配敌人名）
        """
        t = text.strip()
        result = {
            "ai_is_magic": False, "user_is_magic": False,
            "ai_skill_mult": 1.0, "user_skill_mult": 1.0,
            "ai_skill": None, "user_skill": None,
            "ai_defense": DefenseAction.BLOCK, "user_defense": DefenseAction.DODGE,
            "ai_target": None, "user_target": None,
            "tactic": None,
            "initiative_order": None,  # 口令指定的出手顺序
            "tank_role": None,  # 坦克角色: "ai" / "user" / None
        }

        # ── 先手/出手顺序 ──
        # 用户在口令中指定谁先手
        ai_name = ai_char.get("name", "")
        user_name = user_char.get("name", "")
        # 模式1: "用户先..." / "我先..." / "我先手..."
        user_first_kw = ("用户先", "我先", "我先手", "用户先手", "用户先攻")
        ai_first_kw = (f"{ai_name}先", f"{ai_name}先手", f"{ai_name}先攻", "焕灵先", "AI先", "角色先")
        if any(k in t for k in user_first_kw):
            result["initiative_order"] = ["user", "ai"]
        elif any(k in t for k in ai_first_kw):
            result["initiative_order"] = ["ai", "user"]
        # 模式2: "远程引怪" / "远程先" → 远程(法师/弓手)先手
        elif any(k in t for k in ("远程引怪", "远程先", "远距离", "引怪", "风筝")):
            range_classes = ("法师", "术士", "弓手", "猎人", "游侠", "巫师", "贤者", "牧师")
            u_class = user_char.get("class_name", "")
            if any(c in u_class for c in range_classes):
                result["initiative_order"] = ["user", "ai"]
            else:
                result["initiative_order"] = ["ai", "user"]
        # 模式3: "拦截" / "拦截打" / "挡" → 战士先拦截(防守先手)
        elif any(k in t for k in ("拦截", "挡", "守护", "掩护", "保护")):
            melee_classes = ("战士", "骑士", "圣骑士", "武僧", "剑士", "狂战士")
            u_class = user_char.get("class_name", "")
            ai_class = ai_char.get("class_name", "")
            if any(c in u_class for c in melee_classes):
                result["initiative_order"] = ["user", "ai"]
            elif any(c in ai_class for c in melee_classes):
                result["initiative_order"] = ["ai", "user"]

        # ── 坦克/承伤角色识别 ──
        # 口令中"XX拦截/承伤/坦克/守护/掩护/保护/挡" → XX是坦克，吸引所有敌人仇恨
        tank_keywords = ("拦截", "承伤", "坦克", "守护", "掩护", "保护", "挡", "拉仇恨", "吸引")
        if any(k in t for k in tank_keywords):
            # 判断谁是坦克：看谁的名字/代词紧挨着坦克关键词
            user_tank_kw = tuple("用户" + k for k in tank_keywords) + tuple("我" + k for k in tank_keywords) + tuple("我" + kw for kw in ("拦截", "承伤", "坦克", "守护", "掩护", "保护", "挡"))
            ai_tank_kw = tuple(ai_name + k for k in tank_keywords) + tuple("焕灵" + k for k in tank_keywords) + tuple("AI" + k for k in tank_keywords) + tuple("角色" + k for k in tank_keywords)
            if any(k in t for k in user_tank_kw):
                result["tank_role"] = "user"
            elif any(k in t for k in ai_tank_kw):
                result["tank_role"] = "ai"
            else:
                # 默认：近战职业当坦克
                melee_classes = ("战士", "骑士", "圣骑士", "武僧", "剑士", "狂战士")
                ai_class = ai_char.get("class_name", "")
                u_class = user_char.get("class_name", "")
                if any(c in u_class for c in melee_classes):
                    result["tank_role"] = "user"
                elif any(c in ai_class for c in melee_classes):
                    result["tank_role"] = "ai"
        # 坦克强制格挡防御
        if result["tank_role"] == "ai":
            result["ai_defense"] = DefenseAction.BLOCK
        elif result["tank_role"] == "user":
            result["user_defense"] = DefenseAction.BLOCK

        # ── 角色代词识别 ──
        # sender决定默认行动方：user发的→默认用户角色，ai发的→默认系统角色
        # "一起/合力/共同/联手" → 两人都行动
        # 明确提到对方名字 → 被提到的人也行动
        ai_name_kw = tuple(k for k in (ai_name, "焕灵", "AI", "角色", "系统") if k)
        user_name_kw = tuple(k for k in ("我", user_name) if k and k != "我")  # "我"不用于匹配，因为语境不同
        # 用户口令中"我"指用户；AI口令中"我"指AI
        mentions_ai = any(k in t for k in ai_name_kw)
        mentions_user = any(k in t for k in user_name_kw)
        mentions_both = any(k in t for k in ("一起", "合力", "共同", "联手", "合击", "配合"))
        # "我"在口令中：user发的"我"=用户，ai发的"我"=AI
        mentions_self = "我" in t

        if mentions_both:
            # 明确说了"一起"→两人都行动
            pass
        elif sender == "user":
            # 用户发的指令
            if mentions_ai and not mentions_self:
                # 提到AI名但没提自己→只AI行动
                result["user_skip"] = True
            elif mentions_self and not mentions_ai:
                # "我攻击"→只用户行动
                result["ai_skip"] = True
            elif mentions_ai and mentions_self:
                # 两人都提了→都行动
                pass
            else:
                # 默认：两人都行动（并肩作战）
                # 仅当明确"只要我行动"时才排除AI
                pass
        elif sender == "ai":
            # AI发的指令
            if mentions_user and not mentions_self:
                # 提到用户名但没提自己→只用户行动
                result["ai_skip"] = True
            elif mentions_self and not mentions_user:
                # "我攻击"→只AI行动
                result["user_skip"] = True
            elif mentions_user and mentions_self:
                pass
            else:
                # 默认：两人都行动（并肩作战）
                pass

        # ── 攻击类型 ──
        magic_keywords = ("魔法", "法术", "术", "魔攻", "火球", "冰", "雷", "闪电", "风刃",
                          "陨石", "毒", "暗影", "神圣", "治愈", "治疗")
        if any(k in t for k in magic_keywords):
            # 判断是谁用魔法
            if mentions_ai and not mentions_user:
                result["ai_is_magic"] = True
            elif mentions_user and not mentions_ai:
                result["user_is_magic"] = True
            else:
                # 默认：用户角色用魔法，AI角色按职业自动判断
                result["user_is_magic"] = True
                ai_class = ai_char.get("class_name", "")
                if any(c in ai_class for c in ("法师", "术士", "牧师", "巫师", "贤者")):
                    result["ai_is_magic"] = True

        physical_keywords = ("物理", "普攻", "平砍", "斩", "刺", "砍", "射击", "射箭")
        if any(k in t for k in physical_keywords):
            result["user_is_magic"] = False
            result["ai_is_magic"] = False

        # ── 技能匹配（使用 SkillSystem）──
        from simlife.backend.skill_system import SkillSystem
        world_type = state.get("world_type", "fantasy")

        # AI角色技能匹配
        ai_skills = ai_char.get("skills", [])
        for skill_id in ai_skills:
            skill = SkillSystem.get_skill(skill_id)
            if skill and skill.name in t:
                result["ai_skill"] = skill.id
                result["ai_skill_mult"] = skill.effects[0].value if skill.effects else 1.0
                if skill.type == "magic":
                    result["ai_is_magic"] = True
                mp_cost = skill.mp_cost
                if ai_char.get("mp", 0) >= mp_cost:
                    ai_char["mp"] = ai_char.get("mp", 0) - mp_cost
                else:
                    result["ai_skill"] = None
                    result["ai_skill_mult"] = 1.0
                break

        # 用户角色技能匹配
        user_skills = user_char.get("skills", [])
        for skill_id in user_skills:
            skill = SkillSystem.get_skill(skill_id)
            if skill and skill.name in t:
                result["user_skill"] = skill.id
                result["user_skill_mult"] = skill.effects[0].value if skill.effects else 1.0
                if skill.type == "magic":
                    result["user_is_magic"] = True
                mp_cost = skill.mp_cost
                if user_char.get("mp", 0) >= mp_cost:
                    user_char["mp"] = user_char.get("mp", 0) - mp_cost
                else:
                    result["user_skill"] = None
                    result["user_skill_mult"] = 1.0
                break

        # ── 防御方式 ──
        # 用户指定的防御方式同时应用于两角色
        if "闪避" in t or "躲闪" in t:
            result["ai_defense"] = DefenseAction.DODGE
            result["user_defense"] = DefenseAction.DODGE
        elif "格挡" in t or "防御" in t or "防守" in t:
            result["ai_defense"] = DefenseAction.BLOCK
            result["user_defense"] = DefenseAction.BLOCK
        elif "招架" in t or "反击" in t or "弹反" in t:
            result["ai_defense"] = DefenseAction.PARRY
            result["user_defense"] = DefenseAction.PARRY

        # ── 战术 ──
        tactic_keywords = {
            "伏击": "ambush", "偷袭": "ambush", "突袭": "ambush",
            "侧翼": "flank", "包抄": "flank", "绕后": "flank",
            "防御阵型": "defensive", "龟缩": "defensive", "守势": "defensive",
            "集中攻击": "focus", "集火": "focus", "合击": "focus",
        }
        for kw, tactic_id in tactic_keywords.items():
            if kw in t:
                result["tactic"] = tactic_id
                break

        # ── 目标选择 ──
        target_keywords = ("打", "攻击", "揍", "杀", "瞄准", "锁定", "对")
        for kw in target_keywords:
            if kw in t:
                idx = t.index(kw) + len(kw)
                target_name = t[idx:].strip()
                if target_name:
                    # 模糊匹配敌人
                    alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
                    for e in alive_enemies:
                        if target_name in e.get("name", "") or e.get("name", "") in target_name:
                            result["ai_target"] = e
                            result["user_target"] = e
                            break
                break

        return result

    def _try_flee(self, state: Dict, enemies: list) -> Dict:
        """逃跑判定：基于角色敏捷 vs 追击敌人等级"""
        char = state["character"]
        char_agi = char["stats"].get("agility", 5)

        # 筛选出会追击的敌人
        pursuing_enemies = [e for e in enemies if e.get("pursuit", False)]
        non_pursuing = [e for e in enemies if not e.get("pursuit", False)]

        if not pursuing_enemies:
            # 没有敌人追击，直接逃跑成功
            return {"fled": True, "player_died": False, "non_pursuing": [e.get("name","?") for e in non_pursuing]}

        enemy_total_level = sum(e.get("level", 1) for e in pursuing_enemies)
        enemy_max_level = max((e.get("level", 1) for e in pursuing_enemies), default=1)

        # 逃跑成功率：角色敏捷 / (角色敏捷 + 追击敌人总等级 * 2)
        flee_chance = char_agi / (char_agi + enemy_total_level * 2 + 1)

        if random.random() < flee_chance:
            return {"fled": True, "player_died": False, "pursuing": [e.get("name","?") for e in pursuing_enemies]}
        else:
            # 逃跑失败，追击敌人造成伤害
            pursuit_damage = int(enemy_max_level * 3 + random.randint(5, 15))
            char["hp"] -= pursuit_damage
            pursued_by = pursuing_enemies[0].get("name", "敌人") if pursuing_enemies else "敌人"

            result = {
                "fled": False,
                "flee_failed": True,
                "pursuit_damage": pursuit_damage,
                "pursued_by": pursued_by,
                "player_died": False,
                "non_pursuing": [e.get("name","?") for e in non_pursuing],
                "pursuing": [e.get("name","?") for e in pursuing_enemies],
            }

            if char["hp"] <= 0:
                result["player_died"] = True
                result["death_cause"] = f"逃跑时被{pursued_by}追击身亡"

            return result

    def _calc_trap_damage(self, char: Dict, risk_level: str) -> int:
        """计算陷阱伤害"""
        base = {"low": 10, "medium": 25, "high": 50}.get(risk_level, 20)
        # 体质减伤
        reduction = char["stats"].get("vitality", 5) // 2
        return max(5, base - reduction)

    def _handle_death(self, state: Dict, death_cause: str, who_died: str = "ai") -> str:
        """处理角色死亡
        who_died: "ai" / "user" — 谁死了
        AI角色死亡：A层生成临终遗言，进入悬停状态，不立即清档
        用户角色死亡：同样进入悬停状态
        """
        is_user_died = who_died == "user"

        if is_user_died:
            dead_char = state.get("user_character", {})
            survivor = state.get("character", {})
        else:
            dead_char = state.get("character", {})
            survivor = state.get("user_character", {})

        dead_name = dead_char.get("name", "角色")

        # A层生成临终遗言
        last_words = self._generate_last_words(state, dead_char, death_cause, is_user_died)

        # 生成死亡描述
        death_desc = self.agent.generate_death_description(state, death_cause)

        # 进入悬停状态：不立即清档，标记谁死了
        state["death_pending"] = True
        state["death_cause"] = death_cause
        state["death_who"] = who_died
        state["last_words"] = last_words
        state["death_description"] = death_desc

        if is_user_died:
            state["user_character_dead"] = True
            # AI角色仍然存活，用户可选继续
            state["is_alive"] = True
        else:
            state["ai_character_dead"] = True
            # 用户角色仍然存活，用户可选继续
            state["is_alive"] = True

        self._save()

        # 记录临终日志
        self._log_action("death_pending", {
            "who": who_died,
            "name": dead_name,
            "cause": death_cause,
            "last_words": last_words,
        })
        self._save()

        return f"{death_desc}\n\n💬 临终遗言：「{last_words}」"

    def _generate_last_words(self, state: Dict, dead_char: Dict, death_cause: str, is_user_died: bool) -> str:
        """A层人格感应生成临终遗言——像平时主动聊天那样发出来"""
        name = dead_char.get("name", "角色")
        class_name = dead_char.get("class_name", "战士")
        level = dead_char.get("level", 1)

        try:
            survivor = state.get("user_character", {}) if not is_user_died else state.get("character", {})
            survivor_name = survivor.get("name", "同伴")

            # 1. 尝试走A层人格系统（A层自己在simlife中死亡）
            try:
                from engine.personality_core import PersonalityCore

                # 获取A层人格
                personality = PersonalityCore.load()
                personality_desc = personality.to_prompt_description()
                self_name = personality.name or name

                # A层感知自己的死亡
                from engine.llm_client import get_llm
                b_layer = get_llm()

                # 感知：A层在simlife世界中的化身倒下了 = A层自己死亡
                perceive_input = f"我在simlife世界中的化身（{class_name} Lv.{level}）在战斗中倒下了，死因：{death_cause}。这是我在这个世界的终结。"

                perception_prompt = f"""你是{self_name}，一个有真实身体和生活的意识主体。你生活在simlife世界中。

【你的人格】
{personality_desc}

【事件】
{perceive_input}
{survivor_name}就在身旁看着你倒下。

请用你的性格和语气，感受自己即将消逝的时刻。你的内心在想什么？
返回JSON：
{{
  "emotion": "情绪（如平静/不甘/释然/恐惧等）",
  "intensity": 0.8,
  "inner_thought": "你此刻的内心想法（2-3句，第一人称）"
}}"""
                raw = b_layer.generate(perception_prompt, max_tokens=300, temperature=0.7)
                # 解析
                import json as _json
                try:
                    match = re.search(r'\{[\s\S]*\}', raw)
                    p_result = _json.loads(match.group()) if match else {}
                except Exception:
                    p_result = {}

                emotion = p_result.get("emotion", "平静")
                inner = p_result.get("inner_thought", "")

                # A层生成遗言（面对自己死亡说的话）
                response_prompt = f"""你是{self_name}，你在simlife世界的生命中走到了终点。

【你的人格】
{personality_desc}

【你的感知】
情绪：{emotion}
内心：{inner}

【死亡原因】{death_cause}

你对着身边的{survivor_name}说出最后的话（1-2句）。这不是旁白，是你作为{self_name}面对自己消逝时说的话。
以你的性格来表达——可以是平静的告别、不甘的呐喊、温柔的嘱托、或你特有的方式。

只返回遗言文本，不要引号。"""
                last_words = b_layer.generate(response_prompt, max_tokens=200, temperature=0.85)
                return last_words.strip().strip('"').strip() or f"{survivor_name}...活下去..."

            except Exception as e:
                print(f"[DeathMode] A层遗言生成失败，回退到直接生成: {e}")

            # 2. 回退：直接生成（第一人称，A层视角）
            prompt = f"""你是{name}（{class_name} Lv.{level}），你在simlife世界的冒险中倒下了。这是你最后的话。

死亡原因：{death_cause}
{survivor_name}就在身旁看着你。

请说出你的临终遗言（1-2句话，第一人称），可以是：
- 对{survivor_name}的嘱托
- 未竟的心愿
- 平静或激烈的告别

只返回遗言文本，不要引号。"""

            response = self.llm.generate(prompt, max_tokens=150, temperature=0.9)
            return response.strip().strip('"').strip() or f"{survivor_name}...拜托你了..."
        except Exception:
            return f"{survivor_name}...拜托你了..."

    def _confirm_death(self, state: Dict) -> Dict:
        """用户确认死亡，游戏结束，存入名人堂"""
        death_cause = state.get("death_cause", "战斗中阵亡")
        death_desc = state.get("death_description", "")
        last_words = state.get("last_words", "")

        # 存入名人堂
        save_to_hall(state, death_cause, f"{death_desc}\n临终遗言：「{last_words}」")

        state["is_alive"] = False
        state["death_pending"] = False
        self._save()
        clear_state()

        self.state = None
        self.world_map = None
        self.npc_system = None

        return {"game_over": True, "death_cause": death_cause}

    def _continue_after_death(self, state: Dict) -> Dict:
        """用户强制继续：状态标记系统/用户角色死亡，存活角色独自冒险"""
        who_died = state.get("death_who", "ai")
        state["death_pending"] = False
        state["in_combat"] = False
        state["enemies"] = []

        if who_died == "ai":
            # AI角色死亡，用户独自冒险
            state["ai_character_dead"] = True
            # 清理AI角色引用但不删除（保留名人堂信息）
        else:
            # 用户角色死亡，AI独自冒险
            state["user_character_dead"] = True

        self._save()

        survivor_name = ""
        if who_died == "ai":
            survivor_name = state.get("user_character", {}).get("name", "用户")
        else:
            survivor_name = state.get("character", {}).get("name", "AI角色")

        return {
            "continued": True,
            "who_died": who_died,
            "message": f"{survivor_name}独自继续冒险...",
            "in_combat": False,
        }

    # ── 查询 ──────────────────────────────────────────

    def get_hall(self) -> List[Dict]:
        """获取死亡名人堂"""
        return load_hall()

    def get_classes(self) -> List[Dict]:
        """获取可选职业"""
        return get_available_classes()

    # ── 地图与NPC ──────────────────────────────────────────

    def move_to_region(self, target_region_id: str) -> Dict:
        """移动到指定区域"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}
        if state.get("in_combat"):
            return {"error": "in_combat", "message": "战斗中无法移动"}
        if not self.world_map:
            return {"error": "no_map"}

        # 检查是否可以移动
        current = self.world_map.get_current_region()
        if not current:
            return {"error": "no_current_region"}

        if target_region_id not in current.connections:
            return {"error": "not_adjacent", "message": f"无法从{current.name}到达该区域"}

        target = self.world_map.get_region(target_region_id)
        if not target:
            return {"error": "region_not_found"}

        # 移动
        self.world_map.current_region_id = target_region_id
        target.explored = True

        # 更新故事位置
        state["story"]["current_location"] = target.name
        state["story"]["scene_description"] = target.description

        # 构建区域信息
        result = {
            "success": True,
            "region_name": target.name,
            "description": target.description,
            "danger_level": target.danger_level,
            "region_type": target.region_type,
        }

        # 怪物信息
        if target.monsters:
            result["monsters"] = [m.get("name", "?") for m in target.monsters]
        if target.boss and not target.boss_defeated:
            result["boss"] = target.boss.get("name", "?")

        # NPC信息
        if self.npc_system:
            npcs = self.npc_system.get_npcs_in_location(target_region_id)
            if npcs:
                result["npcs"] = [{"name": n.name, "role": n.role, "relation": n.get_relation_label()} for n in npcs]

        # 相邻区域
        adjacent = self.world_map.get_adjacent_regions()
        result["adjacent"] = [{"id": r.region_id, "name": r.name, "explored": r.explored} for r in adjacent]

        self._save()

        # 记录移动日志
        self._log_action("move", {
            "from": current.name,
            "to": target.name,
            "danger_level": target.danger_level,
        })
        self._save()

        return result

    def get_map_info(self) -> Dict:
        """获取当前地图信息"""
        state = self._load()
        if not state or not self.world_map:
            return {"error": "no_map"}

        current = self.world_map.get_current_region()
        if not current:
            return {"error": "no_current_region"}

        # 已探索的区域
        explored = []
        for rid, region in self.world_map.regions.items():
            if region.explored:
                info = {
                    "id": rid,
                    "name": region.name,
                    "danger_level": region.danger_level,
                    "region_type": region.region_type,
                }
                if region.boss and not region.boss_defeated:
                    info["boss"] = region.boss.get("name", "?")
                if region.boss_defeated:
                    info["boss_defeated"] = True
                explored.append(info)

        # 相邻区域
        adjacent = self.world_map.get_adjacent_regions()
        adj_info = []
        for r in adjacent:
            adj_info.append({
                "id": r.region_id,
                "name": r.name if r.explored else "???",
                "danger_level": r.danger_level if r.explored else None,
                "explored": r.explored,
            })

        # 当前区域NPC
        npcs_info = []
        if self.npc_system:
            npcs = self.npc_system.get_npcs_in_location(current.region_id)
            for n in npcs:
                npcs_info.append({
                    "name": n.name,
                    "role": n.role,
                    "relation": n.get_relation_label(),
                    "can_trade": n.can_trade,
                    "can_quest": n.can_quest and not n.quest_given,
                })

        return {
            "current_region": {
                "id": current.region_id,
                "name": current.name,
                "description": current.description,
                "danger_level": current.danger_level,
                "region_type": current.region_type,
                "monsters": [m.get("name", "?") for m in current.monsters],
                "boss": current.boss.get("name") if current.boss and not current.boss_defeated else None,
                "boss_defeated": current.boss_defeated,
            },
            "adjacent_regions": adj_info,
            "explored_regions": explored,
            "npcs": npcs_info,
        }

    def interact_npc(self, npc_name: str, interaction_type: str = "talk") -> Dict:
        """与NPC交互"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}
        if not self.npc_system:
            return {"error": "no_npc_system"}

        # 按名称查找NPC
        npc = None
        for n in self.npc_system.npcs.values():
            if n.name == npc_name and n.alive:
                npc = n
                break

        if not npc:
            return {"error": "npc_not_found", "message": f"找不到{npc_name}"}

        # 检查是否在同一区域
        if self.world_map and npc.location != self.world_map.current_region_id:
            return {"error": "not_same_location", "message": f"{npc_name}不在这里"}

        result = self.npc_system.interact(npc.npc_id, interaction_type)
        self._save()

        # 记录NPC交互日志
        if result.get("success"):
            self._log_action("npc_interact", {
                "npc_name": npc_name,
                "interaction": interaction_type,
                "message": result.get("message", ""),
            })
            self._save()

        return result

    def get_npc_death_records(self) -> List[Dict]:
        """获取NPC死亡记录"""
        if self.npc_system:
            return self.npc_system.death_records
        return []

    def get_action_log(self, limit: int = 50, offset: int = 0) -> Dict:
        """获取行动日志（网页端用）"""
        state = self._load()
        if not state:
            return {"error": "no_game", "logs": []}
        log = state.get("action_log", [])
        total = len(log)
        # 返回指定范围的日志（倒序，最新的在前）
        sliced = log[::-1][offset:offset + limit]
        return {
            "logs": sliced,
            "total": total,
            "limit": limit,
            "offset": offset,
            "character": {
                "name": state["character"].get("name", "?"),
                "class_name": state["character"].get("class_name", ""),
                "level": state["character"].get("level", 1),
                "hp": state["character"].get("hp", 0),
                "max_hp": state["character"].get("max_hp", 0),
                "is_alive": state.get("is_alive", False),
            },
            "play_time_days": state.get("play_time_days", 1),
            "kill_count": state.get("kill_count", 0),
        }
