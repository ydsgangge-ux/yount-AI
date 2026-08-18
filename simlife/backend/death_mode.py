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
    STATE_FILE,
)
from simlife.backend.combat_system import CombatSystem, CombatEntity, DefenseAction
from simlife.backend.growth_system import GrowthSystem
from simlife.backend.story_agent import StoryAgent
from simlife.backend.generator import get_llm_client
from simlife.backend.world_map import WorldMap, MapGenerator
from simlife.backend.npc_system import NPCSystem, NPCGenerator
from simlife.backend.equipment_system import EquipmentSystem
from simlife.backend.quest_system import QuestSystem
from simlife.backend.world_progress import WorldProgress
from simlife.backend.world_simulation import WorldSimulation
from simlife.backend.dungeon_agent import DungeonAgent, Dungeon
from simlife.backend.region_agent import RegionAgent
from simlife.backend.party_agent import PartyAgent, PartyMember
from simlife.backend.ending_system import generate_hidden_ending, HiddenEnding


# 可刷新小怪关键词：只有命中这些"特别普通"的怪，死后才会重新刷出；
# 其余有名有姓的怪物一旦击败即永久登记，无法再新生（地区怪物总量控制）。
REFRESHABLE_MOB_KEYWORDS = (
    "史莱姆", "软泥", "元素", "植物", "蘑菇", "孢子", "水晶", "藤蔓", "花",
    "哥布林", "骷髅", "蜘蛛", "蝙蝠", "狼", "虫", "老鼠", "蛇", "鸟", "鱼",
    "守卫", "卫兵", "士兵", "流浪汉", "佣人", "平民",
    "slime", "goblin", "skeleton", "spider", "bat", "wolf", "rat",
    "bug", "snake", "elemental", "plant", "mushroom", "guard", "soldier",
)


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
        self.region_agent: Optional[RegionAgent] = None
        self.dungeon_agent: Optional[DungeonAgent] = None
        self._current_dungeon: Optional[Dungeon] = None
        self.party_agent: Optional[PartyAgent] = None

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

    def _drop_life_materials(self, enemy: Dict, combat_log: List):
        """战斗掉落：生活技能原材料（LLM 自由组合的物料来源之一）。
        敌人等级越高、类型越强，掉落越高级材料。
        """
        try:
            from simlife.backend import life_skills as LS
            if not self.state:
                return
            ls = LS.ensure_life_state(self.state)
            level = enemy.get("level", 1) or 1
            etype = enemy.get("type", "normal") or "normal"
            # 掉落概率：普通 30%，精英 55%，BOSS 100%；等级越高越容易出
            base_chance = {"normal": 0.30, "elite": 0.55, "boss": 1.0}.get(etype, 0.30)
            if random.random() > min(0.95, base_chance + level * 0.01):
                return
            # 按敌人等级决定可掉落材料池
            pool = [m for m in LS.RAW_MATERIALS if m["type"] in ("ingredient", "ore", "misc", "enchant")]
            high = [m for m in pool if m["type"] == "enchant" or m["price"] >= 15]
            if level >= 8 and high:
                candidates = high
            elif level >= 4:
                candidates = [m for m in pool if m["price"] >= 8] or pool
            else:
                candidates = [m for m in pool if m["price"] <= 10]
            mat = random.choice(candidates)
            qty = random.randint(1, 2) + (1 if level >= 6 else 0)
            LS.add_materials(ls["inventory"], mat["id"], qty, mat["name"], mat["icon"])
            if combat_log is not None:
                combat_log.append(f"采获：{mat['icon']} {mat['name']}×{qty}（生活材料）")
            self._log_action("life_skill", {
                "skill": "采集", "action": f"从{enemy.get('name', '敌人')}身上采获{mat['name']}×{qty}",
                "detail": {"material": mat["name"], "qty": qty, "enemy": enemy.get("name", "")},
            })
        except Exception:
            pass

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
            # 恢复 RegionAgent
            if self.region_agent is None:
                try:
                    world_id = self.state.get("world_setting", {}).get("world_id", "")
                    self.region_agent = RegionAgent(self.world_map, world_id)
                except Exception:
                    pass
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
        # 兼容旧存档：确保生活技能状态存在
        if self.state and not self.state.get("life_state"):
            from simlife.backend.life_skills import ensure_life_state
            ensure_life_state(self.state)
        # 迁移旧存档：技能中文名 → ID
        if self.state:
            _need_save = False
            for char_key in ("character", "user_character"):
                char = self.state.get(char_key, {})
                if char and char.get("skills"):
                    old_skills = list(char["skills"])
                    char["skills"] = self._migrate_skill_names_to_ids(char["skills"])
                    if char["skills"] != old_skills:
                        _need_save = True
                # 迁移旧存档：补发未分配的升级属性点
                if char and char.get("level", 1) > 1:
                    old_sp = char.get("stat_points", 0)
                    self._backfill_stat_points(char, self.state.get("world_type", "fantasy"),
                                               self.state.get("growth_mode", "normal"))
                    # 如果补发了属性点，立即保存防止重复
                    if char.get("stat_points", 0) != old_sp:
                        _need_save = True
            if _need_save:
                save_state(self.state)
        return self.state

    @staticmethod
    def _migrate_skill_names_to_ids(skills: list) -> list:
        """将技能列表中的中文名迁移为标准ID，去重"""
        from simlife.backend.skill_system import SkillSystem
        SkillSystem._build_db()
        name_to_id = {}
        for sid, skill in SkillSystem._SKILL_DB.items():
            name_to_id[skill.name] = sid
        result = []
        seen = set()
        for s in skills:
            if s.startswith("awakening_"):
                if s not in seen:
                    result.append(s)
                    seen.add(s)
                continue
            # 如果已经是ID，直接保留
            if s in SkillSystem._SKILL_DB:
                if s not in seen:
                    result.append(s)
                    seen.add(s)
                continue
            # 尝试中文名 → ID（精确匹配）
            sid = name_to_id.get(s)
            if sid and sid not in seen:
                result.append(sid)
                seen.add(sid)
                continue
            # 模糊匹配：技能名包含或被包含
            for db_name, db_id in name_to_id.items():
                if s in db_name or db_name in s:
                    if db_id not in seen:
                        result.append(db_id)
                        seen.add(db_id)
                    break
            else:
                # 无法匹配，保留原值
                if s not in seen:
                    result.append(s)
                    seen.add(s)
            continue
        return result

    @staticmethod
    def _backfill_stat_points(character: Dict, world_type: str = "fantasy", growth_mode: str = "normal"):
        """补发旧存档中未分配的升级属性点（只执行一次）"""
        if character.get("_stat_backfilled"):
            return
        from simlife.backend.death_mode_state import get_class_template
        from simlife.backend.growth_system import GrowthSystem

        class_id = character.get("class_id", "warrior")
        level = character.get("level", 1)

        # 获取基础属性
        cls_template = get_class_template(world_type, class_id)
        if not cls_template:
            return
        base_stats = cls_template["base_stats"]

        # 计算当前总属性 - 基础总属性 = 已分配点数
        current_stats = character.get("stats", {})
        base_total = sum(base_stats.values())
        current_total = sum(current_stats.values())
        already_allocated = current_total - base_total

        # 应得点数：(level - 1) * 每级点数
        config = GrowthSystem.get_config(growth_mode)
        expected_points = (level - 1) * config["stat_points_per_level"]

        # 需要补发的点数
        to_backfill = expected_points - already_allocated
        if to_backfill <= 0:
            character["_stat_backfilled"] = True
            return

        # 补发到 stat_points，由玩家手动分配
        character["stat_points"] = character.get("stat_points", 0) + to_backfill
        character["_stat_backfilled"] = True

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
        """开始新游戏 — 完全清除旧世界数据"""
        # 清除旧状态文件（包括 .json.dead 备份）
        clear_state()
        old_dead = STATE_FILE.with_suffix(".json.dead")
        if old_dead.exists():
            try:
                old_dead.unlink()
            except Exception:
                pass

        self.state = None
        self.world_map = None
        self.npc_system = None

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

        # 把地图区域的运行时数据合并到文件系统（不覆盖已有的 monsters/npcs/factions）
        # 仅补充文件中缺失的运行时字段：danger_level/region_type/connections/boss/level_range
        try:
            from simlife.worlds import world_manager as wm
            world_id = world_setting.get("world_id", "")
            if world_id:
                for rid, region in self.world_map.regions.items():
                    existing = wm.load_region(world_id, rid)
                    if existing:
                        # 文件已存在（generator 生成的完整数据）→ 只补充运行时字段
                        updated = False
                        if not existing.get("biome") and region.region_type:
                            existing["biome"] = region.region_type
                            updated = True
                        if not existing.get("level_range"):
                            # 根据 danger_level 推算 level_range
                            dl = region.danger_level or 1
                            existing["level_range"] = [max(1, dl * 3 - 2), dl * 3 + 2]
                            updated = True
                        if updated:
                            wm.save_region(world_id, existing)
                    else:
                        # 文件不存在（LLM/模板生成的地图）→ 创建最小区域文件
                        region_data = {
                            "id": rid,
                            "name": region.name,
                            "description": region.description,
                            "biome": region.region_type or "wild",
                            "level_range": [max(1, (region.danger_level or 1) * 3 - 2),
                                           (region.danger_level or 1) * 3 + 2],
                        }
                        # 怪物名存入 dangers（供 prompt 注入）
                        if region.monsters:
                            region_data["dangers"] = [m.get("name", "") for m in region.monsters if m.get("name")]
                        if region.boss:
                            region_data["boss"] = region.boss
                        wm.save_region(world_id, region_data)
        except Exception as e:
            print(f"[DeathMode] 保存区域文件失败: {e}")

        # ── 初始化区域管理 Agent ──
        try:
            world_id = world_setting.get("world_id", "")
            self.region_agent = RegionAgent(self.world_map, world_id)
            print(f"[DeathMode] RegionAgent 初始化完成（world_id={world_id}）")
        except Exception as e:
            print(f"[DeathMode] RegionAgent 初始化失败: {e}")

        # ── 生成隐藏结局（对用户和系统角色完全隐藏）──
        try:
            hidden_ending = generate_hidden_ending(world_setting, self.llm, self.world_map)
            if hidden_ending:
                self.state["hidden_ending"] = hidden_ending.to_dict()
                print(f"[DeathMode] 隐藏结局生成成功：{hidden_ending.title}")
        except Exception as e:
            print(f"[DeathMode] 隐藏结局生成失败: {e}")

        # 生成NPC
        self.npc_system = NPCGenerator.generate_for_world(world_setting, self.world_map, self.llm)
        self.state["npc_system"] = self.npc_system.to_dict()
        self.state["npc_death_records"] = []

        # 设置初始位置为起始区域（使用区域中文名，非ID）
        if self.world_map.start_region_id:
            region = self.world_map.get_region(self.world_map.start_region_id)
            if region:
                self.state["story"]["current_location"] = region.name
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
                "stat_points": char.get("stat_points", 0),
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
            "life_state": state.get("life_state", {}),
            "user_character": state.get("user_character", {}),
            "death_pending": state.get("death_pending", False),
            "death_who": state.get("death_who"),
            "last_words": state.get("last_words", ""),
            "ai_character_dead": state.get("ai_character_dead", False),
            "user_character_dead": state.get("user_character_dead", False),
            "action_log": state.get("action_log", [])[-20:],  # 最近20条给A层用
            "in_dungeon": state.get("in_dungeon", False),
            "dungeon": self.get_dungeon_info().get("dungeon") if state.get("in_dungeon") else None,
            "party_members": state.get("party_members", []),
            # ── 隐藏结局待衔接状态（供网页端"新篇章"按钮显示） ──
            "ending_pending_transition": bool(
                state.get("hidden_ending", {}).get("pending_transition", False)
                and not state.get("hidden_ending", {}).get("completed", False)
            ),
            "ending_title": state.get("hidden_ending", {}).get("title", ""),
            "ending_description": state.get("hidden_ending", {}).get("description", ""),
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

        # ── 坏人路线·NPC怜悯暂停处理 ──
        # 战斗中NPC敌人残血时暂停，用户明确说"杀死/处决/了结"才执行最后一击
        _mercy_pause = state.get("npc_mercy_pause")
        if _mercy_pause and state.get("in_combat"):
            _kill_keywords = ("杀死", "杀掉", "处决", "了结", "终结", "结果", "送死", "下杀手",
                              "补刀", "致命一击", "最后一击", "kill", "execute", "finish")
            _spare_keywords = ("放过", "饶", "留命", "不杀", "停手", "算了", "收手", "放过他",
                               "饶命", "spare", "mercy")
            _action_lower = action.lower()

            if any(k in _action_lower for k in _kill_keywords):
                # 执行最后一击：将残血NPC敌人HP置0，走正常战斗胜利流程
                _npc_names = _mercy_pause.get("npc_names", [])
                _npc_ids = _mercy_pause.get("npc_ids", [])
                enemies = state.get("enemies", [])
                _killed = []
                for e in enemies:
                    if e.get("is_npc") and e.get("hp", 0) > 0:
                        e["hp"] = 0
                        _killed.append(e.get("name", "?"))
                # 清除暂停状态和最后一击标志
                state.pop("npc_mercy_pause", None)
                state.pop("_npc_finish_blow", None)

                # 走战斗胜利流程
                char = state["character"]
                total_exp = sum(e.get("exp_reward", 10) for e in enemies)
                total_gold = sum(e.get("gold_reward", 5) for e in enemies)
                char["gold"] += total_gold
                state["kill_count"] += len(enemies)
                combat_result = {
                    "victory": True,
                    "enemies_defeated": [e.get("name", "") for e in enemies],
                    "combat_log": [f"💀 致命一击：{', '.join(_killed)}已被处决"],
                    "exp_reward": total_exp,
                    "gold_reward": total_gold,
                    "drops": [],
                }

                # 记录NPC死亡 + 任务断裂处理
                _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                _killed_npcs = self._record_npc_kills(state, _killed, killer=_killer)

                # 经验/金币奖励
                result = {
                    "narrative": f"你举起了武器，对身受重伤的{'、'.join(_killed)}给出了致命一击。对方倒地不起，再无声息。",
                    "combat_result": combat_result,
                    "gold_gained": total_gold,
                    "exp_gained": total_exp,
                    "in_combat": False,
                    "npcs_killed": _killed_npcs,
                }
                char["world_type"] = state.get("world_type", "fantasy")
                growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                if growth_result["leveled_up"]:
                    result["leveled_up"] = True
                    result["new_level"] = growth_result["new_level"]
                    result["new_skills"] = growth_result.get("new_skills", [])

                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                self._record_defeated(state, enemies)
                self._record_history_and_save(state, action, result["narrative"], "combat_success", combat_result, result)
                return result

            elif any(k in _action_lower for k in _spare_keywords):
                # 放过NPC：解除战斗状态，NPC保持残血存活
                _npc_names = _mercy_pause.get("npc_names", [])
                state.pop("npc_mercy_pause", None)
                state.pop("_npc_finish_blow", None)
                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                _spare_narrative = f"你收起了武器，放过了身受重伤的{'、'.join(_npc_names)}。对方瘫倒在地，生死未卜。"
                self._record_history_and_save(state, action, _spare_narrative, "social_response", None, {"narrative": _spare_narrative})
                return {
                    "narrative": _spare_narrative,
                    "in_combat": False,
                    "npc_spared": _npc_names,
                }
            else:
                # 其他行动：解除暂停状态，让用户行动正常处理（战斗状态保留，用户可继续战斗或做别的）
                # 如果是攻击行动，设置 _npc_finish_blow 允许下一回合战斗击杀
                _attack_keywords = ("攻击", "打", "继续战斗", "继续打", "出手", "动手", "attack")
                if any(k in _action_lower for k in _attack_keywords):
                    state["_npc_finish_blow"] = True  # 临时允许击杀
                state.pop("npc_mercy_pause", None)

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
        elif in_combat and enemies and any(e.get("is_npc") for e in enemies):
            # 坏人路线：敌人中有NPC时禁止扫荡，避免直接秒杀跳过残血怜悯环节
            is_sweep = False
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

                # 任务进度：击杀敌人触发（扫荡也记录）
                try:
                    _defeated = sweep_result.get("enemies_defeated", [])
                    if _defeated:
                        progressed = QuestSystem.record_progress(state, "kill", enemy_names=_defeated)
                        if progressed:
                            result["quest_progress"] = progressed
                except Exception:
                    pass

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
                state["spotted_enemies"] = []
                result["in_combat"] = False

                # 记录已击败的特殊敌人（小怪不屏蔽，允许重复出现）
                self._record_defeated(state, enemies)

                # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡（只处理is_npc敌人）
                _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies if e.get("is_npc")], killer=_killer)
                if _killed_npcs:
                    result["npcs_killed"] = _killed_npcs

                # ── 地下城：清除房间 ──
                if state.get("in_dungeon"):
                    clear_result = self.clear_dungeon_room()
                    if clear_result.get("success"):
                        result["dungeon_room_cleared"] = True
                        result["dungeon_completed"] = clear_result.get("dungeon_completed", False)
                        if clear_result.get("loot"):
                            result["dungeon_loot"] = clear_result["loot"]
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
            # 优先用叙事中提到的敌人（spotted_enemies），否则随机生成
            state["_current_action"] = action  # 临时存储，供敌人生成时判断坏人路线
            enemies_list = self._generate_enemies_with_spotted(state, risk_level)
            state.pop("_current_action", None)
            state["enemies"] = enemies_list
            state["in_combat"] = True

            # 坏人路线：NPC敌人不走扫荡，强制走逐回合（让残血怜悯暂停生效）
            _has_npc_enemy = any(e.get("is_npc") for e in enemies_list)
            if _has_npc_enemy:
                # 不走扫荡，标记为非扫荡，让后面的逐回合逻辑处理
                is_new_sweep = False
                is_sweep = False
                in_combat = True
                # 直接走逐回合战斗
                combat_result = self._combat_round(state, enemies_list, action_text=action, sender=sender)
                result["combat_result"] = combat_result
                alive_enemies = [e for e in enemies_list if e.get("hp", 0) > 0]
                if not alive_enemies or combat_result.get("victory"):
                    # 战斗胜利
                    state["in_combat"] = False
                    state["enemies"] = []
                    state["spotted_enemies"] = []
                    result["in_combat"] = False
                    result["exp_gained"] = sum(e.get("exp_reward", 10) for e in enemies_list)
                    result["gold_gained"] = sum(e.get("gold_reward", 5) for e in enemies_list)
                    char["gold"] += result["gold_gained"]
                    state["kill_count"] += len(enemies_list)
                    self._record_defeated(state, enemies_list)
                    _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                    _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies_list if e.get("is_npc")], killer=_killer)
                    if _killed_npcs:
                        result["npcs_killed"] = _killed_npcs
                    growth_result = GrowthSystem.gain_exp(char, result["exp_gained"], state.get("growth_mode", "normal"))
                    if growth_result["leveled_up"]:
                        result["leveled_up"] = True
                        result["new_level"] = growth_result["new_level"]
                        result["new_skills"] = growth_result.get("new_skills", [])
                    self._record_history_and_save(state, action, result.get("narrative", ""), "combat_success", combat_result, result)
                    return result
                elif state.get("npc_mercy_pause"):
                    # NPC怜悯暂停
                    result["in_combat"] = True
                    result["enemies"] = alive_enemies
                    _pause_info = state.get("npc_mercy_pause", {})
                    _pause_names = "、".join(_pause_info.get("npc_names", [])) or "NPC"
                    result["npc_mercy_pause"] = True
                    result["narrative"] = (result.get("narrative", "") +
                                          f"\n\n💔 {_pause_names}已身受重伤，倒地不起。是否给予致命一击？\n"
                                          "回复「杀死/处决/了结」执行最后一击，或「放过」饶其一命。")
                    self._record_history_and_save(state, action, result["narrative"], "combat_pause", combat_result, result)
                    return result
                else:
                    # 战斗继续
                    result["in_combat"] = True
                    result["enemies"] = alive_enemies
                    self._record_history_and_save(state, action, result.get("narrative", ""), "combat_ongoing", combat_result, result)
                    return result

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

                # 任务进度：击杀敌人触发（扫荡也记录）
                try:
                    _defeated = sweep_result.get("enemies_defeated", [])
                    if _defeated:
                        progressed = QuestSystem.record_progress(state, "kill", enemy_names=_defeated)
                        if progressed:
                            result["quest_progress"] = progressed
                except Exception:
                    pass

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
                state["spotted_enemies"] = []
                result["in_combat"] = False

                # 记录已击败的特殊敌人（小怪不屏蔽）
                self._record_defeated(state, enemies_list)

                # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡
                _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies_list if e.get("is_npc")], killer=_killer)
                if _killed_npcs:
                    result["npcs_killed"] = _killed_npcs

                # ── 地下城：清除房间 ──
                if state.get("in_dungeon"):
                    clear_result = self.clear_dungeon_room()
                    if clear_result.get("success"):
                        result["dungeon_room_cleared"] = True
                        result["dungeon_completed"] = clear_result.get("dungeon_completed", False)
                        if clear_result.get("loot"):
                            result["dungeon_loot"] = clear_result["loot"]
            else:
                # 坏人路线：NPC怜悯暂停 → 不结算经验金币，保留战斗状态
                if sweep_result.get("npc_mercy_pause") or state.get("npc_mercy_pause"):
                    result["in_combat"] = True
                    result["enemies"] = [e for e in enemies_list if e.get("hp", 0) > 0]
                    result["exp_gained"] = 0
                    result["gold_gained"] = 0
                    result["npc_mercy_pause"] = True
                    _pause_info = state.get("npc_mercy_pause", {})
                    _pause_names = "、".join(_pause_info.get("npc_names", [])) or "NPC"
                    result["narrative"] = (sweep_result.get("narrative", "") +
                                          f"\n\n💔 {_pause_names}已身受重伤，倒地不起。是否给予致命一击？\n"
                                          "回复「杀死/处决/了结」执行最后一击，或「放过」饶其一命。")
                else:
                    result["in_combat"] = True
                    result["enemies"] = [e for e in enemies_list if e.get("hp", 0) > 0]

            self._log_sweep_action(action, result)
            self._save()
            return result

        # ── 战斗回合：先跑战斗系统，再基于 combat_log 生成叙事 ──
        in_combat_now = state.get("in_combat", False)
        _enemies_now = state.get("enemies", [])
        _is_flee_action = ("逃跑" in action or "撤退" in action)

        if in_combat_now and _enemies_now and not _is_flee_action:
            # 战斗回合：先执行战斗系统
            combat_result = self._combat_round(state, _enemies_now, action_text=action, sender=sender)

            # 基于战斗日志生成叙事（带历史上下文，保持剧情连贯）
            agent_result = self.agent.process_combat_action(state, action, combat_result, sender=sender)
            narrative = agent_result.get("narrative", "")
            outcome_type = agent_result.get("outcome_type", "combat_ongoing")
            next_tension = agent_result.get("next_tension", "high")

            # 处理战斗结果
            result = {
                "narrative": narrative,
                "combat_result": combat_result,
                "leveled_up": False,
                "new_skills": [],
                "character_died": False,
                "death_description": None,
                "exp_gained": 0,
                "gold_gained": 0,
            }

            if combat_result.get("player_died"):
                result["character_died"] = True
                result["user_died"] = combat_result.get("user_died", False)
                who = "user" if combat_result.get("user_died") else "ai"
                result["death_description"] = self._handle_death(state, combat_result.get("death_cause", "战斗中阵亡"), who_died=who)
                result["death_pending"] = True
                result["death_who"] = who
                result["last_words"] = state.get("last_words", "")
                # 记录历史后返回
                self._record_history_and_save(state, action, narrative, outcome_type, combat_result, result)
                return result

            # 检查是否所有敌人已击败
            alive_enemies = [e for e in _enemies_now if e.get("hp", 0) > 0]
            if not alive_enemies:
                # 战斗胜利
                char = state["character"]
                total_exp = sum(e.get("exp_reward", 10) for e in _enemies_now)
                total_gold = sum(e.get("gold_reward", 5) for e in _enemies_now)
                char["gold"] += total_gold
                result["gold_gained"] = total_gold
                result["exp_gained"] = total_exp
                state["kill_count"] += len(_enemies_now)
                combat_result["victory"] = True
                combat_result["enemies_defeated"] = [e.get("name", "") for e in _enemies_now]

                # 任务进度：击杀敌人触发
                try:
                    progressed = QuestSystem.record_progress(state, "kill",
                                                             enemy_names=combat_result["enemies_defeated"])
                    if progressed:
                        result["quest_progress"] = progressed
                except Exception:
                    pass

                char["world_type"] = state.get("world_type", "fantasy")
                growth_result = GrowthSystem.gain_exp(char, total_exp, state.get("growth_mode", "normal"))
                if growth_result["leveled_up"]:
                    result["leveled_up"] = True
                    result["new_level"] = growth_result["new_level"]
                    result["new_skills"] = growth_result.get("new_skills", [])

                user_char = state.get("user_character", {})
                if user_char and user_char.get("class_name"):
                    user_char["world_type"] = state.get("world_type", "fantasy")
                    u_growth = GrowthSystem.gain_exp(user_char, total_exp, state.get("growth_mode", "normal"))
                    if u_growth["leveled_up"]:
                        result.setdefault("user_leveled_up", True)
                        result.setdefault("user_new_skills", u_growth.get("new_skills", []))

                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                result["in_combat"] = False

                # 记录已击败的特殊敌人
                self._record_defeated(state, _enemies_now)

                # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡
                _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in _enemies_now if e.get("is_npc")], killer=_killer)
                if _killed_npcs:
                    result["npcs_killed"] = _killed_npcs

                # 地下城：清除房间
                if state.get("in_dungeon"):
                    clear_result = self.clear_dungeon_room()
                    if clear_result.get("success"):
                        result["dungeon_room_cleared"] = True
                        result["dungeon_completed"] = clear_result.get("dungeon_completed", False)
                        if clear_result.get("loot"):
                            result["dungeon_loot"] = clear_result["loot"]
            else:
                # 战斗继续
                state["in_combat"] = True
                result["in_combat"] = True
                result["enemies"] = alive_enemies

            # 记录历史并保存
            self._record_history_and_save(state, action, narrative, outcome_type, combat_result, result)
            return result

        # 1. 非战斗回合：先检测移动，再生成叙事
        # 移动检测必须在StoryAgent之前：避免LLM在不知道能不能走的情况下编造移动叙事
        _region_moved = False
        _region_move_result = None
        _move_blocked = False
        _move_blocked_msg = ""
        try:
            _action = (action or "").strip()
            # 方向移动判定：必须体现"移动意图"才判定为移动，避免误判。
            # 分两类：
            #  A. 自带移动意图的方向词（如"向北/往北/朝北/北上/去北"）→ 直接判定移动
            #  B. 纯方位名词（如"北方/北边/北面"）→ 必须同时出现"移动动词"才判定移动，
            #     否则"请问北方有什么"这类提问会被误判成向北方移动
            _self_move_patterns = [
                ("东北", "东北"), ("西北", "西北"), ("东南", "东南"), ("西南", "西南"),
                ("北上", "北"), ("南下", "南"), ("东行", "东"), ("西行", "西"),
                ("向北", "北"), ("向南", "南"), ("向东", "东"), ("向西", "西"),
                ("往北", "北"), ("往南", "南"), ("往东", "东"), ("往西", "西"),
                ("朝北", "北"), ("朝南", "南"), ("朝东", "东"), ("朝西", "西"),
                ("去北", "北"), ("去南", "南"), ("去东", "东"), ("去西", "西"),
                ("到北", "北"), ("到南", "南"), ("到东", "东"), ("到西", "西"),
                ("向北边", "北"), ("向南边", "南"), ("向东边", "东"), ("向西边", "西"),
                ("前往北", "北"), ("前往南", "南"), ("前往东", "东"), ("前往西", "西"),
            ]
            _spot_patterns = [
                ("北方", "北"), ("南方", "南"), ("东方", "东"), ("西方", "西"),
                ("北边", "北"), ("南边", "南"), ("东边", "东"), ("西边", "西"),
                ("北面", "北"), ("南面", "南"), ("东面", "东"), ("西面", "西"),
                ("北侧", "北"), ("南侧", "南"), ("东侧", "东"), ("西侧", "西"),
            ]
            _move_verbs = ("走", "出发", "移动", "前往", "去", "到", "进", "动身",
                          "启程", "赶路", "赶去", "过去", "沿", "前进", "去往", "穿过", "进入")
            _wanted_dir = ""
            # A. 自带移动意图 → 直接移动
            for _pattern, _dir in _self_move_patterns:
                if _pattern in _action:
                    _wanted_dir = _dir
                    break
            # B. 纯方位名词 → 需有移动动词搭配才算移动
            if not _wanted_dir:
                for _pattern, _dir in _spot_patterns:
                    if _pattern in _action:
                        if any(_v in _action for _v in _move_verbs):
                            _wanted_dir = _dir
                        break

            # "离开"类关键词（无明确方向时列出可用方向）
            _leave_keywords = ("离开", "离去", "出城", "出镇", "出村", "出发", "启程", "上路")
            _is_leave = any(kw in _action for kw in _leave_keywords)

            if _wanted_dir and self.region_agent:
                # 有明确方向 → 尝试移动
                _move_result = self.region_agent.move_by_direction(_wanted_dir)
                if _move_result.get("moved"):
                    _region_moved = True
                    _region_move_result = _move_result
                    _target = _move_result["region"]
                    _original_location = state.get("story", {}).get("current_location", "")
                    state["story"]["current_location"] = _target.name
                    state["story"]["scene_description"] = _target.description
                    # 清理旧区域任务委托
                    QuestSystem.cleanup_offers_by_region(state)
                    print(f"[DeathMode] 方向移动：{_original_location} → {_target.name}（方向={_wanted_dir}）")
                else:
                    # 移动失败 → 返回可用方向
                    _move_blocked = True
                    _avail = _move_result.get("available_directions", [])
                    if _avail:
                        _dir_parts = []
                        for _d in _avail:
                            if _d.get("has_region") and _d.get("explored"):
                                _dir_parts.append(f"{_d['direction']}（{_d['region_name']}）")
                            elif _d.get("has_region"):
                                _dir_parts.append(f"{_d['direction']}（未探索）")
                            else:
                                _dir_parts.append(f"{_d['direction']}（未知区域）")
                        _move_blocked_msg = f"该方向没有路可走。可选择：{'、'.join(_dir_parts)}"
                    else:
                        _move_blocked_msg = "该方向没有路可走。"
                    print(f"[DeathMode] 移动失败：{_wanted_dir}，原因：{_move_result.get('reason')}")
            elif _is_leave and self.region_agent:
                # "离开"但无方向 → 列出可用方向
                _avail = self.world_map.get_available_directions() if self.world_map else []
                if _avail:
                    _dir_parts = []
                    for _d in _avail:
                        if _d.get("has_region") and _d.get("explored"):
                            _dir_parts.append(f"{_d['direction']}（{_d['region_name']}）")
                        elif _d.get("has_region"):
                            _dir_parts.append(f"{_d['direction']}（未探索）")
                        else:
                            _dir_parts.append(f"{_d['direction']}（未知区域）")
                    _move_blocked = True
                    _move_blocked_msg = f"你想离开这里。可以选择：{'、'.join(_dir_parts)}"
                else:
                    _move_blocked = True
                    _move_blocked_msg = "你已经在地图边缘，没有可离开的方向。"
        except Exception as e:
            print(f"[DeathMode] 方向移动检测异常: {e}")

        # 注入可用方向到state（供StoryAgent使用）
        if self.world_map:
            try:
                state["story"]["available_directions"] = self.world_map.get_available_directions()
            except Exception:
                pass

        # 2. 如果移动被阻挡 → 直接返回，不调用StoryAgent
        if _move_blocked:
            _blocked_result = {
                "narrative": _move_blocked_msg,
                "combat_result": None,
                "leveled_up": False,
                "new_skills": [],
                "character_died": False,
                "death_description": None,
                "exp_gained": 0,
                "gold_gained": 0,
            }
            # 记录历史
            _history_entry = {
                "chapter": state["story"]["current_chapter"],
                "summary": _move_blocked_msg[:200],
                "action": action,
                "outcome": "nothing",
                "location": state["story"].get("current_location", ""),
            }
            state["story"]["history"].append(_history_entry)
            self._save()
            self._log_action("action", {
                "action": action,
                "action_type": action_type,
                "outcome": "nothing",
                "narrative": _move_blocked_msg[:300],
            })
            return _blocked_result

        # 3. 非移动 或 移动成功 → 调用StoryAgent生成叙事
        # 世界BOSS身份交流拦截：谈判/求饶/逃跑/加入势力，在LLM叙事前用硬性判定，避免即兴致死
        try:
            _boss_dialogue = self._handle_world_boss_dialogue(state, action, sender=sender)
        except Exception as _e:
            print(f"[DeathMode] 世界BOSS身份交流异常: {_e}")
            _boss_dialogue = None
        if _boss_dialogue:
            _boss_dialogue.setdefault("next_scene", True)
            self._record_history_and_save(state, action, _boss_dialogue.get("narrative", ""),
                                          "world_boss_dialogue", None, _boss_dialogue)
            return _boss_dialogue

        agent_result = self.agent.process_action(state, action, action_type, sender=sender)
        narrative = agent_result.get("narrative", "")
        outcome_type = agent_result.get("outcome_type", "nothing")
        next_tension = agent_result.get("next_tension", "medium")

        # 3.1 子场景切换：进入/离开当前区域内的具体地点（如井底）。
        # 在战斗触发前应用，确保随后的叙事与战斗都发生在子场景内。
        try:
            _enter_sub = agent_result.get("enter_sub_scene")
            _exit_sub = agent_result.get("exit_sub_scene")
            if _enter_sub and isinstance(_enter_sub, dict):
                _sub_name = str(_enter_sub.get("name", "")).strip()
                if _sub_name:
                    stack = state.setdefault("sub_scene_stack", [])
                    if state.get("story", {}).get("current_location") != _sub_name:
                        stack.append({
                            "location": state["story"].get("current_location", ""),
                            "scene_description": state["story"].get("scene_description", ""),
                        })
                        state["story"]["current_location"] = _sub_name
                        _sub_desc = str(_enter_sub.get("scene_description", "")).strip()
                        state["story"]["scene_description"] = _sub_desc or _sub_name
                        print(f"[DeathMode] 子场景进入：{_sub_name}")
            elif _exit_sub:
                stack = state.get("sub_scene_stack", [])
                if stack:
                    _prev = stack.pop()
                    state["story"]["current_location"] = _prev.get("location") or state["story"].get("current_location", "")
                    state["story"]["scene_description"] = _prev.get("scene_description") or state["story"].get("scene_description", "")
                    print(f"[DeathMode] 子场景离开，退回：{state['story']['current_location']}")
        except Exception as e:
            print(f"[DeathMode] 子场景切换异常: {e}")

        # 4. 如果移动成功 → 在叙事后添加到达描述
        if _region_moved and _region_move_result:
            _target = _region_move_result["region"]
            _original = _region_move_result.get("old_region_name", "")
            _arrival_dir = _region_move_result.get("direction", "")
            _arrival_note = f"\n\n两人离开{_original}，向{_arrival_dir}方前行。前方出现了新的景象——{_target.description}"
            narrative += _arrival_note
            agent_result["narrative"] = narrative
            # 任务进度：到达新区域触发
            try:
                QuestSystem.record_progress(state, "visit_location",
                                             location=_target.name,
                                             narrative=narrative, action_text=action)
            except Exception:
                pass

        # 5. 区域状态更新（仅非移动时）
        if not _region_moved:
            try:
                _region_updates = agent_result.get("region_story_updates")
                if _region_updates and isinstance(_region_updates, dict) and self.region_agent:
                    self.region_agent.update_current_region_state(_region_updates)
            except Exception as e:
                print(f"[DeathMode] 区域状态更新异常: {e}")

        # 任务进度：与NPC对话触发（从用户行动和叙事文本中提取NPC名）
        try:
            _talk_keywords = ("对话", "找", "问", "打听", "聊天", "交谈", "拜访", "见面",
                              "talk", "ask", "chat", "speak", "meet", "找一下",
                              "说话", "谈谈", "聊", "见", "找找", "寻")
            _action_lower = (action or "").lower()
            _narrative_lower = (narrative or "").lower()
            _is_talk_action = any(kw in _action_lower for kw in _talk_keywords)
            if self.npc_system:
                # 遍历所有存活的NPC，不依赖位置匹配（因为NPC.location是区域ID，story.location是中文名）
                for _npc in self.npc_system.npcs.values():
                    if not _npc.alive or not _npc.name:
                        continue
                    _npc_name_lower = _npc.name.lower()
                    # 条件1：用户行动含对话意图 + NPC名在用户行动中
                    _matched = _is_talk_action and _npc_name_lower in _action_lower
                    # 条件2：NPC名在叙事文本中（即使没有对话关键词，NPC出现说明在互动）
                    if not _matched:
                        _matched = _npc_name_lower in _narrative_lower
                    if _matched:
                        QuestSystem.record_progress(state, "talk_npc", npc_name=_npc.name,
                                                     narrative=narrative, action_text=action)
        except Exception:
            pass

        # 恫吓自由行动：用户明确输入"恫吓/恐吓/威慑 X" → 确定性亮威判定（当面行为，NPC 必感知）
        try:
            _intimidate_kw = ("恫吓", "威吓", "恐吓", "威慑", "吓唬", "威胁他", "威胁她")
            if any(k in _action_lower for k in _intimidate_kw):
                _cur_region = ""
                try:
                    _cur_region = str(state.get("world_map", {}).get("current_region_id", "") or "")
                except Exception:
                    pass
                for _npc in (self.npc_system.npcs.values() if self.npc_system else []):
                    if not _npc.alive or not _npc.name:
                        continue
                    if _cur_region and _npc.location != _cur_region:
                        continue
                    _npc_name_lower = _npc.name.lower()
                    if _npc_name_lower not in _action_lower:
                        continue
                    _intim = self._resolve_intimidation(state, _npc)
                    _intim_line = f"\n\n【恫吓】{_intim.get('message', '')}" \
                                  + (f"（{_npc.name}对你已是『{_intim.get('fear_label', '')}』）" if _intim.get("success") else "")
                    narrative += _intim_line
                    agent_result["narrative"] = narrative
                    self._log_action("npc_interact", {
                        "npc_name": _npc.name, "interaction": "intimidate",
                        "message": _intim.get("message", ""),
                        "success": _intim.get("success"), "fear": _intim.get("fear"),
                    })
        except Exception:
            pass

        # 叙事中提到的敌人 → 保存到 state，战斗时优先使用
        # 只过滤已击败的特殊敌人（elite/boss），小怪允许重复出现
        # 名字规范化：去连字符、统一空格，防止同一敌人因变体名（Crystal-Scale vs Crystal Scale）被重复生成
        def _normalize_enemy_name(n):
            return re.sub(r'\s+', ' ', n.replace('-', ' ')).strip().lower()

        unique_defeated_set = set(_normalize_enemy_name(d) for d in state.get("defeated_unique_enemies", []))
        killed_named_set = set(_normalize_enemy_name(d) for d in state.get("killed_monsters", []))
        def _is_dead(sname):
            """特殊敌人(elite/boss)或有名怪物(非普通小怪)已死 → 禁止再出现"""
            _sname_l = (sname).lower()
            _key = _normalize_enemy_name(sname)
            if _key in unique_defeated_set:
                return True
            if _key in killed_named_set and not any(k in _sname_l for k in REFRESHABLE_MOB_KEYWORDS):
                return True
            return False
        spotted = agent_result.get("spotted_enemies")
        if spotted and isinstance(spotted, list):
            filtered = []
            seen_normalized = set()
            for s in spotted:
                if isinstance(s, dict):
                    sname = str(s.get("name", "")).strip()
                    normalized = _normalize_enemy_name(sname)
                    if sname and not _is_dead(sname) and normalized not in seen_normalized:
                        # 统一去除连字符，保持名字一致性
                        s["name"] = sname.replace('-', ' ')
                        filtered.append(s)
                        seen_normalized.add(normalized)
                    elif sname:
                        print(f"[DeathMode] 过滤已击败/重复的敌人: {sname}")
            state["spotted_enemies"] = filtered if filtered else []
        else:
            # 兜底：LLM 可能叙事里提到了怪物但没填 spotted_enemies
            _extracted = self._extract_enemy_names_from_narrative(narrative)
            if _extracted and (unique_defeated_set or killed_named_set):
                _extracted = [s for s in _extracted
                              if not _is_dead(str(s.get("name", "")).strip())]
            state["spotted_enemies"] = _extracted

        # 未解决的剧情钩子 → 累积保存（最多 4 个）
        hooks = agent_result.get("unresolved_hooks")
        if hooks and isinstance(hooks, list):
            existing = state.get("story", {}).get("unresolved_hooks", [])
            for h in hooks:
                if isinstance(h, str) and h.strip() and h.strip() not in existing:
                    existing.append(h.strip())
            # 只保留最近 4 个
            state["story"]["unresolved_hooks"] = existing[-4:]

        # ── 剧情线更新（Plot Threads）：跟踪关键设定，防止前后矛盾 ──
        thread_updates = agent_result.get("plot_thread_updates")
        if thread_updates and isinstance(thread_updates, list):
            threads = state.setdefault("plot_threads", [])
            for upd in thread_updates:
                if not isinstance(upd, dict):
                    continue
                _title = str(upd.get("title", "")).strip()
                _action = str(upd.get("action", "")).strip()
                _new_fact = str(upd.get("new_fact", "")).strip()
                if not _title or not _action:
                    continue
                # 查找已有剧情线（标题模糊匹配）
                _existing = None
                for t in threads:
                    if t.get("title", "") == _title or _title in t.get("title", "") or t.get("title", "") in _title:
                        _existing = t
                        break
                if _action == "introduce" and not _existing:
                    threads.append({
                        "title": _title,
                        "status": "introduced",
                        "key_facts": [_new_fact] if _new_fact else [],
                    })
                elif _existing:
                    if _action == "advance":
                        _existing["status"] = "active"
                        if _new_fact and _new_fact not in _existing.get("key_facts", []):
                            _existing.setdefault("key_facts", []).append(_new_fact)
                    elif _action == "resolve":
                        _existing["status"] = "resolved"
                        if _new_fact and _new_fact not in _existing.get("key_facts", []):
                            _existing.setdefault("key_facts", []).append(_new_fact)
            # 只保留未解决的剧情线 + 最近3个已解决的（供参考）
            _unresolved = [t for t in threads if t.get("status") in ("introduced", "active")]
            _resolved = [t for t in threads if t.get("status") == "resolved"]
            state["plot_threads"] = _unresolved + _resolved[-3:]

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

                    # 任务进度：击杀敌人触发
                    try:
                        progressed = QuestSystem.record_progress(state, "kill",
                                                                 enemy_names=combat_result["enemies_defeated"])
                        if progressed:
                            result["quest_progress"] = progressed
                    except Exception:
                        pass

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
                    state["spotted_enemies"] = []  # 清理已实体化的敌人
                    result["in_combat"] = False
                    # 清理怜悯暂停状态（战斗已结束）
                    state.pop("npc_mercy_pause", None)
                    state.pop("_npc_finish_blow", None)

                    # 记录已击败的特殊敌人（小怪不屏蔽）
                    self._record_defeated(state, enemies)

                    # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡
                    _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                    _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies if e.get("is_npc")], killer=_killer)
                    if _killed_npcs:
                        result["npcs_killed"] = _killed_npcs

                    # ── 地下城：清除房间 ──
                    if state.get("in_dungeon"):
                        clear_result = self.clear_dungeon_room()
                        if clear_result.get("success"):
                            result["dungeon_room_cleared"] = True
                            result["dungeon_completed"] = clear_result.get("dungeon_completed", False)
                            if clear_result.get("loot"):
                                result["dungeon_loot"] = clear_result["loot"]
                else:
                    # 战斗继续
                    state["in_combat"] = True
                    result["in_combat"] = True
                    result["enemies"] = alive_enemies
                    # 坏人路线：如果是NPC怜悯暂停，提示用户
                    if combat_result.get("npc_mercy_pause") or state.get("npc_mercy_pause"):
                        _pause_info = state.get("npc_mercy_pause", {})
                        _pause_names = "、".join(_pause_info.get("npc_names", [])) or "NPC"
                        result["npc_mercy_pause"] = True
                        result["narrative"] = (result.get("narrative", "") +
                                              f"\n\n💔 {_pause_names}已身受重伤，倒地不起。是否给予致命一击？\n"
                                              "回复「杀死/处决/了结」执行最后一击，或「放过」饶其一命。")

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
                # 生成敌人列表：优先用叙事中提到的敌人（spotted_enemies），否则随机生成
                state["_current_action"] = action  # 临时存储，供敌人生成时判断坏人路线
                enemies_list = self._generate_enemies_with_spotted(state, risk_level)
                state.pop("_current_action", None)
                state["enemies"] = enemies_list
                state["in_combat"] = True

                # ── 扫荡模式：新战斗触发时，如果含扫荡关键词或敌人远弱 → 快速结算 ──
                # 坏人路线：NPC敌人不走扫荡
                _has_npc_enemy = any(e.get("is_npc") for e in enemies_list)
                if not _has_npc_enemy and (self._is_sweep_action(action) or self._should_auto_sweep(state, enemies_list)):
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

                        # 任务进度：击杀敌人触发（扫荡也记录）
                        try:
                            _defeated = sweep_result.get("enemies_defeated", [])
                            if _defeated:
                                progressed = QuestSystem.record_progress(state, "kill", enemy_names=_defeated)
                                if progressed:
                                    result["quest_progress"] = progressed
                        except Exception:
                            pass

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
                        state["spotted_enemies"] = []
                        result["in_combat"] = False

                        # 记录已击败的特殊敌人（小怪不屏蔽）
                        self._record_defeated(state, enemies_list)

                        # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡
                        _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                        _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies_list if e.get("is_npc")], killer=_killer)
                        if _killed_npcs:
                            result["npcs_killed"] = _killed_npcs
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
                    state["spotted_enemies"] = []
                    result["in_combat"] = False

                    # 记录已击败的特殊敌人（小怪不屏蔽）
                    self._record_defeated(state, enemies_list)

                    # 坏人路线：检查被击败的敌人是否是NPC，如果是则记录死亡
                    _killer = state.get("user_character", {}).get("name", "用户") if sender == "user" else char.get("name", "AI")
                    _killed_npcs = self._record_npc_kills(state, [e.get("name", "") for e in enemies_list if e.get("is_npc")], killer=_killer)
                    if _killed_npcs:
                        result["npcs_killed"] = _killed_npcs

                    # ── 地下城：清除房间 ──
                    if state.get("in_dungeon"):
                        clear_result = self.clear_dungeon_room()
                        if clear_result.get("success"):
                            result["dungeon_room_cleared"] = True
                            result["dungeon_completed"] = clear_result.get("dungeon_completed", False)
                            if clear_result.get("loot"):
                                result["dungeon_loot"] = clear_result["loot"]
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
                    else:
                        # 装备池没有 → 尝试创建消耗品（药剂等）
                        char_level = state.get("character", {}).get("level", 1)
                        cons_item = self._create_consumable_from_name(item_name, char_level)
                        if cons_item:
                            shared_inv.append(cons_item)
                            result.setdefault("items_to_backpack", []).append(cons_item["name"])
                # 任务进度：收集物品触发（传入叙事文本用于 fallback 匹配）
                try:
                    QuestSystem.record_progress(state, "collect",
                                                 items=[{"name": n} for n in items_gained],
                                                 narrative=narrative, action_text=action)
                except Exception:
                    pass

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

        # 4. 记录故事历史（含完整行动和叙事，供下一段场景生成参考）
        action_text = action if action_type == "free" else (choice_info.get("text", "") if choice_info else action)
        _summary_text = narrative[:200]
        # 战斗胜利后，在summary追加明确的战斗结果，防止LLM下一回合以为敌人还活着
        if result.get("combat_result") and result["combat_result"].get("victory"):
            _defeated_names = result["combat_result"].get("enemies_defeated", [])
            _defeated_str = "、".join(_defeated_names) if _defeated_names else "所有敌人"
            _summary_text += f"【战斗结束：{_defeated_str}已被全部击败，战斗结束，敌人已死亡。】"
        _history_entry = {
            "chapter": state["story"]["current_chapter"],
            "summary": _summary_text,
            "action": action_text,
            "outcome": outcome_type,
            "location": state["story"].get("current_location", ""),
        }
        # 记录战斗结果，供 story_agent 下一回合参考
        if result.get("combat_result"):
            _cr = result["combat_result"]
            _history_entry["combat_result"] = {
                "victory": _cr.get("victory", False),
                "enemies_defeated": _cr.get("enemies_defeated", []),
                "combat_summary": "; ".join(_cr.get("combat_log", [])[-3:])[:150],
            }
        state["story"]["history"].append(_history_entry)

        # ── 每10回合自动生成剧情摘要（长期记忆，防止剧情跑偏）──
        _history_len = len(state["story"]["history"])
        _last_summary_len = state.get("_last_summary_history_len", 0)
        if _history_len - _last_summary_len >= 10:
            try:
                self._generate_story_summary(state)
                state["_last_summary_history_len"] = _history_len
            except Exception as _e:
                print(f"[DeathMode] 剧情摘要生成失败: {_e}")

        # 章节按历史进度推进（每5条历史推进一章）
        if len(state["story"]["history"]) % 5 == 0:
            state["story"]["current_chapter"] += 1

        # 5. 战斗中不清除场景；非战斗状态保留叙事作为场景上下文（不再清空）
        if not state.get("in_combat", False):
            # 保留当前叙事作为场景上下文，下次行动时 LLM 能看到之前发生了什么
            state["story"]["scene_description"] = narrative[:300]
            state["story"]["choices"] = []
            state["story"]["pending_action"] = None
            result["next_scene"] = True
        else:
            result["next_scene"] = False

        # 任务系统：处理 LLM 生成的任务委托
        try:
            offers = agent_result.get("quest_offers")
            if offers and isinstance(offers, list):
                # 获取隐藏结局方向提示（供任务系统生成匹配结局的任务链）
                ending_hint_for_quest = ""
                try:
                    ending_data = state.get("hidden_ending")
                    if ending_data and not ending_data.get("triggered", False):
                        ending = HiddenEnding.from_dict(ending_data)
                        ending_hint_for_quest = ending.get_stage_hint_for_quest()
                except Exception:
                    pass
                created_n, created_titles = QuestSystem.create_dynamic_quests(state, offers, ending_hint_for_quest)
                if created_n > 0:
                    result["new_quest_offers"] = created_titles
        except Exception as e:
            print(f"[DeathMode] 任务委托解析失败: {e}")

        # 世界推进：每次行动后检查是否触发新世界事件
        try:
            new_news = WorldProgress.check_and_advance(state)
            if new_news:
                result["world_news"] = new_news
        except Exception:
            pass

        # 世界模拟引擎自转：冲突弧/承诺待办按天自动推进（纯数据，不阻塞叙事）
        try:
            _sim_events = WorldSimulation.tick_by_day(state)
            if _sim_events:
                _sim_msgs = []
                for _ev in _sim_events:
                    if _ev.get("type") == "gate":
                        _sim_msgs.append(f"【世界暗流】{_ev.get('arc', '')}：{_ev.get('title', '')}")
                    elif _ev.get("type") == "commitment_done":
                        _sim_msgs.append(f"{_ev.get('npc', '')} 兑现了承诺：{_ev.get('task', '')}")
                if _sim_msgs:
                    result["world_sim_events"] = _sim_msgs
        except Exception as _sim_e:
            print(f"[DeathMode] 世界模拟自转异常: {_sim_e}")

        # ── 隐藏结局进度检查 ──
        try:
            ending_data = state.get("hidden_ending")
            if ending_data and not ending_data.get("triggered", False) and not ending_data.get("completed", False):
                ending = HiddenEnding.from_dict(ending_data)
                progress = ending.check_progress(state)
                if progress.get("stage_advanced"):
                    state["hidden_ending"] = ending.to_dict()
                    if progress.get("ending_ready"):
                        # 结局条件已满足 → 标记为"待衔接"状态，等玩家下次行动时手动触发
                        # 开放世界设计：玩家可以先欣赏结局叙事，想继续时再开启新章节
                        ending.triggered = True  # 标记已触发，避免重复检测
                        ending.pending_transition = True  # 待衔接标志
                        state["hidden_ending"] = ending.to_dict()
                        print(f"[DeathMode] 隐藏结局触发！{ending.title}（等待玩家手动开启新章节）")
                        result["ending_ready"] = True
                        result["ending_message"] = ending.description
                        result["ending_title"] = ending.title
                        result["ending_pending_transition"] = True  # 通知前端：等待玩家确认
                    else:
                        # 阶段推进（不通知用户，只系统记录）
                        print(f"[DeathMode] 结局阶段推进到 {ending.current_stage}/{len(ending.stages)}")
        except Exception as e:
            print(f"[DeathMode] 结局进度检查失败: {e}")

        # ── 章节衔接：改为网页端"新篇章"按钮手动触发，避免误触发 ──
        # 此处不再自动衔接，仅保留"待衔接"状态，由 /api/death-mode/transition-chapter 接口处理
        # 玩家可继续在当前章节探索，准备好后点击网页端"新篇章"按钮开启下一章

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

    def _create_consumable_from_name(self, item_name: str, char_level: int = 1) -> Optional[Dict]:
        """根据物品名创建消耗品（药剂等），非消耗品返回 None"""
        is_hp = any(k in item_name for k in ("生命", "治疗", "疗伤", "体力", "回血", "HP", "hp", "红药", "伤药"))
        is_mp = any(k in item_name for k in ("魔法", "法力", "灵力", "回蓝", "MP", "mp", "蓝药", "魔力"))
        is_both = any(k in item_name for k in ("恢复", "补给", "全能", "综合", "药剂", "药水"))

        if not (is_hp or is_mp or is_both):
            return None

        base = 20 + char_level * 5
        heal_hp = base if (is_hp or is_both) else 0
        heal_mp = base if (is_mp or is_both) else 0
        desc_parts = []
        if heal_hp:
            desc_parts.append(f"{heal_hp}HP")
        if heal_mp:
            desc_parts.append(f"{heal_mp}MP")

        return {
            "type": "consumable",
            "name": item_name,
            "heal_hp": heal_hp,
            "heal_mp": heal_mp,
            "description": f"恢复{'和'.join(desc_parts)}",
            "value": 30 + char_level * 5,
        }

    def _record_history_and_save(self, state: Dict, action: str, narrative: str,
                                  outcome_type: str, combat_result: Dict, result: Dict):
        """战斗回合的公共逻辑：记录历史 + 剧情线 + 摘要 + 保存"""
        # 记录剧情钩子
        if combat_result:
            hooks = [f"战斗中：{combat_result.get('combat_log', ['战斗进行中'])[-1]}"]
            existing = state.get("story", {}).get("unresolved_hooks", [])
            for h in hooks:
                if isinstance(h, str) and h.strip() and h.strip() not in existing:
                    existing.append(h.strip())
            state["story"]["unresolved_hooks"] = existing[-4:]

        # 记录故事历史
        _summary_text = narrative[:200]
        if combat_result and combat_result.get("victory"):
            _defeated_names = combat_result.get("enemies_defeated", [])
            _defeated_str = "、".join(_defeated_names) if _defeated_names else "所有敌人"
            _summary_text += f"【战斗结束：{_defeated_str}已被全部击败，战斗结束，敌人已死亡。】"
        _history_entry = {
            "chapter": state["story"]["current_chapter"],
            "summary": _summary_text,
            "action": action,
            "outcome": outcome_type,
            "location": state["story"].get("current_location", ""),
        }
        if combat_result:
            _history_entry["combat_result"] = {
                "victory": combat_result.get("victory", False),
                "enemies_defeated": combat_result.get("enemies_defeated", []),
                "combat_summary": "; ".join(combat_result.get("combat_log", [])[-3:])[:150],
            }
        state["story"]["history"].append(_history_entry)

        # 每10回合生成剧情摘要
        _history_len = len(state["story"]["history"])
        _last_summary_len = state.get("_last_summary_history_len", 0)
        if _history_len - _last_summary_len >= 10:
            try:
                self._generate_story_summary(state)
                state["_last_summary_history_len"] = _history_len
            except Exception as _e:
                print(f"[DeathMode] 剧情摘要生成失败: {_e}")

        # 章节推进
        if len(state["story"]["history"]) % 5 == 0:
            state["story"]["current_chapter"] += 1

        # 非战斗状态保留叙事作为场景上下文
        if not state.get("in_combat", False):
            state["story"]["scene_description"] = narrative[:300]
            state["story"]["choices"] = []
            state["story"]["pending_action"] = None
            result["next_scene"] = True
        else:
            result["next_scene"] = False

        # 将 combat_result 映射为前端期望的 combat 字段
        if result.get("combat_result") and not result.get("combat"):
            _cr = result["combat_result"]
            result["combat"] = {
                "victory": _cr.get("victory", False),
                "enemy_names": _cr.get("enemies_defeated", []),
                "combat_log": _cr.get("combat_log", []),
            }
        self._log_action("combat_round", result)
        self._save()

    @staticmethod
    def _monster_name_key(name: str) -> str:
        """怪物名字规范化（去连字符、统一空格、转小写）"""
        return re.sub(r'\s+', ' ', (name or '').replace('-', ' ')).strip().lower()

    @staticmethod
    def _is_refreshable_mob(enemy: Dict) -> bool:
        """是否为可刷新的普通小怪：命中关键词且非特殊敌人(精英/BOSS)。
        特殊敌人永远不刷新（区容 boss 等），普通小怪死后可重新刷出。"""
        from simlife.backend.enemy_agent import EnemyAgent
        if EnemyAgent.is_unique_enemy(enemy):
            return False
        _name = (enemy.get("name") or "").lower()
        return any(k in _name for k in REFRESHABLE_MOB_KEYWORDS)

    @staticmethod
    def _record_defeated(state: Dict, enemies: list):
        """记录已击败的敌人。
        1) 特殊敌人(elite/boss)：永久屏蔽（原有逻辑）；
        2) 有名有姓的怪物（非普通小怪）：永久登记击杀名单 + 分地区计数，
           死后不再生成，实现「地区怪物总量控制」。普通小怪允许刷新。
        """
        from simlife.backend.enemy_agent import EnemyAgent
        unique_list = state.setdefault("defeated_unique_enemies", [])
        killed = state.setdefault("killed_monsters", [])          # 全局击杀名单（有名怪物）
        region_key = str(state.get("world_map", {}).get("current_region_id")
                         or state.get("story", {}).get("current_location", ""))
        region_killed = state.setdefault("region_killed_monsters", {})
        r_list = region_killed.setdefault(region_key, [])          # 分地区清单
        _unique_hits = 0                                          # 本次合战击杀的特殊/BOSS数量
        for e in enemies:
            _name = e.get("name", "")
            if not _name:
                continue
            _key = DeathModeEngine._monster_name_key(_name)
            # A. 特殊敌人(elite/boss)加入永久屏蔽
            if EnemyAgent.is_unique_enemy(e) and _key not in unique_list:
                unique_list.append(_key)
                _unique_hits += 1
            # B. 有名怪物（非普通小怪）→ 永久击杀登记，普通小怪不入此列
            if not DeathModeEngine._is_refreshable_mob(e):
                if _key not in killed:
                    killed.append(_key)
                if _key not in r_list:
                    r_list.append(_key)
        # 击杀名单全局保留（不截断，防止跨区"复活"同名怪物）
        state["defeated_unique_enemies"] = unique_list[-50:]  # 保留最近50个特殊敌人

        # 世界模拟引擎·因果结算：击杀大敌(特殊/boss) → 抵消正在崩坏的暗流（可测量影响力）
        if _unique_hits > 0:
            try:
                from simlife.backend.world_simulation import WorldSimulation
                _declining = [
                    {"arc": _aid, "delta": min(_unique_hits, 3) * 2.0,
                     "note": "击杀大敌，暂缓暗流"}
                    for _aid, _arc in state.get("world_sim", {}).get("arcs", {}).items()
                    if float(_arc.get("tick_rate", 0)) < 0
                ]
                if _declining:
                    WorldSimulation.apply_influence(state, _declining, by="战斗")
            except Exception:
                pass

    def _record_npc_kills(self, state: Dict, defeated_enemy_names: list, killer: str = "未知"):
        """战斗胜利后，检查被击败的敌人是否匹配NPC，如果是则记录NPC死亡。
        这解决了'坏人路线'的核心问题：杀NPC后NPC在剧情中仍然出现。
        支持模糊匹配和动态注册（NPC不在npc_system中时自动创建）。
        """
        if not self.npc_system or not defeated_enemy_names:
            return []

        killed_npc_names = []
        for enemy_name in defeated_enemy_names:
            if not enemy_name:
                continue
            # 去除编号后缀（如"旅店老板1"→"旅店老板"）用于匹配
            base_name = re.sub(r'\d+$', '', enemy_name).strip()
            _matched = False
            for npc in self.npc_system.npcs.values():
                if not npc.alive:
                    continue
                _npc_lower = npc.name.lower()
                _en_lower = enemy_name.lower()
                _bn_lower = base_name.lower()
                # 精确匹配、基础名匹配 或 包含匹配
                if (_npc_lower == _en_lower or _npc_lower == _bn_lower
                        or (_npc_lower and _npc_lower in _en_lower)
                        or (_npc_lower and _npc_lower in _bn_lower)
                        or (_en_lower and _en_lower in _npc_lower)):
                    self.npc_system.kill_npc(npc.npc_id, f"被{killer}击杀", killer=killer)
                    killed_npc_names.append(npc.name)
                    try:
                        from simlife.backend.quest_system import QuestSystem
                        QuestSystem.on_npc_killed(state, npc.name)
                    except Exception:
                        pass
                    _matched = True
                    break
            # 未匹配上已注册NPC的敌人一律视为普通怪物，不动态注册、不记录死亡。
            # （敌人生成时已通过名称匹配给 is_npc 打标记，只有 is_npc=True 才会进入本方法）

        if killed_npc_names:
            state["npc_system"] = self.npc_system.to_dict()
            state["npc_death_records"] = self.npc_system.death_records
            print(f"[DeathMode] NPC死亡记录: {', '.join(killed_npc_names)}（凶手：{killer}）")
        return killed_npc_names

    def trigger_chapter_transition(self, force: bool = False) -> Dict:
        """网页端"新篇章"按钮入口：手动触发章节衔接
        - 结局达成（pending_transition=True）：正常衔接，生成完整结局叙事
        - 主动开启（force=True）：即使结局未达成也可衔接，生成"未完篇章"叙事
        - 处理：生成结局叙事 + 800字章节总结 + 新章节开场 + 新隐藏结局
        - 返回衔接结果给前端展示
        """
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}

        ending_data = state.get("hidden_ending") or {}

        # 幂等保护：已完成则不再触发
        if ending_data.get("completed", False):
            return {"error": "already_completed", "message": "该章节已完成衔接"}

        # 判断是"结局达成衔接"还是"主动放弃衔接"
        is_ending_completed = ending_data.get("pending_transition", False)

        if is_ending_completed:
            # 结局已达成，正常衔接
            ending = HiddenEnding.from_dict(ending_data)
            print(f"[DeathMode] 网页端触发章节衔接（结局达成）：{ending.title}")
        else:
            # 用户主动开启新篇章，当前结局未达成
            if not force:
                return {"error": "not_ready", "message": "隐藏结局尚未达成，需确认主动开启新篇章"}
            # 构造一个"未完篇章"的虚拟ending用于衔接流程
            ending = HiddenEnding({
                "ending_id": ending_data.get("ending_id", ""),
                "title": ending_data.get("title", "未完的篇章"),
                "description": "冒险者选择了新的方向，前路的故事暂告一段落。",
                "final_goal": ending_data.get("final_goal", ""),
                "stages": ending_data.get("stages", []),
                "current_stage": ending_data.get("current_stage", 0),
                "triggered": True,
                "completed": False,
                "pending_transition": True,  # 标记为待衔接，供后续流程使用
            })
            print(f"[DeathMode] 网页端主动触发章节衔接（当前结局未达成）：{ending.title}")

        try:
            result = self._trigger_chapter_transition(state, ending, is_ending_completed)
            self._save()
            # 返回结果给前端展示
            return {
                "ok": True,
                "ending_title": ending.title,
                "ending_narrative": result.get("ending_narrative", ""),
                "new_chapter_narrative": result.get("new_chapter_narrative", ""),
                "new_chapter": result.get("new_chapter", state.get("story", {}).get("current_chapter", 1)),
                "completed_chapter": result.get("completed_chapter", state.get("story", {}).get("current_chapter", 1) - 1),
                "chapter_summary": result.get("chapter_summary", ""),
                "is_ending_completed": is_ending_completed,  # 告知前端是结局达成还是主动放弃
            }
        except Exception as e:
            print(f"[DeathMode] 章节衔接执行失败: {e}")
            return {"error": "transition_failed", "message": str(e)}

    def _trigger_chapter_transition(self, state: Dict, ending, is_ending_completed: bool = True) -> Dict:
        """章节衔接：结局达成后保存当前章节存档，生成新结局，开启下一章
        开放世界设计：角色参数保留，故事总结传承，世界扩展新区域和新剧情线
        """
        import time
        from simlife.backend.ending_system import generate_hidden_ending

        char = state.get("character", {})
        user_char = state.get("user_character", {})
        char_name = char.get("name", "无名")
        user_name = user_char.get("name", "")

        # 1. 生成结局叙事
        #    - 结局达成：基于结局的 final_goal 和 description 生成完整结局叙事
        #    - 主动放弃：生成"未完篇章"叙事，描述冒险者选择新方向
        ending_narrative = ""
        try:
            if is_ending_completed:
                # 结局达成，生成完整结局叙事
                narrative_prompt = ending.get_ending_narrative_prompt(state)
                if narrative_prompt:
                    ending_narrative = self.llm.generate(
                        narrative_prompt, max_tokens=600, temperature=0.8, thinking=False
                    ).strip()
            else:
                # 主动放弃当前剧情，生成"未完篇章"叙事
                history = state.get("story", {}).get("history", [])
                recent_text = ""
                for h in history[-8:]:
                    recent_text += f"• {h.get('action', '')} → {h.get('summary', '')}\n"
                pending_prompt = f"""你是死亡模式人生模拟器的叙事Agent。冒险者主动选择结束当前章节，开启新的篇章。
请生成一段"未完篇章"的过渡叙事（200-300字），要求：
1. 自然收束当前剧情线，不要强行完结（故事未真正结束，只是冒险者转向了新方向）
2. 暗示当前世界的某些悬念仍未解开，留待未来
3. 为新章节的开启做铺垫，氛围从"暂别"转向"新的征途"

【角色】{char_name}（Lv.{char.get('level', 1)}）{f"与同伴{user_name}" if user_name else ""}
【当前区域】{state.get('story', {}).get('current_location', '未知')}

【最近发生的事】
{recent_text or '（暂无近期记录）'}

请直接输出叙事文本，不要其他内容。"""
                ending_narrative = self.llm.generate(
                    pending_prompt, max_tokens=400, temperature=0.7, thinking=False
                ).strip()
        except Exception as e:
            print(f"[DeathMode] 结局叙事生成失败: {e}")
            if is_ending_completed:
                ending_narrative = f"历经重重考验，{char_name}终于完成了『{ending.title}』的使命。{ending.description}"
            else:
                ending_narrative = f"{char_name}的这段冒险暂告一段落，新的征途即将开始……"

        # 2. 生成当前章节的完整故事总结（传承到下一章）
        chapter_summary = state.get("story_summary", "")
        try:
            history = state.get("story", {}).get("history", [])
            history_text = ""
            for h in history[-30:]:
                _act = h.get("action", "")
                _sum = h.get("summary", "")
                history_text += f"• {_act} → {_sum}\n"

            summary_prompt = f"""请把以下整个章节的游戏历史压缩成详细的章节总结（800字左右）。
保留关键信息：重要NPC名字和身份、地点、获得的道具、完成的任务、关键战斗、剧情转折、角色成长、势力关系变化。
这是为了传承到下一个章节，让新章节的剧情能延续前作，不要遗漏重要细节。

结局标题：{ending.title}
结局目标：{ending.final_goal}

最近发生的事：
{history_text}

已有摘要：{chapter_summary}

请直接输出章节总结文本，不要其他内容。"""
            chapter_summary = self.llm.generate(
                summary_prompt, max_tokens=1200, temperature=0.3, thinking=False
            ).strip()
        except Exception as e:
            print(f"[DeathMode] 章节总结生成失败: {e}")

        # 3. 保存章节存档到 completed_chapters
        completed_chapters = state.setdefault("completed_chapters", [])
        current_chapter_num = state.get("story", {}).get("current_chapter", 1)
        completed_chapters.append({
            "chapter": current_chapter_num,
            "ending_title": ending.title,
            "ending_description": ending.description,
            "final_goal": ending.final_goal,
            "ending_narrative": ending_narrative[:500],
            "chapter_summary": chapter_summary,
            "char_level": char.get("level", 1),
            "char_name": char_name,
            "user_name": user_name,
            "completed_at": int(time.time()),
        })
        # 保留最近10个章节存档
        state["completed_chapters"] = completed_chapters[-10:]

        # 4. 标记当前结局已完成
        ending.completed = True
        ending.triggered = True
        state["hidden_ending"] = ending.to_dict()

        # 5. 章节推进
        state["story"]["current_chapter"] = current_chapter_num + 1

        # 6. 保留角色参数，但重置故事状态（新章节新故事）
        # 清空当前章节的历史和钩子，但保留 completed_chapters 和 story_summary
        state["story"]["history"] = []
        state["story"]["unresolved_hooks"] = []
        state["story"]["pending_action"] = None
        state["in_combat"] = False
        state["enemies"] = []
        state["spotted_enemies"] = []
        state["plot_threads"] = []  # 清空剧情线，新章节重新建立

        # 7. story_summary 更新为章节总结（传承到下一章）
        state["story_summary"] = chapter_summary

        # 8. 恢复角色 HP/MP（新章节开始，状态回满）
        char["hp"] = char.get("max_hp", char.get("hp", 100))
        char["mp"] = char.get("max_mp", char.get("mp", 50))
        if user_char and user_char.get("class_name"):
            user_char["hp"] = user_char.get("max_hp", user_char.get("hp", 100))
            user_char["mp"] = user_char.get("max_mp", user_char.get("mp", 50))

        # 9. 生成新的隐藏结局（下一章的世界故事）
        try:
            world_setting = state.get("world_setting", {})
            # 构建章节传承上下文，让新结局能延续前作
            chapter_context = ""
            if completed_chapters:
                last_ch = completed_chapters[-1]
                chapter_context = f"\n前作结局：{last_ch.get('ending_title', '')}（{last_ch.get('ending_description', '')[:100]}）\n前作总结：{last_ch.get('chapter_summary', '')[:200]}"

            # 临时注入章节上下文到 world_setting
            original_history = world_setting.get("history", {})
            if not isinstance(original_history, dict):
                original_history = {}
            world_setting["history"] = {
                **original_history,
                "current_situation": f"新章节开始。{chapter_context}",
            }

            new_ending = generate_hidden_ending(world_setting, self.llm, self.world_map)
            if new_ending:
                state["hidden_ending"] = new_ending.to_dict()
                print(f"[DeathMode] 新章节隐藏结局生成：{new_ending.title}（{len(new_ending.stages)}个阶段）")
            else:
                print("[DeathMode] 新章节结局生成失败，使用默认")
        except Exception as e:
            print(f"[DeathMode] 新章节结局生成失败: {e}")

        # 10. 生成新章节开场叙事
        new_chapter_narrative = ""
        try:
            opening_prompt = f"""你是死亡模式人生模拟器的叙事Agent。一个新的章节即将开始。

【前作传承】
{chapter_summary}

【当前角色】
{char_name}（Lv.{char.get('level', 1)}）
{f"同伴：{user_name}（Lv.{user_char.get('level', 1)}）" if user_name else ""}

【新章节】第{state['story']['current_chapter']}章

请生成一段新章节的开场叙事（150-200字），描述前作结局后世界的变化，以及新的冒险如何开始。
要求：
1. 自然衔接前作结局，不要生硬转折
2. 暗示新的危机或冒险方向，但不透露隐藏结局
3. 保持开放世界的氛围，角色可以自由探索
"""
            new_chapter_narrative = self.llm.generate(
                opening_prompt, max_tokens=400, temperature=0.7, thinking=False
            ).strip()
        except Exception as e:
            print(f"[DeathMode] 新章节开场叙事生成失败: {e}")
            new_chapter_narrative = f"第{state['story']['current_chapter']}章开始了。{char_name}的冒险还在继续……"

        # 更新场景描述
        state["story"]["scene_description"] = new_chapter_narrative

        print(f"[DeathMode] 章节衔接完成：第{current_chapter_num}章『{ending.title}』→ 第{state['story']['current_chapter']}章")

        return {
            "ending_narrative": ending_narrative,
            "new_chapter_narrative": new_chapter_narrative,
            "new_chapter": state["story"]["current_chapter"],
            "completed_chapter": current_chapter_num,
            "chapter_summary": chapter_summary[:300],
        }

    def _generate_story_summary(self, state: Dict):
        """生成剧情摘要：把最近10条历史压缩成简短摘要，作为长期记忆注入prompt"""
        history = state.get("story", {}).get("history", [])
        if not history:
            return
        # 取最近10条历史
        recent = history[-10:]
        history_text = ""
        for h in recent:
            _act = h.get("action", "")
            _sum = h.get("summary", "")
            _loc = h.get("location", "")
            _combat = ""
            if h.get("combat_result"):
                cr = h["combat_result"]
                if cr.get("victory"):
                    _combat = f"[击败{', '.join(cr.get('enemies_defeated', []))}]"
                else:
                    _combat = f"[战斗中]"
            history_text += f"• {_act} → {_sum}{_combat}" + (f"（{_loc}）" if _loc else "") + "\n"

        existing_summary = state.get("story_summary", "")
        char_name = state.get("character", {}).get("name", "角色")

        prompt = f"""请把以下游戏历史记录压缩成简短的剧情摘要（不超过200字）。
保留关键信息：重要NPC名字、地点、获得的线索/道具、战斗结果、剧情设定。
去掉无关细节。

{f"已有摘要（在此基础上补充）：{existing_summary}" if existing_summary else ""}

最近发生的事：
{history_text}

请直接输出摘要文本，不要其他内容。"""

        try:
            summary = self.llm.generate(prompt, max_tokens=400, temperature=0.3, thinking=False)
            summary = summary.strip()
            if summary:
                state["story_summary"] = summary
                print(f"[DeathMode] 剧情摘要已更新（{len(summary)}字）")
        except Exception as e:
            print(f"[DeathMode] 摘要LLM调用失败: {e}")

    def _extract_enemy_names_from_narrative(self, narrative: str) -> list:
        """从叙事文本中提取敌人名（兜底：LLM 没填 spotted_enemies 时使用）
        三重数据源：
        1. world_map 所有区域的预定义怪物名
        2. history 里击败过的敌人名
        3. 中文怪物关键词模式匹配（识别 LLM 临时编的敌人，如"骨魔"/"腐木蜥蜴"/"灰雾吞噬者"等）
        返回 [{"name": "怪物名", "count": 1}, ...]
        """
        if not narrative:
            return []
        _known_names = set()

        # 1. 从 world_map 所有区域收集怪物名
        if self.world_map:
            for region in self.world_map.regions.values():
                for m in (region.monsters or []):
                    _n = m.get("name", "")
                    if _n:
                        _known_names.add(_n)
                if region.boss:
                    _bn = region.boss.get("name", "")
                    if _bn:
                        _known_names.add(_bn)

        # 2. 从 history 里收集击败过的敌人名
        _history = self.state.get("story", {}).get("history", [])
        for h in _history:
            _cr = h.get("combat_result", {})
            for _en in (_cr.get("enemies_defeated") or []):
                if _en:
                    _known_names.add(_en)

        # 3. 在叙事文本中搜索已知怪物名
        _found = []
        _used_names = set()
        for name in _known_names:
            if name in narrative and name not in _used_names:
                count = self._estimate_enemy_count(narrative, name)
                _found.append({"name": name, "count": count})
                _used_names.add(name)

        # 4. 中文怪物关键词模式匹配已禁用（过于激进，会把"体内魔""然而贤者""趁追兵"等
        #    叙事文本误识别为敌人名）。LLM 应主动填 spotted_enemies，未填则走随机生成。

        return _found

    def _estimate_enemy_count(self, narrative: str, name: str) -> int:
        """从叙事文本估算某个怪物的数量"""
        for kw, n in [("两只", 2), ("三只", 3), ("四只", 4), ("五只", 5),
                      ("一群", 4), ("数只", 3), ("几只", 2), ("数头", 3),
                      ("两头", 2), ("三头", 3), ("数个", 3)]:
            if kw in narrative:
                return n
        return 1

    def _generate_enemies_with_spotted(self, state: Dict, risk_level: str) -> list:
        """生成敌人：优先用叙事中提到的敌人（spotted_enemies），否则随机生成。
        spotted_enemies 格式: [{"name": "Elemental Slime", "count": 3}, ...]
        """
        spotted = state.get("spotted_enemies", [])
        if spotted and isinstance(spotted, list):
            char = state["character"]
            char_level = char.get("level", 1)
            world_setting = state.get("world_setting", {})

            enemies = []
            for spot in spotted:
                if not isinstance(spot, dict):
                    continue
                name = str(spot.get("name", "")).strip()
                count = int(spot.get("count", 1))
                if not name or count < 1:
                    continue
                # 特殊敌人已被击败 → 跳过（永久屏蔽）
                from simlife.backend.enemy_agent import EnemyAgent
                _spot_key = DeathModeEngine._monster_name_key(name)
                # 有名怪物（非普通小怪）已在击杀名单 → 禁止再生成
                _named_dead = _spot_key in state.setdefault("killed_monsters", []) and \
                              not any(k in name.lower() for k in REFRESHABLE_MOB_KEYWORDS)
                if EnemyAgent.is_already_defeated(state, name) or _named_dead:
                    print(f"[DeathMode] 跳过已击败的怪物: {name}")
                    continue
                count = min(count, 5)  # 上限防止过载
                # 等级和类型按 risk_level + 数量决定
                if risk_level == "low":
                    enemy_level = max(1, char_level - random.randint(2, 4))
                    enemy_type = "normal"
                elif risk_level == "medium":
                    enemy_level = max(1, char_level - random.randint(0, 2))
                    enemy_type = "normal"
                else:
                    enemy_level = char_level + random.randint(0, 1)
                    # high risk: 单个敌人更可能是精英/boss，群体则混搭
                    if count == 1:
                        enemy_type = "elite" if random.random() < 0.5 else "normal"
                    else:
                        enemy_type = "elite" if random.random() < 0.3 else "normal"
                for i in range(count):
                    enemy = CombatSystem.generate_enemy(enemy_level, world_setting, enemy_type)
                    # 用叙事中提到的名字覆盖
                    if name:
                        enemy["name"] = name if count == 1 else f"{name}{i+1}"
                    # 坏人路线：敌人名匹配NPC → 标记 is_npc，残血时触发怜悯暂停
                    if self.npc_system:
                        _base_name = re.sub(r'\d+$', '', enemy["name"]).strip()
                        for _n in self.npc_system.npcs.values():
                            if not _n.alive:
                                continue
                            # 精确匹配 或 包含匹配（"药剂师莱恩"包含"莱恩"，或反之）
                            _en_lower = enemy["name"].lower()
                            _bn_lower = _base_name.lower()
                            _npc_lower = _n.name.lower()
                            if (_npc_lower == _en_lower or _npc_lower == _bn_lower
                                    or (_npc_lower and _npc_lower in _en_lower)
                                    or (_npc_lower and _npc_lower in _bn_lower)
                                    or (_en_lower and _en_lower in _npc_lower)):
                                enemy["is_npc"] = True
                                enemy["npc_id"] = _n.npc_id
                                # 用NPC的真实名字（避免"药剂师莱恩"和"莱恩"不一致）
                                enemy["name"] = _n.name if count == 1 else f"{_n.name}{i+1}"
                                # NPC作为敌人通常更强（有名字的角色）
                                enemy["max_hp"] = int(enemy.get("max_hp", 50) * 1.5)
                                enemy["hp"] = enemy["max_hp"]
                                break

                    # 坏人路线兜底：NPC不在npc_system中，但从action_text可判断是攻击有名字的角色
                    if not enemy.get("is_npc"):
                        _action_text = state.get("_current_action", "") or ""
                        _attack_kw = ("杀死", "杀掉", "攻击", "袭击", "干掉", "除掉", "了结",
                                      "处决", "抢劫", "击杀", "kill", "attack", "murder")
                        _monster_kw = ("史莱姆", "哥布林", "守卫", "卫兵", "骷髅", "蜘蛛", "蝙蝠",
                                       "狼", "元素", "蘑菇", "水晶", "藤蔓", "slime", "goblin",
                                       "skeleton", "guard", "soldier", "wolf", "elemental")
                        _bn_lower = _base_name.lower()
                        _is_monster_name = any(k in _bn_lower for k in _monster_kw)
                        _is_attack_action = any(k in _action_text.lower() for k in _attack_kw)
                        _name_in_action = _base_name and _base_name in _action_text
                        # 用户行动含"杀死XX"且敌人名XX不是怪物名 → 标记为NPC
                        if _is_attack_action and _name_in_action and not _is_monster_name:
                            enemy["is_npc"] = True
                            enemy["npc_id"] = ""  # 动态注册时填充
                            enemy["max_hp"] = int(enemy.get("max_hp", 50) * 1.5)
                            enemy["hp"] = enemy["max_hp"]
                    enemies.append(enemy)
            if enemies:
                # 清理 spotted_enemies（已实体化）
                state["spotted_enemies"] = []
                return enemies
        # 没有 spotted → 走原逻辑
        return self._generate_enemies(state, risk_level)

    def _generate_enemies(self, state: Dict, risk_level: str) -> list:
        """生成敌人列表（支持一群怪，优先使用地图区域的怪物）
        优先从区域文件读取 monsters 完整战斗数据，回退到内存 world_map
        """
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

        # 优先从区域文件读取怪物完整数据（含战斗数值）
        region_monsters = []  # 完整怪物对象列表
        region_monster_names = []  # 只有名字（回退用）
        boss_data = None

        # 1. 先从文件读取
        try:
            from simlife.worlds import world_manager as wm
            world_id = world_setting.get("world_id", "")
            cur_region_name = state.get("story", {}).get("current_location", "")
            if world_id and cur_region_name:
                file_region = wm.load_region(world_id, cur_region_name)
                if file_region:
                    file_monsters = file_region.get("monsters", [])
                    if file_monsters and isinstance(file_monsters, list):
                        region_monsters = [m for m in file_monsters if isinstance(m, dict) and m.get("name")]
                    file_boss = file_region.get("boss")
                    if file_boss and isinstance(file_boss, dict):
                        boss_data = file_boss
        except Exception:
            pass

        # 2. 回退到内存 world_map
        if not region_monsters and self.world_map:
            current = self.world_map.get_current_region()
            if current and current.monsters:
                region_monsters = [m for m in current.monsters if isinstance(m, dict) and m.get("name")]
            if not boss_data and current and current.boss and not current.boss_defeated:
                boss_data = current.boss

        # 提取名字列表
        region_monster_names = [m.get("name", "") for m in region_monsters if m.get("name")]

        # BOSS区域可能触发BOSS战
        if boss_data and risk_level == "high" and random.random() < 0.4:
            boss_level = boss_data.get("level", char_level + 5)
            boss_enemy = CombatSystem.generate_enemy(boss_level, world_setting, "boss")
            # 用区域 BOSS 数据覆盖
            boss_enemy["name"] = boss_data.get("name", boss_enemy.get("name", "BOSS"))
            if boss_data.get("description"):
                boss_enemy["behavior"] = boss_data["description"]
            return [boss_enemy]

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

            # 如果区域文件有完整怪物数据，优先使用
            if region_monsters:
                # 过滤已死的名怪：有名怪物(非普通小怪)不能重生，普通小怪可刷新
                _alive_pool = region_monsters
                try:
                    _killed_set = set(state.get("killed_monsters", []))
                    _alive_pool = [m for m in region_monsters if
                                   DeathModeEngine._monster_name_key(str(m.get("name", ""))) not in _killed_set
                                   or any(k in str(m.get("name", "")).lower() for k in REFRESHABLE_MOB_KEYWORDS)]
                    _alive_pool = _alive_pool or region_monsters  # 全被击杀则回退原列表（彻底清空该区怪物）
                except Exception:
                    pass
                chosen = random.choice(_alive_pool)
                enemy["name"] = chosen.get("name", enemy.get("name", "怪物"))
                # 应用区域怪物的战斗数据（如果有）
                if chosen.get("level"):
                    enemy["level"] = chosen["level"]
                if chosen.get("hp"):
                    enemy["hp"] = chosen["hp"]
                    enemy["max_hp"] = chosen.get("max_hp", chosen["hp"])
                if chosen.get("attack_power"):
                    enemy["attack_power"] = chosen["attack_power"]
                if chosen.get("defense_power"):
                    enemy["defense_power"] = chosen["defense_power"]
                if chosen.get("exp_reward"):
                    enemy["exp_reward"] = chosen["exp_reward"]
                if chosen.get("gold_reward"):
                    enemy["gold_reward"] = chosen["gold_reward"]
                if chosen.get("type"):
                    enemy["type"] = chosen["type"]
                if chosen.get("behavior"):
                    enemy["behavior"] = chosen["behavior"]
                if chosen.get("skills"):
                    enemy["skills"] = chosen["skills"]
            elif region_monster_names:
                # 只有名字，回退到旧逻辑
                enemy["name"] = random.choice(region_monster_names)

            # 多个敌人时编号
            if count > 1:
                enemy["name"] = f"{enemy['name']}{i+1}"
            enemies.append(enemy)

        return enemies

    def _apply_life_buffs(self, state: Dict, char: Dict, user_char: Dict):
        """战斗开始前应用生活技能食物增益（攻击/防御）并递减回合数。
        buff 由 main.py 的 eat 记录 owner（target: ai/user），这里按属主累加。
        """
        try:
            ls = state.get("life_state") or {}
            buffs = list(ls.get("buffs") or [])
            # 清空旧的临时增益，保证只反映当前生效的食物增益
            char["temp_life_attack"] = 0
            char["temp_life_defense"] = 0
            if user_char:
                user_char["temp_life_attack"] = 0
                user_char["temp_life_defense"] = 0
            if not buffs:
                return
            alive = []
            for b in buffs:
                try:
                    b["turns"] = int(b.get("turns", 0)) - 1
                except (TypeError, ValueError):
                    b["turns"] = 0
                if not isinstance(b, dict):
                    continue
                owner = user_char if (b.get("target") == "user" and user_char) else char
                _t = b.get("type")
                _v = int(b.get("value", 0) or 0)
                if _t == "attack":
                    owner["temp_life_attack"] = owner.get("temp_life_attack", 0) + _v
                elif _t == "defense":
                    owner["temp_life_defense"] = owner.get("temp_life_defense", 0) + _v
                if b["turns"] > 0:
                    alive.append(b)
            ls["buffs"] = alive
        except Exception as e:
            print(f"[DeathMode] 应用食物增益异常: {e}")

    def _combat_round(self, state: Dict, enemies: list, ai_alone: bool = False,
                      action_text: str = "", sender: str = "user",
                      cmd_override: dict = None) -> Dict:
        """执行一回合战斗，解析用户行动口令驱动战斗策略
        action_text: 用户输入的行动文本，用于解析战斗策略
        ai_alone: 用户已逃跑，AI角色独自面对所有敌人
        sender: "user"或"ai"，谁发的行动
        cmd_override: 若提供，则跳过口令解析直接使用此战斗策略
        """
        from simlife.backend.combat_system import TacticalSystem
        from simlife.backend.skill_system import SkillSystem
        from simlife.backend.enemy_agent import EnemyAgent, get_enemy_agent

        char = state["character"]  # AI角色
        user_char = state.get("user_character", {})  # 用户角色
        # 战斗前应用生活技能食物增益（攻击/防御），按属主分配到AI或用户角色
        self._apply_life_buffs(state, char, user_char)
        # 注入职业被动效果到Dict实体
        world_type = state.get("world_type", "fantasy")
        char["passive_effects"] = SkillSystem.get_passive_effects(char, world_type)
        if user_char and user_char.get("class_name"):
            user_char["passive_effects"] = SkillSystem.get_passive_effects(user_char, world_type)
        # ── 队友参战 ──
        party_members = state.get("party_members", [])
        party_in_combat = []
        for pm_dict in party_members:
            if pm_dict.get("is_alive", True) and pm_dict.get("hp", 0) > 0:
                pm = PartyMember.from_dict(pm_dict)
                pm.passive_effects = SkillSystem.get_passive_effects(pm.to_combat_entity(), world_type)
                party_in_combat.append(pm)
        user_in_combat = not ai_alone and user_char and user_char.get("hp", 0) > 0 and user_char.get("class_name")
        # 如果AI角色已死（用户继续冒险），AI不参战
        ai_in_combat = char.get("hp", 0) > 0 and not state.get("ai_character_dead", False)
        # 如果用户角色已死（AI继续冒险），用户不参战
        if state.get("user_character_dead", False):
            user_in_combat = False
        combat_log = []
        drops = []

        # ── 解析战斗口令（支持cmd_override） ──
        cmd = self._parse_combat_command(action_text, char, user_char, enemies, state, sender)
        if cmd_override:
            cmd.update(cmd_override)

        # ── 创建敌人Agent（精英/BOSS使用EnemyAgent智能决策） ──
        enemy_agents = {}  # id(enemy_dict) -> EnemyAgent
        world_setting = state.get("world_setting", {})
        for e in enemies:
            agent = get_enemy_agent(e, world_setting)
            if agent:
                enemy_agents[id(e)] = agent
                # 战斗开始对话
                dialogue = agent.get_dialogue("battle_start")
                if dialogue:
                    combat_log.append(f"💬 {e.get('name','?')}：{dialogue}")

        def _enemy_defense(enemy=None):
            """敌人随机防御（精英/BOSS使用EnemyAgent决策）"""
            e = enemy or target
            if not e:
                return DefenseAction.BLOCK
            # 检查是否有EnemyAgent（用id作key，避免同名冲突）
            agent = enemy_agents.get(id(e))
            if agent:
                return agent.choose_defense()
            # 默认随机防御
            choices = [DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.NONE]
            if e.get("stats", {}).get("intelligence", 5) > 12:
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
                # 生活技能原材料掉落（战斗掉落，LLM 自由组合的物料来源）
                self._drop_life_materials(enemy, combat_log)

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
            # 队友加入出手顺序
            for pm in party_in_combat:
                pm_agi = pm.stats.get("agility", 5)
                pm_class = pm.class_name
                pm_initiative = pm_agi + (5 if any(c in pm_class for c in range_classes) else 0)
                actors.append((pm_initiative, f"party_{pm.member_id}", pm.to_combat_entity()))
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
        # 指定具体技能时强制单回合，确保精确执行用户指令
        if cmd.get("has_specific_skill", False):
            max_sub_rounds = 1
        elif _party_power >= _enemy_power * 2.0:
            max_sub_rounds = 1
        elif _party_power >= _enemy_power * 1.3:
            max_sub_rounds = 2
        else:
            max_sub_rounds = 3

        total_combat_log = []
        victory = False
        death_return = None
        # ── 远程先手攻击（远程职业/法术在战斗开始时先造成一轮伤害，敌人无防御）──
        ranged_classes = ("法师", "术士", "弓手", "猎人", "游侠", "巫师", "贤者", "牧师")
        preemptive_log = []
        for role_name, role_char in [("ai", char), ("user", user_char)]:
            if role_char.get("hp", 0) <= 0:
                continue
            if role_name == "user" and not user_in_combat:
                continue
            class_name = role_char.get("class_name", "")
            if not any(c in class_name for c in ranged_classes):
                continue
            # 找一个存活的敌人
            target_enemy = next((e for e in enemies if e.get("hp", 0) > 0), None)
            if not target_enemy:
                continue
            # 使用攻击技能或普通攻击
            learned = role_char.get("skills", [])
            atk_skill = None
            mp = role_char.get("mp", 0)
            for sid in learned:
                sk = SkillSystem.get_skill(sid)
                if sk and sk.type in ("physical", "magic", "finesse", "ranged") and sk.mp_cost <= mp:
                    atk_skill = sk
                    break
            if atk_skill:
                skill_mult = atk_skill.effects[0].value if atk_skill.effects else 1.0
                _atk_type = CombatSystem.skill_attack_type(atk_skill.type)
                role_char["mp"] = mp - atk_skill.mp_cost
                skill_name = atk_skill.name
            else:
                skill_mult = 1.0
                _atk_type = "physical"
                skill_name = ""
            # 先手攻击：敌人无防御
            preemptive_result = CombatSystem.attack(role_char, target_enemy,
                                                     defense_action=DefenseAction.NONE,
                                                     attack_type=_atk_type,
                                                     skill_multiplier=skill_mult)
            preemptive_log.append(f"{role_char.get('name','?')}{'【'+skill_name+'】' if skill_name else ''}先手突袭{preemptive_result['description']} → {target_enemy.get('name', '?')}")
            _check_drop(target_enemy, role_char.get("stats", {}))
        if preemptive_log:
            combat_log.append("🏹 远程先手攻击：")
            combat_log.extend(preemptive_log)
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

                # ── 队友由 PartyAgent 决策 ──
                if role.startswith("party_"):
                    member_id = role[6:]
                    pm_obj = next((m for m in party_in_combat if m.member_id == member_id), None)
                    if not pm_obj:
                        continue
                    # PartyAgent 决策
                    decision = PartyAgent.decide_action(
                        pm_obj, {}, enemies, [char, user_char], world_type
                    )
                    if decision.get("action") == "defend":
                        round_log.append(f"{pm_obj.name}进入防御姿态")
                        continue
                    # 选目标
                    target_idx = decision.get("target_index", 0)
                    target = enemies[target_idx] if target_idx < len(enemies) else next((e for e in enemies if e.get("hp", 0) > 0), None)
                    if not target:
                        continue
                    is_magic = decision.get("is_magic", False)
                    skill_mult = decision.get("skill_mult", 1.0)
                    _pm_skill_name = ""
                    _atk_type = "magic" if is_magic else "physical"
                    # 消耗MP
                    if decision.get("action") == "skill":
                        sk_id = decision.get("skill_id", "")
                        sk = SkillSystem.get_skill(sk_id) if sk_id else None
                        if sk:
                            pm_obj.mp -= sk.mp_cost
                            attacker["mp"] = pm_obj.mp
                            _pm_skill_name = f"【{sk.name}】"
                            _atk_type = CombatSystem.skill_attack_type(sk.type)
                    atk_result = CombatSystem.attack(attacker, target, defense_action=_enemy_defense(target),
                                                     attack_type=_atk_type, skill_multiplier=skill_mult)
                    _pm_log_prefix = f"{pm_obj.name}{_pm_skill_name}" if _pm_skill_name else f"{pm_obj.name} "
                    round_log.append(f"{_pm_log_prefix}{atk_result['description']} → {target.get('name', '?')}")
                    _check_drop(target, attacker.get("stats", {}))
                    continue

                # ── 消耗品使用（药水/恢复品）：回HP/MP，不攻击，从背包移除 ──
                _consumable_name = cmd.get(f"{role}_use_consumable")
                if _consumable_name:
                    shared_inv = state.get("shared_inventory", [])
                    _used_item = None
                    for _idx, _it in enumerate(shared_inv):
                        if isinstance(_it, dict) and _it.get("type") == "consumable" and _it.get("name") == _consumable_name:
                            _used_item = shared_inv.pop(_idx)
                            break
                    if _used_item:
                        _heal_hp = _used_item.get("heal_hp", 0)
                        _heal_mp = _used_item.get("heal_mp", 0)
                        if _heal_hp:
                            _max_hp = attacker.get("max_hp", 50)
                            attacker["hp"] = min(_max_hp, attacker.get("hp", 0) + _heal_hp)
                        if _heal_mp:
                            _max_mp = attacker.get("max_mp", 20)
                            attacker["mp"] = min(_max_mp, attacker.get("mp", 0) + _heal_mp)
                        _log_parts = []
                        if _heal_hp:
                            _log_parts.append(f"+{_heal_hp}HP")
                        if _heal_mp:
                            _log_parts.append(f"+{_heal_mp}MP")
                        round_log.append(f"🧪 {attacker.get('name','?')}使用【{_consumable_name}】{'·'.join(_log_parts)}")
                        continue

                # ── 辅助技能（heal/buff/utility）：走 resolve_skill，不攻击敌人 ──
                _support_skill_id = cmd.get(f"{role}_support_skill")
                if _support_skill_id:
                    _sk_obj = SkillSystem.get_skill(_support_skill_id)
                    if _sk_obj:
                        _targets = {"self": [attacker], "all_allies": [attacker]}
                        if role == "ai" and user_in_combat and user_char.get("hp", 0) > 0:
                            _targets["all_allies"].append(user_char)
                        elif role == "user" and char.get("hp", 0) > 0:
                            _targets["all_allies"].append(char)
                        _skill_result = SkillSystem.resolve_skill(_sk_obj, attacker, _targets)
                        round_log.append(f"{attacker.get('name','?')}【{_sk_obj.name}】")
                        for _log_line in _skill_result.get("log", []):
                            round_log.append(f"  {_log_line}")
                        continue

                target = cmd.get(f"{role}_target") or next((e for e in enemies if e.get("hp", 0) > 0), None)
                if not target:
                    continue
                is_magic = cmd.get(f"{role}_is_magic", False)
                skill_mult = cmd.get(f"{role}_skill_mult", 1.0)
                _used_skill_id = cmd.get(f"{role}_skill")
                _used_skill_name = ""
                _atk_type = "magic" if is_magic else "physical"
                if _used_skill_id:
                    _sk_obj = SkillSystem.get_skill(_used_skill_id)
                    if _sk_obj:
                        _used_skill_name = f"【{_sk_obj.name}】"
                        _atk_type = CombatSystem.skill_attack_type(_sk_obj.type)
                atk_result = CombatSystem.attack(attacker, target, defense_action=_enemy_defense(target),
                                                 attack_type=_atk_type, skill_multiplier=skill_mult)
                # 战术加成
                if tactic_result and (role == "ai" or cmd["tactic"] in ("focus", "flank")):
                    atk_result = TacticalSystem.apply_tactic_modifiers(atk_result, tactic_result)
                round_log.append(f"{attacker.get('name','?')}{_used_skill_name}{' ' if not _used_skill_name else ''}{atk_result['description']} → {target.get('name', '?')}")
                _check_drop(target, attacker.get("stats", {}))

                # ── 多效果技能：处理额外效果（heal/buff/stun/dot等）──
                if _used_skill_id and _sk_obj and len(_sk_obj.effects) > 1:
                    for _extra_eff in _sk_obj.effects[1:]:
                        if isinstance(_extra_eff, dict):
                            _e_type = _extra_eff.get("type", "")
                            _e_target = _extra_eff.get("target", "self")
                            _e_value = _extra_eff.get("value", 1.0)
                            _e_chance = _extra_eff.get("chance", 1.0)
                            _e_duration = _extra_eff.get("duration", 0)
                            _e_stat = _extra_eff.get("stat", None)
                        else:
                            _e_type = getattr(_extra_eff, 'type', "")
                            _e_target = getattr(_extra_eff, 'target', "self")
                            _e_value = getattr(_extra_eff, 'value', 1.0)
                            _e_chance = getattr(_extra_eff, 'chance', 1.0)
                            _e_duration = getattr(_extra_eff, 'duration', 0)
                            _e_stat = getattr(_extra_eff, 'stat', None)
                        # 治疗效果
                        if _e_type in ("heal",) and _e_target in ("self", "single_ally", "all_allies"):
                            heal_targets = [attacker] if _e_target == "self" else [attacker, char]
                            for _ht in heal_targets:
                                if _ht.get("hp", 0) <= 0:
                                    continue
                                # 循环治疗加成：叠加施法者职业被动"治疗效果+X%"
                                heal_mult = (attacker.get("passive_effects", {}) or {}).get("heal_mult", 1.0)
                                heal_amount = int(_ht.get("stats", {}).get("intelligence", 5) * 3 * _e_value * heal_mult)
                                max_hp = _ht.get("max_hp", 50)
                                _ht["hp"] = min(max_hp, _ht.get("hp", 0) + heal_amount)
                                round_log.append(f"  💚 {_ht.get('name','?')}【{_sk_obj.name}】治疗{heal_amount}HP")
                        # 控制效果（stun/freeze）
                        if _e_type in ("stun", "freeze") and random.random() < _e_chance:
                            eff_targets = [target] if _e_target in ("single_enemy", "self") else [e for e in enemies if e.get("hp", 0) > 0]
                            for _et in eff_targets:
                                _et["stagger_turns"] = max(_et.get("stagger_turns", 0), int(_e_value))
                            round_log.append(f"  ⚡ {target.get('name','?')}被{_e_type}，持续{int(_e_value)}回合")
                        # 持续伤害（dot）
                        if _e_type in ("dot", "hot"):
                            eff_targets = [target] if _e_target in ("single_enemy", "self") else [e for e in enemies if e.get("hp", 0) > 0]
                            for _et in eff_targets:
                                _et.setdefault("temp_dots", []).append({"type": _e_type, "value": _e_value, "remaining": _e_duration, "source": attacker.get("name", "?")})
                            round_log.append(f"  🔥 {target.get('name','?')}受到{_e_type}效果，持续{_e_duration}回合")
                        # 属性减益（debuff）
                        if _e_type in ("debuff_stat", "slow") and _e_stat:
                            eff_targets = [target] if _e_target in ("single_enemy", "self") else [e for e in enemies if e.get("hp", 0) > 0]
                            for _et in eff_targets:
                                _et.setdefault("temp_debuffs", {})[_e_stat] = _et.get("temp_debuffs", {}).get(_e_stat, 0) + int(_e_value)
                            round_log.append(f"  📉 {target.get('name','?')}的{_e_stat}降低{abs(int(_e_value))}点，持续{_e_duration}回合")
                        # 吸血（life_steal，在攻击后回血）
                        if _e_type in ("life_steal",):
                            ls_amount = int(atk_result.get("damage", 0) * _e_value)
                            if ls_amount > 0:
                                attack_max_hp = attacker.get("max_hp", 50)
                                attacker["hp"] = min(attack_max_hp, attacker.get("hp", 0) + ls_amount)
                                round_log.append(f"  ❤️‍🔥 {attacker.get('name','?')}吸血{ls_amount}HP")

            # ── 存活敌人反击（智能承伤 + EnemyAgent）──
            for enemy in enemies:
                if enemy.get("hp", 0) <= 0:
                    continue

                # 检查是否有EnemyAgent（用id作key）
                agent = enemy_agents.get(id(enemy))

                # 低血量/阶段变化对话
                if agent:
                    if agent.is_low_hp():
                        dialogue = agent.get_dialogue("crisis_low_hp")
                        if dialogue:
                            round_log.append(f"💬 {enemy.get('name','?')}：{dialogue}")
                    if agent.check_phase_change():
                        dialogue = agent.get_dialogue("stage_enter")
                        if dialogue:
                            round_log.append(f"💬 {enemy.get('name','?')}：{dialogue}")

                # 决定攻击目标：坦克优先 > EnemyAgent选择 > 加权随机
                if tank_role == "ai" and char.get("hp", 0) > 0:
                    target_char, target_defense, target_name = char, cmd.get("ai_defense", DefenseAction.BLOCK), char.get("name", "你")
                elif tank_role == "user" and user_in_combat and user_char.get("hp", 0) > 0:
                    target_char, target_defense, target_name = user_char, cmd.get("user_defense", DefenseAction.BLOCK), user_char.get("name", "用户")
                elif agent:
                    # EnemyAgent 智能选择目标
                    all_targets = []
                    # 构建可用目标列表
                    for r_name, r_char in [("ai", char), ("user", user_char)]:
                        if r_char.get("hp", 0) <= 0:
                            continue
                        if r_name == "user" and not user_in_combat:
                            continue
                        is_tank = (tank_role == r_name)
                        all_targets.append({
                            "name": r_char.get("name", r_name),
                            "hp": r_char.get("hp", 0),
                            "max_hp": r_char.get("max_hp", 1),
                            "is_tank": is_tank,
                        })
                    for pm in party_in_combat:
                        all_targets.append({
                            "name": pm.name,
                            "hp": pm.hp,
                            "max_hp": pm.max_hp,
                            "is_tank": False,
                        })
                    if all_targets:
                        chosen = agent.choose_target(all_targets)
                        # 将选中的目标名匹配回实际对象
                        target_name = chosen.get("name", "")
                        target_char = None
                        if target_name == char.get("name"):
                            target_char = char
                        elif target_name == user_char.get("name"):
                            target_char = user_char
                        else:
                            # 匹配队友
                            for pm in party_in_combat:
                                if pm.name == target_name:
                                    target_char = pm.to_combat_entity()
                                    break
                        if not target_char:
                            target_char = char
                        target_defense = cmd.get("ai_defense" if target_char is char else "user_defense", DefenseAction.BLOCK)
                    else:
                        continue
                else:
                    # 无坦克 + 无Agent：加权随机选择（原逻辑）
                    import random as _rng
                    candidates = []
                    melee_classes = ("战士", "骑士", "圣骑士", "武僧", "剑士", "狂战士")
                    for r_name, r_char, r_def in [
                        ("ai", char, cmd.get("ai_defense", DefenseAction.BLOCK)),
                        ("user", user_char, cmd.get("user_defense", DefenseAction.DODGE)),
                    ]:
                        if r_char.get("hp", 0) <= 0:
                            continue
                        if r_name == "user" and not user_in_combat:
                            continue
                        hp_ratio = r_char.get("hp", 0) / max(1, r_char.get("max_hp", 1))
                        r_class = r_char.get("class_name", "")
                        is_melee = any(c in r_class for c in melee_classes)
                        weight = 1.0
                        if is_melee:
                            weight = 3.0
                        if hp_ratio < 0.3:
                            weight *= 0.2
                        elif hp_ratio < 0.5:
                            weight *= 0.5
                        candidates.append((r_name, r_char, r_def, weight))
                    for pm in party_in_combat:
                        if pm.hp > 0:
                            pm_entity = pm.to_combat_entity()
                            hp_ratio = pm.hp / max(1, pm.max_hp)
                            weight = 1.0
                            pm_class = pm.class_name or ""
                            if any(c in pm_class for c in melee_classes):
                                weight = 3.0
                            if hp_ratio < 0.3:
                                weight *= 0.2
                            elif hp_ratio < 0.5:
                                weight *= 0.5
                            candidates.append((f"party_{pm.member_id}", pm_entity, DefenseAction.BLOCK, weight))
                    if not candidates:
                        continue
                    total_weight = sum(c[3] for c in candidates)
                    if total_weight <= 0:
                        pick = _rng.choice(candidates)
                    else:
                        r_val = _rng.uniform(0, total_weight)
                        cum = 0
                        pick = candidates[0]
                        for c in candidates:
                            cum += c[3]
                            if r_val <= cum:
                                pick = c
                                break
                    target_char, target_defense, target_name = pick[1], pick[2], pick[1].get("name", "?")
                    # 队友承伤保护
                    target_hp_ratio = target_char.get("hp", 0) / max(1, target_char.get("max_hp", 1))
                    if target_hp_ratio <= 0.3:
                        other_allies = [c for c in candidates if c[1] is not target_char and c[1].get("hp", 0) > 0]
                        if other_allies and _rng.random() < 0.3:
                            protector = _rng.choice(other_allies)
                            target_char, target_defense, target_name = protector[1], protector[2], protector[1].get("name", "?")
                            combat_log.append(f"🛡️ {target_name}挺身而出，为{pick[1].get('name','?')}挡下攻击！")

                if target_char.get("stagger_turns", 0) > 0:
                    target_defense = DefenseAction.NONE

                # ── EnemyAgent 使用技能攻击 ──
                enemy_skill_name = ""
                if agent:
                    skills = agent.get_skills()
                    if skills:
                        chosen_skill = random.choice(skills)
                        caster_attack = (enemy.get("stats", {}).get("strength", 5) * 2 +
                                         enemy.get("stats", {}).get("agility", 5) * 0.5 +
                                         enemy.get("stats", {}).get("intelligence", 5) * 0.5)
                        # 计算技能伤害
                        skill_mult = chosen_skill.get("multiplier", 1.0)
                        is_magic = chosen_skill.get("type") == "magic"
                        base_damage = int(caster_attack * skill_mult)
                        defense = target_char.get("stats", {}).get("vitality", 5) * 1.5
                        for eq in target_char.get("equipment", []):
                            if eq.get("type") == "outfit":
                                base_damage -= eq.get("bonus", 0)
                        damage = max(1, base_damage - int(defense))
                        damage = max(1, int(damage * random.uniform(0.9, 1.1)))
                        target_char["hp"] = max(0, target_char.get("hp", 0) - damage)
                        enemy_skill_name = f"【{chosen_skill['name']}】"
                        def_result = {"description": f"使用{chosen_skill['name']}造成{damage}点伤害", "damage": damage,
                                      "defense_result": {"damage_taken": damage, "defense_used": str(target_defense)}}
                    else:
                        def_result = CombatSystem.attack(enemy, target_char, defense_action=target_defense)
                else:
                    def_result = CombatSystem.attack(enemy, target_char, defense_action=target_defense)

                if ai_alone and target_char is char and def_result.get("damage", 0) > 0:
                    def_result["damage"] = int(def_result["damage"] * 1.4)
                    if def_result.get("defense_result"):
                        def_result["defense_result"]["damage_taken"] = int(
                            def_result["defense_result"].get("damage_taken", 0) * 1.4
                        )

                round_log.append(f"{enemy.get('name', '?')}{enemy_skill_name}{' ' if not enemy_skill_name else ''}{def_result['description']} → {target_name}")

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

            # ── HP危险检查：子回合结束后，任一角色HP<20%则停止战斗 ──
            ai_hp_ratio = char.get("hp", 0) / max(1, char.get("max_hp", 1))
            user_hp_ratio = (user_char.get("hp", 0) / max(1, user_char.get("max_hp", 1))) if user_in_combat else 1.0
            if ai_hp_ratio < 0.2 or user_hp_ratio < 0.2:
                total_combat_log.append(f"⚠️ HP危险（焕灵{int(ai_hp_ratio*100)}%，yount{int(user_hp_ratio*100)}%），战斗中断")
                break

            # ── 坏人路线·NPC怜悯暂停：有名字的NPC敌人HP≤20%时停止战斗 ──
            # 用户需明确说"杀死/处决/了结"才执行最后一击，避免误杀剧情NPC
            _npc_low_hp = [e for e in enemies if e.get("is_npc") and e.get("hp", 0) > 0
                           and e.get("hp", 0) / max(1, e.get("max_hp", 1)) <= 0.2]
            if _npc_low_hp and not state.get("_npc_finish_blow"):
                _npc_names = "、".join(e.get("name", "?") for e in _npc_low_hp)
                total_combat_log.append(f"💔 {_npc_names}已身受重伤，摇摇欲坠（HP≤20%）——是否给予致命一击？")
                state["npc_mercy_pause"] = {
                    "npc_names": [e.get("name", "") for e in _npc_low_hp],
                    "npc_ids": [e.get("npc_id", "") for e in _npc_low_hp],
                }
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
            # 同步队友状态到state
            self._sync_party_state(state, party_in_combat)
            death_return["combat_log"] = total_combat_log + death_return.get("combat_log", [])
            return death_return

        # 同步队友状态到state
        self._sync_party_state(state, party_in_combat)

        return {
            "victory": victory,
            "player_died": False,
            "combat_log": total_combat_log,
            "drops": drops,
            "npc_mercy_pause": bool(state.get("npc_mercy_pause")),
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
        # 注入职业被动效果
        from simlife.backend.skill_system import SkillSystem
        world_type = state.get("world_type", "fantasy")
        char["passive_effects"] = SkillSystem.get_passive_effects(char, world_type)
        if user_char and user_char.get("class_name"):
            user_char["passive_effects"] = SkillSystem.get_passive_effects(user_char, world_type)
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

        # ── 伤害过低检测：连续N回合伤害不足 → 自动退出扫荡 ──
        low_damage_streak = 0
        prev_enemy_total_hp = sum(e.get("hp", e.get("max_hp", 0)) for e in enemies)

        # 初始敌人总HP（用于"打到半血"目标）
        enemy_total_hp_start = sum(e.get("hp", e.get("max_hp", 0)) for e in enemies)
        enemy_half_target = enemy_total_hp_start * 0.5 if stop_condition == "half" else 0

        # ── 扫荡开始前自动施放辅助技能（buff/shield/heal）──
        support_log = []
        for role_name, role_char in [("ai", char), ("user", user_char)]:
            if role_char.get("hp", 0) <= 0:
                continue
            if role_name == "user" and not user_in_combat:
                continue
            learned = role_char.get("skills", [])
            if not learned:
                continue
            mp = role_char.get("mp", 0)
            for sid in learned:
                sk = SkillSystem.get_skill(sid)
                if not sk or sk.type not in ("buff", "heal"):
                    continue
                if sk.mp_cost > mp:
                    continue
                targets = {
                    "self": [role_char],
                    "single_enemy": [],
                    "all_enemies": [],
                    "single_ally": [role_char],
                    "all_allies": [role_char],
                }
                if sk.type == "heal":
                    allies = []
                    if char.get("hp", 0) > 0:
                        allies.append(char)
                    if user_in_combat and user_char.get("hp", 0) > 0:
                        allies.append(user_char)
                    if not allies:
                        continue
                    lowest_hp_ally = min(allies, key=lambda a: a.get("hp", 0) / max(1, a.get("max_hp", 1)))
                    if lowest_hp_ally.get("hp", 0) >= lowest_hp_ally.get("max_hp", 1) * 0.9:
                        continue
                    targets["single_ally"] = [lowest_hp_ally]
                    targets["all_allies"] = allies
                skill_result = SkillSystem.resolve_skill(sk, role_char, targets)
                mp -= sk.mp_cost
                role_char["mp"] = mp
                if skill_result.get("log"):
                    support_log.extend(skill_result["log"])
        if support_log:
            all_combat_logs.append("💫 扫荡开始前施放辅助技能：")
            for log_line in support_log:
                all_combat_logs.append(f"  {log_line}")

        # 用于兜底（当循环未执行时）
        combat_result = {"combat_log": [], "drops": [], "player_died": False, "user_died": False}

        for round_num in range(1, max_rounds + 1):
            rounds = round_num
            alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]
            if not alive_enemies:
                stopped_at = "enemies_defeated"
                break

            # ── 坏人路线：NPC怜悯暂停检查 ──
            if state.get("npc_mercy_pause"):
                stopped_at = "npc_mercy"
                _pause_names = "、".join(state["npc_mercy_pause"].get("npc_names", []))
                key_events.append(f"NPC怜悯暂停：{_pause_names}已身受重伤")
                all_combat_logs.append(f"💔 {_pause_names}已身受重伤，摇摇欲坠（HP≤20%）——是否给予致命一击？")
                break

            # ── HP阈值检查：任一角色HP<20%时自动停止扫荡，切换到逐回合模式 ──
            ai_hp_ratio = char.get("hp", 0) / max(1, char.get("max_hp", 1))
            user_hp_ratio = (user_char.get("hp", 0) / max(1, user_char.get("max_hp", 1))) if user_in_combat else 1.0
            if ai_hp_ratio < 0.2 or user_hp_ratio < 0.2:
                stopped_at = "low_hp"
                key_events.append(f"角色HP危险（焕灵{int(ai_hp_ratio*100)}%/yount{int(user_hp_ratio*100)}%），自动停止扫荡")
                all_combat_logs.append(f"⚠️ 角色HP危险，自动停止扫荡！焕灵{int(ai_hp_ratio*100)}%，yount{int(user_hp_ratio*100)}%")
                break

            # ── MP耗尽检测：双方MP都为0 → 无法施放技能，退出扫荡 ──
            ai_mp = char.get("mp", 0)
            user_mp = user_char.get("mp", 0) if user_in_combat else 0
            if ai_mp <= 0 and user_mp <= 0 and round_num > 2:
                stopped_at = "mp_exhausted"
                key_events.append(f"双方MP耗尽（焕灵MP:{ai_mp}/yount MP:{user_mp}），无法有效输出，退出扫荡")
                all_combat_logs.append(f"💧 双方MP耗尽，普攻伤害不足，自动退出扫荡！请恢复MP后再战。")
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

            # ── 自动选择技能（扫荡模式自动使用已学技能）──
            from simlife.backend.skill_system import SkillSystem
            cmd_override = {}
            for role_name, role_char in [("ai", char), ("user", user_char)]:
                if role_char.get("hp", 0) <= 0:
                    continue
                if role_name == "user" and not user_in_combat:
                    continue
                learned = role_char.get("skills", [])
                if not learned:
                    continue
                mp = role_char.get("mp", 0)
                # 筛选有MP可用的伤害技能
                usable = []
                for sid in learned:
                    sk = SkillSystem.get_skill(sid)
                    if sk and sk.type in ("physical", "magic") and sk.mp_cost <= mp:
                        usable.append(sk)
                if not usable:
                    continue
                # 随机选一个技能
                sk = random.choice(usable)
                is_magic = sk.type == "magic"
                cmd_override[f"{role_name}_is_magic"] = is_magic
                cmd_override[f"{role_name}_skill_mult"] = sk.effects[0].value if sk.effects else 1.0
                cmd_override[f"{role_name}_skill"] = sk.id
                # 消耗MP
                role_char["mp"] = mp - sk.mp_cost

            # ── 执行一回合战斗（复用 _combat_round）──
            sweep_action = f"扫荡攻击{target_enemy.get('name', '敌人')}"
            combat_result = self._combat_round(
                state, alive_enemies,
                action_text=sweep_action, sender=sender,
                cmd_override=cmd_override if cmd_override else None
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

            # ── 伤害过低检测：连续3回合对敌人总HP减少<初始HP的3% → 退出 ──
            cur_enemy_total_hp = sum(e.get("hp", 0) for e in enemies if e.get("hp", 0) > 0)
            round_damage_dealt = prev_enemy_total_hp - cur_enemy_total_hp
            prev_enemy_total_hp = cur_enemy_total_hp
            # 阈值：初始敌人总HP的3%，至少5点
            _low_dmg_threshold = max(5, enemy_total_hp_start * 0.03)
            if round_damage_dealt < _low_dmg_threshold:
                low_damage_streak += 1
            else:
                low_damage_streak = 0
            if low_damage_streak >= 3:
                stopped_at = "low_damage"
                key_events.append(f"连续3回合伤害不足（阈值{_low_dmg_threshold:.0f}点），可能MP耗尽或敌人防御过高，退出扫荡")
                all_combat_logs.append(f"⚠️ 连续3回合伤害过低，自动退出扫荡！建议恢复MP或调整策略后再战。")
                break

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
            "stopped_at": stopped_at,  # 停止原因：kill/enemies_defeated/low_hp/mp_exhausted/low_damage
            "alive_enemies": [e.get("name", "?") for e in enemies if e.get("hp", 0) > 0],
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
        elif not victory and stopped_at in ("mp_exhausted", "low_damage"):
            # MP耗尽或伤害过低导致扫荡中止 → 生成中止叙事
            _alive_names = "、".join([e.get("name", "?") for e in enemies if e.get("hp", 0) > 0])
            if stopped_at == "mp_exhausted":
                narrative = f"经过{rounds}回合的战斗，双方魔力耗尽，普攻难以造成有效伤害，{_alive_names}仍未被击败。需要恢复魔力后再战。"
            else:
                narrative = f"经过{rounds}回合的战斗，伤害输出持续不足，难以击破{_alive_names}的防御，扫荡被迫中止。建议调整策略或恢复状态后再战。"
        elif not victory and stopped_at == "npc_mercy":
            # 坏人路线：NPC怜悯暂停 → 不结算经验金币
            _alive_names = "、".join([e.get("name", "?") for e in enemies if e.get("hp", 0) > 0])
            narrative = f"经过{rounds}回合的战斗，{_alive_names}已身受重伤，摇摇欲坠。是否给予致命一击？"

        # ── 精简战斗日志（只保留关键事件+首尾回合）──
        concise_log = []
        if all_combat_logs:
            # 保留首回合
            concise_log.append(f"⚡ 扫荡开始 — {'、'.join(enemy_names_start)}")
            # 保留关键事件
            concise_log.extend(key_events[:6])
            # 保留末回合
            if victory:
                concise_log.append(f"⚡ 扫荡完成 — {rounds}回合，全部击败")
            elif stopped_at == "mp_exhausted":
                concise_log.append(f"⚡ 扫荡中止 — 共{rounds}回合，MP耗尽")
            elif stopped_at == "low_damage":
                concise_log.append(f"⚡ 扫荡中止 — 共{rounds}回合，伤害不足")
            elif stopped_at == "low_hp":
                concise_log.append(f"⚡ 扫荡中止 — 共{rounds}回合，HP危险")
            elif stopped_at == "npc_mercy":
                concise_log.append(f"💔 NPC残血暂停 — 共{rounds}回合，等待致命一击")
            else:
                concise_log.append(f"⚡ 扫荡结束 — 共{rounds}回合")

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
            "npc_mercy_pause": stopped_at == "npc_mercy",
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
        坏人路线：NPC敌人 → 不扫荡（需要残血怜悯暂停）
        """
        for enemy in enemies:
            # BOSS和精英怪走逐回合叙事
            if enemy.get("type") == "boss" or enemy.get("type") == "elite":
                return False
            # 坏人路线：NPC敌人不走扫荡
            if enemy.get("is_npc"):
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
            "ai_use_consumable": None,  # AI角色使用的消耗品名
            "user_use_consumable": None,  # 用户角色使用的消耗品名
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
        tank_keywords = ("拦截", "承伤", "抗伤", "坦克", "守护", "掩护", "保护", "挡", "拉仇恨", "吸引", "顶住", "扛")
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
        # sender="user"时，用户用自己的名字提到自己也算 mentions_self
        mentions_self = "我" in t or (sender == "user" and user_name and user_name in t)

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
                          "陨石", "毒", "暗影", "神圣")
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

        # ── 复合指令切分：按角色名分配子句 ──
        # "yount使用冥想，焕灵抗伤" → yount:"使用冥想" 焕灵:"抗伤"
        import re as _re
        _clauses = [c.strip() for c in _re.split(r'[，,。；;！!？?\n]', t) if c.strip()]
        _ai_text = []
        _user_text = []
        _general_text = []
        for _cl in _clauses:
            _has_ai = any(k in _cl for k in ai_name_kw)
            _has_user = any(k in _cl for k in user_name_kw) or ("我" in _cl and sender == "user")
            if _has_ai and not _has_user:
                _ai_text.append(_cl)
            elif _has_user and not _has_ai:
                _user_text.append(_cl)
            else:
                _general_text.append(_cl)
        # 有明确角色子句时按角色匹配，否则用全文
        _ai_search = " ".join(_ai_text + _general_text) if (_ai_text or _user_text) else t
        _user_search = " ".join(_user_text + _general_text) if (_ai_text or _user_text) else t

        # ── 消耗品使用识别（药水/恢复品等）──
        use_item_keywords = ("使用", "喝", "服用", "嗑", "吃", "灌", "吞")
        if any(k in t for k in use_item_keywords):
            shared_inv = state.get("shared_inventory", [])
            consumables = [it for it in shared_inv if isinstance(it, dict) and it.get("type") == "consumable"]
            if consumables:
                def _match_consumable(search_text, cons_list):
                    for c in cons_list:
                        if c.get("name") and c["name"] in search_text:
                            return c
                    for c in cons_list:
                        c_name = c.get("name", "")
                        if c_name:
                            _core = c_name
                            for suffix in ("药水", "药剂", "药丸", "药膏"):
                                _core = _core.replace(suffix, "")
                            if _core and len(_core) >= 2 and _core in search_text:
                                return c
                    return None
                if mentions_ai or (sender == "ai" and mentions_self):
                    _mc = _match_consumable(_ai_search, consumables)
                    if _mc:
                        result["ai_use_consumable"] = _mc.get("name")
                if mentions_self or (sender == "user" and not mentions_ai):
                    _mc = _match_consumable(_user_search, consumables)
                    if _mc:
                        result["user_use_consumable"] = _mc.get("name")
                if not result["ai_use_consumable"] and not result["user_use_consumable"]:
                    _mc = _match_consumable(t, consumables)
                    if _mc:
                        result["user_use_consumable"] = _mc.get("name")

        # AI角色技能匹配
        ai_skills = ai_char.get("skills", [])
        for skill_id in ai_skills:
            skill = SkillSystem.get_skill(skill_id)
            if skill and skill.name in _ai_search:
                result["has_specific_skill"] = True
                if skill.type in ("heal", "buff", "utility"):
                    # 辅助技能：走 resolve_skill 路径，不当攻击用
                    mp_cost = skill.mp_cost
                    if ai_char.get("mp", 0) >= mp_cost:
                        ai_char["mp"] = ai_char.get("mp", 0) - mp_cost
                        result["ai_support_skill"] = skill.id
                    break
                elif skill.type in ("physical", "magic"):
                    # 攻击技能：走 attack 路径
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
            if skill and skill.name in _user_search:
                result["has_specific_skill"] = True
                if skill.type in ("heal", "buff", "utility"):
                    # 辅助技能：走 resolve_skill 路径，不当攻击用
                    mp_cost = skill.mp_cost
                    if user_char.get("mp", 0) >= mp_cost:
                        user_char["mp"] = user_char.get("mp", 0) - mp_cost
                        result["user_support_skill"] = skill.id
                    break
                elif skill.type in ("physical", "magic"):
                    # 攻击技能：走 attack 路径
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

        # ── 智能自动选择技能（用户未指定技能时）──
        # 优先级：用户口令明确指定 > 智能选择（治疗/辅助优先保命，输出按效率+随机）> 普通攻击
        # 收集所有友军（AI角色、用户角色、队友），用于判断是否需要治疗
        _all_allies = []
        if ai_char.get("hp", 0) > 0:
            _all_allies.append(ai_char)
        if user_char.get("hp", 0) > 0:
            _all_allies.append(user_char)
        for _pm in state.get("party_members", []):
            if _pm.get("is_alive", True) and _pm.get("hp", 0) > 0:
                _all_allies.append(_pm)
        _enemy_count = sum(1 for e in enemies if e.get("hp", 0) > 0)

        for role_name, role_char in [("ai", ai_char), ("user", user_char)]:
            if result.get(f"{role_name}_skill"):  # 用户口令已指定技能，跳过
                continue
            if result.get(f"{role_name}_support_skill"):  # 已选辅助技能，跳过
                continue
            if role_char.get("hp", 0) <= 0:
                continue
            learned = role_char.get("skills", [])
            if not learned:
                continue
            mp = role_char.get("mp", 0)
            max_mp = role_char.get("max_mp", 1) or 1
            max_hp = role_char.get("max_hp", 1) or 1
            hp_pct = role_char.get("hp", 0) / max_hp

            # 判断是否为治疗/辅助职业：class_id=cleric 或技能列表中含heal类技能
            _is_support = (role_char.get("class_id") == "cleric"
                           or role_char.get("class_name", "") in ("牧师", "德鲁伊", "祭司", "萨满"))

            # 分类技能
            _dmg_skills = []    # 伤害类
            _heal_skills = []   # 治疗类
            _buff_skills = []   # 增益类
            for sid in learned:
                sk = SkillSystem.get_skill(sid)
                if not sk or sk.mp_cost > mp:
                    continue
                if sk.type in ("physical", "magic"):
                    _dmg_skills.append(sk)
                elif sk.type == "heal":
                    _heal_skills.append(sk)
                elif sk.type == "buff":
                    _buff_skills.append(sk)

            _chosen = None  # 最终选中的Skill对象

            # ── 策略1：治疗/辅助职业优先保命 ──
            if _is_support:
                # 自己或队友有残血(<60%)且能用治疗技能 → 优先治疗
                _needs_heal = any(
                    (a.get("hp", 0) / (a.get("max_hp", 1) or 1)) < 0.6
                    for a in _all_allies
                )
                if _needs_heal and _heal_skills:
                    # 选治疗量最高的（按effect.value）
                    _heal_skills.sort(
                        key=lambda s: max((e.value for e in s.effects if e.type == "heal"), default=0),
                        reverse=True
                    )
                    _chosen = _heal_skills[0]
                    # 走辅助技能路径（resolve_skill），不当攻击用
                    result[f"{role_name}_support_skill"] = _chosen.id
                    role_char["mp"] = mp - _chosen.mp_cost
                    continue
                # HP健康但有buff技能且队友未满状态 → 50%概率上buff（不要每次都buff）
                if _buff_skills and not _needs_heal and random.random() < 0.5:
                    _chosen = _buff_skills[0]
                    result[f"{role_name}_support_skill"] = _chosen.id
                    role_char["mp"] = mp - _chosen.mp_cost
                    continue

            # ── 策略2：输出技能智能选择 ──
            if _dmg_skills:
                # MP紧张（<20%）→ 优先低消耗技能，留MP给关键时刻
                if mp / max_mp < 0.2:
                    _dmg_skills.sort(key=lambda s: s.mp_cost)
                    # 80%概率用最低消耗，20%概率普攻省MP
                    if random.random() < 0.8:
                        _chosen = _dmg_skills[0]
                # 多敌人(≥2)且自己HP不紧张 → 优先AOE技能
                elif _enemy_count >= 2 and hp_pct > 0.3:
                    _aoe = [s for s in _dmg_skills
                            if any(e.target == "all_enemies" for e in s.effects)]
                    if _aoe:
                        # 按倍率排序选最高，加20%随机性
                        _aoe.sort(key=lambda s: s.effects[0].value if s.effects else 1.0, reverse=True)
                        _chosen = _aoe[0] if random.random() < 0.8 else random.choice(_aoe)
                # 残血(<30%) → 优先带吸血/护盾的技能保命
                elif hp_pct < 0.3:
                    _survival = [s for s in _dmg_skills
                                 if any(e.type in ("life_steal", "heal") for e in s.effects)]
                    if _survival:
                        _chosen = random.choice(_survival)

                # 默认：按伤害倍率/MP效率加权随机（不每次都用最强，避免单调）
                if not _chosen:
                    def _score(s):
                        mult = s.effects[0].value if s.effects else 1.0
                        # 效率 = 倍率 / (MP消耗+1)，MP越低效率越高
                        return mult / (s.mp_cost + 1)
                    _dmg_skills.sort(key=_score, reverse=True)
                    # 70%选Top1，20%选Top2，10%随机
                    _r = random.random()
                    if _r < 0.7 and _dmg_skills:
                        _chosen = _dmg_skills[0]
                    elif _r < 0.9 and len(_dmg_skills) > 1:
                        _chosen = _dmg_skills[1]
                    elif _dmg_skills:
                        _chosen = random.choice(_dmg_skills)

            # 应用选中的技能
            if _chosen:
                is_magic = _chosen.type == "magic"
                result[f"{role_name}_is_magic"] = is_magic
                result[f"{role_name}_skill_mult"] = _chosen.effects[0].value if _chosen.effects else 1.0
                result[f"{role_name}_skill"] = _chosen.id
                role_char["mp"] = mp - _chosen.mp_cost

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

    def _handle_world_boss_dialogue(self, state: Dict, action: str, sender: str = "user") -> Optional[Dict]:
        """世界BOSS身份交流：谈判/对话/求饶/逃跑/加入势力。

        在 LLM 叙事生成之前拦截，用 BOSS 性格(identity)与开关(can_surrender/can_join)做硬性判定，
        避免纯 LLM 即兴导致玩家直接死亡。核心安全原则：
        - 拒绝谈判/求饶时绝不直接致死，而是退回战斗或给逃生机会
        - 加入成功后记录世界BOSS盟友关系，之后该BOSS不再敌对
        返回 dict 或 None(None=不适用，继续正常流程)。
        """
        if not action:
            return None
        if not self.world_map:
            return None
        region = self.world_map.get_current_region()
        if not region or not getattr(region, "world_boss_id", None) or region.boss_defeated:
            return None
        boss = region.boss if isinstance(region.boss, dict) else None
        if not boss:
            return None  # 铺垫/势力中转领地无本体，走正常流程

        boss_name = boss.get("name", "世界BOSS")
        boss_id = boss.get("world_boss_id") or region.world_boss_id
        identity = boss.get("identity", "") or ""
        can_surrender = boss.get("can_surrender", True)
        can_join = boss.get("can_join", True)

        a = (action or "").strip()
        is_negotiate = any(k in a for k in ("谈判", "对话", "交涉", "商量", "求和", "沟通", "聊聊", "交谈", "和谈", "谈条件", "谈和", "谈判"))
        is_surrender = any(k in a for k in ("求饶", "投降", "饶命", "认输", "臣服", "放过我", "饶了我", "乞求", "请饶", "饶命啊"))
        is_join = any(k in a for k in ("加入", "投靠", "归顺", "效忠", "追随", "入伙", "臣服于你", "归附", "投奔", "加入你"))
        is_flee = any(k in a for k in ("逃跑", "撤退", "逃离", "撤走", "溜走", "逃命"))

        if not (is_negotiate or is_surrender or is_join or is_flee):
            return None

        # 已加入该BOSS → 是盟友，不再敌对
        alliances = state.get("world_boss_alliances", [])
        already_ally = boss_id in alliances

        # 性格关键词
        merciful_kw = ("仁慈", "宽厚", "惜才", "爱才", "欣赏", "尊重", "宽容", "赏识", "惜", "高傲", "自负", "孤高", "重才", "求贤")
        cruel_kw = ("凶残", "残忍", "冷酷", "嗜杀", "无情", "冷血", "暴虐", "残暴", "嗜血", "疯狂", "阴狠", "狰狞")
        recruiting_kw = ("招揽", "野心", "需要人手", "招募", "求贤", "扩张", "笼络", "孤独", "雄才", "创业", "用人之际")
        has_merciful = any(k in identity for k in merciful_kw)
        has_cruel = any(k in identity for k in cruel_kw)
        has_recruiting = any(k in identity for k in recruiting_kw)

        # ── 逃跑：多数BOSS允许离开，凶残Boss小概率拦路 ──
        if is_flee:
            if already_ally:
                return {"narrative": f"你是{boss_name}的麾下，想来便来，想走便走。", "joined_boss": boss_id}
            if has_cruel and not has_merciful:
                if random.random() < 0.5:
                    state["in_combat"] = False
                    state["enemies"] = []
                    state["spotted_enemies"] = []
                    return {"narrative": f"{boss_name}狞笑追来，你拼尽全力，终于甩开追兵，逃出了这片领地。", "in_combat": False, "fled": True}
                return {"narrative": f"{boss_name}狞笑着挡住去路：「想逃？没那么容易！」", "blocked": True, "flee_chance": True}
            state["in_combat"] = False
            state["enemies"] = []
            state["spotted_enemies"] = []
            return {"narrative": f"{boss_name}冷冷望着你离去，并未阻拦。你顺利离开了这片领地。", "in_combat": False, "fled": True}

        # ── 加入势力 ──
        if is_join:
            if already_ally:
                return {"narrative": f"你已是{boss_name}的麾下，对方自然对你以礼相待、不设戒备。", "joined_boss": boss_id}
            if not can_join:
                return {"narrative": f"{boss_name}冷哼一声：「本座不收无名之辈，滚。」", "blocked": True}
            if has_recruiting or random.random() < 0.6:
                if boss_id not in alliances:
                    alliances.append(boss_id)
                    state["world_boss_alliances"] = alliances
                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                return {"narrative": f"{boss_name}打量你片刻，竟点头应允：「有点胆识，本座收下你了。」你加入了{boss_name}麾下，成为其势力的一员。",
                        "joined_boss": boss_id, "in_combat": False}
            return {"narrative": f"{boss_name}斜睨你一眼：「想投靠本座？先证明你的价值——去猎杀本座的敌人，或献上诚意之物。」", "blocked": True, "needs_trial": True}

        # ── 求饶：性格决定，拒绝也不致死 ──
        if is_surrender:
            if already_ally:
                return {"narrative": f"作为{boss_name}的麾下，你无需求饶。", "joined_boss": boss_id}
            if not can_surrender:
                return {"narrative": f"{boss_name}目光冰寒：「求饶无用，本座只认实力。」", "blocked": True}
            if has_merciful or (not has_cruel and random.random() < 0.5):
                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                return {"narrative": f"{boss_name}看着你，竟收起杀意：「……也罢，本座不杀弃甲之人。滚吧。」你侥幸保住一命。",
                        "in_combat": False, "spared": True}
            return {"narrative": f"{boss_name}冷笑着步步逼近，杀意凛然——但就在此刻，你若想逃命，趁现在！", "blocked": True, "flee_chance": True}

        # ── 谈判 ──
        if is_negotiate:
            if already_ally:
                return {"narrative": f"你与{boss_name}相谈甚欢，对方对你十分友善。", "joined_boss": boss_id}
            if not can_surrender and not has_merciful:
                return {"narrative": f"{boss_name}摆手打断：「本座没兴趣跟你谈条件。」", "blocked": True}
            if has_merciful or random.random() < 0.5:
                state["in_combat"] = False
                state["enemies"] = []
                state["spotted_enemies"] = []
                return {"narrative": f"{boss_name}与你一番交谈，竟愿意放你通行：「今日给你个面子，走吧。」你们达成了和平默契。",
                        "in_combat": False, "negotiated": True}
            return {"narrative": f"{boss_name}权衡片刻，仍摇了摇头：「你的条件打动不了本座。」", "blocked": True}

        return None

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
        """移动到指定区域（坐标制：检查坐标相邻）"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}
        if state.get("in_combat"):
            return {"error": "in_combat", "message": "战斗中无法移动"}
        if state.get("in_dungeon"):
            return {"error": "in_dungeon", "message": "地下城中无法直接移动到区域"}
        if not self.world_map:
            return {"error": "no_map"}

        # 检查是否可以移动（坐标制）
        current = self.world_map.get_current_region()
        if not current:
            return {"error": "no_current_region"}

        target = self.world_map.get_region(target_region_id)
        if not target:
            return {"error": "region_not_found"}

        # 坐标相邻检查（曼哈顿距离=1）
        if not self.world_map.can_move_to(target_region_id):
            return {"error": "not_adjacent", "message": f"无法从{current.name}到达{target.name}（不相邻）"}

        # 移动
        self.world_map.current_region_id = target_region_id
        target.explored = True
        # 清理旧区域任务委托
        QuestSystem.cleanup_offers_by_region(state)

        # ── 地下城区域：触发 DungeonAgent ──
        if target.region_type == "dungeon":
            # 更新故事位置为地下城入口
            state["story"]["current_location"] = target.name
            dungeon_result = self._enter_dungeon_region(state, target)
            if dungeon_result.get("success"):
                result = {
                    "success": True,
                    "region_name": target.name,
                    "description": target.description,
                    "danger_level": target.danger_level,
                    "region_type": "dungeon",
                    "is_dungeon": True,
                    "dungeon": dungeon_result.get("dungeon_display"),
                }
                # 任务进度：到达地下城触发
                try:
                    QuestSystem.record_progress(state, "visit_location",
                                                 location=target.name,
                                                 narrative=target.description)
                except Exception:
                    pass
                adjacent = self.world_map.get_adjacent_regions()
                result["adjacent"] = [{"id": r.region_id, "name": r.name, "explored": r.explored} for r in adjacent]
                self._log_action("enter_dungeon", {
                    "dungeon_name": dungeon_result.get("dungeon_display", {}).get("dungeon_name", target.name),
                })
                self._save()
                return result

        # 更新故事位置
        state["story"]["current_location"] = target.name
        state["story"]["scene_description"] = target.description

        # 任务进度：到达新区域触发
        try:
            QuestSystem.record_progress(state, "visit_location",
                                         location=target.name,
                                         narrative=target.description)
        except Exception:
            pass

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

    # ── 地下城探索 ──────────────────────────────────────

    def _sync_party_state(self, state: Dict, party_in_combat: list):
        """同步队友HP/MP到state（战斗后调用）"""
        state_members = state.get("party_members", [])
        for pm in party_in_combat:
            for sm in state_members:
                if sm.get("member_id") == pm.member_id:
                    sm["hp"] = pm.hp
                    sm["mp"] = pm.mp
                    sm["is_alive"] = pm.hp > 0
                    break

    def _ensure_dungeon_agent(self):
        """惰性初始化 DungeonAgent"""
        if self.dungeon_agent is None:
            self.dungeon_agent = DungeonAgent(self.llm)
        return self.dungeon_agent

    def _ensure_party_agent(self):
        """惰性初始化 PartyAgent"""
        if self.party_agent is None:
            self.party_agent = PartyAgent()
        return self.party_agent

    def _enter_dungeon_region(self, state: Dict, region) -> Dict:
        """进入地下城区域（触发 DungeonAgent）"""
        agent = self._ensure_dungeon_agent()
        char = state.get("character", {})
        char_level = char.get("level", 1)
        world_setting = state.get("world_setting", {})
        world_type = state.get("world_type", "fantasy")

        dungeon = agent.enter_dungeon(
            region_id=region.region_id,
            region_name=region.name,
            world_type=world_type,
            world_setting=world_setting,
            char_level=char_level,
        )
        self._current_dungeon = dungeon

        state["in_dungeon"] = True
        state["dungeon_id"] = dungeon.dungeon_id

        display = agent.get_dungeon_display(dungeon)
        return {"success": True, "dungeon_display": display}

    def move_to_dungeon_room(self, target_room_id: str) -> Dict:
        """在地下城内移动到相邻房间"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}
        if not state.get("in_dungeon"):
            return {"error": "not_in_dungeon"}
        if state.get("in_combat"):
            return {"error": "in_combat", "message": "战斗中无法移动"}

        agent = self._ensure_dungeon_agent()
        dungeon_id = state.get("dungeon_id")
        if not dungeon_id:
            return {"error": "no_dungeon_id"}

        dungeon = DungeonAgent.load_dungeon(dungeon_id)
        if not dungeon:
            return {"error": "dungeon_not_found"}

        self._current_dungeon = dungeon
        char = state.get("character", {})
        char_level = char.get("level", 1)
        world_setting = state.get("world_setting", {})

        result = agent.move_to_room(dungeon, target_room_id, char_level, world_setting)
        if result.get("success"):
            self._log_action("dungeon_move", {
                "room_name": result.get("room_name", ""),
                "is_boss": result.get("is_boss", False),
            })

            # 更新故事位置为当前房间名
            _room_name = result.get("room_name", "")
            if _room_name:
                state["story"]["current_location"] = _room_name
                # 任务进度：到达新房间触发
                try:
                    QuestSystem.record_progress(state, "visit_location",
                                                 location=_room_name)
                except Exception:
                    pass

            # 房间有敌人 → 触发战斗
            if result.get("has_enemies"):
                room = dungeon.get_current_room()
                if room:
                    enemies = self._generate_dungeon_enemies(state, room, char_level)
                    state["enemies"] = enemies
                    state["in_combat"] = True
                    result["enemies"] = [{"name": e.get("name", "?"), "level": e.get("level", 1)} for e in enemies]
                    result["in_combat"] = True
            else:
                result["in_combat"] = False

            # 房间有陷阱 → 触发伤害
            room = dungeon.get_current_room()
            if room and room.hazards:
                for hazard in room.hazards:
                    if not hazard.get("triggered"):
                        self._trigger_dungeon_hazard(state, hazard)
                        hazard["triggered"] = True
                        result["hazard_triggered"] = hazard
                        agent.save_dungeon(dungeon)

            self._save()
            return result
        return result

    def _generate_dungeon_enemies(self, state: Dict, room, char_level: int) -> list:
        """根据房间配置生成敌人"""
        world_setting = state.get("world_setting", {})
        enemies = []
        for cfg in room.enemies:
            enemy_level = cfg.get("level", char_level)
            enemy_type = cfg.get("type", "normal")
            enemy = CombatSystem.generate_enemy(enemy_level, world_setting, enemy_type)
            enemy["name"] = cfg.get("name", enemy.get("name", "敌人"))
            enemies.append(enemy)
        return enemies

    def _trigger_dungeon_hazard(self, state: Dict, hazard: Dict):
        """触发地下城陷阱"""
        damage = hazard.get("damage", 5)
        char = state.get("character", {})
        user_char = state.get("user_character", {})
        if char.get("hp", 0) > 0:
            char["hp"] = max(0, char["hp"] - damage)
        if user_char and user_char.get("hp", 0) > 0:
            user_char["hp"] = max(0, user_char["hp"] - damage)
        # 队友也受伤
        for pm in state.get("party_members", []):
            if pm.get("is_alive", True) and pm.get("hp", 0) > 0:
                pm["hp"] = max(0, pm["hp"] - damage)
                if pm["hp"] <= 0:
                    pm["is_alive"] = False
        self._log_action("dungeon_hazard", {
            "hazard_name": hazard.get("name", "陷阱"),
            "damage": damage,
        })

    def clear_dungeon_room(self) -> Dict:
        """清除当前房间敌人后调用"""
        state = self._load()
        if not state.get("in_dungeon"):
            return {"error": "not_in_dungeon"}

        agent = self._ensure_dungeon_agent()
        dungeon_id = state.get("dungeon_id")
        dungeon = DungeonAgent.load_dungeon(dungeon_id) if dungeon_id else None
        if not dungeon:
            return {"error": "dungeon_not_found"}

        room_id = dungeon.current_room_id
        if room_id:
            agent.clear_room_enemies(dungeon, room_id)
            self._current_dungeon = dungeon

            # 发放战利品
            room = dungeon.get_room(room_id)
            loot_result = {"gold": 0, "items": []}
            if room and room.loot:
                for item in room.loot:
                    if item.get("type") == "gold":
                        gold = item.get("amount", 0)
                        char = state.get("character", {})
                        char["gold"] = char.get("gold", 0) + gold
                        loot_result["gold"] += gold
                    elif item.get("type") == "equipment":
                        loot_result["items"].append(item.get("name", "装备"))
                    elif item.get("type") == "consumable":
                        loot_result["items"].append(item.get("name", "药水"))

            if dungeon.completed:
                state["in_dungeon"] = False
                state["dungeon_id"] = None
                self._log_action("dungeon_complete", {
                    "dungeon_name": dungeon.name,
                    "loot": loot_result,
                })
            else:
                self._log_action("dungeon_room_cleared", {
                    "room_name": room.name if room else "",
                    "loot": loot_result,
                })

            self._save()
            return {
                "success": True,
                "room_cleared": True,
                "dungeon_completed": dungeon.completed,
                "loot": loot_result,
                "dungeon_display": agent.get_dungeon_display(dungeon) if not dungeon.completed else None,
            }
        return {"error": "no_current_room"}

    def exit_dungeon(self) -> Dict:
        """退出地下城（返回区域地图）"""
        state = self._load()
        state["in_dungeon"] = False
        state["dungeon_id"] = None
        state["in_combat"] = False
        state["enemies"] = []
        self._current_dungeon = None
        self._save()
        return {"success": True, "message": "已退出地下城"}

    def get_dungeon_info(self) -> Dict:
        """获取当前地下城信息"""
        state = self._load()
        if not state or not state.get("in_dungeon"):
            return {"in_dungeon": False}

        agent = self._ensure_dungeon_agent()
        dungeon_id = state.get("dungeon_id")
        if not dungeon_id:
            return {"in_dungeon": False}

        dungeon = DungeonAgent.load_dungeon(dungeon_id)
        if not dungeon:
            return {"in_dungeon": False, "error": "dungeon_not_found"}

        self._current_dungeon = dungeon
        display = agent.get_dungeon_display(dungeon)
        display["in_combat"] = state.get("in_combat", False)
        if state.get("in_combat"):
            display["enemies"] = state.get("enemies", [])
        return {"in_dungeon": True, "dungeon": display}

    # ── 队友系统 ──────────────────────────────────────

    def get_recruit_options(self) -> Dict:
        """获取可招募的队友列表"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}

        char = state.get("character", {})
        char_level = char.get("level", 1)
        world_type = state.get("world_type", "fantasy")

        # 检查队伍是否已满
        current_members = state.get("party_members", [])
        if len(current_members) >= PartyAgent.MAX_PARTY_SIZE:
            return {"error": "party_full", "message": f"队伍已满（最多{PartyAgent.MAX_PARTY_SIZE}人）"}

        options = PartyAgent.generate_recruit_options(world_type, char_level, count=3)
        return {"options": options, "current_count": len(current_members),
                "max_count": PartyAgent.MAX_PARTY_SIZE}

    def recruit_member(self, member_dict: Dict) -> Dict:
        """招募一个队友"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}

        current_members = state.get("party_members", [])
        if len(current_members) >= PartyAgent.MAX_PARTY_SIZE:
            return {"error": "party_full", "message": f"队伍已满"}

        world_type = state.get("world_type", "fantasy")
        member = PartyAgent.recruit_member(member_dict, world_type)

        # 注入职业被动效果
        from simlife.backend.skill_system import SkillSystem
        member.passive_effects = SkillSystem.get_passive_effects(member.to_combat_entity(), world_type)

        current_members.append(member.to_dict())
        state["party_members"] = current_members

        self._log_action("recruit", {"name": member.name, "class": member.class_name})
        self._save()
        return {"success": True, "member": member.to_dict(),
                "party_members": current_members}

    def dismiss_member(self, member_id: str) -> Dict:
        """解散一个队友"""
        state = self._load()
        members = state.get("party_members", [])
        state["party_members"] = [m for m in members if m.get("member_id") != member_id]
        self._log_action("dismiss", {"member_id": member_id})
        self._save()
        return {"success": True, "party_members": state["party_members"]}

    def move_by_direction_api(self, direction: str) -> Dict:
        """方向移动API（供前端点击调用）：北/南/东/西，支持空白格子生成"""
        state = self._load()
        if not state or not state.get("is_alive"):
            return {"error": "game_not_active"}
        if state.get("in_combat"):
            return {"error": "in_combat", "message": "战斗中无法移动"}
        if state.get("in_dungeon"):
            return {"error": "in_dungeon", "message": "地下城中无法移动到区域"}
        if not self.world_map or not self.region_agent:
            return {"error": "no_map"}

        result = self.region_agent.move_by_direction(direction)
        if not result.get("moved"):
            return {"error": "move_failed", "message": result.get("reason", ""),
                    "available_directions": result.get("available_directions", [])}

        target = result["region"]
        old_name = result.get("old_region_name", "")
        state["story"]["current_location"] = target.name
        state["story"]["scene_description"] = target.description

        # 清理旧区域任务委托
        QuestSystem.cleanup_offers_by_region(state)

        # 任务进度
        try:
            QuestSystem.record_progress(state, "visit_location",
                                         location=target.name,
                                         narrative=target.description)
        except Exception:
            pass

        self._save()

        self._log_action("move", {
            "direction": direction,
            "from": old_name,
            "to": target.name,
            "coords": f"({target.x},{target.y})",
        })

        return {
            "success": True,
            "region_name": target.name,
            "description": target.description,
            "danger_level": target.danger_level,
            "region_type": target.region_type,
            "direction": direction,
            "from": old_name,
            "coords": f"({target.x},{target.y})",
        }

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

    def _resolve_intimidation(self, state: Dict, npc) -> Dict:
        """恫吓判定（确定性结算）：玩家威慑力 vs NPC 胆量。
        成功 → 恐惧暴涨，越高恐惧越可能跪地求饶/让路；失败 → 反被讥讽，关系再降。
        由 interact_npc 接口与自由行动两种入口共用。"""
        import random
        char = state.get("character", {}) or {}
        stats = char.get("stats", {}) or {}
        level = int(char.get("level", 1) or 1)
        strength = float(stats.get("strength", 5) or 5)
        intelligence = float(stats.get("intelligence", 5) or 5)
        agility = float(stats.get("agility", 5) or 5)
        luck = float(stats.get("luck", 5) or 5)

        # 玩家威慑力 = 等级*4 + 看家属性(力量/智力/敏捷取最高)*1.2 + 运气*0.5
        # 取最高：力量系(战士/剑客)靠蛮力，智力系(法师/魂修)靠威压，敏捷系(盗贼/弓箭手/刺客)靠"能无声取你性命"的威胁
        _best_stat = max(strength, intelligence, agility)
        threat = level * 4 + _best_stat * 1.2 + luck * 0.5

        # 威慑方式按看家属性区分（力量系逼近压制 / 智力系无形威压 / 敏捷系无声杀机）
        if strength >= intelligence and strength >= agility:
            _flavor = "你步步逼近，周身煞气逼人，沉重的压迫感扑面而来"
        elif intelligence >= strength and intelligence >= agility:
            _flavor = "你目光幽深冷冽，无形的威压如远古深渊般罩下"
        else:
            _flavor = "你无声无息地贴近，指尖寒光一闪，杀意已锁死他身上要害"

        # NPC 胆量（已有恐惧越大越易怂；胆大性格与硬派身份更坚韧）
        resolute_keys = ("沉稳", "坚定", "冷酷", "严肃", "严厉", "固执", "正义", "果断",
                         "冷漠", "睿智", "超然", "胆大", "正直", "硬气", "刚烈")
        timid_keys = ("胆小", "懦弱", "怯懦", "惊恐", "紧张", "猥琐", "圆滑", "市侩",
                      "畏缩", "心虚", "怕事", "怕死")
        resolve = npc.level * 2 + 30
        resolve -= npc.fear * 0.25
        if any(k in (npc.personality or "") for k in resolute_keys):
            resolve += 12
        if any(k in (npc.personality or "") for k in timid_keys):
            resolve -= 15
        if npc.role in ("守卫", "护卫", "领袖", "长老", "剑客", "将军", "镖师", "舰长",
                        "教官", "侠客", "隐世高手", "掌门"):
            resolve += 8

        roll = threat + random.uniform(0, 22)
        success = roll > resolve

        # 结算恐惧与关系
        fear_gain = 16 + random.randint(0, 18) if success else 5
        rel_change = -8 if success else -12
        npc.change_fear(fear_gain)
        npc.change_relationship(rel_change)
        new_fear = npc.fear

        # 结果行为（高恐惧 → 爽文出口：跪地求饶 / 让路 / 服软）
        if success:
            if new_fear >= 85:
                word = (f"{npc.name}「扑通」一声跪倒在地，浑身筛糠般发抖，连声磕头："
                        f"「大…大人饶命！小的什么都听您的！求您高抬贵手！」眼泪鼻涕糊了一脸。")
            elif new_fear >= 65:
                word = (f"{npc.name}脸色煞白，本能地往后缩，声音都抖了："
                        f"「别、别杀我…我这就让开，您要什么都可以商量…」") 
            elif new_fear >= 45:
                word = (f"{npc.name}瞳孔一缩，强装镇定却止不住发抖，声音发飘："
                        f"「你、你究竟想怎样…我劝你冷静点。」脚已经悄悄往后挪了一步。")
            else:
                word = f"{npc.name}被你一瞪，下意识退后半步，微微避开你的目光，不敢再吭声。"
        else:
            word = (f"{npc.name}先是一愣，随即冷笑一声，面不改色："
                    f"「就这点本事也想吓住我？省省吧。」反把你呛了个没趣。")

        return {"success": success, "npc_name": npc.name, "type": "intimidate",
                "fear": npc.fear, "fear_label": npc.get_fear_label(),
                "relationship": npc.relationship,
                "message": (f"{_flavor}。" + word) if success else word}

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

        # 敌对后果：关系为敌对/死敌时，拒绝对话/交易/求助，只可攻击或消除敌意
        if npc.relationship <= -50 and interaction_type in ("talk", "quest", "trade"):
            return {"success": False, "npc_name": npc.name, "type": interaction_type,
                    "message": f"{npc.name}冷冷盯着你，把手按在武器上：「少来套近乎，我不愿待见你。」",
                    "hostile": True, "relationship": npc.relationship}

        # 恫吓：确定性判定（威慑 vs 胆量），当面亮威，NPC 必然感知
        if interaction_type == "intimidate":
            result = self._resolve_intimidation(state, npc)
            self._save()
            # 记录交互日志
            if result.get("success"):
                self._log_action("npc_interact", {
                    "npc_name": npc_name, "interaction": "intimidate",
                    "message": result.get("message", ""),
                })
                self._save()
            return result

        result = self.npc_system.interact(npc.npc_id, interaction_type)
        self._save()

        # 记录NPC交互日志
        if result.get("success"):
            self._log_action("npc_interact", {
                "npc_name": npc_name,
                "interaction": interaction_type,
                "message": result.get("message", ""),
            })
            # 任务进度：与NPC交谈触发
            try:
                QuestSystem.record_progress(state, "talk_npc", npc_name=npc_name,
                                             action_text=f"和{npc_name}对话")
            except Exception:
                pass
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
