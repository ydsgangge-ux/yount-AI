"""
装备系统 v2 — 装备池、掉落、穿戴、属性加成

核心设计：
- 装备按品质分级：普通(白) / 优秀(绿) / 稀有(蓝) / 史诗(紫) / 传说(橙)
- 四个装备槽位：主手 / 副手 / 远程 / 穿着
- 武器子类型：单手武器、双手武器(占主手+副手)、远程武器、盾牌、副手物品
- 重量系统：武器有重量，按力量需求，力量不足有减益
- 战斗胜利后根据敌人等级/类型掉落装备
- 同槽位装备只能穿戴一件，替换时旧装备进入背包
"""
import random
from typing import Dict, List, Optional


# ============================================================
# 装备品质
# ============================================================

class ItemRarity:
    COMMON = "common"       # 白色
    UNCOMMON = "uncommon"   # 绿色
    RARE = "rare"           # 蓝色
    EPIC = "epic"           # 紫色
    LEGENDARY = "legendary" # 橙色

    RARITY_CONFIG = {
        "common":    {"name": "普通", "color": "#9ca3af", "multiplier": 1.0, "drop_weight": 50},
        "uncommon":  {"name": "优秀", "color": "#3fb950", "multiplier": 1.3, "drop_weight": 30},
        "rare":      {"name": "稀有", "color": "#58a6ff", "multiplier": 1.7, "drop_weight": 14},
        "epic":      {"name": "史诗", "color": "#bc8cff", "multiplier": 2.2, "drop_weight": 5},
        "legendary": {"name": "传说", "color": "#f0883e", "multiplier": 3.0, "drop_weight": 1},
    }

    @classmethod
    def get_config(cls, rarity: str) -> Dict:
        return cls.RARITY_CONFIG.get(rarity, cls.RARITY_CONFIG["common"])

    @classmethod
    def roll_rarity(cls, luck: int = 5, enemy_type: str = "normal") -> str:
        """根据运气和敌人类型决定掉落品质"""
        weights = {k: v["drop_weight"] for k, v in cls.RARITY_CONFIG.items()}
        luck_bonus = luck / 100.0
        weights["uncommon"] += luck_bonus * 20
        weights["rare"] += luck_bonus * 10
        weights["epic"] += luck_bonus * 3
        weights["legendary"] += luck_bonus * 1
        weights["common"] -= luck_bonus * 34

        if enemy_type == "elite":
            weights["uncommon"] += 15
            weights["rare"] += 10
            weights["common"] -= 25
        elif enemy_type == "boss":
            weights["uncommon"] += 10
            weights["rare"] += 20
            weights["epic"] += 10
            weights["legendary"] += 3
            weights["common"] -= 43

        for k in weights:
            weights[k] = max(0, weights[k])

        rarities = list(weights.keys())
        w = [weights[r] for r in rarities]
        return random.choices(rarities, weights=w, k=1)[0]


# ============================================================
# 武器子类型与槽位映射
# ============================================================

# 武器子类型定义
WEAPON_SUBTYPES = {
    "one_handed": {
        "name": "单手武器",
        "slot": "main_hand",       # 占主手
        "icon": "🗡️",
        "damage_type": "physical", # 近战物理
        "weight_base": 3,
        "description": "单手剑、锤、匕首等，可搭配盾牌或双持",
    },
    "two_handed": {
        "name": "双手武器",
        "slot": "main_hand",       # 占主手，但会占用副手位
        "icon": "⚔️",
        "damage_type": "physical",
        "weight_base": 8,
        "description": "双手剑、长柄武器、巨锤等，伤害高，需要力量",
    },
    "ranged": {
        "name": "远程武器",
        "slot": "ranged",
        "icon": "🏹",
        "damage_type": "ranged",   # 远程物理
        "weight_base": 2,
        "description": "弓、弩、火枪等，远程物理攻击",
    },
    "wand": {
        "name": "法杖/魔杖",
        "slot": "ranged",
        "icon": "🔮",
        "damage_type": "magic",    # 法术伤害
        "weight_base": 2,
        "description": "法杖、魔杖等，法术攻击",
    },
    "shield": {
        "name": "盾牌",
        "slot": "off_hand",        # 占副手
        "icon": "🛡️",
        "damage_type": "defense",  # 纯防御
        "weight_base": 5,
        "description": "盾牌，大幅提升防御",
    },
    "off_hand": {
        "name": "副手物品",
        "slot": "off_hand",
        "icon": "📖",
        "damage_type": "magic",    # 法术辅助
        "weight_base": 1,
        "description": "副手物品、魔法书等，辅助法术",
    },
}

