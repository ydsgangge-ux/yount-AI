"""
技能系统 v2 — 高度开放的技能框架

设计：
- 技能数据库：每个职业8-10个技能，含伤害/治疗/增益/控制/特殊效果
- 效果系统：damage / heal / dot / hot / stun / freeze / slow / buff_stat / debuff_stat / shield / cleansing
- 状态效果管理：持续回合、每回合tick、叠加规则
- 技能学习：自由选择，不限制职业，但技能总数限制为10个
- 觉醒技能：每个角色预留3个由用户自定义创造的觉醒技能槽位
- 战斗集成：SkillSystem.resolve_skill() 执行技能所有效果
"""
import random
import math
from typing import Dict, List, Optional, Tuple, Set
from enum import Enum


# ============================================================
# 全局常量
# ============================================================

MAX_SKILLS = 10  # 单个角色最多可学习的技能数量
MAX_LEVEL = 60   # 角色满级
AWAKENING_SLOTS = 3  # 每个角色预留的觉醒技能槽位数量
# 觉醒技能槽位等级要求：槽位0需40级，槽位1需50级，槽位2需60级
AWAKENING_LEVEL_REQ = [40, 50, 60]


# 觉醒技能模板（空槽位用）
AWAKENING_SKILL_TEMPLATE = {
    "id": "",        # 自动生成：awakening_0, awakening_1, awakening_2
    "name": "空",     # 用户自定义
    "type": "physical",  # 用户选择
    "mp_cost": 10,
    "effects": [{"type": "damage", "target": "single_enemy", "value": 1.0}],
    "req_level": 1,
    "description": "尚未觉醒的技能",
}


# ============================================================
# 效果类型枚举
# ============================================================

class EffectType(str, Enum):
    DAMAGE = "damage"           # 直接伤害
    HEAL = "heal"               # 治疗
    DOT = "dot"                 # 持续伤害（每回合）
    HOT = "hot"                 # 持续治疗（每回合）
    STUN = "stun"               # 眩晕（跳过回合）
    FREEZE = "freeze"           # 冻结（跳过回合+破防）
    SLOW = "slow"               # 减速（降低先手值）
    BUFF_STAT = "buff_stat"     # 属性增益
    DEBUFF_STAT = "debuff_stat" # 属性减益
    SHIELD = "shield"           # 护盾（吸收伤害）
    CLEANSING = "cleansing"     # 净化（移除debuff）
    TAUNT = "taunt"             # 嘲讽（强制攻击自己）
    TELEPORT = "teleport"       # 瞬移（闪避提升）
    SUMMON = "summon"           # 召唤（临时召唤物）
    COUNTER = "counter"         # 反击（受击时反击）
    LIFE_STEAL = "life_steal"   # 吸血（造成伤害回血）
    EXECUTE = "execute"         # 斩杀（对低HP敌人增伤）


# 效果目标类型
class EffectTarget(str, Enum):
    SELF = "self"
    SINGLE_ENEMY = "single_enemy"
    ALL_ENEMIES = "all_enemies"
    SINGLE_ALLY = "single_ally"
    ALL_ALLIES = "all_allies"


# ============================================================
# 技能效果定义
# ============================================================

