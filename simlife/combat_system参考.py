"""
战斗/判定系统 v2 — 纯数值系统，LLM 只负责叙事
设计目标：跨世界观通用。世界观只提供"皮肤"（敌人名/技能文本/部位描述），
判定逻辑（命中/防御三选一/硬直/等级压制）完全独立于具体设定。

核心改动（相较 v1）：
1. 角色状态从"静态 stats 字典"改为 CombatEntity，带 current_stats（受伤/硬直修正后的实时值）
2. 防御手段拆分为互斥三选一：闪避 / 格挡 / 招架，各自不同资源消耗与后果
3. 硬直（stagger）作为攻防失败的结果状态，影响下回合判定
4. 等级差直接修正命中/闪避概率，而不仅是数值线性缩放
5. 受伤对属性的实时衰减（伤势影响判定，而不只是扣血）
"""
import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List


# ============================================================
# 基础配置（可按世界观调整数值，但结构不变）
# ============================================================

DAMAGE_VARIANCE = 0.15          # 伤害浮动 ±15%
CRIT_MULTIPLIER = 1.8
BASE_HIT_CHANCE = 0.90
MAX_DODGE_CHANCE = 0.35
BLOCK_DAMAGE_REDUCTION = 0.55   # 格挡成功减伤 55%
PARRY_WINDOW = 0.18             # 招架基础成功率（高风险，需要架势/技巧加成）
STAGGER_TURNS_ON_PARRY_FAIL = 2
STAGGER_TURNS_ON_BLOCK_BREAK = 1
LEVEL_DIFF_HIT_BONUS_PER_LEVEL = 0.025   # 每级差修正命中率
LEVEL_DIFF_DODGE_PENALTY_PER_LEVEL = 0.03  # 每级差修正闪避率（被压制方）
LEVEL_DIFF_HARD_CAP = 8         # 等级差超过此值，弱者闪避/招架强制归零（碾压区）


class DefenseAction(str, Enum):
    DODGE = "dodge"
    BLOCK = "block"
    PARRY = "parry"
    NONE = "none"  # 硬直中/不设防


# ============================================================
# 角色状态
# ============================================================

@dataclass
class CombatEntity:
    name: str
    level: int
    base_stats: Dict[str, int]        # 基础属性，不因战斗中受伤而改变
    hp: int
    max_hp: int
    equipment: List[Dict] = field(default_factory=list)
    # 战斗中动态状态
    stagger_turns: int = 0            # 剩余硬直回合数
    stance_points: int = 100          # 架势值，格挡消耗，归零则被击破
    max_stance: int = 100
    injuries: Dict[str, float] = field(default_factory=dict)  # 部位: 属性衰减系数(0~1)

    @property
    def current_stats(self) -> Dict[str, float]:
        """实时属性 = 基础属性 * (1 - 累计伤势衰减)，伤势影响判定而不只是扣血"""
        total_penalty = min(0.6, sum(self.injuries.values()))  # 衰减上限60%，避免属性归零打不了
        return {k: v * (1 - total_penalty) for k, v in self.base_stats.items()}

    @property
    def is_staggered(self) -> bool:
        return self.stagger_turns > 0

    def apply_injury(self, part: str, severity: float):
        """受到部位伤害，累积属性衰减。severity 0~1，同部位取较大值不叠加"""
        self.injuries[part] = max(self.injuries.get(part, 0.0), severity)

    def tick_stagger(self):
        if self.stagger_turns > 0:
            self.stagger_turns -= 1

    def regen_stance(self, amount: int = 15):
        self.stance_points = min(self.max_stance, self.stance_points + amount)

    def is_dead(self) -> bool:
        return self.hp <= 0


# ============================================================
# 核心判定
# ============================================================

