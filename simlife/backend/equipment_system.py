"""
装备系统 — 装备池、掉落、穿戴、属性加成

核心设计：
- 装备按品质分级：普通(白) / 优秀(绿) / 稀有(蓝) / 史诗(紫) / 传说(橙)
- 只有两种装备位：武器 / 穿着（整套衣服/护甲）
- 战斗胜利后根据敌人等级/类型掉落装备
- 装备穿戴后属性加成立即生效（影响战斗判定）
- 同类型装备只能穿戴一件，替换时旧装备进入背包
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
# 装备生成
# ============================================================

class EquipmentSystem:
    """装备系统：生成、掉落、穿戴（只有武器+穿着两个位）"""

    EQUIPMENT_NAMES = {
        "fantasy": {
            "weapon": {
                "common": ["木棍", "生锈短剑", "粗制弓"],
                "uncommon": ["铁剑", "精制弓", "战斗法杖"],
                "rare": ["秘银长剑", "精灵之弓", "烈焰法杖"],
                "epic": ["龙牙巨剑", "暗影匕首", "圣光权杖"],
                "legendary": ["灭世之剑", "命运之弓", "创世法杖"],
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
            "weapon": {
                "common": ["铁剑", "木杖"],
                "uncommon": ["灵剑", "玄铁剑"],
                "rare": ["飞剑·青锋", "天雷符剑"],
                "epic": ["仙剑·紫霄", "灭世魔剑"],
                "legendary": ["天道剑", "混沌之剑"],
            },
            "outfit": {
                "common": ["道袍", "布衣"],
                "uncommon": ["灵丝法袍", "玄铁护甲"],
                "rare": ["金丝软甲", "天蚕丝袍"],
                "epic": ["九天玄甲", "万法不侵袍"],
                "legendary": ["不灭金身", "混元道袍"],
            },
        },
        "post_apocalyptic": {
            "weapon": {
                "common": ["铁管", "生锈刀"],
                "uncommon": ["改装手枪", "焊接刀"],
                "rare": ["等离子手枪", "合金刀"],
                "epic": ["电磁步枪", "纳米刀"],
                "legendary": ["毁灭者", "终结者之刃"],
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
            "weapon": {
                "common": ["短棍", "折叠刀"],
                "uncommon": ["能量手套", "强化刀"],
                "rare": ["念力增幅器", "暗影刃"],
                "epic": ["毁灭之拳", "虚空之刃"],
                "legendary": ["天罚", "弑神之刃"],
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
            "weapon": {
                "common": ["激光手枪", "振动刀"],
                "uncommon": ["等离子步枪", "纳米刀"],
                "rare": ["反物质炮", "量子刃"],
                "epic": ["歼星炮", "暗物质刀"],
                "legendary": ["宇宙毁灭者", "创世之刃"],
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

    @staticmethod
    def generate_equipment(world_type: str, eq_type: str, rarity: str,
                           enemy_level: int = 1) -> Dict:
        """生成一件装备（weapon / outfit）"""
        config = ItemRarity.get_config(rarity)
        bonus_config = EquipmentSystem.RARITY_BONUS.get(rarity, EquipmentSystem.RARITY_BONUS["common"])

        # 名称
        names_pool = EquipmentSystem.EQUIPMENT_NAMES.get(world_type, EquipmentSystem.EQUIPMENT_NAMES["fantasy"])
        type_pool = names_pool.get(eq_type, names_pool.get("weapon", {}))
        rarity_names = type_pool.get(rarity, type_pool.get("common", ["未知装备"]))
        name = random.choice(rarity_names)

        # 属性加成
        base_bonus = int(bonus_config["bonus"] * (1 + (enemy_level - 1) * 0.15))
        stat_bonus = {}
        for k, v in bonus_config.get("stat_bonus", {}).items():
            stat_bonus[k] = int(v * (1 + (enemy_level - 1) * 0.1))

        # 穿着额外加体质和运气
        if eq_type == "outfit":
            stat_bonus["vitality"] = stat_bonus.get("vitality", 0) + int(config["multiplier"])
            if rarity in ("rare", "epic", "legendary"):
                stat_bonus["luck"] = stat_bonus.get("luck", 0) + int(config["multiplier"] * 0.5)

        return {
            "name": name,
            "type": eq_type,
            "rarity": rarity,
            "rarity_name": config["name"],
            "color": config["color"],
            "bonus": base_bonus,
            "stat_bonus": stat_bonus,
            "level_req": max(1, enemy_level - 2),
            "sell_price": int(base_bonus * 3 + enemy_level * 2),
        }

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
        eq_type = random.choices(["weapon", "outfit"], weights=[55, 45], k=1)[0]

        return EquipmentSystem.generate_equipment(world_type, eq_type, rarity, enemy_level)

    @staticmethod
    def equip_item(character: Dict, item: Dict) -> Dict:
        """穿戴装备，同类型替换，旧装备进背包"""
        eq_type = item.get("type", "weapon")
        equipment = character.get("equipment", [])
        inventory = character.get("inventory", [])

        old_item = None
        new_equipment = []
        for eq in equipment:
            if eq.get("type") == eq_type:
                old_item = eq
            else:
                new_equipment.append(eq)

        new_equipment.append(item)
        character["equipment"] = new_equipment

        if old_item:
            inventory.append(old_item)
            character["inventory"] = inventory

        return {
            "success": True,
            "equipped": item["name"],
            "replaced": old_item["name"] if old_item else None,
            "rarity": item.get("rarity_name", "普通"),
        }

    @staticmethod
    def unequip_item(character: Dict, item_name: str) -> Dict:
        """卸下装备到背包"""
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

        character["equipment"] = new_equipment
        inventory.append(found)
        character["inventory"] = inventory

        return {"success": True, "unequipped": item_name}

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
            icon = {"weapon": "🗡️", "outfit": "🛡️"}.get(eq.get("type", ""), "📦")
            parts.append(f"{icon}{eq.get('name', '?')}({eq.get('rarity_name', '普通')})")

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