class SkillEffect:
    """单个技能效果"""

    def __init__(self, effect_type: str, target: str = "single_enemy",
                 value: float = 1.0, duration: int = 0, chance: float = 1.0,
                 stat: str = None, description: str = ""):
        self.type = effect_type          # EffectType
        self.target = target             # EffectTarget
        self.value = value               # 基础数值（倍率/数值）
        self.duration = duration         # 持续回合数（0=即时）
        self.chance = chance             # 触发概率（0~1）
        self.stat = stat                 # 影响的属性（buff_stat/debuff_stat用）
        self.description = description   # 效果描述

    def to_dict(self) -> Dict:
        return {
            "type": self.type,
            "target": self.target,
            "value": self.value,
            "duration": self.duration,
            "chance": self.chance,
            "stat": self.stat,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "SkillEffect":
        return cls(
            effect_type=d.get("type", "damage"),
            target=d.get("target", "single_enemy"),
            value=d.get("value", 1.0),
            duration=d.get("duration", 0),
            chance=d.get("chance", 1.0),
            stat=d.get("stat"),
            description=d.get("description", ""),
        )


# ============================================================
# 技能定义
# ============================================================

class Skill:
    """完整技能定义"""

    def __init__(self, skill_id: str, name: str, skill_type: str,
                 mp_cost: int, effects: List[Dict],
                 req_level: int = 1, req_class: str = None,
                 req_stats: Dict = None,
                 cooldown: int = 0,
                 description: str = ""):
        self.id = skill_id
        self.name = name
        self.type = skill_type          # physical / magic / heal / buff / utility
        self.mp_cost = mp_cost
        self.effects = [SkillEffect.from_dict(e) for e in effects]
        self.req_level = req_level
        self.req_class = req_class
        self.req_stats = req_stats or {}
        self.cooldown = cooldown
        self.description = description

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "mp_cost": self.mp_cost,
            "effects": [e.to_dict() for e in self.effects],
            "req_level": self.req_level,
            "req_class": self.req_class,
            "req_stats": dict(self.req_stats),
            "cooldown": self.cooldown,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Skill":
        return cls(
            skill_id=d.get("id", ""),
            name=d.get("name", ""),
            skill_type=d.get("type", "physical"),
            mp_cost=d.get("mp_cost", 0),
            effects=d.get("effects", []),
            req_level=d.get("req_level", 1),
            req_class=d.get("req_class"),
            req_stats=d.get("req_stats", {}),
            cooldown=d.get("cooldown", 0),
            description=d.get("description", ""),
        )


# ============================================================
# 技能数据库
# ============================================================

def _s(damage_type: str, mult: float = 1.0, target: str = "single_enemy") -> List[Dict]:
    """快捷创建单伤害效果"""
    return [{"type": "damage", "target": target, "value": mult}]


def _h(mult: float = 0.5, target: str = "self") -> List[Dict]:
    """快捷创建治疗效果"""
    return [{"type": "heal", "target": target, "value": mult}]


def _b(stat: str, value: int = 5, duration: int = 3, target: str = "self") -> List[Dict]:
    """快捷创建属性增益效果"""
    return [{"type": "buff_stat", "target": target, "value": value, "duration": duration, "stat": stat}]


def _d(stat: str, value: int = -3, duration: int = 3, target: str = "single_enemy") -> List[Dict]:
    """快捷创建属性减益效果"""
    return [{"type": "debuff_stat", "target": target, "value": value, "duration": duration, "stat": stat}]


# 技能数据库：按世界类型 → 职业 → [技能列表]
SKILL_DATABASE = {
    # ═══════════════════════════════════════════════════
    # 奇幻魔法
    # ═══════════════════════════════════════════════════
    "fantasy": {
        "warrior": [
            # 1级初始技能
            {"id": "war_heavy_strike", "name": "重击", "type": "physical", "mp_cost": 5,
             "effects": _s("physical", 1.2), "req_level": 1, "description": "凝聚力量的一击"},
            {"id": "war_block", "name": "格挡架势", "type": "buff", "mp_cost": 8,
             "effects": [{"type": "buff_stat", "target": "self", "value": 10, "duration": 2, "stat": "vitality"}],
             "req_level": 1, "description": "举起武器进入防御姿态"},
            # 3级
            {"id": "war_whirlwind", "name": "旋风斩", "type": "physical", "mp_cost": 15,
             "effects": _s("physical", 1.4, "all_enemies"), "req_level": 3,
             "req_stats": {"strength": 10}, "cooldown": 1,
             "description": "旋转身体攻击所有敌人"},
            # 5级
            {"id": "war_battle_cry", "name": "战吼", "type": "buff", "mp_cost": 12,
             "effects": _b("strength", 5, 3) + _b("vitality", 5, 3),
             "req_level": 5, "cooldown": 2, "description": "发出战吼激励自己和队友"},
            # 7级
            {"id": "war_shield_bash", "name": "盾击", "type": "physical", "mp_cost": 12,
             "effects": _s("physical", 1.3) + [{"type": "stun", "target": "single_enemy", "value": 1, "chance": 0.6}],
             "req_level": 7, "req_stats": {"strength": 14}, "cooldown": 2,
             "description": "用盾牌猛击敌人，有概率眩晕"},
            # 9级
            {"id": "war_bleed", "name": "撕裂", "type": "physical", "mp_cost": 18,
             "effects": _s("physical", 1.2) + [{"type": "dot", "target": "single_enemy", "value": 0.3, "duration": 3}],
             "req_level": 9, "description": "撕裂敌人伤口，造成持续流血"},
            # 10级
            {"id": "war_berserker", "name": "狂战士", "type": "buff", "mp_cost": 25,
             "effects": _b("strength", 10, 4) + _b("agility", -3, 4),
             "req_level": 10, "cooldown": 4, "description": "进入狂怒状态，攻击力大幅提升但敏捷降低"},
            # 12级
            {"id": "war_execute", "name": "斩杀", "type": "physical", "mp_cost": 20,
             "effects": [{"type": "execute", "target": "single_enemy", "value": 2.5, "chance": 1.0}],
             "req_level": 12, "req_stats": {"strength": 18}, "cooldown": 2,
             "description": "对重伤敌人的致命一击"},
            # 15级
            {"id": "war_taunt", "name": "嘲讽", "type": "utility", "mp_cost": 10,
             "effects": [{"type": "taunt", "target": "all_enemies", "value": 1, "duration": 2}],
             "req_level": 15, "cooldown": 3, "description": "嘲讽所有敌人，强制他们攻击自己"},
            # 20级
            {"id": "war_earthquake", "name": "地震", "type": "physical", "mp_cost": 35,
             "effects": _s("physical", 1.8, "all_enemies") + [{"type": "slow", "target": "all_enemies", "value": -5, "duration": 2, "chance": 0.7}],
             "req_level": 20, "req_stats": {"strength": 22}, "cooldown": 3,
             "description": "猛击地面造成范围伤害并减速敌人"},
        ],
        "mage": [
            # 1级
            {"id": "mag_fireball", "name": "火球术", "type": "magic", "mp_cost": 8,
             "effects": [{"type": "damage", "target": "single_enemy", "value": 1.3}],
             "req_level": 1, "description": "发射火球攻击敌人"},
            {"id": "mag_magic_shield", "name": "魔法护盾", "type": "buff", "mp_cost": 10,
             "effects": [{"type": "shield", "target": "self", "value": 30, "duration": 3}],
             "req_level": 1, "description": "召唤魔法护盾吸收伤害"},
            # 3级
            {"id": "mag_frostbolt", "name": "冰霜箭", "type": "magic", "mp_cost": 12,
             "effects": _s("magic", 1.2) + [{"type": "slow", "target": "single_enemy", "value": -3, "duration": 2, "chance": 0.8}],
             "req_level": 3, "req_stats": {"intelligence": 10}, "description": "冰霜箭击中敌人并减速"},
            # 5级
            {"id": "mag_chain_lightning", "name": "闪电链", "type": "magic", "mp_cost": 20,
             "effects": _s("magic", 1.5, "all_enemies"),
             "req_level": 5, "req_stats": {"intelligence": 14}, "cooldown": 1,
             "description": "闪电在敌人之间跳跃，攻击所有敌人"},
            # 7级
            {"id": "mag_freeze", "name": "冻结", "type": "magic", "mp_cost": 18,
             "effects": _s("magic", 1.0) + [{"type": "freeze", "target": "single_enemy", "value": 1, "chance": 0.5}],
             "req_level": 7, "cooldown": 3, "description": "冰霜之力冻结敌人，使其无法行动"},
            # 9级
            {"id": "mag_firewall", "name": "火墙", "type": "magic", "mp_cost": 22,
             "effects": _s("magic", 1.2, "all_enemies") + [{"type": "dot", "target": "all_enemies", "value": 0.2, "duration": 2}],
             "req_level": 9, "cooldown": 2, "description": "召唤火墙，范围伤害并灼烧敌人"},
            # 10级
            {"id": "mag_teleport", "name": "瞬移", "type": "utility", "mp_cost": 15,
             "effects": [{"type": "teleport", "target": "self", "value": 0.6, "duration": 1}],
             "req_level": 10, "cooldown": 3, "description": "瞬间移动，大幅提升闪避"},
            # 12级
            {"id": "mag_mana_burn", "name": "魔力燃烧", "type": "magic", "mp_cost": 25,
             "effects": _s("magic", 1.5) + [{"type": "debuff_stat", "target": "single_enemy", "value": -5, "duration": 3, "stat": "intelligence"}],
             "req_level": 12, "req_stats": {"intelligence": 20}, "cooldown": 2,
             "description": "燃烧敌人的魔力，造成伤害并降低智力"},
            # 15级
            {"id": "mag_blizzard", "name": "暴风雪", "type": "magic", "mp_cost": 30,
             "effects": _s("magic", 1.6, "all_enemies") + [{"type": "freeze", "target": "all_enemies", "value": 1, "chance": 0.3}],
             "req_level": 15, "req_stats": {"intelligence": 24}, "cooldown": 3,
             "description": "召唤暴风雪，范围伤害并概率冻结"},
            # 20级
            {"id": "mag_meteor", "name": "陨石术", "type": "magic", "mp_cost": 45,
             "effects": _s("magic", 2.5, "all_enemies"),
             "req_level": 20, "req_stats": {"intelligence": 28}, "cooldown": 4,
             "description": "召唤陨石，毁灭性的范围攻击"},
        ],
        "rogue": [
            # 1级
            {"id": "rog_backstab", "name": "偷袭", "type": "physical", "mp_cost": 6,
             "effects": _s("physical", 1.5), "req_level": 1, "description": "从暗处偷袭，造成额外伤害"},
            {"id": "rog_dodge", "name": "闪避姿态", "type": "buff", "mp_cost": 8,
             "effects": [{"type": "buff_stat", "target": "self", "value": 8, "duration": 2, "stat": "agility"}],
             "req_level": 1, "description": "进入闪避姿态，大幅提升敏捷"},
            # 3级
            {"id": "rog_poison_blade", "name": "毒刃", "type": "physical", "mp_cost": 10,
             "effects": _s("physical", 1.1) + [{"type": "dot", "target": "single_enemy", "value": 0.3, "duration": 3}],
             "req_level": 3, "description": "淬毒攻击，造成持续中毒伤害"},
            # 5级
            {"id": "rog_shadow_clone", "name": "影分身", "type": "utility", "mp_cost": 20,
             "effects": [{"type": "buff_stat", "target": "self", "value": 10, "duration": 3, "stat": "agility"},
                         {"type": "buff_stat", "target": "self", "value": -3, "duration": 3, "stat": "strength"}],
             "req_level": 5, "cooldown": 3, "description": "制造影分身，敏捷大幅提升"},
            # 7级
            {"id": "rog_assassinate", "name": "暗杀", "type": "physical", "mp_cost": 25,
             "effects": [{"type": "execute", "target": "single_enemy", "value": 2.8}],
             "req_level": 7, "req_stats": {"agility": 16}, "cooldown": 2,
             "description": "对低血量敌人的致命刺杀"},
            # 9级
            {"id": "rog_smoke_bomb", "name": "烟雾弹", "type": "utility", "mp_cost": 15,
             "effects": [{"type": "debuff_stat", "target": "all_enemies", "value": -5, "duration": 2, "stat": "agility"},
                         {"type": "buff_stat", "target": "self", "value": 5, "duration": 2, "stat": "agility"}],
             "req_level": 9, "cooldown": 3, "description": "投掷烟雾弹，降低敌人命中，提升自己闪避"},
            # 10级
            {"id": "rog_invisible", "name": "无形", "type": "utility", "mp_cost": 15,
             "effects": [{"type": "counter", "target": "self", "value": 2.0, "duration": 2}],
             "req_level": 10, "cooldown": 4, "description": "进入潜行状态，下一次攻击伤害翻倍"},
            # 12级
            {"id": "rog_bleed", "name": "割喉", "type": "physical", "mp_cost": 18,
             "effects": _s("physical", 1.4) + [{"type": "dot", "target": "single_enemy", "value": 0.5, "duration": 2}],
             "req_level": 12, "req_stats": {"agility": 20}, "cooldown": 1,
             "description": "割喉攻击，造成大量流血"},
            # 15级
            {"id": "rog_blade_flurry", "name": "剑刃乱舞", "type": "physical", "mp_cost": 25,
             "effects": _s("physical", 1.5, "all_enemies") + [{"type": "life_steal", "target": "self", "value": 0.2}],
             "req_level": 15, "req_stats": {"agility": 24}, "cooldown": 3,
             "description": "快速挥舞武器攻击所有敌人并吸血"},
            # 20级
            {"id": "rog_death_mark", "name": "死亡标记", "type": "utility", "mp_cost": 20,
             "effects": [{"type": "debuff_stat", "target": "single_enemy", "value": -8, "duration": 5, "stat": "vitality"},
                         {"type": "debuff_stat", "target": "single_enemy", "value": -5, "duration": 5, "stat": "agility"}],
             "req_level": 20, "req_stats": {"agility": 28}, "cooldown": 3,
             "description": "标记敌人，大幅降低其体质和敏捷"},
        ],
        "archer": [
            # 1级
            {"id": "arc_precise_shot", "name": "精准射击", "type": "physical", "mp_cost": 6,
             "effects": _s("ranged", 1.3), "req_level": 1, "description": "远程精准射击"},
            {"id": "arc_quick_move", "name": "快速移动", "type": "buff", "mp_cost": 8,
             "effects": [{"type": "buff_stat", "target": "self", "value": 5, "duration": 2, "stat": "agility"}],
             "req_level": 1, "description": "快速移动，提升敏捷"},
            # 3级
            {"id": "arc_rapid_fire", "name": "连射", "type": "physical", "mp_cost": 12,
             "effects": _s("ranged", 1.3) + _s("ranged", 0.6),
             "req_level": 3, "description": "快速连射两次"},
            # 5级
            {"id": "arc_pierce_shot", "name": "穿透箭", "type": "physical", "mp_cost": 18,
             "effects": _s("ranged", 1.5, "all_enemies"),
             "req_level": 5, "req_stats": {"agility": 14}, "cooldown": 1,
             "description": "一箭穿透所有敌人"},
            # 7级
            {"id": "arc_rain_of_arrows", "name": "箭雨", "type": "physical", "mp_cost": 25,
             "effects": _s("ranged", 1.6, "all_enemies") + [{"type": "slow", "target": "all_enemies", "value": -3, "duration": 2, "chance": 0.5}],
             "req_level": 7, "req_stats": {"agility": 16}, "cooldown": 2,
             "description": "箭雨覆盖所有敌人并减速"},
            # 9级
            {"id": "arc_snipe", "name": "狙击", "type": "physical", "mp_cost": 20,
             "effects": [{"type": "execute", "target": "single_enemy", "value": 2.2}],
             "req_level": 9, "req_stats": {"agility": 18}, "cooldown": 2,
             "description": "远程狙击，对低血量敌人造成巨额伤害"},
            # 10级
            {"id": "arc_eagle_eye", "name": "鹰眼", "type": "buff", "mp_cost": 15,
             "effects": [{"type": "buff_stat", "target": "self", "value": 8, "duration": 3, "stat": "agility"},
                         {"type": "buff_stat", "target": "self", "value": 5, "duration": 3, "stat": "luck"}],
             "req_level": 10, "cooldown": 3, "description": "鹰眼聚焦，大幅提升敏捷和运气"},
            # 12级
            {"id": "arc_poison_arrow", "name": "毒箭", "type": "physical", "mp_cost": 15,
             "effects": _s("ranged", 1.1) + [{"type": "dot", "target": "single_enemy", "value": 0.4, "duration": 3}],
             "req_level": 12, "description": "淬毒箭矢，持续中毒"},
            # 15级
            {"id": "arc_explosive_shot", "name": "爆裂箭", "type": "physical", "mp_cost": 28,
             "effects": _s("ranged", 1.8, "all_enemies"),
             "req_level": 15, "req_stats": {"agility": 24}, "cooldown": 3,
             "description": "爆炸箭矢，范围高伤害"},
            # 20级
            {"id": "arc_hunters_mark", "name": "猎人之印", "type": "utility", "mp_cost": 15,
             "effects": [{"type": "debuff_stat", "target": "single_enemy", "value": -8, "duration": 4, "stat": "agility"},
                         {"type": "debuff_stat", "target": "single_enemy", "value": -5, "duration": 4, "stat": "vitality"}],
             "req_level": 20, "cooldown": 2, "description": "标记猎物，降低其敏捷和体质"},
        ],
        "cleric": [
            # 1级
            {"id": "cle_heal", "name": "治愈术", "type": "heal", "mp_cost": 10,
             "effects": _h(0.5, "single_ally"), "req_level": 1, "description": "治疗目标"},
            {"id": "cle_bless", "name": "祝福", "type": "buff", "mp_cost": 10,
             "effects": _b("luck", 5, 3) + _b("vitality", 3, 3),
             "req_level": 1, "description": "祝福目标，提升运气和体质"},
            # 3级
            {"id": "cle_holy_light", "name": "圣光术", "type": "magic", "mp_cost": 15,
             "effects": _s("magic", 1.3) + _h(0.3, "self"),
             "req_level": 3, "req_stats": {"intelligence": 10}, "description": "圣光攻击敌人并治疗自己"},
            # 5级
            {"id": "cle_group_heal", "name": "群体治愈", "type": "heal", "mp_cost": 25,
             "effects": _h(0.4, "all_allies"),
             "req_level": 5, "req_stats": {"intelligence": 14}, "cooldown": 2,
             "description": "治愈所有队友"},
            # 7级
            {"id": "cle_cleanse", "name": "净化", "type": "utility", "mp_cost": 12,
             "effects": [{"type": "cleansing", "target": "single_ally", "value": 1}],
             "req_level": 7, "description": "移除目标所有负面效果"},
            # 9级
            {"id": "cle_regen", "name": "再生", "type": "heal", "mp_cost": 18,
             "effects": [{"type": "hot", "target": "single_ally", "value": 0.2, "duration": 3}],
             "req_level": 9, "cooldown": 2, "description": "持续治疗目标，每回合恢复"},
            # 10级
            {"id": "cle_holy_judgment", "name": "神圣审判", "type": "magic", "mp_cost": 35,
             "effects": _s("magic", 2.0) + [{"type": "stun", "target": "single_enemy", "value": 1, "chance": 0.4}],
             "req_level": 10, "req_stats": {"intelligence": 20}, "cooldown": 3,
             "description": "神圣审判，高伤害并概率眩晕"},
            # 12级
            {"id": "cle_protect", "name": "守护之盾", "type": "buff", "mp_cost": 20,
             "effects": [{"type": "shield", "target": "single_ally", "value": 50, "duration": 3}],
             "req_level": 12, "cooldown": 3, "description": "为目标施加护盾"},
            # 15级（替换为新的技能）
            {"id": "cle_sanctuary", "name": "圣佑", "type": "utility", "mp_cost": 30,
             "effects": [{"type": "shield", "target": "all_allies", "value": 40, "duration": 2}],
             "req_level": 15, "req_stats": {"intelligence": 24}, "cooldown": 3,
             "description": "为所有队友施加神圣护盾，持续2回合"},
            # 20级
            {"id": "cle_divine", "name": "神圣化身", "type": "buff", "mp_cost": 40,
             "effects": _b("intelligence", 10, 4) + _b("vitality", 10, 4),
             "req_level": 20, "req_stats": {"intelligence": 28}, "cooldown": 4,
             "description": "化身神圣存在，智力与体质大幅提升"},
        ],
    },
    # 其他世界类型保留基本的技能（后续可扩展）
    "xianxia": {},
    "wuxia": {},
    "post_apocalyptic": {},
    "modern_power": {},
    "scifi": {},
}

# 通用技能（所有职业都能学）
COMMON_SKILLS = [
    {"id": "common_rest", "name": "冥想", "type": "heal", "mp_cost": 0,
     "effects": [{"type": "heal", "target": "self", "value": 0.2},
                 {"type": "heal", "target": "self", "value": 0.3, "stat": "mp"}],
     "req_level": 1, "description": "冥想恢复HP和MP，战斗中也可使用（消耗一回合）"},
    {"id": "common_guard", "name": "防御", "type": "buff", "mp_cost": 0,
     "effects": [{"type": "buff_stat", "target": "self", "value": 10, "duration": 1, "stat": "vitality"}],
     "req_level": 1, "description": "标准防御姿态，提升体质一回合"},
    {"id": "common_charge", "name": "冲锋", "type": "physical", "mp_cost": 8,
     "effects": _s("physical", 1.2), "req_level": 3,
     "description": "向前冲锋攻击"},
    {"id": "common_inspire", "name": "鼓舞", "type": "buff", "mp_cost": 15,
     "effects": _b("luck", 5, 2) + _b("agility", 3, 2),
     "req_level": 5, "cooldown": 3, "description": "鼓舞士气，提升全队运气和敏捷"},
    {"id": "common_bandage", "name": "包扎", "type": "heal", "mp_cost": 5,
     "effects": [{"type": "heal", "target": "single_ally", "value": 0.15}],
     "req_level": 2, "description": "简单包扎，恢复少量HP"},
]


# ============================================================
# 职业被动技能（始终生效，不占技能槽位）
# ============================================================

PASSIVE_SKILLS = {
    # ── 奇幻魔法 ──
    "fantasy": {
        "warrior":  {"id": "passive_warrior",  "name": "坚韧体魄", "description": "最大HP+15%，受到的物理伤害-10%",
                     "effects": {"max_hp_mult": 1.15, "phys_damage_reduce": 0.10}},
        "mage":     {"id": "passive_mage",     "name": "魔法亲和", "description": "魔法伤害+15%，最大MP+10%",
                     "effects": {"magic_damage_mult": 1.15, "max_mp_mult": 1.10}},
        "rogue":    {"id": "passive_rogue",    "name": "暗影直觉", "description": "暴击率+15%，闪避+10%",
                     "effects": {"crit_rate_bonus": 0.15, "dodge_bonus": 0.10}},
        "archer":   {"id": "passive_archer",   "name": "鹰眼瞄准", "description": "远程伤害+15%，命中率+10%",
                     "effects": {"ranged_damage_mult": 1.15, "hit_rate_bonus": 0.10}},
        "cleric":   {"id": "passive_cleric",   "name": "神圣庇护", "description": "治疗效果+20%，受到伤害-8%",
                     "effects": {"heal_mult": 1.20, "damage_reduce": 0.08}},
    },
    # ── 仙侠修真 ──
    "xianxia": {
        "sword_cultivator":       {"id": "passive_sword",  "name": "剑意护体", "description": "物理伤害+12%，闪避+8%",
                                   "effects": {"phys_damage_mult": 1.12, "dodge_bonus": 0.08}},
        "body_cultivator":        {"id": "passive_body",   "name": "金刚不坏", "description": "最大HP+20%，物理减伤+12%",
                                   "effects": {"max_hp_mult": 1.20, "phys_damage_reduce": 0.12}},
        "pill_cultivator":        {"id": "passive_pill",   "name": "丹毒免疫", "description": "治疗效果+15%，免疫中毒",
                                   "effects": {"heal_mult": 1.15, "immune_dot": True}},
        "talisman_cultivator":    {"id": "passive_talisman","name": "符箓护身", "description": "受到魔法伤害-15%，最大MP+10%",
                                   "effects": {"magic_damage_reduce": 0.15, "max_mp_mult": 1.10}},
        "soul_cultivator":        {"id": "passive_soul",   "name": "神魂凝聚", "description": "魔法伤害+12%，MP恢复+20%",
                                   "effects": {"magic_damage_mult": 1.12, "mp_regen_mult": 1.20}},
    },
    # ── 武侠江湖 ──
    "wuxia": {
        "swordsman":  {"id": "passive_swordsman", "name": "剑心通明", "description": "物理伤害+15%，暴击+8%",
                       "effects": {"phys_damage_mult": 1.15, "crit_rate_bonus": 0.08}},
        "boxer":      {"id": "passive_boxer",     "name": "铁布衫", "description": "最大HP+18%，物理减伤+10%",
                       "effects": {"max_hp_mult": 1.18, "phys_damage_reduce": 0.10}},
        "assassin":   {"id": "passive_assassin",  "name": "踏雪无痕", "description": "闪避+15%，暴击+10%",
                       "effects": {"dodge_bonus": 0.15, "crit_rate_bonus": 0.10}},
        "doctor":     {"id": "passive_doctor",    "name": "妙手回春", "description": "治疗效果+20%，免疫中毒",
                       "effects": {"heal_mult": 1.20, "immune_dot": True}},
        "scholar":    {"id": "passive_scholar",   "name": "浩然正气", "description": "魔法伤害+12%，MP恢复+15%",
                       "effects": {"magic_damage_mult": 1.12, "mp_regen_mult": 1.15}},
    },
    # ── 末世废土 ──
    "post_apocalyptic": {
        "esper":      {"id": "passive_esper",     "name": "超能觉醒", "description": "魔法伤害+15%，MP+10%",
                       "effects": {"magic_damage_mult": 1.15, "max_mp_mult": 1.10}},
        "scavenger":  {"id": "passive_scavenger", "name": "废土求生", "description": "闪避+12%，物品掉落率+15%",
                       "effects": {"dodge_bonus": 0.12, "drop_rate_bonus": 0.15}},
        "mechanic":   {"id": "passive_mechanic",  "name": "机械改造", "description": "物理减伤+10%，HP+10%",
                       "effects": {"phys_damage_reduce": 0.10, "max_hp_mult": 1.10}},
        "mutant":     {"id": "passive_mutant",    "name": "基因变异", "description": "HP再生+5%/回合，力量+10%",
                       "effects": {"hp_regen_pct": 0.05, "stat_mult": {"strength": 1.10}}},
        "survivor":   {"id": "passive_survivor",  "name": "适者生存", "description": "全属性+5%，受伤-5%",
                       "effects": {"all_stat_mult": 1.05, "damage_reduce": 0.05}},
    },
    # ── 现世超武 ──
    "modern_power": {
        "martial_artist":     {"id": "passive_martial",   "name": "内力贯通", "description": "物理伤害+12%，HP+8%",
                               "effects": {"phys_damage_mult": 1.12, "max_hp_mult": 1.08}},
        "awakened":           {"id": "passive_awakened",  "name": "异能增幅", "description": "魔法伤害+12%，MP+12%",
                               "effects": {"magic_damage_mult": 1.12, "max_mp_mult": 1.12}},
        "ancient_inheritor":  {"id": "passive_ancient",   "name": "古武传承", "description": "闪避+10%，暴击+10%",
                               "effects": {"dodge_bonus": 0.10, "crit_rate_bonus": 0.10}},
        "dark_ability":       {"id": "passive_dark",      "name": "暗影潜行", "description": "闪避+15%，先手+10%",
                               "effects": {"dodge_bonus": 0.15, "initiative_bonus": 10}},
        "enhancer":           {"id": "passive_enhancer",  "name": "全维强化", "description": "全属性+8%",
                               "effects": {"all_stat_mult": 1.08}},
    },
    # ── 科幻未来 ──
    "scifi": {
        "mecha_pilot":         {"id": "passive_mecha",   "name": "机甲装甲", "description": "物理减伤+15%，HP+15%",
                                "effects": {"phys_damage_reduce": 0.15, "max_hp_mult": 1.15}},
        "nano_soldier":        {"id": "passive_nano",    "name": "纳米自适应", "description": "HP再生+3%/回合，全属性+5%",
                                "effects": {"hp_regen_pct": 0.03, "all_stat_mult": 1.05}},
        "hacker":              {"id": "passive_hacker",  "name": "信息操控", "description": "魔法伤害+15%，先手+15%",
                                "effects": {"magic_damage_mult": 1.15, "initiative_bonus": 15}},
        "gene_modified":       {"id": "passive_gene",    "name": "基因优化", "description": "物理伤害+10%，HP再生+3%/回合",
                                "effects": {"phys_damage_mult": 1.10, "hp_regen_pct": 0.03}},
        "energy_manipulator":  {"id": "passive_energy",  "name": "能量场域", "description": "魔法减伤+12%，MP+15%",
                                "effects": {"magic_damage_reduce": 0.12, "max_mp_mult": 1.15}},
    },
}


# ============================================================
# 技能系统主类
# ============================================================

class SkillSystem:
    """技能系统：查询、学习、战斗执行"""

    # 统一技能数据库（含通用技能）
    _SKILL_DB = None

    @staticmethod
    def get_passive_skill(world_type: str, class_id: str) -> Optional[Dict]:
        """获取职业被动技能"""
        world_passives = PASSIVE_SKILLS.get(world_type, {})
        return world_passives.get(class_id)

    @staticmethod
    def get_passive_effects(character: Dict, world_type: str) -> Dict:
        """获取角色的被动技能效果（合并到战斗计算中）"""
        class_id = character.get("class_id", "")
        passive = SkillSystem.get_passive_skill(world_type, class_id)
        if not passive:
            return {}
        return passive.get("effects", {})

    @classmethod
    def _build_db(cls):
        """构建统一的技能数据库（按id索引）"""
        if cls._SKILL_DB is not None:
            return cls._SKILL_DB
        db = {}
        # 通用技能
        for s in COMMON_SKILLS:
            db[s["id"]] = Skill.from_dict(s)
        # 世界/职业技能
        for world_type, classes in SKILL_DATABASE.items():
            for class_id, skills in classes.items():
                for s in skills:
                    db[s["id"]] = Skill.from_dict(s)
        cls._SKILL_DB = db
        return db

    @classmethod
    def get_skill(cls, skill_id: str) -> Optional[Skill]:
        """按id获取技能"""
        cls._build_db()
        return cls._SKILL_DB.get(skill_id)

    @classmethod
    def get_skill_by_name(cls, name: str) -> Optional[Skill]:
        """按名称获取技能"""
        cls._build_db()
        for s in cls._SKILL_DB.values():
            if s.name == name:
                return s
        return None

    @classmethod
    def get_class_skills(cls, world_type: str, class_id: str) -> List[Skill]:
        """获取职业的所有技能"""
        world_data = SKILL_DATABASE.get(world_type, {})
        class_skills = world_data.get(class_id, [])
        return [Skill.from_dict(s) for s in class_skills]

    @classmethod
    def get_available_skills(cls, world_type: str, class_id: str,
                              level: int, stats: Dict,
                              known_skill_ids: List[str]) -> List[Skill]:
        """获取当前可学习的新技能（仅限本职业+通用技能，兼容旧版调用）"""
        return cls.get_all_learnable_skills(world_type, level, stats, known_skill_ids)

    @classmethod
    def get_all_learnable_skills(cls, world_type: str,
                                  level: int, stats: Dict,
                                  known_skill_ids: List[str],
                                  include_awakening: bool = False) -> List[Dict]:
        """
        获取所有可学习的技能（跨职业自由选择）
        
        返回格式: [{"skill": Skill对象, "source": "职业名/通用", "source_class_id": "warrior", "class_icon": "⚔️"}]
        
        自由选择规则：
        - 返回当前世界类型下所有职业的全部技能 + 通用技能
        - 不限制职业，只看等级和属性需求
        - 已学习的技能不会出现
        """
        known = set(known_skill_ids)
        result = []
        cls._build_db()

        # 1. 遍历当前世界类型的所有职业
        world_data = SKILL_DATABASE.get(world_type, {})
        for class_id, skills in world_data.items():
            # 获取职业名称和图标
            from simlife.backend.death_mode_state import get_class_template
            tmpl = get_class_template(world_type, class_id)
            source_name = tmpl["name"] if tmpl else class_id
            class_icon = tmpl.get("icon", "❓") if tmpl else "❓"

            for skill_dict in skills:
                skill = Skill.from_dict(skill_dict)
                if skill.id in known:
                    continue
                # 等级检查
                if skill.req_level > level:
                    continue
                # 属性需求检查
                if not cls._check_stats_requirement(skill, stats):
                    continue
                result.append({
                    "skill": skill,
                    "source": source_name,
                    "source_class_id": class_id,
                    "class_icon": class_icon,
                })

        # 2. 通用技能
        for skill_dict in COMMON_SKILLS:
            skill = Skill.from_dict(skill_dict)
            if skill.id in known:
                continue
            if skill.req_level > level:
                continue
            if not cls._check_stats_requirement(skill, stats):
                continue
            result.append({
                "skill": skill,
                "source": "通用",
                "source_class_id": "common",
                "class_icon": "🌟",
            })

        # 按等级排序
        result.sort(key=lambda x: x["skill"].req_level)
        return result

    @classmethod
    def _check_stats_requirement(cls, skill: Skill, stats: Dict) -> bool:
        """检查属性需求"""
        for stat, val in skill.req_stats.items():
            if stats.get(stat, 0) < val:
                return False
        return True

    @classmethod
    def get_skills_by_level(cls, world_type: str, class_id: str,
                             level: int) -> List[Skill]:
        """获取某等级解锁的所有技能（含前置）"""
        class_skills = cls.get_class_skills(world_type, class_id)
        return [s for s in class_skills if s.req_level <= level]

    @classmethod
    def check_skill_usable(cls, skill: Skill, caster: Dict,
                            cooldown_tracker: Dict = None) -> Tuple[bool, str]:
        """检查技能是否可用"""
        # MP检查
        if caster.get("mp", 0) < skill.mp_cost:
            return False, "MP不足"
        # 冷却检查
        if cooldown_tracker and skill.id in cooldown_tracker:
            remaining = cooldown_tracker[skill.id]
            if remaining > 0:
                return False, f"技能冷却中（剩余{remaining}回合）"
        return True, ""

    # ── 敌人技能分配 ──────────────────────────────────

    @classmethod
    def assign_skills_for_enemy(cls, count: int, level: int, enemy_type: str) -> List[Dict]:
        """从技能数据库给敌人分配技能
        
        count: 技能数量
        level: 敌人等级
        enemy_type: "normal" / "elite" / "boss"
        返回: [{"skill_id": str, "name": str, "type": str, "target_type": str, "multiplier": float, "mp_cost": int, "effects": [...]}, ...]
        """
        cls._build_db()
        all_skills = list(cls._SKILL_DB.values())

        # 过滤：只选攻击类技能（physical/magic），排除辅助/治疗/通用技能
        combat_skills = [s for s in all_skills if s.type in ("physical", "magic")]

        if not combat_skills:
            return []

        # 按等级筛选合适的技能
        level_range = max(1, level - 5)
        suitable = [s for s in combat_skills if s.req_level <= level and s.req_level >= level_range - 3]
        if not suitable:
            suitable = combat_skills

        # 随机选 count 个（不重复）
        import random
        selected = random.sample(suitable, min(count, len(suitable)))

        result = []
        for s in selected:
            # 判断是否为AOE
            is_aoe = any(
                e.target in ("all_enemies", "all_allies")
                for e in s.effects
            )
            target_type = "aoe" if is_aoe else "single"
            mult = s.effects[0].value if s.effects else 1.0
            result.append({
                "skill_id": s.id,
                "name": s.name,
                "type": s.type,
                "target_type": target_type,
                "multiplier": mult,
                "mp_cost": s.mp_cost,
                "effects": [e.to_dict() for e in s.effects],
            })

        return result

    @classmethod
    def get_random_aoe_skill(cls, level: int) -> Optional[Dict]:
        """获取一个随机的AOE技能（专供BOSS使用）"""
        cls._build_db()
        all_skills = list(cls._SKILL_DB.values())
        aoe_skills = [
            s for s in all_skills
            if s.type in ("physical", "magic")
            and any(e.target in ("all_enemies", "all_allies") for e in s.effects)
            and s.req_level <= level
        ]
        if not aoe_skills:
            return None
        import random
        s = random.choice(aoe_skills)
        is_aoe = any(e.target in ("all_enemies", "all_allies") for e in s.effects)
        return {
            "skill_id": s.id,
            "name": s.name,
            "type": s.type,
            "target_type": "aoe" if is_aoe else "single",
            "multiplier": s.effects[0].value if s.effects else 1.0,
            "mp_cost": s.mp_cost,
            "effects": [e.to_dict() for e in s.effects],
        }

    @classmethod
    def get_starting_skills(cls, world_type: str, class_id: str) -> List[str]:
        """获取初始技能（Lv.1可学的技能id列表）"""
        skills = cls.get_available_skills(world_type, class_id, 1, {}, [])
        # skills 现在是 [{"skill": Skill, ...}, ...] 格式
        return [item["skill"].id for item in skills if item["skill"].req_level <= 1]

    @classmethod
    def can_learn_more_skills(cls, known_skill_ids: List[str], awakening_count: int = 0) -> Tuple[bool, int]:
        """
        检查是否还能学习更多技能
        
        返回: (can_learn, remaining_slots)
        - 普通技能最多10个
        - 觉醒技能最多3个（不计入10个限制）
        """
        # 只计算非觉醒技能的普通技能数量
        normal_skills = [sid for sid in known_skill_ids if not sid.startswith("awakening_")]
        remaining = MAX_SKILLS - len(normal_skills)
        return remaining > 0, max(0, remaining)

    # ── 觉醒技能管理 ──────────────────────────────────

    @classmethod
    def get_awakening_slots(cls, character: Dict) -> List[Dict]:
        """
        获取角色的觉醒技能槽位

        返回: [{"slot_index": 0, "skill": Skill|None, "is_empty": bool, "req_level": 40, "unlocked": bool}, ...]
        """
        awakening_skills = character.get("awakening_skills", [])
        char_level = character.get("level", 1)
        slots = []
        for i in range(AWAKENING_SLOTS):
            req_level = AWAKENING_LEVEL_REQ[i]
            unlocked = char_level >= req_level
            if i < len(awakening_skills) and awakening_skills[i]:
                skill_data = awakening_skills[i]
                if skill_data.get("name") and skill_data.get("name") != "空":
                    skill = Skill.from_dict(skill_data)
                    slots.append({
                        "slot_index": i,
                        "skill": skill,
                        "is_empty": False,
                        "req_level": req_level,
                        "unlocked": unlocked,
                    })
                else:
                    slots.append({
                        "slot_index": i,
                        "skill": None,
                        "is_empty": True,
                        "req_level": req_level,
                        "unlocked": unlocked,
                    })
            else:
                slots.append({
                    "slot_index": i,
                    "skill": None,
                    "is_empty": True,
                    "req_level": req_level,
                    "unlocked": unlocked,
                })
        return slots

    @classmethod
    def set_awakening_skill(cls, character: Dict, slot_index: int,
                             skill_data: Dict) -> Tuple[bool, str]:
        """
        设置觉醒技能

        skill_data: {
            "name": str,          # 技能名称
            "type": str,          # physical/magic/heal/buff/utility
            "mp_cost": int,       # MP消耗
            "effects": [list],    # 效果列表
            "description": str,   # 描述
        }
        """
        if slot_index < 0 or slot_index >= AWAKENING_SLOTS:
            return False, f"槽位索引无效（0~{AWAKENING_SLOTS-1}）"

        # 等级检查：槽位0需40级，槽位1需50级，槽位2需60级
        req_level = AWAKENING_LEVEL_REQ[slot_index]
        char_level = character.get("level", 1)
        if char_level < req_level:
            return False, f"觉醒技能槽位{slot_index}需要等级{req_level}，当前等级{char_level}"

        # 验证技能数据
        name = skill_data.get("name", "").strip()
        if not name:
            return False, "技能名称不能为空"

        skill_type = skill_data.get("type", "physical")
        if skill_type not in ("physical", "magic", "heal", "buff", "utility"):
            return False, "无效的技能类型"

        effects = skill_data.get("effects", [])
        if not effects:
            return False, "至少需要一个效果"

        # 构建觉醒技能
        awakening_id = f"awakening_{slot_index}"
        awakening = {
            "id": awakening_id,
            "name": name,
            "type": skill_type,
            "mp_cost": max(0, skill_data.get("mp_cost", 10)),
            "effects": effects,
            "req_level": req_level,
            "req_class": None,
            "req_stats": {},
            "cooldown": max(0, skill_data.get("cooldown", 0)),
            "description": skill_data.get("description", ""),
        }

        # 存储到角色
        awakening_skills = character.get("awakening_skills", [])
        while len(awakening_skills) <= slot_index:
            awakening_skills.append(None)
        awakening_skills[slot_index] = awakening
        character["awakening_skills"] = awakening_skills

        return True, f"觉醒技能「{name}」设置成功"

    @classmethod
    def get_character_skills(cls, character: Dict, world_type: str = "fantasy") -> List[Skill]:
        """
        获取角色的所有技能（含觉醒技能）
        
        返回: [Skill, ...]
        """
        skills = []
        # 普通技能
        for sid in character.get("skills", []):
            skill = cls.get_skill(sid)
            if skill:
                skills.append(skill)
        # 觉醒技能
        for slot in cls.get_awakening_slots(character):
            if not slot["is_empty"] and slot["skill"]:
                skills.append(slot["skill"])
        return skills

    # ── 技能效果执行 ──────────────────────────────────

    @classmethod
    def resolve_skill(cls, skill: Skill, caster: Dict,
                       targets: Dict[str, List[Dict]],
                       combat_context: Dict = None) -> Dict:
        """
        执行技能的所有效果
        
        caster: 施法者字典
        targets: 目标字典 {"self": [...], "single_enemy": [...], "all_enemies": [...], "single_ally": [...], "all_allies": [...]}
        combat_context: 战斗上下文（回合数、敌人列表等）
        
        返回: {"effects": [{effect结果}], "total_damage": int, "total_heal": int, "status_changes": [...]}
        """
        result = {
            "effects": [],
            "total_damage": 0,
            "total_heal": 0,
            "status_changes": [],
            "log": [],
        }

        caster_stats = caster.get("stats", {})
        caster_level = caster.get("level", 1)
        caster_attack = (caster_stats.get("strength", 5) * 2 +
                         caster_stats.get("agility", 5) * 0.5 +
                         caster_stats.get("intelligence", 5) * 0.5)

        for effect in skill.effects:
            effect_result = cls._resolve_effect(effect, caster, targets,
                                                 caster_attack, caster_level,
                                                 combat_context)
            result["effects"].append(effect_result)
            result["total_damage"] += effect_result.get("damage", 0)
            result["total_heal"] += effect_result.get("heal", 0)
            if effect_result.get("status_changes"):
                result["status_changes"].extend(effect_result["status_changes"])
            if effect_result.get("log"):
                result["log"].extend(effect_result["log"])

        # 扣MP
        result["mp_cost"] = min(caster.get("mp", 0), skill.mp_cost)
        caster["mp"] = max(0, caster.get("mp", 0) - skill.mp_cost)

        return result

    @classmethod
    def _resolve_effect(cls, effect: SkillEffect, caster: Dict,
                         targets: Dict, caster_attack: float,
                         caster_level: int, combat_context: Dict) -> Dict:
        """解析单个效果"""
        effect_type = effect.type
        target_list = targets.get(effect.target, [])
        result = {
            "type": effect_type,
            "target": effect.target,
            "damage": 0,
            "heal": 0,
            "status_changes": [],
            "log": [],
        }

        if not target_list:
            return result

        if random.random() > effect.chance:
            result["log"].append(f"{effect_type}未触发（概率{effect.chance}）")
            return result

        if effect_type == EffectType.DAMAGE:
            total_dmg = 0
            for t in target_list:
                base_damage = int(caster_attack * effect.value)
                defense = t.get("stats", {}).get("vitality", 5) * 1.5
                # 加上装备防御
                for eq in t.get("equipment", []):
                    if eq.get("type") == "outfit":
                        base_damage -= eq.get("bonus", 0)
                    if eq.get("subtype") == "shield":
                        base_damage -= eq.get("bonus", 0)
                damage = max(1, base_damage - int(defense))
                # 浮动±10%
                damage = max(1, int(damage * random.uniform(0.9, 1.1)))
                t["hp"] = max(0, t.get("hp", 0) - damage)
                total_dmg += damage
                result["log"].append(f"对{t.get('name','?')}造成{damage}点伤害")
            result["damage"] = total_dmg

        elif effect_type == EffectType.HEAL:
            total_heal = 0
            for t in target_list:
                # 如果是MP恢复（通过stat="mp"标记）
                if effect.stat == "mp":
                    mp_recover = int(t.get("max_mp", 50) * effect.value)
                    t["mp"] = min(t.get("max_mp", 50), t.get("mp", 0) + mp_recover)
                    result["log"].append(f"恢复{t.get('name','?')}{mp_recover}MP")
                    total_heal += mp_recover
                else:
                    # HP治疗：基于目标max_hp百分比 + 智力加成
                    max_hp = t.get("max_hp", 50)
                    heal_stat = caster.get("stats", {}).get("intelligence", 5)
                    heal_amount = int(max_hp * effect.value * (1 + heal_stat * 0.02))
                    t["hp"] = min(max_hp, t.get("hp", 0) + heal_amount)
                    total_heal += heal_amount
                    result["log"].append(f"治疗{t.get('name','?')}{heal_amount}点HP")
            if effect.stat != "mp":
                result["heal"] = total_heal
            else:
                result["mp_heal"] = total_heal

        elif effect_type == EffectType.DOT:
            for t in target_list:
                dot_per_tick = int(caster_attack * effect.value)
                status = {
                    "type": "dot",
                    "target": t.get("name", "?"),
                    "value": dot_per_tick,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                    "source": caster.get("name", "?"),
                }
                result["status_changes"].append(status)
                result["log"].append(f"对{t.get('name','?')}施加灼烧/中毒，每回合{dot_per_tick}伤害，持续{effect.duration}回合")

        elif effect_type == EffectType.HOT:
            for t in target_list:
                hot_per_tick = int(t.get("max_hp", 50) * effect.value)
                status = {
                    "type": "hot",
                    "target": t.get("name", "?"),
                    "value": hot_per_tick,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                    "source": caster.get("name", "?"),
                }
                result["status_changes"].append(status)
                result["log"].append(f"对{t.get('name','?')}施加再生，每回合恢复{hot_per_tick}HP，持续{effect.duration}回合")

        elif effect_type == EffectType.STUN:
            for t in target_list:
                # 设置stagger_turns
                t["stagger_turns"] = max(t.get("stagger_turns", 0), int(effect.value))
                result["status_changes"].append({
                    "type": "stun",
                    "target": t.get("name", "?"),
                    "duration": int(effect.value),
                    "remaining": int(effect.value),
                })
                result["log"].append(f"眩晕{t.get('name','?')}，持续{int(effect.value)}回合")

        elif effect_type == EffectType.FREEZE:
            for t in target_list:
                t["stagger_turns"] = max(t.get("stagger_turns", 0), int(effect.value))
                # 冻结额外降低防御
                t.setdefault("temp_debuffs", {})["vitality"] = t.get("temp_debuffs", {}).get("vitality", 0) - 5
                result["status_changes"].append({
                    "type": "freeze",
                    "target": t.get("name", "?"),
                    "duration": int(effect.value),
                    "remaining": int(effect.value),
                })
                result["log"].append(f"冻结{t.get('name','?')}，持续{int(effect.value)}回合，防御降低")

        elif effect_type == EffectType.SLOW:
            for t in target_list:
                t.setdefault("temp_debuffs", {})["agility"] = t.get("temp_debuffs", {}).get("agility", 0) + effect.value
                result["status_changes"].append({
                    "type": "slow",
                    "target": t.get("name", "?"),
                    "value": effect.value,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"减速{t.get('name','?')}，敏捷降低{abs(effect.value)}，持续{effect.duration}回合")

        elif effect_type == EffectType.BUFF_STAT:
            for t in target_list:
                t.setdefault("temp_buffs", {})[effect.stat] = t.get("temp_buffs", {}).get(effect.stat, 0) + effect.value
                result["status_changes"].append({
                    "type": "buff",
                    "target": t.get("name", "?"),
                    "stat": effect.stat,
                    "value": effect.value,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"提升{t.get('name','?')}的{effect.stat}{effect.value}点，持续{effect.duration}回合")

        elif effect_type == EffectType.DEBUFF_STAT:
            for t in target_list:
                t.setdefault("temp_debuffs", {})[effect.stat] = t.get("temp_debuffs", {}).get(effect.stat, 0) + effect.value
                result["status_changes"].append({
                    "type": "debuff",
                    "target": t.get("name", "?"),
                    "stat": effect.stat,
                    "value": effect.value,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"降低{t.get('name','?')}的{effect.stat}{abs(effect.value)}点，持续{effect.duration}回合")

        elif effect_type == EffectType.SHIELD:
            for t in target_list:
                t["shield"] = t.get("shield", 0) + int(effect.value)
                result["status_changes"].append({
                    "type": "shield",
                    "target": t.get("name", "?"),
                    "value": int(effect.value),
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"为{t.get('name','?')}施加护盾，吸收{int(effect.value)}点伤害")

        elif effect_type == EffectType.CLEANSING:
            for t in target_list:
                removed = []
                if "temp_debuffs" in t:
                    removed = list(t["temp_debuffs"].keys())
                    del t["temp_debuffs"]
                result["log"].append(f"净化{t.get('name','?')}，移除{len(removed)}个负面效果")

        elif effect_type == EffectType.TAUNT:
            if combat_context:
                combat_context["taunt_target"] = caster.get("name", "?")
            result["log"].append(f"{caster.get('name','?')}嘲讽所有敌人，强制攻击自己")

        elif effect_type == EffectType.TELEPORT:
            for t in target_list:
                t.setdefault("temp_buffs", {})["agility"] = t.get("temp_buffs", {}).get("agility", 0) + int(20 * effect.value)
                result["status_changes"].append({
                    "type": "teleport",
                    "target": t.get("name", "?"),
                    "value": int(20 * effect.value),
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"{t.get('name','?')}瞬移，闪避大幅提升")

        elif effect_type == EffectType.COUNTER:
            for t in target_list:
                t.setdefault("temp_buffs", {})["counter"] = t.get("temp_buffs", {}).get("counter", 0) + effect.value
                result["status_changes"].append({
                    "type": "counter",
                    "target": t.get("name", "?"),
                    "value": effect.value,
                    "duration": effect.duration,
                    "remaining": effect.duration,
                })
                result["log"].append(f"{t.get('name','?')}进入反击姿态，受击时反击{effect.value}倍伤害")

        elif effect_type == EffectType.LIFE_STEAL:
            # 吸血加成：在伤害计算后额外处理
            caster.setdefault("temp_buffs", {})["life_steal"] = caster.get("temp_buffs", {}).get("life_steal", 0) + effect.value
            result["log"].append(f"{caster.get('name','?')}获得{effect.value}倍吸血")

        elif effect_type == EffectType.EXECUTE:
            for t in target_list:
                max_hp = t.get("max_hp", 50)
                current_hp = t.get("hp", 0)
                hp_ratio = current_hp / max_hp if max_hp > 0 else 1.0
                # 目标HP越低，斩杀伤害越高
                execute_mult = effect.value * (1.0 + (1.0 - hp_ratio) * 1.5)
                base_damage = int(caster_attack * execute_mult)
                defense = t.get("stats", {}).get("vitality", 5) * 1.5
                damage = max(1, base_damage - int(defense))
                damage = max(1, int(damage * random.uniform(0.9, 1.1)))
                t["hp"] = max(0, t.get("hp", 0) - damage)
                result["damage"] = damage
                result["log"].append(f"斩杀{t.get('name','?')}！HP比例{hp_ratio:.0%}，造成{damage}点伤害")

        return result

    # ── 状态效果管理 ──────────────────────────────────

    @classmethod
    def tick_status_effects(cls, entity: Dict, status_tracker: List[Dict]) -> Dict:
        """
        每回合开始时处理状态效果tick
        返回: {"damage": int, "heal": int, "expired": [status_index], "log": [...]}
        """
        result = {"damage": 0, "heal": 0, "expired": [], "log": []}
        expired_indices = []

        for i, status in enumerate(status_tracker):
            target_name = status.get("target", "?")
            if status.get("remaining", 0) <= 0:
                expired_indices.append(i)
                continue

            status_type = status.get("type")

            if status_type == "dot":
                dmg = status.get("value", 0)
                entity["hp"] = max(0, entity.get("hp", 0) - dmg)
                result["damage"] += dmg
                result["log"].append(f"[状态] {target_name}受到{status_type}伤害{dmg}点")

            elif status_type == "hot":
                heal = status.get("value", 0)
                max_hp = entity.get("max_hp", 50)
                entity["hp"] = min(max_hp, entity.get("hp", 0) + heal)
                result["heal"] += heal
                result["log"].append(f"[状态] {target_name}受到{status_type}治疗{heal}点")

            # 减少剩余回合
            status["remaining"] = status.get("remaining", 1) - 1
            if status["remaining"] <= 0:
                expired_indices.append(i)

        # 从后往前移除过期效果
        for idx in sorted(expired_indices, reverse=True):
            expired = status_tracker.pop(idx)
            result["expired"].append(expired)
            result["log"].append(f"[状态] {expired.get('target','?')}的{expired.get('type','?')}效果已结束")

        return result

    @classmethod
    def cleanup_temp_buffs(cls, entity: Dict, status_tracker: List[Dict]):
        """清理已过期的临时buff/debuff"""
        # 检查是否有任何buff/debuff还在持续
        active_buffs = set()
        active_debuffs = set()
        for s in status_tracker:
            if s.get("type") == "buff" and s.get("remaining", 0) > 0:
                active_buffs.add(s.get("stat"))
            if s.get("type") == "debuff" and s.get("remaining", 0) > 0:
                active_debuffs.add(s.get("stat"))

        # 清理已过期的buff
        if "temp_buffs" in entity:
            for stat in list(entity["temp_buffs"].keys()):
                if stat not in active_buffs:
                    del entity["temp_buffs"][stat]
            if not entity["temp_buffs"]:
                del entity["temp_buffs"]

        # 清理已过期的debuff
        if "temp_debuffs" in entity:
            for stat in list(entity["temp_debuffs"].keys()):
                if stat not in active_debuffs:
                    del entity["temp_debuffs"][stat]
            if not entity["temp_debuffs"]:
                del entity["temp_debuffs"]

        # 清理护盾
        if "shield" in entity and not any(s.get("type") == "shield" and s.get("remaining", 0) > 0 for s in status_tracker):
            entity.pop("shield", None)

    @classmethod
    def get_effective_stats(cls, entity: Dict) -> Dict:
        """获取实时的有效属性（含临时buff/debuff）"""
        stats = dict(entity.get("stats", {}))
        # 临时buff
        for k, v in entity.get("temp_buffs", {}).items():
            if k in stats:
                stats[k] = stats[k] + v
        # 临时debuff
        for k, v in entity.get("temp_debuffs", {}).items():
            if k in stats:
                stats[k] = max(1, stats[k] + v)
        return stats