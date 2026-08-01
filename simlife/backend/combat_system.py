"""
战斗/判定系统 v2 — 纯数值系统，LLM 只负责叙事

核心升级（相较 v1）：
1. 防御手段拆分为互斥三选一：闪避 / 格挡 / 招架，各自不同资源消耗与后果
2. 硬直（stagger）作为攻防失败的结果状态，影响下回合判定
3. 架势值（stance）：格挡消耗架势，架势归零则被击破陷入硬直
4. 等级差直接修正命中/闪避概率，碾压区弱者闪避/招架强制归零
5. 受伤对属性的实时衰减（伤势影响判定，而不只是扣血）
6. 装备加成：武器/护甲/饰品的属性加成纳入计算
7. 兼容旧版 Dict 格式调用（自动转换）
"""
import random
from enum import Enum
from typing import Dict, Optional, List


# ============================================================
# 基础配置
# ============================================================

DAMAGE_VARIANCE = 0.15          # 伤害浮动 ±15%
CRIT_MULTIPLIER = 1.8
BASE_HIT_CHANCE = 0.90
MAX_DODGE_CHANCE = 0.35
BLOCK_DAMAGE_REDUCTION = 0.55   # 格挡成功减伤 55%
PARRY_WINDOW = 0.18             # 招架基础成功率（高风险高回报）
STAGGER_TURNS_ON_PARRY_FAIL = 2
STAGGER_TURNS_ON_BLOCK_BREAK = 1
LEVEL_DIFF_HIT_BONUS_PER_LEVEL = 0.025
LEVEL_DIFF_DODGE_PENALTY_PER_LEVEL = 0.03
LEVEL_DIFF_HARD_CAP = 8         # 等级差超过此值进入碾压区


class DefenseAction(str, Enum):
    DODGE = "dodge"
    BLOCK = "block"
    PARRY = "parry"
    NONE = "none"


# ============================================================
# 战斗实体（兼容 Dict 格式）
# ============================================================