class CombatSystem:

    @staticmethod
    def _weapon_bonus(entity: CombatEntity) -> int:
        return sum(e.get("bonus", 0) for e in entity.equipment if e.get("type") == "weapon")

    @staticmethod
    def _armor_bonus(entity: CombatEntity) -> int:
        return sum(e.get("bonus", 0) for e in entity.equipment if e.get("type") == "armor")

    @staticmethod
    def calc_attack_power(entity: CombatEntity, is_magic: bool = False) -> int:
        s = entity.current_stats
        bonus = CombatSystem._weapon_bonus(entity)
        base = s.get("intelligence", 5) * 2 if is_magic else s.get("strength", 5) * 2
        return int(base + bonus)

    @staticmethod
    def calc_defense(entity: CombatEntity) -> int:
        s = entity.current_stats
        return int(s.get("vitality", 5) * 1.5 + CombatSystem._armor_bonus(entity))

    @staticmethod
    def _level_diff_modifiers(attacker: CombatEntity, defender: CombatEntity) -> Dict[str, float]:
        """
        等级差修正：攻击者等级 - 防御者等级。
        正值 = 攻击者是"高等级打低等级"，命中提升、防御方闪避/招架被压制。
        超过 LEVEL_DIFF_HARD_CAP 视为碾压区，直接锁定判定结果。
        """
        diff = attacker.level - defender.level
        hit_bonus = diff * LEVEL_DIFF_HIT_BONUS_PER_LEVEL
        dodge_penalty = diff * LEVEL_DIFF_DODGE_PENALTY_PER_LEVEL  # diff>0 时是惩罚防御方
        crushing = abs(diff) >= LEVEL_DIFF_HARD_CAP
        return {"diff": diff, "hit_bonus": hit_bonus, "dodge_penalty": dodge_penalty, "crushing": crushing}

    @staticmethod
    def calc_hit_chance(attacker: CombatEntity, defender: CombatEntity) -> float:
        atk_s, def_s = attacker.current_stats, defender.current_stats
        mods = CombatSystem._level_diff_modifiers(attacker, defender)
        if mods["crushing"] and mods["diff"] > 0:
            return 0.99  # 碾压区：高等级方必中
        if mods["crushing"] and mods["diff"] < 0:
            return 0.55  # 以下犯上：命中率大幅下降但不至于打不到
        base = BASE_HIT_CHANCE
        agi_term = atk_s.get("agility", 5) / 300.0 - def_s.get("agility", 5) / 300.0
        return max(0.35, min(0.99, base + agi_term + mods["hit_bonus"]))

    @staticmethod
    def calc_crit_chance(entity: CombatEntity) -> float:
        s = entity.current_stats
        return (s.get("agility", 5) + s.get("luck", 5)) / 200.0

    @staticmethod
    def roll_damage(base_damage: int) -> int:
        variance = base_damage * DAMAGE_VARIANCE
        return max(1, int(base_damage + random.uniform(-variance, variance)))

    # ------------------------------------------------------------
    # 防御方选择：闪避 / 格挡 / 招架 / 不设防（硬直中自动 NONE）
    # ------------------------------------------------------------

    @staticmethod
    def resolve_defense(
        attacker: CombatEntity,
        defender: CombatEntity,
        action: DefenseAction,
        incoming_damage: int,
    ) -> Dict:
        """
        返回防御结果，包含：最终是否命中/减伤多少/是否触发硬直/资源消耗
        """
        if defender.is_staggered:
            action = DefenseAction.NONE  # 硬直中无法主动防御

        mods = CombatSystem._level_diff_modifiers(attacker, defender)

        if action == DefenseAction.DODGE:
            if mods["crushing"] and mods["diff"] > 0:
                dodge_chance = 0.0  # 碾压区：弱者闪不掉
            else:
                base_dodge = min(MAX_DODGE_CHANCE, defender.current_stats.get("agility", 5) / 200.0)
                dodge_chance = max(0.0, base_dodge - mods["dodge_penalty"])
            if random.random() < dodge_chance:
                return {"action": "dodge", "success": True, "damage_taken": 0,
                        "stagger_applied": 0, "stance_cost": 0,
                        "description": f"{defender.name}闪避了攻击"}
            else:
                # 闪避失败：判断失误，进入短暂失衡但不算硬直击破
                return {"action": "dodge", "success": False, "damage_taken": incoming_damage,
                        "stagger_applied": 0, "stance_cost": 0,
                        "description": f"{defender.name}闪避判断失误，攻击命中"}

        elif action == DefenseAction.BLOCK:
            stance_cost = max(10, int(incoming_damage * 0.4))
            if defender.stance_points < stance_cost:
                # 架势不足，格挡被击破 -> 硬直 + 承受全额伤害
                defender.stance_points = 0
                defender.stagger_turns = max(defender.stagger_turns, STAGGER_TURNS_ON_BLOCK_BREAK)
                return {"action": "block", "success": False, "damage_taken": incoming_damage,
                        "stagger_applied": STAGGER_TURNS_ON_BLOCK_BREAK, "stance_cost": defender.stance_points,
                        "description": f"{defender.name}架势被击破，陷入硬直"}
            defender.stance_points -= stance_cost
            reduced = int(incoming_damage * (1 - BLOCK_DAMAGE_REDUCTION))
            return {"action": "block", "success": True, "damage_taken": reduced,
                    "stagger_applied": 0, "stance_cost": stance_cost,
                    "description": f"{defender.name}格挡，减免伤害"}

        elif action == DefenseAction.PARRY:
            # 招架：高风险高回报，等级差直接影响成功率，碾压区弱者不可能招架
            if mods["crushing"] and mods["diff"] > 0:
                parry_chance = 0.0
            else:
                parry_chance = max(0.0, PARRY_WINDOW - mods["dodge_penalty"] * 0.5
                                    + defender.current_stats.get("agility", 5) / 500.0)
            if random.random() < parry_chance:
                # 招架成功：完全免伤 + 反给攻击者施加硬直
                attacker.stagger_turns = max(attacker.stagger_turns, STAGGER_TURNS_ON_PARRY_FAIL)
                return {"action": "parry", "success": True, "damage_taken": 0,
                        "stagger_applied": 0, "attacker_staggered": STAGGER_TURNS_ON_PARRY_FAIL,
                        "stance_cost": 0,
                        "description": f"{defender.name}精准招架，{attacker.name}门户大开"}
            else:
                # 招架失败：代价最重，自己陷入长硬直并承受全额+额外伤害
                defender.stagger_turns = max(defender.stagger_turns, STAGGER_TURNS_ON_PARRY_FAIL)
                penalty_damage = int(incoming_damage * 1.2)
                return {"action": "parry", "success": False, "damage_taken": penalty_damage,
                        "stagger_applied": STAGGER_TURNS_ON_PARRY_FAIL, "stance_cost": 0,
                        "description": f"{defender.name}招架失败，破绽被抓住，伤害加重"}

        else:  # NONE / 硬直中
            return {"action": "none", "success": False, "damage_taken": incoming_damage,
                    "stagger_applied": 0, "stance_cost": 0,
                    "description": f"{defender.name}毫无防备，直接承受攻击"}

    # ------------------------------------------------------------
    # 完整攻击流程
    # ------------------------------------------------------------

    @staticmethod
    def attack(
        attacker: CombatEntity,
        defender: CombatEntity,
        defense_action: DefenseAction = DefenseAction.NONE,
        is_magic: bool = False,
        skill_multiplier: float = 1.0,
        target_part: Optional[str] = None,
        part_injury_severity: float = 0.0,
    ) -> Dict:
        """
        执行一次完整攻击：命中判定 -> 防御方三选一处理 -> 伤害结算 -> 部位伤势(可选)
        target_part: 例如 "右臂"/"腿部"，配合 part_injury_severity 造成属性衰减（跨世界观通用，文本自定）
        """
        hit_chance = CombatSystem.calc_hit_chance(attacker, defender)
        if random.random() > hit_chance:
            return {"hit": False, "crit": False, "damage": 0, "defense_result": None,
                    "description": f"{attacker.name}的攻击落空"}

        base_atk = int(CombatSystem.calc_attack_power(attacker, is_magic) * skill_multiplier)
        defense_stat = CombatSystem.calc_defense(defender)
        raw_damage = max(1, base_atk - defense_stat)
        damage = CombatSystem.roll_damage(raw_damage)

        is_crit = random.random() < CombatSystem.calc_crit_chance(attacker)
        if is_crit:
            damage = int(damage * CRIT_MULTIPLIER)

        defense_result = CombatSystem.resolve_defense(attacker, defender, defense_action, damage)
        final_damage = defense_result["damage_taken"]
        defender.hp = max(0, defender.hp - final_damage)

        if target_part and part_injury_severity > 0 and final_damage > 0:
            defender.apply_injury(target_part, part_injury_severity)

        return {
            "hit": True,
            "crit": is_crit,
            "damage": final_damage,
            "raw_damage": damage,
            "defense_result": defense_result,
            "attacker_staggered": defense_result.get("attacker_staggered", 0),
            "description": f"{'暴击！' if is_crit else ''}{defense_result['description']}，"
                            f"{'造成' + str(final_damage) + '点伤害' if final_damage > 0 else '未造成伤害'}",
        }

    @staticmethod
    def end_of_turn(entity: CombatEntity):
        """每回合结束调用：结算硬直倒计时、架势自然回复"""
        entity.tick_stagger()
        if not entity.is_staggered:
            entity.regen_stance()

    # ------------------------------------------------------------
    # 敌人生成（世界观外挂：只需传入 monster pool，逻辑通用）
    # ------------------------------------------------------------

    @staticmethod
    def generate_enemy(level: int, world_setting: Optional[Dict] = None, enemy_type: str = "normal") -> CombatEntity:
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

        monster_types = []
        if world_setting:
            monster_types = world_setting.get("dangers", {}).get("monster_types", [])

        if monster_types:
            mt = random.choice(monster_types[:5])
            enemy_name = mt.get("name", "未知敌人") if isinstance(mt, dict) else str(mt)
        else:
            enemy_name = random.choice(["哥布林", "野狼", "盗贼", "魔物", "骷髅兵"])

        if enemy_type == "elite":
            enemy_name = f"精英·{enemy_name}"
        elif enemy_type == "boss":
            enemy_name = f"首领·{enemy_name}"

        return CombatEntity(
            name=enemy_name,
            level=max(1, level + random.randint(-1, 1)),
            base_stats=base_stats,
            hp=base_hp,
            max_hp=base_hp,
        )

    @staticmethod
    def calculate_exp_reward(enemy: CombatEntity, player_level: int) -> int:
        base_exp = int(30 * (1 + (enemy.level - 1) * 0.3))
        diff = player_level - enemy.level
        if diff > 5:
            return max(1, base_exp // 4)
        elif diff > 3:
            return max(1, base_exp // 2)
        return base_exp


# ============================================================
# 简单自测（跑一场碾压 vs 一场势均力敌，检查行为是否符合预期）
# ============================================================
if __name__ == "__main__":
    hero = CombatEntity("勇者", level=10, base_stats={"strength": 20, "agility": 18, "vitality": 15, "luck": 10, "intelligence": 8}, hp=200, max_hp=200)
    weak_goblin = CombatSystem.generate_enemy(level=1, enemy_type="normal")

    print("=== 碾压测试：Lv10 打 Lv1 ===")
    for i in range(3):
        r = CombatSystem.attack(hero, weak_goblin, defense_action=DefenseAction.DODGE)
        print(r["description"])
        CombatSystem.end_of_turn(weak_goblin)
        if weak_goblin.is_dead():
            print(f"{weak_goblin.name} 死亡")
            break

    print("\n=== 势均力敌测试：Lv10 vs Lv10，含格挡/招架 ===")
    rival = CombatEntity("对手", level=10, base_stats={"strength": 18, "agility": 16, "vitality": 14, "luck": 8, "intelligence": 10}, hp=180, max_hp=180)
    for i in range(5):
        action = random.choice([DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.PARRY])
        r = CombatSystem.attack(hero, rival, defense_action=action)
        print(f"[回合{i+1}] {r['description']} (HP剩余 {rival.hp}, 硬直{rival.stagger_turns}, 架势{rival.stance_points})")
        CombatSystem.end_of_turn(rival)
        CombatSystem.end_of_turn(hero)
        if rival.is_dead():
            break