# 武器子类型权重（掉落时按此权重分配）
WEAPON_SUBTYPE_WEIGHTS = {
    "one_handed": 30,
    "two_handed": 20,
    "ranged": 15,
    "wand": 15,
    "shield": 12,
    "off_hand": 8,
}

# 子类型 → 掉落品质加成修正
SUBTYPE_BONUS_MULTIPLIER = {
    "one_handed": 1.0,
    "two_handed": 1.4,   # 双手武器伤害更高
    "ranged": 1.0,
    "wand": 1.0,
    "shield": 0.6,       # 盾牌防御为主
    "off_hand": 0.5,     # 副手物品偏辅助
}


# ============================================================
# 装备生成
# ============================================================

class EquipmentSystem:
    """装备系统：生成、掉落、穿戴（四个槽位：主手/副手/远程/穿着）"""

    # 装备名称池（按世界类型、子类型、品质）
    EQUIPMENT_NAMES = {
        "fantasy": {
            "one_handed": {
                "common": ["生锈短剑", "木棍", "旧匕首"],
                "uncommon": ["铁剑", "钢锤", "精制匕首"],
                "rare": ["秘银长剑", "暗影匕首", "符文锤"],
                "epic": ["龙牙剑", "圣光之刃", "暗影之牙"],
                "legendary": ["灭世之剑", "永恒之刃", "霜之哀伤"],
            },
            "two_handed": {
                "common": ["旧木杖", "铁棍"],
                "uncommon": ["双手铁剑", "战斗法杖", "钢制长柄"],
                "rare": ["秘银巨剑", "烈焰法杖", "精灵长戟"],
                "epic": ["龙牙巨剑", "凤凰法杖", "龙枪"],
                "legendary": ["泰坦之剑", "创世法杖", "永恒之枪"],
            },
            "ranged": {
                "common": ["粗制弓", "旧弩"],
                "uncommon": ["短弓", "轻弩"],
                "rare": ["精灵之弓", "精准弩", "长弓"],
                "epic": ["暗影之弓", "穿云弩", "龙息弓"],
                "legendary": ["命运之弓", "灭世弩", "星辰之弓"],
            },
            "wand": {
                "common": ["短木杖", "旧魔杖"],
                "uncommon": ["灵木法杖", "水晶魔杖"],
                "rare": ["秘银法杖", "蓝宝石魔杖"],
                "epic": ["凤凰法杖", "星辰魔杖", "元素之杖"],
                "legendary": ["创世法杖", "无尽之杖", "时空杖"],
            },
            "shield": {
                "common": ["木盾"],
                "uncommon": ["铁盾", "钢盾"],
                "rare": ["秘银盾", "精灵盾"],
                "epic": ["龙鳞盾", "圣光盾"],
                "legendary": ["不灭之盾", "永恒壁垒"],
            },
            "off_hand": {
                "common": ["旧书"],
                "uncommon": ["魔法书", "咒术符"],
                "rare": ["元素典籍", "暗影宝典"],
                "epic": ["大法师之书", "禁咒书"],
                "legendary": ["万法全书", "创世法典"],
            },
            "outfit": {
                "common": ["布衣", "皮甲"],
                "uncommon": ["链甲", "铁皮护甲"],
                "rare": ["秘银甲", "精灵皮甲"],
                "epic": ["龙鳞甲", "暗影斗篷"],
                "legendary": ["不灭铠甲", "神圣法袍"],
            },
        },
        "xianxia": {
            "one_handed": {
                "common": ["铁剑", "木剑"],
                "uncommon": ["灵剑", "玄铁剑"],
                "rare": ["飞剑·青锋", "天罡剑"],
                "epic": ["仙剑·紫霄", "灭世魔剑"],
                "legendary": ["天道剑", "混沌之剑"],
            },
            "two_handed": {
                "common": ["铁棍", "木杖"],
                "uncommon": ["玄铁重剑", "灵木法杖"],
                "rare": ["天罡重剑", "青莲法杖"],
                "epic": ["紫霄巨剑", "九天法杖"],
                "legendary": ["开天巨剑", "鸿蒙法杖"],
            },
            "ranged": {
                "common": ["竹弓", "木弩"],
                "uncommon": ["灵弓", "铁胎弓"],
                "rare": ["追风弓", "破云弩"],
                "epic": ["落日弓", "穿云弩"],
                "legendary": ["射日弓", "天罚弩"],
            },
            "wand": {
                "common": ["桃木杖", "竹杖"],
                "uncommon": ["灵木杖", "符笔"],
                "rare": ["天师杖", "紫竹法杖"],
                "epic": ["九天玄杖", "五行法杖"],
                "legendary": ["鸿蒙杖", "天道法杖"],
            },
            "shield": {
                "common": ["木盾"],
                "uncommon": ["铁盾", "玄铁盾"],
                "rare": ["灵纹盾", "秘银盾"],
                "epic": ["九天玄盾", "五行盾"],
                "legendary": ["不灭金盾", "太极盾"],
            },
            "off_hand": {
                "common": ["旧符箓"],
                "uncommon": ["灵符", "阵盘"],
                "rare": ["天罡符", "八卦盘"],
                "epic": ["九天符箓", "五行阵盘"],
                "legendary": ["天道符", "混沌阵盘"],
            },
            "outfit": {
                "common": ["道袍", "布衣"],
                "uncommon": ["灵丝法袍", "玄铁护甲"],
                "rare": ["金丝软甲", "天蚕丝袍"],
                "epic": ["九天玄甲", "万法不侵袍"],
                "legendary": ["不灭金身", "混元道袍"],
            },
        },
        "wuxia": {
            "one_handed": {
                "common": ["铁剑", "单刀", "短剑"],
                "uncommon": ["精铁长剑", "缅刀", "青锋剑"],
                "rare": ["龙泉剑", "绣春刀", "碧水剑"],
                "epic": ["倚天剑", "屠龙刀", "紫薇软剑"],
                "legendary": ["轩辕剑", "干将莫邪", "天丛云"],
            },
            "two_handed": {
                "common": ["长棍", "铁枪", "朴刀"],
                "uncommon": ["玄铁棍", "亮银枪", "大环刀"],
                "rare": ["镔铁棍", "红缨枪", "九环刀"],
                "epic": ["混铁棍", "丈八蛇矛", "青龙偃月刀"],
                "legendary": ["如意金箍棒", "方天画戟", "霸王枪"],
            },
            "ranged": {
                "common": ["竹弓", "木弩"],
                "uncommon": ["铁胎弓", "手弩"],
                "rare": ["神臂弓", "连弩"],
                "epic": ["落日弓", "穿云弩"],
                "legendary": ["射日神弓", "追魂弩"],
            },
            "wand": {
                "common": ["竹笛", "木箫"],
                "uncommon": ["玉笛", "铁箫"],
                "rare": ["碧玉箫", "紫竹笛"],
                "epic": ["九霄笛", "天魔琴"],
                "legendary": ["无弦琴", "天道箫"],
            },
            "shield": {
                "common": ["木盾"],
                "uncommon": ["铁盾", "藤甲盾"],
                "rare": ["精铁盾", "玄铁盾"],
                "epic": ["金刚盾", "玄铁重盾"],
                "legendary": ["不灭金盾", "太极玄盾"],
            },
            "off_hand": {
                "common": ["旧书", "酒葫芦"],
                "uncommon": ["武功秘籍", "药箱"],
                "rare": ["武林绝学", "百宝囊"],
                "epic": ["易筋经", "毒经"],
                "legendary": ["九阴真经", "葵花宝典"],
            },
            "outfit": {
                "common": ["粗布衣", "短打劲装"],
                "uncommon": ["绸缎长衫", "皮甲"],
                "rare": ["金丝软甲", "天蚕宝衣"],
                "epic": ["乌蚕甲", "玄铁重甲"],
                "legendary": ["金蝉丝甲", "不灭战袍"],
            },
        },
        "post_apocalyptic": {
            "one_handed": {
                "common": ["生锈刀", "铁管"],
                "uncommon": ["焊接刀", "强化匕首"],
                "rare": ["合金刀", "电磁匕首"],
                "epic": ["纳米刀", "等离子刃"],
                "legendary": ["终结者之刃", "虚空匕首"],
            },
            "two_handed": {
                "common": ["铁棍", "重铁管"],
                "uncommon": ["焊接巨剑", "重锤"],
                "rare": ["合金巨剑", "动力锤"],
                "epic": ["纳米巨剑", "等离子巨锤"],
                "legendary": ["毁灭者", "审判之锤"],
            },
            "ranged": {
                "common": ["旧手枪", "铁管枪"],
                "uncommon": ["改装手枪", "猎枪"],
                "rare": ["突击步枪", "狙击枪"],
                "epic": ["电磁步枪", "等离子枪"],
                "legendary": ["毁灭者", "天罚"],
            },
            "wand": {
                "common": ["旧天线", "铁棒"],
                "uncommon": ["改装发射器", "能量棒"],
                "rare": ["电磁发射器", "脉冲棒"],
                "epic": ["等离子发射器", "能量炮"],
                "legendary": ["毁灭射线", "天罚炮"],
            },
            "shield": {
                "common": ["铁皮盾"],
                "uncommon": ["加固盾", "防爆盾"],
                "rare": ["合金盾", "能量盾"],
                "epic": ["纳米盾", "等离子护盾"],
                "legendary": ["不灭之盾", "绝对防御"],
            },
            "off_hand": {
                "common": ["旧零件"],
                "uncommon": ["工具包", "修理箱"],
                "rare": ["扫描仪", "干扰器"],
                "epic": ["纳米工具", "电磁干扰器"],
                "legendary": ["万能工具", "次元装置"],
            },
            "outfit": {
                "common": ["防弹背心", "厚皮夹克"],
                "uncommon": ["加固护甲", "防辐射服"],
                "rare": ["动力装甲", "纳米护盾"],
                "epic": ["泰坦装甲", "能量护盾"],
                "legendary": ["不灭战甲", "绝对防御"],
            },
        },
        "modern_power": {
            "one_handed": {
                "common": ["短棍", "折叠刀"],
                "uncommon": ["强化刀", "能量匕首"],
                "rare": ["暗影刃", "念力短剑"],
                "epic": ["虚空之刃", "毁灭之拳"],
                "legendary": ["弑神之刃", "永恒之拳"],
            },
            "two_handed": {
                "common": ["铁棍", "木棍"],
                "uncommon": ["强化长棍", "能量长矛"],
                "rare": ["暗影长戟", "念力巨剑"],
                "epic": ["虚空巨剑", "毁灭长枪"],
                "legendary": ["弑神枪", "永恒之枪"],
            },
            "ranged": {
                "common": ["旧弩", "弹弓"],
                "uncommon": ["强化弩", "能量手枪"],
                "rare": ["暗影弩", "念力手枪"],
                "epic": ["虚空弩", "毁灭手枪"],
                "legendary": ["弑神弩", "天罚"],
            },
            "wand": {
                "common": ["旧杖", "木杖"],
                "uncommon": ["灵能杖", "能量杖"],
                "rare": ["念力增幅器", "暗影法杖"],
                "epic": ["虚空法杖", "毁灭之杖"],
                "legendary": ["弑神法杖", "永恒之杖"],
            },
            "shield": {
                "common": ["木盾"],
                "uncommon": ["强化盾", "能量盾"],
                "rare": ["念力盾", "暗影盾"],
                "epic": ["虚空盾", "毁灭护盾"],
                "legendary": ["不灭之盾", "绝对防御"],
            },
            "off_hand": {
                "common": ["旧书"],
                "uncommon": ["笔记", "记录本"],
                "rare": ["古武秘籍", "念力手册"],
                "epic": ["虚空典籍", "毁灭之书"],
                "legendary": ["万法全书", "天道之书"],
            },
            "outfit": {
                "common": ["防刺背心", "皮夹克"],
                "uncommon": ["强化护甲", "能量护盾衣"],
                "rare": ["念力装甲", "暗影斗篷"],
                "epic": ["绝对防御", "不灭战衣"],
                "legendary": ["神盾", "天衣无缝"],
            },
        },
        "scifi": {
            "one_handed": {
                "common": ["振动刀", "激光匕首"],
                "uncommon": ["纳米刀", "等离子匕首"],
                "rare": ["量子刃", "反物质匕首"],
                "epic": ["暗物质刀", "时空刃"],
                "legendary": ["创世之刃", "永恒之刃"],
            },
            "two_handed": {
                "common": ["铁棍", "激光棒"],
                "uncommon": ["纳米巨剑", "等离子长矛"],
                "rare": ["量子巨剑", "反物质长戟"],
                "epic": ["暗物质巨剑", "时空长枪"],
                "legendary": ["创世之剑", "宇宙毁灭者"],
            },
            "ranged": {
                "common": ["激光手枪", "旧步枪"],
                "uncommon": ["等离子步枪", "激光步枪"],
                "rare": ["反物质炮", "量子步枪"],
                "epic": ["歼星炮", "时空步枪"],
                "legendary": ["宇宙毁灭者", "创世炮"],
            },
            "wand": {
                "common": ["能量棒", "激光棒"],
                "uncommon": ["等离子杖", "纳米杖"],
                "rare": ["量子发射器", "反物质杖"],
                "epic": ["暗物质发射器", "时空杖"],
                "legendary": ["创世之杖", "宇宙之杖"],
            },
            "shield": {
                "common": ["能量盾"],
                "uncommon": ["离子盾", "等离子盾"],
                "rare": ["量子盾", "纳米盾"],
                "epic": ["暗物质盾", "时空护盾"],
                "legendary": ["维度护盾", "不灭之盾"],
            },
            "off_hand": {
                "common": ["旧数据板"],
                "uncommon": ["扫描仪", "分析仪"],
                "rare": ["量子计算机", "AI核心"],
                "epic": ["暗物质核心", "时空核心"],
                "legendary": ["宇宙之心", "创世核心"],
            },
            "outfit": {
                "common": ["轻型护甲", "太空服"],
                "uncommon": ["重型护甲", "能量护盾"],
                "rare": ["纳米装甲", "量子护盾"],
                "epic": ["暗物质护甲", "时空护盾"],
                "legendary": ["不灭之甲", "维度护盾"],
            },
        },
    }

    # 品质 → 基础属性加成
    RARITY_BONUS = {
        "common":    {"bonus": 2, "stat_bonus": {}},
        "uncommon":  {"bonus": 4, "stat_bonus": {"strength": 1}},
        "rare":      {"bonus": 7, "stat_bonus": {"strength": 2, "agility": 1}},
        "epic":      {"bonus": 11, "stat_bonus": {"strength": 3, "agility": 2, "vitality": 1}},
        "legendary": {"bonus": 16, "stat_bonus": {"strength": 5, "agility": 3, "vitality": 2, "luck": 2}},
    }

    # 武器子类型 → 对应槽位
    SUBTYPE_SLOT_MAP = {
        "one_handed": "main_hand",
        "two_handed": "main_hand",
        "ranged": "ranged",
        "wand": "ranged",
        "shield": "off_hand",
        "off_hand": "off_hand",
    }

    # 装备槽位显示名称
    SLOT_NAMES = {
        "main_hand": "主手",
        "off_hand": "副手",
        "ranged": "远程",
        "outfit": "穿着",
    }

    SLOT_ICONS = {
        "main_hand": "🗡️",
        "off_hand": "🛡️",
        "ranged": "🏹",
        "outfit": "👕",
    }

    @staticmethod
    def _get_subtype_for_outfit() -> str:
        """穿着装备没有子类型，返回None"""
        return None

    @staticmethod
    def get_item_slot(item: Dict) -> str:
        """获取装备对应的槽位。
        优先读已记录的 equipped_slot（已穿戴的装备），没有再按 subtype 推断（背包里的物品）。
        这样双持时两把单手武器能区分 main_hand / off_hand。
        """
        # 已穿戴装备记录了实际槽位
        recorded = item.get("equipped_slot")
        if recorded:
            return recorded
        # 向后兼容：旧存档里可能存的是 "slot"
        recorded = item.get("slot")
        if recorded:
            return recorded
        # 背包里的物品：按 subtype 推断默认槽位
        eq_type = item.get("type", "weapon")
        if eq_type == "outfit":
            return "outfit"
        subtype = item.get("subtype", "one_handed")
        return EquipmentSystem.SUBTYPE_SLOT_MAP.get(subtype, "main_hand")

    @staticmethod
    def get_item_weight(item: Dict) -> int:
        """获取装备重量"""
        eq_type = item.get("type", "weapon")
        if eq_type == "outfit":
            return 3
        subtype = item.get("subtype", "one_handed")
        subtype_info = WEAPON_SUBTYPES.get(subtype, WEAPON_SUBTYPES["one_handed"])
        weight = subtype_info["weight_base"]
        # 品质越高越重（但重量也代表更好的材料）
        rarity_mult = {"common": 0.8, "uncommon": 1.0, "rare": 1.2, "epic": 1.4, "legendary": 1.6}
        weight = int(weight * rarity_mult.get(item.get("rarity", "common"), 1.0))
        return max(1, weight)

    @staticmethod
    def check_weight_penalty(character: Dict, item: Dict) -> Dict:
        """检查角色力量是否满足装备重量要求，返回减益信息"""
        strength = character.get("stats", {}).get("strength", 5)
        weight = EquipmentSystem.get_item_weight(item)
        if strength >= weight:
            return {"penalty": False, "weight": weight, "strength": strength}
        # 力量不足，计算减益
        diff = weight - strength
        penalty = {
            "hit_chance": -0.05 * diff,      # 命中率降低
            "damage": -0.08 * diff,           # 伤害降低
            "dodge": -0.03 * diff,            # 闪避降低
        }
        return {"penalty": True, "weight": weight, "strength": strength, "diff": diff, "penalty_values": penalty}

    @staticmethod
    def generate_equipment(world_type: str, eq_type: str, rarity: str,
                           enemy_level: int = 1, subtype: str = None) -> Dict:
        """生成一件装备"""
        config = ItemRarity.get_config(rarity)
        bonus_config = EquipmentSystem.RARITY_BONUS.get(rarity, EquipmentSystem.RARITY_BONUS["common"])

        if eq_type == "outfit":
            subtype = None
            slot = "outfit"
            # 名称
            names_pool = EquipmentSystem.EQUIPMENT_NAMES.get(world_type, EquipmentSystem.EQUIPMENT_NAMES["fantasy"])
            type_pool = names_pool.get("outfit", {})
            rarity_names = type_pool.get(rarity, type_pool.get("common", ["未知装备"]))
            name = random.choice(rarity_names)
            # 基础属性
            base_bonus = int(bonus_config["bonus"] * (1 + (enemy_level - 1) * 0.15))
            stat_bonus = {}
            for k, v in bonus_config.get("stat_bonus", {}).items():
                stat_bonus[k] = int(v * (1 + (enemy_level - 1) * 0.1))
            # 穿着额外加体质和运气
            stat_bonus["vitality"] = stat_bonus.get("vitality", 0) + int(config["multiplier"])
            if rarity in ("rare", "epic", "legendary"):
                stat_bonus["luck"] = stat_bonus.get("luck", 0) + int(config["multiplier"] * 0.5)
            weight = 3
            damage_type = "defense"
        else:
            # 武器：确定子类型
            if subtype is None:
                subtype = EquipmentSystem._roll_weapon_subtype()
            subtype_info = WEAPON_SUBTYPES.get(subtype, WEAPON_SUBTYPES["one_handed"])
            slot = subtype_info["slot"]
            damage_type = subtype_info["damage_type"]
            subtype_mult = SUBTYPE_BONUS_MULTIPLIER.get(subtype, 1.0)

            # 名称
            names_pool = EquipmentSystem.EQUIPMENT_NAMES.get(world_type, EquipmentSystem.EQUIPMENT_NAMES["fantasy"])
            type_pool = names_pool.get(subtype, names_pool.get("one_handed", {}))
            rarity_names = type_pool.get(rarity, type_pool.get("common", ["未知装备"]))
            name = random.choice(rarity_names)

            # 属性加成
            base_bonus = int(bonus_config["bonus"] * subtype_mult * (1 + (enemy_level - 1) * 0.15))
            stat_bonus = {}
            for k, v in bonus_config.get("stat_bonus", {}).items():
                stat_bonus[k] = int(v * (1 + (enemy_level - 1) * 0.1))

            # 双手武器额外加力量
            if subtype == "two_handed":
                stat_bonus["strength"] = stat_bonus.get("strength", 0) + int(config["multiplier"])
            # 盾牌额外加体质
            if subtype == "shield":
                stat_bonus["vitality"] = stat_bonus.get("vitality", 0) + int(config["multiplier"])
            # 远程武器和法杖额外加敏捷或智力
            if subtype == "ranged":
                stat_bonus["agility"] = stat_bonus.get("agility", 0) + int(config["multiplier"] * 0.5)
            if subtype == "wand":
                stat_bonus["intelligence"] = stat_bonus.get("intelligence", 0) + int(config["multiplier"])

            weight = EquipmentSystem.get_item_weight({"type": "weapon", "subtype": subtype, "rarity": rarity})

        return {
            "name": name,
            "type": eq_type,
            "subtype": subtype,
            "slot": slot,
            "damage_type": damage_type,
            "rarity": rarity,
            "rarity_name": config["name"],
            "color": config["color"],
            "bonus": base_bonus,
            "stat_bonus": stat_bonus,
            "weight": weight,
            "level_req": max(1, enemy_level - 2),
            "sell_price": int(base_bonus * 3 + enemy_level * 2),
        }

    @staticmethod
    def _roll_weapon_subtype() -> str:
        """随机选择武器子类型"""
        subtypes = list(WEAPON_SUBTYPE_WEIGHTS.keys())
        weights = [WEAPON_SUBTYPE_WEIGHTS[s] for s in subtypes]
        return random.choices(subtypes, weights=weights, k=1)[0]

    @staticmethod
    def roll_drop(enemy_level: int, enemy_type: str, luck: int = 5,
                  world_type: str = "fantasy") -> Optional[Dict]:
        """战斗胜利后掉落装备，返回 None 表示无掉落"""
        if enemy_type == "boss":
            drop_chance = 1.0
        elif enemy_type == "elite":
            drop_chance = 0.6
        else:
            drop_chance = 0.25

        if random.random() > drop_chance:
            return None

        rarity = ItemRarity.roll_rarity(luck, enemy_type)
        # 50% 武器 / 50% 穿着
        eq_type = random.choices(["weapon", "outfit"], weights=[50, 50], k=1)[0]

        return EquipmentSystem.generate_equipment(world_type, eq_type, rarity, enemy_level)

    @staticmethod
    def equip_item(character: Dict, item: Dict) -> Dict:
        """穿戴装备，同槽位替换，旧装备进背包。
        支持双持单手武器：主手已装单手武器时，第二把装到副手。
        双手武器占主手+副手。
        """
        equipment = character.get("equipment", [])
        inventory = character.get("inventory", [])
        subtype = item.get("subtype", "one_handed")

        # 穿着装备（衣服）没有 subtype，若保留默认"one_handed"会被误判成单手武器装进武器槽。
        # 强制置 None → 走下方 else 按 get_item_slot 落到 outfit（穿着）槽。
        if item.get("type") == "outfit":
            subtype = None

        # 找出当前主手/副手已装备的物品
        main_hand_item = None
        off_hand_item = None
        for eq in equipment:
            eq_slot = EquipmentSystem.get_item_slot(eq)
            if eq_slot == "main_hand":
                main_hand_item = eq
            elif eq_slot == "off_hand":
                off_hand_item = eq

        # 决定本次装备的目标槽位
        if subtype == "two_handed":
            # 双手武器：占主手+副手
            target_slot = "main_hand"
            occupied_slots = ["main_hand", "off_hand"]
        elif subtype == "one_handed":
            # 单手武器：智能选择主手或副手
            if main_hand_item is None:
                # 主手空 → 装主手
                target_slot = "main_hand"
                occupied_slots = ["main_hand"]
            elif main_hand_item.get("subtype") == "two_handed":
                # 主手是双手武器 → 替换掉双手武器（同时清空副手）
                target_slot = "main_hand"
                occupied_slots = ["main_hand", "off_hand"]
            elif off_hand_item is None:
                # 主手已装单手武器 + 副手空 → 装副手（双持）
                target_slot = "off_hand"
                occupied_slots = ["off_hand"]
            else:
                # 主手+副手都满 → 替换副手（玩家意图双持）
                target_slot = "off_hand"
                occupied_slots = ["off_hand"]
        else:
            # 其他类型（盾/副手物品/远程/穿着）按默认槽位
            target_slot = EquipmentSystem.get_item_slot(item)
            occupied_slots = [target_slot]

        # 收集被替换的旧装备
        old_items = []
        new_equipment = []
        for eq in equipment:
            eq_slot = EquipmentSystem.get_item_slot(eq)
            if eq_slot in occupied_slots:
                old_items.append(eq)
            else:
                new_equipment.append(eq)

        # 给新装备打上 equipped_slot 标记（双持时区分主/副手）
        # 同时更新 slot 字段，让前端无需改动
        item = dict(item)
        item["equipped_slot"] = target_slot
        item["slot"] = target_slot
        new_equipment.append(item)
        character["equipment"] = new_equipment

        # 旧装备进背包（清理槽位标记，恢复成"背包物品"状态）
        for old in old_items:
            old_clean = dict(old)
            old_clean.pop("equipped_slot", None)
            # 恢复 slot 为基于 subtype 的默认值（背包物品状态）
            old_subtype = old_clean.get("subtype", "one_handed")
            old_clean["slot"] = EquipmentSystem.SUBTYPE_SLOT_MAP.get(old_subtype, "main_hand")
            inventory.append(old_clean)
            character["inventory"] = inventory

        replaced_names = [o["name"] for o in old_items] if old_items else None

        return {
            "success": True,
            "equipped": item["name"],
            "slot": EquipmentSystem.SLOT_NAMES.get(target_slot, target_slot),
            "replaced": replaced_names,
            "rarity": item.get("rarity_name", "普通"),
        }

    @staticmethod
    def unequip_item(character: Dict, item_name: str) -> Dict:
        """卸下装备到背包，处理双手武器联动"""
        equipment = character.get("equipment", [])
        inventory = character.get("inventory", [])

        found = None
        new_equipment = []
        for eq in equipment:
            if eq.get("name") == item_name:
                found = eq
            else:
                new_equipment.append(eq)

        if not found:
            return {"success": False, "message": f"未穿戴 {item_name}"}

        # 如果是双手武器，同时卸下占用的副手槽位
        related_items = []
        if found.get("subtype") == "two_handed":
            related_items = [e for e in new_equipment if EquipmentSystem.get_item_slot(e) == "off_hand"]
            new_equipment = [e for e in new_equipment if EquipmentSystem.get_item_slot(e) != "off_hand"]

        character["equipment"] = new_equipment
        # 卸下的装备恢复成"背包物品"状态（清理槽位标记）
        found_clean = dict(found)
        found_clean.pop("equipped_slot", None)
        if found_clean.get("type") == "outfit":
            # 衣服（outfit）没有 subtype，slot 必须恢复为 outfit，避免被当成武器
            found_clean["slot"] = "outfit"
        else:
            found_subtype = found_clean.get("subtype", "one_handed")
            found_clean["slot"] = EquipmentSystem.SUBTYPE_SLOT_MAP.get(found_subtype, "main_hand")
        inventory.append(found_clean)
        character["inventory"] = inventory
        for ri in related_items:
            ri_clean = dict(ri)
            ri_clean.pop("equipped_slot", None)
            ri_subtype = ri_clean.get("subtype", "one_handed")
            ri_clean["slot"] = EquipmentSystem.SUBTYPE_SLOT_MAP.get(ri_subtype, "main_hand")
            inventory.append(ri_clean)
            character["inventory"] = inventory

        msg = f"卸下 {item_name}"
        if related_items:
            msg += f"（同时卸下 {'、'.join(r['name'] for r in related_items)}）"

        return {"success": True, "unequipped": item_name, "message": msg}

    @staticmethod
    def sell_item(character: Dict, item_name: str) -> Dict:
        """出售背包中的装备"""
        inventory = character.get("inventory", [])

        found = None
        new_inventory = []
        for item in inventory:
            if item.get("name") == item_name and not found:
                found = item
            else:
                new_inventory.append(item)

        if not found:
            return {"success": False, "message": f"背包中没有 {item_name}"}

        sell_price = found.get("sell_price", 5)
        character["inventory"] = new_inventory
        character["gold"] = character.get("gold", 0) + sell_price

        return {"success": True, "sold": item_name, "gold": sell_price}

    @staticmethod
    def get_equipment_summary(character: Dict) -> str:
        """获取装备摘要"""
        equipment = character.get("equipment", [])
        if not equipment:
            return "装备：无"

        parts = []
        for eq in equipment:
            slot_icon = EquipmentSystem.SLOT_ICONS.get(EquipmentSystem.get_item_slot(eq), "📦")
            parts.append(f"{slot_icon}{eq.get('name', '?')}({eq.get('rarity_name', '普通')})")

        return "装备：" + "、".join(parts)

    @staticmethod
    def get_inventory_summary(character: Dict) -> str:
        """获取背包摘要"""
        inventory = character.get("inventory", [])
        if not inventory:
            return "背包：空"

        parts = []
        for item in inventory:
            parts.append(f"{item.get('name', '?')}({item.get('rarity_name', '普通')})")

        return "背包：" + "、".join(parts[:5]) + (f" 等{len(inventory)}件" if len(inventory) > 5 else "")

    @staticmethod
    def get_equipment_by_slot(character: Dict, slot: str) -> Optional[Dict]:
        """按槽位获取装备"""
        for eq in character.get("equipment", []):
            if EquipmentSystem.get_item_slot(eq) == slot:
                return eq
        return None

    @staticmethod
    def get_equipment_damage_types(character: Dict) -> List[str]:
        """获取角色所有装备的伤害类型（用于战斗计算）"""
        types = set()
        for eq in character.get("equipment", []):
            dt = eq.get("damage_type")
            if dt and dt != "defense":
                types.add(dt)
        if not types:
            types.add("physical")  # 默认近战物理
        return list(types)

    @staticmethod
    def get_weapon_stats(character: Dict) -> Dict:
        """获取角色武器统计数据（用于战斗系统）"""
        result = {
            "physical_bonus": 0,   # 近战物理加成
            "ranged_bonus": 0,     # 远程物理加成
            "magic_bonus": 0,      # 法术加成
            "defense_bonus": 0,    # 防御加成
            "total_weight": 0,     # 总重量
            "weight_penalty": {},  # 重量减益
        }
        for eq in character.get("equipment", []):
            dt = eq.get("damage_type", "physical")
            bonus = eq.get("bonus", 0)
            weight = eq.get("weight", 0)
            result["total_weight"] += weight

            if dt == "physical":
                result["physical_bonus"] += bonus
            elif dt == "ranged":
                result["ranged_bonus"] += bonus
            elif dt == "magic":
                result["magic_bonus"] += bonus
            elif dt == "defense":
                result["defense_bonus"] += bonus

            # 检查重量惩罚
            penalty = EquipmentSystem.check_weight_penalty(character, eq)
            if penalty["penalty"]:
                for k, v in penalty["penalty_values"].items():
                    result["weight_penalty"][k] = result["weight_penalty"].get(k, 0) + v

        return result