class CombatEntity:
    """战斗中的角色/敌人状态，带动态属性和硬直"""

    def __init__(self, name: str, level: int, base_stats: Dict[str, int],
                 hp: int, max_hp: int, equipment: List[Dict] = None,
                 mp: int = 0, max_mp: int = 0, skills: List[str] = None,
                 passive_effects: Dict = None):
        self.name = name
        self.level = level
        self.base_stats = dict(base_stats)
        self.hp = hp
        self.max_hp = max_hp
        self.mp = mp
        self.max_mp = max_mp
        self.equipment = equipment or []
        self.skills = skills or []
        self.passive_effects = passive_effects or {}  # 职业被动技能效果
        # 战斗中动态状态
        self.stagger_turns = 0
        self.stance_points = 100
        self.max_stance = 100
        self.injuries: Dict[str, float] = {}  # 部位: 属性衰减系数(0~1)

    @property
    def current_stats(self) -> Dict[str, float]:
        """实时属性 = 基础属性 * (1 - 累计伤势衰减)，上限衰减60%"""
        total_penalty = min(0.6, sum(self.injuries.values()))
        # 加上装备加成
        result = {}
        for k, v in self.base_stats.items():
            result[k] = v * (1 - total_penalty)
        # 装备属性加成
        for eq in self.equipment:
            if eq.get("stat_bonus"):
                for k, v in eq["stat_bonus"].items():
                    if k in result:
                        result[k] += v
        return result

    @property
    def is_staggered(self) -> bool:
        return self.stagger_turns > 0

    def apply_injury(self, part: str, severity: float):
        """受到部位伤害，同部位取较大值不叠加"""
        self.injuries[part] = max(self.injuries.get(part, 0.0), severity)

    def tick_stagger(self):
        if self.stagger_turns > 0:
            self.stagger_turns -= 1

    def regen_stance(self, amount: int = 15):
        self.stance_points = min(self.max_stance, self.stance_points + amount)

    def is_dead(self) -> bool:
        return self.hp <= 0

    def to_dict(self) -> Dict:
        """转换为旧版兼容 Dict 格式"""
        return {
            "name": self.name,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "mp": self.mp,
            "max_mp": self.max_mp,
            "stats": dict(self.base_stats),
            "equipment": self.equipment,
            "skills": self.skills,
            "stagger_turns": self.stagger_turns,
            "stance_points": self.stance_points,
            "injuries": dict(self.injuries),
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "CombatEntity":
        """从旧版 Dict 格式创建"""
        char = data.get("character", data)  # 兼容嵌套结构
        # 自动加载职业被动技能
        passive_effects = {}
        class_id = char.get("class_id", "")
        world_type = data.get("world_type", char.get("world_type", ""))
        if class_id and world_type:
            from simlife.backend.skill_system import SkillSystem
            passive_effects = SkillSystem.get_passive_effects(char, world_type)
        entity = cls(
            name=char.get("name", "未知"),
            level=char.get("level", 1),
            base_stats=char.get("stats", {"strength": 5, "agility": 5, "intelligence": 5, "vitality": 5, "luck": 5}),
            hp=char.get("hp", 50),
            max_hp=char.get("max_hp", 50),
            mp=char.get("mp", 0),
            max_mp=char.get("max_mp", 0),
            equipment=char.get("equipment", []),
            skills=char.get("skills", []),
            passive_effects=passive_effects,
        )
        # 应用被动HP/MP倍率
        if passive_effects.get("max_hp_mult"):
            bonus_hp = int(entity.max_hp * (passive_effects["max_hp_mult"] - 1))
            entity.max_hp += bonus_hp
            entity.hp += bonus_hp
        if passive_effects.get("max_mp_mult"):
            bonus_mp = int(entity.max_mp * (passive_effects["max_mp_mult"] - 1))
            entity.max_mp += bonus_mp
            entity.mp += bonus_mp
        entity.stagger_turns = data.get("stagger_turns", 0)
        entity.stance_points = data.get("stance_points", 100)
        entity.injuries = data.get("injuries", {})
        return entity


# ============================================================
# 核心判定
# ============================================================

class CombatSystem:
    """数值战斗系统 v2：防御三选一、硬直、等级压制、伤势、装备"""

    @staticmethod
    def _weapon_bonus_by_type(entity, damage_type: str = "physical") -> int:
        """按伤害类型获取武器加成"""
        equip_list = entity.get("equipment", []) if isinstance(entity, dict) else entity.equipment
        total = 0
        for e in equip_list:
            e_type = e.get("type") if isinstance(e, dict) else getattr(e, "type", "weapon")
            if e_type == "outfit":
                continue
            dt = e.get("damage_type", "physical") if isinstance(e, dict) else "physical"
            if dt == damage_type or (damage_type == "physical" and dt == "physical"):
                total += e.get("bonus", 0) if isinstance(e, dict) else 0
            elif dt == "defense":
                pass  # 盾牌不加攻击力
            elif dt == "magic" and damage_type == "magic":
                total += e.get("bonus", 0) if isinstance(e, dict) else 0
            elif dt == "ranged" and damage_type == "ranged":
                total += e.get("bonus", 0) if isinstance(e, dict) else 0
            elif damage_type == "physical" and dt in ("physical",):
                total += e.get("bonus", 0) if isinstance(e, dict) else 0
        return total

    @staticmethod
    def _armor_bonus(entity) -> int:
        if isinstance(entity, dict):
            outfit_bonus = sum(e.get("bonus", 0) for e in entity.get("equipment", []) if e.get("type") == "outfit")
            shield_bonus = sum(e.get("bonus", 0) for e in entity.get("equipment", [])
                               if e.get("type") == "weapon" and e.get("subtype") == "shield")
            return outfit_bonus + shield_bonus
        return sum(e.get("bonus", 0) for e in entity.equipment if e.get("type") == "outfit")

    @staticmethod
    def _get_weight_penalty(entity) -> Dict:
        """获取角色重量减益"""
        from simlife.backend.equipment_system import EquipmentSystem
        equip_list = entity.get("equipment", []) if isinstance(entity, dict) else []
        penalty = {"hit_chance": 0, "damage": 0, "dodge": 0}
        for e in equip_list:
            p = EquipmentSystem.check_weight_penalty(
                entity if isinstance(entity, dict) else {},
                e if isinstance(e, dict) else {}
            )
            if p.get("penalty"):
                for k, v in p["penalty_values"].items():
                    penalty[k] = penalty.get(k, 0) + v
        return penalty

    @staticmethod
    def _get_stats(entity) -> Dict:
        if isinstance(entity, CombatEntity):
            return entity.current_stats
        return entity.get("stats", {})

    @staticmethod
    def _get_passive(entity) -> Dict:
        """获取实体的职业被动效果"""
        if isinstance(entity, CombatEntity):
            return entity.passive_effects
        return entity.get("passive_effects", {})

    @staticmethod
    def _get_level(entity) -> int:
        if isinstance(entity, CombatEntity):
            return entity.level
        return entity.get("level", 1)

    @staticmethod
    def _get_name(entity) -> str:
        if isinstance(entity, CombatEntity):
            return entity.name
        return entity.get("name", "未知")

    @staticmethod
    def calc_attack_power(entity, attack_type: str = "physical") -> int:
        """
        计算攻击力
        attack_type: physical(近战物理) / ranged(远程物理) / magic(法术)
        """
        s = CombatSystem._get_stats(entity)
        bonus = CombatSystem._weapon_bonus_by_type(entity, attack_type)
        if attack_type == "magic":
            base = s.get("intelligence", 5) * 2
        elif attack_type == "ranged":
            base = s.get("agility", 5) * 2
        else:  # physical
            base = s.get("strength", 5) * 2
        raw = int(base + bonus)
        # 职业被动伤害加成
        passive = CombatSystem._get_passive(entity)
        if attack_type == "magic" and passive.get("magic_damage_mult"):
            raw = int(raw * passive["magic_damage_mult"])
        elif attack_type == "ranged" and passive.get("ranged_damage_mult"):
            raw = int(raw * passive["ranged_damage_mult"])
        elif attack_type == "physical" and passive.get("phys_damage_mult"):
            raw = int(raw * passive["phys_damage_mult"])
        return raw

    @staticmethod
    def calc_defense(entity) -> int:
        s = CombatSystem._get_stats(entity)
        return int(s.get("vitality", 5) * 1.5 + CombatSystem._armor_bonus(entity))

    @staticmethod
    def _level_diff_modifiers(attacker, defender) -> Dict[str, float]:
        diff = CombatSystem._get_level(attacker) - CombatSystem._get_level(defender)
        hit_bonus = diff * LEVEL_DIFF_HIT_BONUS_PER_LEVEL
        dodge_penalty = diff * LEVEL_DIFF_DODGE_PENALTY_PER_LEVEL
        crushing = abs(diff) >= LEVEL_DIFF_HARD_CAP
        return {"diff": diff, "hit_bonus": hit_bonus, "dodge_penalty": dodge_penalty, "crushing": crushing}

    @staticmethod
    def calc_hit_chance(attacker, defender) -> float:
        atk_s = CombatSystem._get_stats(attacker)
        def_s = CombatSystem._get_stats(defender)
        mods = CombatSystem._level_diff_modifiers(attacker, defender)
        if mods["crushing"] and mods["diff"] > 0:
            return 0.99
        if mods["crushing"] and mods["diff"] < 0:
            return 0.55
        agi_term = atk_s.get("agility", 5) / 300.0 - def_s.get("agility", 5) / 300.0
        return max(0.35, min(0.99, BASE_HIT_CHANCE + agi_term + mods["hit_bonus"]))

    @staticmethod
    def calc_dodge_chance(entity) -> float:
        s = CombatSystem._get_stats(entity)
        dodge = s.get("agility", 5) / 200.0
        passive = CombatSystem._get_passive(entity)
        dodge += passive.get("dodge_bonus", 0)
        return min(MAX_DODGE_CHANCE + passive.get("dodge_bonus", 0), dodge)

    @staticmethod
    def calc_crit_chance(entity) -> float:
        s = CombatSystem._get_stats(entity)
        crit = (s.get("agility", 5) + s.get("luck", 5)) / 200.0
        passive = CombatSystem._get_passive(entity)
        crit += passive.get("crit_rate_bonus", 0)
        return min(0.75, crit)

    @staticmethod
    def roll_damage(base_damage: int) -> int:
        variance = base_damage * DAMAGE_VARIANCE
        return max(1, int(base_damage + random.uniform(-variance, variance)))

    # ------------------------------------------------------------
    # 防御方三选一：闪避 / 格挡 / 招架 / 不设防
    # ------------------------------------------------------------

    @staticmethod
    def resolve_defense(attacker, defender, action: DefenseAction,
                        incoming_damage: int) -> Dict:
        """防御判定，返回最终伤害和状态变化"""
        # 检查硬直
        if isinstance(defender, CombatEntity) and defender.is_staggered:
            action = DefenseAction.NONE

        mods = CombatSystem._level_diff_modifiers(attacker, defender)
        def_name = CombatSystem._get_name(defender)
        atk_name = CombatSystem._get_name(attacker)

        if action == DefenseAction.DODGE:
            if mods["crushing"] and mods["diff"] > 0:
                dodge_chance = 0.0
            else:
                base_dodge = CombatSystem.calc_dodge_chance(defender)
                dodge_chance = max(0.0, base_dodge - mods["dodge_penalty"])
            if random.random() < dodge_chance:
                return {"action": "dodge", "success": True, "damage_taken": 0,
                        "stagger_applied": 0, "stance_cost": 0,
                        "description": f"{def_name}闪避了攻击"}
            else:
                return {"action": "dodge", "success": False, "damage_taken": incoming_damage,
                        "stagger_applied": 0, "stance_cost": 0,
                        "description": f"{def_name}闪避判断失误，攻击命中"}

        elif action == DefenseAction.BLOCK:
            if isinstance(defender, CombatEntity):
                stance_cost = max(10, int(incoming_damage * 0.4))
                if defender.stance_points < stance_cost:
                    defender.stance_points = 0
                    defender.stagger_turns = max(defender.stagger_turns, STAGGER_TURNS_ON_BLOCK_BREAK)
                    return {"action": "block", "success": False, "damage_taken": incoming_damage,
                            "stagger_applied": STAGGER_TURNS_ON_BLOCK_BREAK, "stance_cost": 0,
                            "description": f"{def_name}架势被击破，陷入硬直"}
                defender.stance_points -= stance_cost
                reduced = int(incoming_damage * (1 - BLOCK_DAMAGE_REDUCTION))
                return {"action": "block", "success": True, "damage_taken": reduced,
                        "stagger_applied": 0, "stance_cost": stance_cost,
                        "description": f"{def_name}格挡，减免伤害"}
            else:
                # Dict 格式：简化格挡，减伤40%
                reduced = int(incoming_damage * 0.6)
                return {"action": "block", "success": True, "damage_taken": reduced,
                        "stagger_applied": 0, "stance_cost": 0,
                        "description": f"{def_name}格挡，减免部分伤害"}

        elif action == DefenseAction.PARRY:
            if mods["crushing"] and mods["diff"] > 0:
                parry_chance = 0.0
            else:
                def_s = CombatSystem._get_stats(defender)
                parry_chance = max(0.0, PARRY_WINDOW - mods["dodge_penalty"] * 0.5
                                    + def_s.get("agility", 5) / 500.0)
            if random.random() < parry_chance:
                # 招架成功：完全免伤 + 反给攻击者施加硬直
                if isinstance(attacker, CombatEntity):
                    attacker.stagger_turns = max(attacker.stagger_turns, STAGGER_TURNS_ON_PARRY_FAIL)
                return {"action": "parry", "success": True, "damage_taken": 0,
                        "stagger_applied": 0, "attacker_staggered": STAGGER_TURNS_ON_PARRY_FAIL,
                        "stance_cost": 0,
                        "description": f"{def_name}精准招架，{atk_name}门户大开"}
            else:
                # 招架失败：代价最重，长硬直 + 额外伤害
                if isinstance(defender, CombatEntity):
                    defender.stagger_turns = max(defender.stagger_turns, STAGGER_TURNS_ON_PARRY_FAIL)
                penalty_damage = int(incoming_damage * 1.2)
                return {"action": "parry", "success": False, "damage_taken": penalty_damage,
                        "stagger_applied": STAGGER_TURNS_ON_PARRY_FAIL, "stance_cost": 0,
                        "description": f"{def_name}招架失败，破绽被抓住，伤害加重"}

        else:  # NONE / 硬直中
            return {"action": "none", "success": False, "damage_taken": incoming_damage,
                    "stagger_applied": 0, "stance_cost": 0,
                    "description": f"{def_name}毫无防备，直接承受攻击"}

    # ------------------------------------------------------------
    # 完整攻击流程
    # ------------------------------------------------------------

    @staticmethod
    def attack(
        attacker,
        defender,
        defense_action: DefenseAction = DefenseAction.NONE,
        attack_type: str = "physical",
        skill_multiplier: float = 1.0,
        target_part: Optional[str] = None,
        part_injury_severity: float = 0.0,
    ) -> Dict:
        """
        执行一次完整攻击：命中判定 → 防御三选一 → 伤害结算 → 部位伤势
        attack_type: physical(近战物理) / ranged(远程物理) / magic(法术)
        """
        # 重量减益
        atk_penalty = CombatSystem._get_weight_penalty(attacker)
        hit_chance = CombatSystem.calc_hit_chance(attacker, defender) + atk_penalty.get("hit_chance", 0)
        atk_name = CombatSystem._get_name(attacker)
        def_name = CombatSystem._get_name(defender)

        if random.random() > hit_chance:
            return {"hit": False, "crit": False, "dodged": False, "damage": 0,
                    "defense_result": None, "description": f"{atk_name}的攻击落空"}

        base_atk = int(CombatSystem.calc_attack_power(attacker, attack_type) * skill_multiplier)
        # 重量减益：伤害降低
        dmg_penalty = atk_penalty.get("damage", 0)
        base_atk = max(1, int(base_atk * (1 + dmg_penalty)))

        defense_stat = CombatSystem.calc_defense(defender)
        raw_damage = max(1, base_atk - defense_stat)
        damage = CombatSystem.roll_damage(raw_damage)

        # 暴击
        is_crit = random.random() < CombatSystem.calc_crit_chance(attacker)
        if is_crit:
            damage = int(damage * CRIT_MULTIPLIER)

        # 防御判定
        defense_result = CombatSystem.resolve_defense(attacker, defender, defense_action, damage)
        final_damage = defense_result["damage_taken"]

        # 防御方职业被动减伤
        def_passive = CombatSystem._get_passive(defender)
        if def_passive.get("damage_reduce"):
            final_damage = int(final_damage * (1 - def_passive["damage_reduce"]))
        if attack_type == "physical" and def_passive.get("phys_damage_reduce"):
            final_damage = int(final_damage * (1 - def_passive["phys_damage_reduce"]))
        elif attack_type == "magic" and def_passive.get("magic_damage_reduce"):
            final_damage = int(final_damage * (1 - def_passive["magic_damage_reduce"]))
        final_damage = max(0, final_damage)

        # 扣血（兼容两种格式）
        if isinstance(defender, CombatEntity):
            defender.hp = max(0, defender.hp - final_damage)
            if target_part and part_injury_severity > 0 and final_damage > 0:
                defender.apply_injury(target_part, part_injury_severity)
        elif isinstance(defender, dict):
            defender["hp"] = max(0, defender.get("hp", 0) - final_damage)

        # 加攻击者重量减益到闪避
        if isinstance(attacker, dict):
            def_penalty = CombatSystem._get_weight_penalty(attacker)
            res_dodge_penalty = def_penalty.get("dodge", 0)
        else:
            res_dodge_penalty = 0

        # 构建描述
        crit_str = "暴击！" if is_crit else ""
        def_desc = defense_result["description"]
        if final_damage > 0:
            damage_str = f"造成{final_damage}点伤害"
        else:
            damage_str = "未造成伤害"

        return {
            "hit": True,
            "crit": is_crit,
            "dodged": defense_result.get("action") == "dodge" and defense_result.get("success"),
            "damage": final_damage,
            "raw_damage": damage,
            "defense_result": defense_result,
            "description": f"{crit_str}{def_desc}，{damage_str}",
        }

    @staticmethod
    def end_of_turn(entity):
        """每回合结束：硬直倒计时、架势回复"""
        if isinstance(entity, CombatEntity):
            entity.tick_stagger()
            if not entity.is_staggered:
                entity.regen_stance()

    @staticmethod
    def check_death(character) -> bool:
        if isinstance(character, CombatEntity):
            return character.is_dead()
        return character.get("hp", 0) <= 0

    # ------------------------------------------------------------
    # 敌人生成
    # ------------------------------------------------------------

    @staticmethod
    def generate_enemy(level: int, world_setting: Dict = None, enemy_type: str = "normal") -> Dict:
        """根据角色等级和世界观生成敌人（返回兼容Dict格式）"""
        level_scale = 1 + (level - 1) * 0.3
        type_multiplier = {"normal": 1.0, "elite": 1.5, "boss": 2.5}.get(enemy_type, 1.0)
        scale = level_scale * type_multiplier

        base_hp = int(50 * scale)
        base_stats = {
            "strength": max(5, int(8 * scale)),
            "agility": max(5, int(7 * scale)),
            "intelligence": max(5, int(6 * scale)),
            "vitality": max(5, int(8 * scale)),
            "luck": max(1, int(5 * scale)),
        }

        # 敌人名称从世界观中取
        monster_types = []
        if world_setting:
            dangers = world_setting.get("dangers", {})
            monster_types = dangers.get("monster_types", [])

        if monster_types:
            mt = random.choice(monster_types[:5])
            if isinstance(mt, dict):
                enemy_name = mt.get("name", "未知敌人")
            else:
                enemy_name = str(mt)
        else:
            enemy_name = random.choice(["哥布林", "野狼", "盗贼", "魔物", "骷髅兵"])

        if enemy_type == "elite":
            enemy_name = f"精英·{enemy_name}"
        elif enemy_type == "boss":
            enemy_name = f"首领·{enemy_name}"

        # 敌人可能有装备（精英/BOSS）
        enemy_equipment = []
        if enemy_type == "elite" and random.random() < 0.4:
            enemy_equipment.append({"name": "粗制武器", "type": "weapon", "bonus": 3})
        elif enemy_type == "boss":
            enemy_equipment.append({"name": "强力武器", "type": "weapon", "bonus": 6})
            if random.random() < 0.5:
                enemy_equipment.append({"name": "坚硬护甲", "type": "outfit", "bonus": 4})

        return {
            "name": enemy_name,
            "level": max(1, level + random.randint(-1, 1)),
            "hp": base_hp,
            "max_hp": base_hp,
            "mp": int(20 * scale),
            "max_mp": int(20 * scale),
            "stats": base_stats,
            "equipment": enemy_equipment,
            "skills": [],
            "exp_reward": int(30 * scale),
            "gold_reward": int(15 * scale),
            "type": enemy_type,
            "stagger_turns": 0,
            "stance_points": 100,
            "injuries": {},
            "pursuit": _enemy_pursuit(enemy_name, enemy_type),
        }

def _enemy_pursuit(name: str, etype: str) -> bool:
    """判断敌人是否会追击逃跑的玩家"""
    no_pursuit_kw = ("史莱姆", "软泥", "元素", "植物", "蘑菇", "孢子", "水晶", "藤蔓")
    for kw in no_pursuit_kw:
        if kw in name:
            return False
    # 按类型
    if etype == "boss":
        return True
    if etype == "elite":
        return random.random() < 0.75
    # 普通怪 40% 追击
    return random.random() < 0.4

    @staticmethod
    def calculate_exp_reward(enemy, player_level: int) -> int:
        if isinstance(enemy, CombatEntity):
            base_exp = int(30 * (1 + (enemy.level - 1) * 0.3))
            diff = player_level - enemy.level
        else:
            base_exp = enemy.get("exp_reward", 30)
            diff = player_level - enemy.get("level", 1)
        if diff > 5:
            return max(1, base_exp // 4)
        elif diff > 3:
            return max(1, base_exp // 2)
        return base_exp

    # ------------------------------------------------------------
    # 旧版兼容接口（attack_simple）
    # ------------------------------------------------------------

    @staticmethod
    def attack_simple(attacker: Dict, defender: Dict, attack_type: str = "physical",
                      skill_multiplier: float = 1.0) -> Dict:
        """旧版简单攻击接口（无防御三选一，自动随机选择防御方式）"""
        # 敌人随机选择防御方式
        defense_choices = [DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.NONE]
        # 智力高的敌人更倾向招架
        def_stats = defender.get("stats", {})
        if def_stats.get("intelligence", 5) > 12:
            defense_choices.append(DefenseAction.PARRY)
        defense = random.choice(defense_choices)

        return CombatSystem.attack(attacker, defender, defense_action=defense,
                                   attack_type=attack_type, skill_multiplier=skill_multiplier)


# ============================================================
# 战术系统 — 地形、阵型、伏击、合击
# ============================================================

class TacticalSystem:
    """
    战术判定系统：通过战术选择获得战斗优势，可以挑战更强敌人

    战术类型：
    - ambush  伏击：先手攻击，敌人首回合无防御
    - flank   侧翼：增加命中率和暴击率
    - defensive 防御阵型：减少受到的伤害，但攻击降低
    - focus   集中攻击：多个角色攻击同一目标，伤害加成
    - terrain 利用地形：根据地形获得不同优势（高地/掩体/狭窄通道）
    """

    TERRAIN_TYPES = {
        "high_ground":   {"name": "高地",   "hit_bonus": 0.10, "dodge_bonus": 0.05, "damage_bonus": 0.10},
        "narrow_pass":   {"name": "狭窄通道", "hit_bonus": 0.05, "dodge_bonus": -0.05, "damage_bonus": 0.15, "enemy_dodge_penalty": 0.10},
        "forest":        {"name": "密林",   "hit_bonus": -0.05, "dodge_bonus": 0.15, "damage_bonus": 0.0},
        "ruins":         {"name": "废墟",   "hit_bonus": 0.05, "dodge_bonus": 0.10, "damage_bonus": 0.05},
        "open_field":    {"name": "开阔地", "hit_bonus": 0.0, "dodge_bonus": -0.10, "damage_bonus": 0.0},
        "water":         {"name": "水域",   "hit_bonus": -0.10, "dodge_bonus": -0.05, "damage_bonus": -0.10},
        "cave":          {"name": "洞穴",   "hit_bonus": 0.05, "dodge_bonus": 0.0, "damage_bonus": 0.10, "enemy_dodge_penalty": 0.05},
        "boss_lair":     {"name": "BOSS巢穴", "hit_bonus": -0.05, "dodge_bonus": -0.05, "damage_bonus": -0.05},
    }

    @staticmethod
    def apply_tactic(tactic: str, attacker, defender, terrain: str = "") -> Dict:
        """
        应用战术修正，返回修正后的攻击结果和战术描述
        tactic: ambush / flank / defensive / focus / terrain
        """
        result = {"tactic": tactic, "modifiers": {}, "description": ""}

        # 地形修正
        terrain_mods = TacticalSystem.TERRAIN_TYPES.get(terrain, {})

        if tactic == "ambush":
            # 伏击：首回合敌人无防御，必定命中，伤害+30%
            result["modifiers"] = {
                "hit_bonus": 0.30,
                "damage_multiplier": 1.3,
                "enemy_no_defense": True,
            }
            result["description"] = "伏击成功！敌人毫无防备，攻击伤害大幅提升！"

        elif tactic == "flank":
            # 侧翼：命中+15%，暴击+20%
            result["modifiers"] = {
                "hit_bonus": 0.15 + terrain_mods.get("hit_bonus", 0),
                "crit_bonus": 0.20,
            }
            result["description"] = "侧翼包抄！攻击更精准，暴击概率提升！"

        elif tactic == "defensive":
            # 防御阵型：受伤-30%，但攻击-20%
            result["modifiers"] = {
                "damage_reduction": 0.30,
                "attack_penalty": 0.20,
                "dodge_bonus": 0.10 + terrain_mods.get("dodge_bonus", 0),
            }
            result["description"] = "防御阵型！减少受到的伤害，但攻击力降低。"

        elif tactic == "focus":
            # 集中攻击：对同一目标伤害+25%（多人合击时+50%）
            result["modifiers"] = {
                "damage_multiplier": 1.25,
                "hit_bonus": 0.05,
            }
            result["description"] = "集中火力！攻击伤害提升！"

        elif tactic == "terrain":
            # 利用地形：根据地形类型获得不同加成
            if terrain_mods:
                result["modifiers"] = {
                    "hit_bonus": terrain_mods.get("hit_bonus", 0),
                    "dodge_bonus": terrain_mods.get("dodge_bonus", 0),
                    "damage_bonus": terrain_mods.get("damage_bonus", 0),
                    "enemy_dodge_penalty": terrain_mods.get("enemy_dodge_penalty", 0),
                }
                terrain_name = terrain_mods.get("name", "未知地形")
                result["description"] = f"利用{terrain_name}地形优势！"
            else:
                result["modifiers"] = {"hit_bonus": 0.05}
                result["description"] = "利用周围环境获得少许优势。"

        return result

    @staticmethod
    def apply_tactic_modifiers(attack_result: Dict, tactic_result: Dict) -> Dict:
        """将战术修正应用到攻击结果上"""
        mods = tactic_result.get("modifiers", {})
        if not mods:
            return attack_result

        # 命中修正
        if mods.get("hit_bonus") and not attack_result.get("hit"):
            # 重新判定命中
            hit_bonus = mods["hit_bonus"]
            if random.random() < hit_bonus:
                attack_result["hit"] = True
                attack_result["description"] = attack_result.get("description", "") + "（战术命中）"

        # 伤害修正
        if attack_result.get("hit") and attack_result.get("damage", 0) > 0:
            if mods.get("damage_multiplier"):
                mult = mods["damage_multiplier"]
                attack_result["damage"] = int(attack_result["damage"] * mult)
            if mods.get("damage_bonus"):
                attack_result["damage"] = int(attack_result["damage"] * (1 + mods["damage_bonus"]))
            if mods.get("attack_penalty"):
                attack_result["damage"] = int(attack_result["damage"] * (1 - mods["attack_penalty"]))

        # 暴击修正
        if mods.get("crit_bonus") and attack_result.get("hit") and not attack_result.get("crit"):
            if random.random() < mods["crit_bonus"]:
                attack_result["crit"] = True
                attack_result["damage"] = int(attack_result["damage"] * CRIT_MULTIPLIER)

        # 敌人无防御（伏击）
        if mods.get("enemy_no_defense") and attack_result.get("defense_result"):
            attack_result["defense_result"]["damage_taken"] = attack_result.get("damage", 0)

        # 闪避修正
        if mods.get("dodge_bonus"):
            attack_result["dodge_bonus"] = mods["dodge_bonus"]

        # 伤害减免
        if mods.get("damage_reduction") and attack_result.get("damage", 0) > 0:
            reduction = mods["damage_reduction"]
            attack_result["damage"] = int(attack_result["damage"] * (1 - reduction))

        # 战术描述
        if tactic_result.get("description"):
            attack_result["tactic_description"] = tactic_result["description"]

        return attack_result

    @staticmethod
    def get_available_tactics(dm_state: dict) -> List[Dict]:
        """根据当前状态获取可用战术列表"""
        tactics = []
        in_combat = dm_state.get("in_combat", False)
        enemies = dm_state.get("enemies", [])
        alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]

        if not in_combat or not alive_enemies:
            return tactics

        # 基础战术
        tactics.append({
            "id": "ambush",
            "name": "伏击",
            "icon": "🗡️",
            "description": "先手攻击，敌人首回合无防御，伤害+30%",
            "condition": "战斗刚开始时可用",
            "available": True,
        })

        tactics.append({
            "id": "flank",
            "name": "侧翼包抄",
            "icon": "↗️",
            "description": "命中+15%，暴击+20%",
            "condition": "始终可用",
            "available": True,
        })

        tactics.append({
            "id": "defensive",
            "name": "防御阵型",
            "icon": "🛡️",
            "description": "受伤-30%，闪避+10%，但攻击-20%",
            "condition": "始终可用",
            "available": True,
        })

        # 多敌人时可用集中攻击
        if len(alive_enemies) >= 2:
            tactics.append({
                "id": "focus",
                "name": "集中攻击",
                "icon": "🎯",
                "description": "对同一目标伤害+25%",
                "condition": "多个敌人时可用",
                "available": True,
            })

        # 地形战术
        current_region = dm_state.get("world_map", {}).get("current_region_id", "")
        if current_region:
            # 根据区域类型推断地形
            terrain_map = {
                "town": "ruins", "wild": "forest", "dungeon": "cave",
                "boss_lair": "boss_lair", "secret": "cave"
            }
            # 从world_map中获取区域信息
            regions = dm_state.get("world_map", {}).get("regions", {})
            region = regions.get(current_region, {})
            region_type = region.get("region_type", "wild")
            terrain = terrain_map.get(region_type, "open_field")

            if terrain in TacticalSystem.TERRAIN_TYPES:
                terrain_info = TacticalSystem.TERRAIN_TYPES[terrain]
                tactics.append({
                    "id": "terrain",
                    "name": f"利用{terrain_info['name']}",
                    "icon": "🏔️",
                    "description": f"利用{terrain_info['name']}地形优势",
                    "condition": f"当前地形：{terrain_info['name']}",
                    "available": True,
                    "terrain": terrain,
                })

        return tactics
