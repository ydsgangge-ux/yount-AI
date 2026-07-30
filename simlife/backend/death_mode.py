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

    def _load(self):
        """加载或刷新状态"""
        if self.state is None:
            self.state = load_state()
        # 恢复地图和NPC
        if self.state and self.world_map is None and self.state.get("world_map"):
            self.world_map = WorldMap.from_dict(self.state["world_map"])
        if self.state and self.npc_system is None and self.state.get("npc_system"):
            self.npc_system = NPCSystem.from_dict(self.state["npc_system"])
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
    ) -> Dict:
        """开始新游戏"""
        self.state = create_initial_state(
            character_name=character_name,
            class_id=class_id,
            world_setting=world_setting,
            growth_mode=growth_mode,
            custom_stat_points=custom_stat_points,
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
            self._save(state)

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
            "npc_death_records": state.get("npc_death_records", []),
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

    def process_choice(self, choice_id: str = None, free_action: str = None) -> Dict:
        """
        处理用户选择或自由行动。
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

        # 确定行动
        action = free_action if free_action else choice_id
        action_type = "free" if free_action else "choice"

        if not action:
            return {"error": "no_action"}

        # 1. Agent 生成叙事（不含数值结果）
        agent_result = self.agent.process_action(state, action, action_type)
        narrative = agent_result.get("narrative", "")
        outcome_type = agent_result.get("outcome_type", "nothing")
        next_tension = agent_result.get("next_tension", "medium")

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
                combat_result = self._combat_round(state, enemies, ai_alone=True)
                result["combat_result"] = combat_result
                result["in_combat"] = combat_result.get("in_combat", True)
                result["enemies"] = combat_result.get("enemies", enemies)
                if combat_result.get("character_died"):
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "独自战斗时阵亡"))
            elif is_flee:
                # AI角色逃跑判定
                flee_result = self._try_flee(state, enemies)
                result["combat_result"] = flee_result
                if flee_result.get("player_died"):
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, flee_result.get("death_cause", "逃跑时被追击身亡"))
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
                combat_result = self._combat_round(state, enemies)
                result["combat_result"] = combat_result

                if combat_result.get("player_died"):
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "战斗中阵亡"))
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

                # 第一回合
                combat_result = self._combat_round(state, enemies_list)
                result["combat_result"] = combat_result

                if combat_result.get("player_died"):
                    result["character_died"] = True
                    result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "战斗中阵亡"))
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
                    return result

            # 休息恢复
            elif action_type_value == "rest" or outcome_type == "rest":
                heal_amount = int(char["max_hp"] * 0.2)
                mp_recover = int(char["max_mp"] * 0.3)
                char["hp"] = min(char["max_hp"], char["hp"] + heal_amount)
                char["mp"] = min(char["max_mp"], char["mp"] + mp_recover)
                result["combat_result"] = {"rest_heal": heal_amount, "mp_recover": mp_recover, "hp_remaining": char["hp"]}

            # 发现宝箱
            elif outcome_type == "discovery":
                gold_found = random.randint(10, 50) + char["level"] * 5
                char["gold"] += gold_found
                result["gold_gained"] = gold_found
                if random.random() < 0.3:
                    exp_bonus = 20 + char["level"] * 5
                    result["exp_gained"] = exp_bonus
                    GrowthSystem.gain_exp(char, exp_bonus, state.get("growth_mode", "normal"))

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

        self._log_action("action", log_data)
        self._save()

        return result

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
            enemy = CombatSystem.generate_enemy(char_level, world_setting, enemy_type)
            # 如果当前区域有怪物，替换名称
            if region_monster_names:
                enemy["name"] = random.choice(region_monster_names)
            # 多个敌人时编号
            if count > 1:
                enemy["name"] = f"{enemy['name']}{i+1}"
            enemies.append(enemy)

        return enemies

    def _combat_round(self, state: Dict, enemies: list, ai_alone: bool = False) -> Dict:
        """执行一回合战斗（回合制：玩家攻击 → 存活敌人反击，使用v2战斗系统）
        ai_alone: 用户已逃跑，AI角色独自面对所有敌人（受到更多伤害）
        """
        char = state["character"]
        combat_log = []
        drops = []  # 本回合掉落

        # AI角色攻击第一个存活的敌人
        target = next((e for e in enemies if e.get("hp", 0) > 0), None)
        if target:
            # 敌人随机选择防御方式
            def_choices = [DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.NONE]
            if target.get("stats", {}).get("intelligence", 5) > 12:
                def_choices.append(DefenseAction.PARRY)
            enemy_defense = random.choice(def_choices)

            atk_result = CombatSystem.attack(char, target, defense_action=enemy_defense)
            combat_log.append(f"{char.get('name','你')}{atk_result['description']} → {target.get('name', '?')}")

            # 检查敌人是否被击败
            if target.get("hp", 0) <= 0:
                # 装备掉落
                luck = char.get("stats", {}).get("luck", 5)
                drop = EquipmentSystem.roll_drop(
                    target.get("level", 1), target.get("type", "normal"),
                    luck, state.get("world_type", "fantasy")
                )
                if drop:
                    drops.append(drop)
                    EquipmentSystem.equip_item(char, drop)
                    combat_log.append(f"掉落：{drop['name']}（{drop.get('rarity_name', '普通')}）已装备")

        # 存活敌人反击
        for enemy in enemies:
            if enemy.get("hp", 0) <= 0:
                continue
            # AI角色防御
            player_defense = DefenseAction.BLOCK
            if char.get("stagger_turns", 0) > 0:
                player_defense = DefenseAction.NONE

            def_result = CombatSystem.attack(enemy, char, defense_action=player_defense)

            # 独自战斗时，敌人伤害更高（无人分担）
            if ai_alone and def_result.get("damage", 0) > 0:
                def_result["damage"] = int(def_result["damage"] * 1.4)
                if def_result.get("defense_result"):
                    def_result["defense_result"]["damage_taken"] = int(
                        def_result["defense_result"].get("damage_taken", 0) * 1.4
                    )

            combat_log.append(f"{enemy.get('name', '?')}{def_result['description']} → {char.get('name','你')}")

            if char["hp"] <= 0:
                return {
                    "victory": False,
                    "player_died": True,
                    "death_cause": f"被{enemy.get('name', '敌人')}击败" + ("（独自战斗时阵亡）" if ai_alone else ""),
                    "combat_log": combat_log,
                    "drops": drops,
                }

        return {
            "victory": False,
            "player_died": False,
            "combat_log": combat_log,
            "drops": drops,
        }

    def _try_flee(self, state: Dict, enemies: list) -> Dict:
        """逃跑判定：基于角色敏捷 vs 敌人等级，强敌追击"""
        char = state["character"]
        char_agi = char["stats"].get("agility", 5)
        enemy_total_level = sum(e.get("level", 1) for e in enemies)
        enemy_max_level = max((e.get("level", 1) for e in enemies), default=1)

        # 逃跑成功率：角色敏捷 / (角色敏捷 + 敌人总等级 * 2)
        flee_chance = char_agi / (char_agi + enemy_total_level * 2 + 1)

        if random.random() < flee_chance:
            return {"fled": True, "player_died": False}
        else:
            # 逃跑失败，敌人追击
            # 强敌（高等级）追击伤害更高
            pursuit_damage = int(enemy_max_level * 3 + random.randint(5, 15))
            char["hp"] -= pursuit_damage
            pursued_by = enemies[0].get("name", "敌人") if enemies else "敌人"

            result = {
                "fled": False,
                "flee_failed": True,
                "pursuit_damage": pursuit_damage,
                "pursued_by": pursued_by,
                "player_died": False,
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

    def _handle_death(self, state: Dict, death_cause: str) -> str:
        """处理角色死亡"""
        death_desc = self.agent.generate_death_description(state, death_cause)

        state["is_alive"] = False
        state["death_cause"] = death_cause
        save_to_hall(state, death_cause, death_desc)
        self._save()
        clear_state()

        # 修复内存泄漏：清空引用，下次 _load() 重新从磁盘加载
        self.state = None
        self.world_map = None
        self.npc_system = None

        return death_desc

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
