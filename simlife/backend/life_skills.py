"""
生活技能系统（Life Skills）
烹饪 / 锻造 / 钓鱼 三个生活技能，独立于战斗系统。

核心设计：
- 原材料（Ingredient）：从商店购买、钓鱼获得、战斗掉落、探索采集
- 菜谱（Recipe）：分「固定菜谱」与「自由组合」，烹饪按顺序步骤判定
- 设计图（Blueprint）：锻造图纸，按真实锻造工艺步骤（加热/锻打/淬火/成型）判定
- 鱼类（Fish）：参考魔兽世界设定，按水域/稀有度/体型区分
- 判定系统：依据角色生活技能等级 + 步骤精确度给出 完美/良好/普通/失败

数据全部存于 state["life_state"]，商品与配方为静态数据（本模块常量）。
"""
from typing import Dict, List, Optional, Any
from datetime import datetime
import random


# ── 原材料（商店出售 + 钓鱼/掉落获得）────────────────────
# id: 唯一标识  name: 名称  type: 材料类型  price: 商店售价
# 材料类型用于区分各技能用途：ingredient(烹饪) ore(锻造) fish(钓鱼产出) misc(杂项)

RAW_MATERIALS: List[Dict] = [
    # ── 烹饪食材 ──
    {"id": "wheat", "name": "小麦", "type": "ingredient", "price": 3, "icon": "🌾"},
    {"id": "rice", "name": "大米", "type": "ingredient", "price": 3, "icon": "🍚"},
    {"id": "egg", "name": "鸡蛋", "type": "ingredient", "price": 4, "icon": "🥚"},
    {"id": "milk", "name": "牛奶", "type": "ingredient", "price": 5, "icon": "🥛"},
    {"id": "meat", "name": "鲜肉", "type": "ingredient", "price": 8, "icon": "🥩"},
    {"id": "fish_meat", "name": "鱼肉", "type": "ingredient", "price": 6, "icon": "🐟"},
    {"id": "vegetable", "name": "蔬菜", "type": "ingredient", "price": 4, "icon": "🥬"},
    {"id": "mushroom", "name": "蘑菇", "type": "ingredient", "price": 5, "icon": "🍄"},
    {"id": "herb", "name": "香料", "type": "ingredient", "price": 6, "icon": "🌿"},
    {"id": "salt", "name": "盐", "type": "ingredient", "price": 2, "icon": "🧂"},
    {"id": "honey", "name": "蜂蜜", "type": "ingredient", "price": 7, "icon": "🍯"},
    {"id": "fruit", "name": "水果", "type": "ingredient", "price": 5, "icon": "🍎"},
    # ── 锻造材料 ──
    {"id": "iron_ore", "name": "铁矿石", "type": "ore", "price": 10, "icon": "⛏"},
    {"id": "copper_ore", "name": "铜矿石", "type": "ore", "price": 7, "icon": "⛏"},
    {"id": "silver_ore", "name": "银矿石", "type": "ore", "price": 15, "icon": "⛏"},
    {"id": "gold_ore", "name": "金矿石", "type": "ore", "price": 20, "icon": "⛏"},
    {"id": "coal", "name": "煤炭", "type": "ore", "price": 5, "icon": "🪨"},
    {"id": "mithril", "name": "秘银", "type": "ore", "price": 40, "icon": "✨"},
    {"id": "leather", "name": "皮革", "type": "misc", "price": 8, "icon": "👜"},
    {"id": "wood", "name": "木材", "type": "misc", "price": 4, "icon": "🪵"},
    {"id": "string", "name": "丝线", "type": "misc", "price": 3, "icon": "🧵"},
    # ── 钓鱼材料（蚯蚓/鱼饵） ──
    {"id": "worm", "name": "蚯蚓", "type": "bait", "price": 2, "icon": "🪱"},
    {"id": "bait", "name": "高级鱼饵", "type": "bait", "price": 8, "icon": "🎣"},
    # ── 附魔材料（锻造附魔工序专用，探索/战斗掉落，商店限级购买） ──
    {"id": "magic_stone", "name": "魔法石", "type": "enchant", "price": 25, "icon": "🔮"},
    {"id": "life_petal", "name": "生命花瓣", "type": "enchant", "price": 28, "icon": "🌸"},
    {"id": "fire_rune", "name": "火焰符文", "type": "enchant", "price": 30, "icon": "🔥"},
    {"id": "frost_rune", "name": "寒冰符文", "type": "enchant", "price": 30, "icon": "❄️"},
    {"id": "storm_rune", "name": "雷霆符文", "type": "enchant", "price": 35, "icon": "⚡"},
    {"id": "soul_crystal", "name": "灵魂水晶", "type": "enchant", "price": 60, "icon": "💎"},
    {"id": "dragon_scale", "name": "龙鳞", "type": "enchant", "price": 80, "icon": "🐉"},
]


# ── 鱼类（参考 diaoyu 原项目：力量/攻击性/耐力/体重/价值/水域/家族）──
# 字段含义：
#   family: 家族（与鱼饵偏好联动）  strength: 拉力(搏斗张力)  aggress: 攻击性(咬钩率)
#   fight: 挣扎热情(耐力)  min/max: 体重范围kg  value: 每公斤售价  energy: 每公斤食用回复HP
#   zones: 出没水域  legendary: 传说级  color: 绘制颜色
FISH_TABLE: List[Dict] = [
    # ── 老磨坊池塘 (新手) ──
    {"id": "bream", "name": "太平鱼", "family": "杂鱼", "min": 0.3, "max": 1.2, "value": 8, "strength": 14, "aggress": 0.9, "fight": 22, "energy": 20, "rarity": "common", "color": "#b8a24e", "zones": ["pond"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "none", "pattern": "none", "mark": "none"}},
    {"id": "perch", "name": "河鲈", "family": "鲈鱼", "min": 0.4, "max": 1.8, "value": 14, "strength": 22, "aggress": 0.8, "fight": 30, "energy": 22, "rarity": "common", "color": "#86a15a", "zones": ["pond", "lake"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "stripes", "mark": "none"}},
    {"id": "roach", "name": "北欧鲤", "family": "鲤科", "min": 0.5, "max": 3.0, "value": 20, "strength": 30, "aggress": 0.7, "fight": 40, "energy": 25, "rarity": "common", "color": "#c98b3d", "zones": ["pond", "lake"], "icon": "🐠", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "scales", "mark": "none"}},
    {"id": "trout", "name": "溪鳟", "family": "鳟鱼", "min": 0.5, "max": 2.5, "value": 32, "strength": 38, "aggress": 0.6, "fight": 48, "energy": 30, "rarity": "rare", "color": "#5f9ea0", "zones": ["pond", "lake"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fan", "fin": "adipose", "pattern": "spots", "mark": "none"}},
    {"id": "minnow", "name": "白条鱼", "family": "杂鱼", "min": 0.1, "max": 0.4, "value": 5, "strength": 8, "aggress": 0.95, "fight": 15, "energy": 12, "rarity": "common", "color": "#c7cfdd", "zones": ["pond"], "icon": "🐟", "silhouette": {"body": "slender", "tail": "fork", "fin": "none", "pattern": "none", "mark": "none"}},
    {"id": "crucian", "name": "鲫鱼", "family": "鲤科", "min": 0.2, "max": 1.5, "value": 10, "strength": 20, "aggress": 0.8, "fight": 35, "energy": 22, "rarity": "common", "color": "#9a9a6a", "zones": ["pond", "lake"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "scales", "mark": "none"}},
    {"id": "tilapia", "name": "罗非鱼", "family": "慈鲷", "min": 0.3, "max": 2.0, "value": 12, "strength": 24, "aggress": 0.85, "fight": 34, "energy": 24, "rarity": "common", "color": "#7a8a6a", "zones": ["pond", "lake"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "stripes", "mark": "none"}},
    {"id": "gudgeon", "name": "麦穗鱼", "family": "杂鱼", "min": 0.05, "max": 0.3, "value": 4, "strength": 6, "aggress": 0.98, "fight": 12, "energy": 10, "rarity": "common", "color": "#b9c3d0", "zones": ["pond"], "icon": "🐟", "silhouette": {"body": "slender", "tail": "fan", "fin": "none", "pattern": "none", "mark": "none"}},
    # ── 月光湖 (进阶) ──
    {"id": "pike", "name": "北方梭鱼", "family": "梭鱼", "min": 1.0, "max": 8.0, "value": 26, "strength": 52, "aggress": 0.5, "fight": 70, "energy": 28, "rarity": "rare", "color": "#7a9b4e", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fork", "fin": "dorsal", "pattern": "spots", "mark": "none"}},
    {"id": "zander", "name": "梭鲈", "family": "鲈鱼", "min": 0.8, "max": 6.0, "value": 30, "strength": 48, "aggress": 0.5, "fight": 62, "energy": 30, "rarity": "rare", "color": "#8fbf6f", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fork", "fin": "dorsal", "pattern": "stripes", "mark": "none"}},
    {"id": "carp", "name": "镜鲤", "family": "鲤科", "min": 1.5, "max": 12, "value": 22, "strength": 58, "aggress": 0.4, "fight": 90, "energy": 32, "rarity": "epic", "color": "#d4a24a", "zones": ["lake", "pond"], "icon": "🐠", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "scales", "mark": "whisker"}},
    {"id": "asp", "name": "赤梢鱼", "family": "鲤科", "min": 0.6, "max": 4.0, "value": 34, "strength": 44, "aggress": 0.6, "fight": 55, "energy": 28, "rarity": "rare", "color": "#b8c4d0", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fork", "fin": "dorsal", "pattern": "none", "mark": "none"}},
    {"id": "tench", "name": "丁鳜", "family": "鲤科", "min": 0.8, "max": 6.0, "value": 24, "strength": 46, "aggress": 0.55, "fight": 68, "energy": 30, "rarity": "rare", "color": "#8a9a5a", "zones": ["lake"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "none", "mark": "none"}},
    {"id": "blackbass", "name": "大口黑鲈", "family": "鲈鱼", "min": 0.5, "max": 5.0, "value": 28, "strength": 40, "aggress": 0.6, "fight": 75, "energy": 28, "rarity": "rare", "color": "#6b8e4e", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fan", "fin": "dorsal", "pattern": "spots", "mark": "none"}},
    {"id": "bream_lake", "name": "青鱼", "family": "鲤科", "min": 1.0, "max": 20, "value": 26, "strength": 62, "aggress": 0.4, "fight": 110, "energy": 34, "rarity": "epic", "color": "#5a6a5a", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fork", "fin": "dorsal", "pattern": "none", "mark": "none"}},
    {"id": "grasscarp", "name": "草鱼", "family": "鲤科", "min": 1.0, "max": 15, "value": 24, "strength": 60, "aggress": 0.45, "fight": 100, "energy": 33, "rarity": "epic", "color": "#6a7a4a", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fork", "fin": "dorsal", "pattern": "scales", "mark": "none"}},
    {"id": "culter", "name": "翘嘴鲌", "family": "鲤科", "min": 0.5, "max": 5.0, "value": 32, "strength": 42, "aggress": 0.6, "fight": 60, "energy": 28, "rarity": "rare", "color": "#c9d4e0", "zones": ["lake", "river"], "icon": "🐟", "silhouette": {"body": "slender", "tail": "fork", "fin": "dorsal", "pattern": "none", "mark": "none"}},
    # ── 暗礁河 (困难) ──
    {"id": "catfish", "name": "六须鲶", "family": "鲶鱼", "min": 2.0, "max": 30, "value": 18, "strength": 70, "aggress": 0.3, "fight": 120, "energy": 35, "rarity": "epic", "color": "#6b5b4a", "zones": ["river"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "none", "pattern": "none", "mark": "whisker"}},
    {"id": "sturgeon", "name": "欧洲鲟", "family": "鲟鱼", "min": 3.0, "max": 40, "value": 40, "strength": 80, "aggress": 0.25, "fight": 140, "energy": 40, "rarity": "epic", "color": "#8a8a8a", "zones": ["river"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fork", "fin": "dorsal", "pattern": "scales", "mark": "snout"}},
    {"id": "salmon", "name": "大西洋鲑", "family": "鲑鱼", "min": 1.5, "max": 15, "value": 45, "strength": 62, "aggress": 0.5, "fight": 85, "energy": 38, "rarity": "epic", "color": "#9ec6d0", "zones": ["river"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fork", "fin": "adipose", "pattern": "spots", "mark": "none"}},
    {"id": "burbot", "name": "江鳕", "family": "鳕鱼", "min": 0.8, "max": 6.0, "value": 28, "strength": 50, "aggress": 0.45, "fight": 65, "energy": 30, "rarity": "rare", "color": "#a08a5a", "zones": ["river", "pond"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fan", "fin": "dorsal", "pattern": "spots", "mark": "whisker"}},
    {"id": "eel", "name": "鳗鲡", "family": "鳗鱼", "min": 0.5, "max": 8.0, "value": 36, "strength": 48, "aggress": 0.5, "fight": 95, "energy": 36, "rarity": "epic", "color": "#4a5a4a", "zones": ["river"], "icon": "🐍", "silhouette": {"body": "serpent", "tail": "none", "fin": "none", "pattern": "none", "mark": "none"}},
    {"id": "trout_brown", "name": "褐鳟", "family": "鳟鱼", "min": 0.4, "max": 4.0, "value": 34, "strength": 42, "aggress": 0.55, "fight": 70, "energy": 32, "rarity": "rare", "color": "#b0805a", "zones": ["river", "lake"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fan", "fin": "adipose", "pattern": "spots", "mark": "none"}},
    {"id": "salmon_chum", "name": "驼背大麻哈", "family": "鲑鱼", "min": 1.0, "max": 10, "value": 40, "strength": 56, "aggress": 0.45, "fight": 80, "energy": 36, "rarity": "epic", "color": "#c08060", "zones": ["river"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fork", "fin": "adipose", "pattern": "stripes", "mark": "none"}},
    {"id": "mandarinfish", "name": "鳜鱼", "family": "鲈鱼", "min": 0.5, "max": 8.0, "value": 38, "strength": 54, "aggress": 0.5, "fight": 78, "energy": 34, "rarity": "rare", "color": "#7a8a4e", "zones": ["river", "lake"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "spots", "mark": "none"}},
    {"id": "yellow_catfish", "name": "黄颡鱼", "family": "鲶鱼", "min": 0.2, "max": 1.5, "value": 20, "strength": 28, "aggress": 0.7, "fight": 40, "energy": 26, "rarity": "common", "color": "#c9a03a", "zones": ["river", "pond"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "none", "pattern": "none", "mark": "whisker"}},
    # ── 深渊之眼 (精英/赏金) ──
    {"id": "tuna", "name": "蓝鳍金枪", "family": "金枪鱼", "min": 10, "max": 200, "value": 38, "strength": 95, "aggress": 0.4, "fight": 200, "energy": 60, "rarity": "legendary", "color": "#3d5a80", "zones": ["abyss"], "icon": "🐋", "silhouette": {"body": "torpedo", "tail": "crescent", "fin": "dorsal", "pattern": "none", "mark": "none"}},
    {"id": "amberjack", "name": "琥珀鱼", "family": "鲹科", "min": 3.0, "max": 40, "value": 30, "strength": 72, "aggress": 0.5, "fight": 110, "energy": 45, "rarity": "epic", "color": "#e0a04a", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "fork", "fin": "dorsal", "pattern": "stripes", "mark": "none"}},
    {"id": "swordfish", "name": "剑鱼", "family": "旗鱼", "min": 8.0, "max": 120, "value": 52, "strength": 88, "aggress": 0.35, "fight": 160, "energy": 55, "rarity": "legendary", "color": "#6a7a92", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "crescent", "fin": "dorsal", "pattern": "none", "mark": "sail"}},
    {"id": "goliath", "name": "巨型石斑", "family": "石斑鱼", "min": 5.0, "max": 80, "value": 35, "strength": 78, "aggress": 0.4, "fight": 130, "energy": 50, "rarity": "epic", "color": "#8a6a4a", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "spots", "mark": "none"}},
    {"id": "monster", "name": "湖中巨怪", "family": "传说", "min": 20, "max": 500, "value": 88, "strength": 99, "aggress": 0.15, "fight": 300, "energy": 100, "rarity": "legendary", "color": "#5a4a8a", "zones": ["abyss"], "icon": "🐲", "legendary": True, "silhouette": {"body": "serpent", "tail": "none", "fin": "dorsal", "pattern": "scales", "mark": "horn"}},
    {"id": "marlin", "name": "大西洋旗鱼", "family": "旗鱼", "min": 10, "max": 150, "value": 55, "strength": 90, "aggress": 0.4, "fight": 180, "energy": 58, "rarity": "legendary", "color": "#4a5a8a", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "torpedo", "tail": "crescent", "fin": "dorsal", "pattern": "stripes", "mark": "sail"}},
    {"id": "cod_atlantic", "name": "大西洋鳕", "family": "鳕鱼", "min": 1.0, "max": 12, "value": 22, "strength": 55, "aggress": 0.5, "fight": 90, "energy": 32, "rarity": "epic", "color": "#7a8a6a", "zones": ["abyss", "river"], "icon": "🐟", "silhouette": {"body": "elongated", "tail": "fan", "fin": "dorsal", "pattern": "spots", "mark": "whisker"}},
    {"id": "deep_angler", "name": "深海鮟鱇", "family": "深海", "min": 2.0, "max": 25, "value": 42, "strength": 60, "aggress": 0.5, "fight": 120, "energy": 45, "rarity": "epic", "color": "#3a3a4a", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "bulbous", "tail": "fan", "fin": "none", "pattern": "spots", "mark": "lantern"}},
    {"id": "mantaray", "name": "深海魔魟", "family": "深海", "min": 15, "max": 180, "value": 60, "strength": 75, "aggress": 0.3, "fight": 210, "energy": 70, "rarity": "legendary", "color": "#5a5a7a", "zones": ["abyss"], "icon": "🦈", "silhouette": {"body": "ray", "tail": "none", "fin": "none", "pattern": "none", "mark": "none"}},
    {"id": "hairtail", "name": "带鱼", "family": "鲹科", "min": 0.5, "max": 5.0, "value": 26, "strength": 50, "aggress": 0.55, "fight": 70, "energy": 30, "rarity": "epic", "color": "#b9c4d6", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "serpent", "tail": "none", "fin": "none", "pattern": "none", "mark": "none"}},
    {"id": "yellowcroaker", "name": "大黄鱼", "family": "鲈鱼", "min": 1.0, "max": 8.0, "value": 36, "strength": 52, "aggress": 0.5, "fight": 85, "energy": 36, "rarity": "epic", "color": "#d1a03a", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "dorsal", "pattern": "scales", "mark": "none"}},
    {"id": "pomfret", "name": "银鲳", "family": "鲹科", "min": 0.5, "max": 4.0, "value": 30, "strength": 40, "aggress": 0.6, "fight": 60, "energy": 32, "rarity": "rare", "color": "#c7d0da", "zones": ["abyss"], "icon": "🐟", "silhouette": {"body": "oval", "tail": "fan", "fin": "none", "pattern": "none", "mark": "none"}},
]


# ── 水域（参考 diaoyu 原项目：按累计收益解锁）────────────────
# id  name  need(解锁所需累计收益)  difficulty  desc
FISH_ZONES: List[Dict] = [
    {"id": "pond",  "name": "老磨坊池塘", "need": 0,    "difficulty": "新手", "desc": "风平浪静的小池塘，适合入门。"},
    {"id": "lake",  "name": "月光湖",     "need": 200,  "difficulty": "进阶", "desc": "明澈的湖面，藏着大鱼。"},
    {"id": "river", "name": "暗礁河",     "need": 800,  "difficulty": "困难", "desc": "水流湍急，物产凶猛。"},
    {"id": "abyss", "name": "深渊之眼",   "need": 2500, "difficulty": "精英", "desc": "深海与深渊交汇之处，只容强者。"},
]
_ENGLISH_ZONE = {"pond": "老磨坊池塘", "lake": "月光湖", "river": "暗礁河", "abyss": "深渊之眼"}


# ── 钓鱼装备（参考 diaoyu 原项目：杆/轮/线/饵 四槽位）────────
# 鱼竿 rods: cast(抛投力) fight(刺鱼/控鱼加成)
FISH_RODS: List[Dict] = [
    {"id": "rod1", "name": "木竿", "price": 0, "cast": 40, "fight": 10, "icon": "🪵", "desc": "新手木竿，够用。"},
    {"id": "rod2", "name": "碳素竿", "price": 300, "cast": 60, "fight": 20, "icon": "🎣", "desc": "轻盈坚韧，抛得更远。"},
    {"id": "rod3", "name": "鲟鱼重竿", "price": 1200, "cast": 80, "fight": 35, "icon": "🏹", "desc": "专为巨物打造的强竿。"},
    {"id": "rod4", "name": "深渊神竿", "price": 4000, "cast": 100, "fight": 55, "icon": "✨", "desc": "传世神兵，无所不钓。"},
]
# 卷线轮 reels: speed(收线速度) drag(泄力/张力吸收)
FISH_REELS: List[Dict] = [
    {"id": "reel1", "name": "基础轮", "price": 0, "speed": 30, "drag": 0, "icon": "⚙️", "desc": "转起来有点涩。"},
    {"id": "reel2", "name": "轻量轮", "price": 400, "speed": 50, "drag": 10, "icon": "⚙️", "desc": "顺滑轻快。"},
    {"id": "reel3", "name": "强攻轮", "price": 1500, "speed": 70, "drag": 25, "icon": "⚙️", "desc": "大拖力，抗冲击。"},
    {"id": "reel4", "name": "星辰滑轮", "price": 5000, "speed": 95, "drag": 45, "icon": "✨", "desc": "收线如行云流水。"},
]
# 鱼线 lines: maxTension(强度/断线阈值)
FISH_LINES: List[Dict] = [
    {"id": "line1", "name": "尼龙线", "price": 0, "maxTension": 90, "icon": "🧵", "desc": "弹性好但强度一般。"},
    {"id": "line2", "name": "编织线", "price": 500, "maxTension": 110, "icon": "🧵", "desc": "高强低延展。"},
    {"id": "line3", "name": "氟碳线", "price": 1800, "maxTension": 160, "icon": "🧵", "desc": "水下隐形，强度惊人。"},
    {"id": "line4", "name": "神之钓线", "price": 6000, "maxTension": 240, "icon": "✨", "desc": "几乎不可能被拉断。"},
]
# 鱼饵 baits: bite(咬钩加成) family(偏好鱼群)
FISH_BAITS: List[Dict] = [
    {"id": "bait1", "name": "蚯蚓", "price": 0, "family": "杂鱼", "bite": 1.15, "icon": "🪱", "desc": "万能饵，新手之友。"},
    {"id": "bait2", "name": "玉米粒", "price": 80, "family": "鲤科", "bite": 1.30, "icon": "🌽", "desc": "鲤科的最爱。"},
    {"id": "bait3", "name": "活小鱼", "price": 200, "family": "鲈鱼", "bite": 1.35, "icon": "🐟", "desc": "吸引掠食鱼类。"},
    {"id": "bait4", "name": "香肠丁", "price": 350, "family": "鲶鱼", "bite": 1.40, "icon": "🌭", "desc": "鲶鱼和鳕鱼难以抗拒。"},
    {"id": "bait5", "name": "虾肉", "price": 600, "family": "深海", "bite": 1.45, "icon": "🦐", "desc": "深海鱼的美味。"},
    {"id": "bait6", "name": "黄金鱼饵", "price": 2000, "family": "传说", "bite": 1.60, "icon": "✨", "desc": "传说级诱饵，吸引巨物。"},
]
# 装备合并表，便于按 id 查找
FISH_GEAR_LISTS: Dict[str, List[Dict]] = {
    "rod": FISH_RODS, "reel": FISH_REELS, "line": FISH_LINES, "bait": FISH_BAITS,
}
_GEAR_ICON = {"rod": "🎣", "reel": "⚙️", "line": "🧵", "bait": "🪱"}


# ── 固定菜谱（烹饪）────────────────────────────────────
# materials: 所需材料 id 列表  steps: 顺序步骤（判定的关键）  result: 产物
# buff: 服用后获得的临时增益 {type: hp/mp/attack/defense, value, turns}

COOK_RECIPES: List[Dict] = [
    {"id": "bread", "name": "烤面包", "icon": "🍞", "level": 1, "materials": [["wheat", 2], ["salt", 1]],
     "steps": ["和面", "揉面", "烘烤"], "result": {"name": "烤面包", "type": "food", "icon": "🍞"},
     "buff": {"type": "hp", "value": 40, "turns": 0}},
    {"id": "fried_egg", "name": "煎蛋", "icon": "🍳", "level": 1, "materials": [["egg", 2], ["salt", 1]],
     "steps": ["打蛋", "热锅", "煎制"], "result": {"name": "煎蛋", "type": "food", "icon": "🍳"},
     "buff": {"type": "hp", "value": 35, "turns": 0}},
    {"id": "meat_skewer", "name": "烤肉串", "icon": "🍢", "level": 2, "materials": [["meat", 2], ["herb", 1]],
     "steps": ["腌制", "串签", "烤制"], "result": {"name": "烤肉串", "type": "food", "icon": "🍢"},
     "buff": {"type": "mp", "value": 30, "turns": 0}},
    {"id": "fish_soup", "name": "鲜鱼汤", "icon": "🍲", "level": 2, "materials": [["fish_meat", 2], ["vegetable", 1], ["salt", 1]],
     "steps": ["切鱼", "爆香", "炖煮"], "result": {"name": "鲜鱼汤", "type": "food", "icon": "🍲"},
     "buff": {"type": "hp", "value": 60, "turns": 0}},
    {"id": "mushroom_stew", "name": "蘑菇炖菜", "icon": "🥘", "level": 3, "materials": [["mushroom", 2], ["vegetable", 1], ["herb", 1]],
     "steps": ["备料", "爆炒", "炖煮"], "result": {"name": "蘑菇炖菜", "type": "food", "icon": "🥘"},
     "buff": {"type": "hp", "value": 70, "turns": 0}},
    {"id": "honey_cake", "name": "蜂蜜蛋糕", "icon": "🍰", "level": 3, "materials": [["wheat", 2], ["honey", 2], ["egg", 1]],
     "steps": ["和面", "加蜜", "烘烤"], "result": {"name": "蜂蜜蛋糕", "type": "food", "icon": "🍰"},
     "buff": {"type": "mp", "value": 50, "turns": 0}},
    {"id": "beef_platter", "name": "豪华全餐", "icon": "🍖", "level": 4, "materials": [["meat", 3], ["vegetable", 2], ["herb", 1], ["salt", 1]],
     "steps": ["备料", "腌制", "煎制", "摆盘"], "result": {"name": "豪华全餐", "type": "food", "icon": "🍖"},
     "buff": {"type": "hp", "value": 100, "turns": 0}},
    {"id": "golden_meal", "name": "黄金盛宴", "icon": "👑", "level": 5, "materials": [["meat", 3], ["fish_meat", 2], ["honey", 2], ["mushroom", 2], ["herb", 2]],
     "steps": ["精选食材", "分批烹制", "秘制调味", "华丽装盘"], "result": {"name": "黄金盛宴", "type": "food", "icon": "👑"},
     "buff": {"type": "attack", "value": 15, "turns": 3}},
]


# ── 锻造设计图（真实锻造工艺）────────────────────────────
# materials: 所需材料  steps: 真实工艺步骤序列（判定关键）
# 步骤释义：选材→加热→锻打→淬火→回火→成型→打磨
# 锻造品质取决于各步骤的执行精度（完美/良好/普通由时机判定）

FORGE_BLUEPRINTS: List[Dict] = [
    {"id": "iron_dagger", "name": "铁匕首", "icon": "🔪", "level": 1, "materials": [["iron_ore", 2], ["coal", 2], ["wood", 1]],
     "steps": ["选材", "加热", "锻打", "淬火", "成型"],
     "result": {"name": "铁匕首", "type": "weapon", "icon": "🔪", "damage_type": "physical", "bonus": 8}},
    {"id": "copper_sword", "name": "铜剑", "icon": "⚔️", "level": 1, "materials": [["copper_ore", 3], ["coal", 2]],
     "steps": ["选材", "加热", "锻打", "淬火", "成型"],
     "result": {"name": "铜剑", "type": "weapon", "icon": "⚔️", "damage_type": "physical", "bonus": 10}},
    {"id": "iron_sword", "name": "铁剑", "icon": "⚔️", "level": 2, "materials": [["iron_ore", 3], ["coal", 2], ["leather", 1]],
     "steps": ["选材", "加热", "锻打", "折叠锻打", "淬火", "成型"],
     "result": {"name": "铁剑", "type": "weapon", "icon": "⚔️", "damage_type": "physical", "bonus": 14}},
    {"id": "silver_shield", "name": "银盾", "icon": "🛡️", "level": 3, "materials": [["silver_ore", 3], ["coal", 2], ["leather", 1]],
     "steps": ["选材", "加热", "锻打", "淬火", "回火", "成型"],
     "result": {"name": "银盾", "type": "outfit", "icon": "🛡️", "damage_type": "defense", "bonus": 16}},
    {"id": "mithril_sword", "name": "秘银长剑", "icon": "⚔️", "level": 4, "materials": [["mithril", 3], ["silver_ore", 2], ["coal", 3], ["leather", 1]],
     "steps": ["选材", "加热", "锻打", "折叠锻打", "淬火", "回火", "成型"],
     "result": {"name": "秘银长剑", "type": "weapon", "icon": "⚔️", "damage_type": "physical", "bonus": 26}},
    # ── 钓鱼装备（锻造产出，非武器/防具）────────────────
    # fishing_gear: 锻造成功后将对应钓鱼装备加入已拥有列表
    {"id": "forge_rod2", "name": "工匠碳素竿", "icon": "🎣", "level": 2, "materials": [["wood", 2], ["string", 2], ["iron_ore", 1], ["coal", 1]],
     "steps": ["选材", "加热", "锻打", "淬火", "成型"],
     "fishing_gear": {"slot": "rod", "gear_id": "rod2"}},
    {"id": "forge_reel2", "name": "轻量卷线轮", "icon": "⚙️", "level": 2, "materials": [["iron_ore", 2], ["copper_ore", 1], ["string", 1]],
     "steps": ["选材", "加热", "锻打", "淬火", "成型"],
     "fishing_gear": {"slot": "reel", "gear_id": "reel2"}},
    {"id": "forge_line2", "name": "编织钓线", "icon": "🧵", "level": 2, "materials": [["string", 3], ["silver_ore", 1]],
     "steps": ["选材", "锻打", "淬火", "成型"],
     "fishing_gear": {"slot": "line", "gear_id": "line2"}},
    {"id": "forge_rod3", "name": "鲟鱼重竿", "icon": "🏹", "level": 4, "materials": [["wood", 3], ["mithril", 1], ["leather", 2], ["string", 2], ["coal", 2]],
     "steps": ["选材", "加热", "锻打", "折叠锻打", "淬火", "成型"],
     "fishing_gear": {"slot": "rod", "gear_id": "rod3"}},
    {"id": "forge_reel3", "name": "强攻卷线轮", "icon": "⚙️", "level": 4, "materials": [["mithril", 2], ["silver_ore", 2], ["coal", 2]],
     "steps": ["选材", "加热", "锻打", "淬火", "回火", "成型"],
     "fishing_gear": {"slot": "reel", "gear_id": "reel3"}},
    {"id": "forge_line3", "name": "氟碳钓线", "icon": "🧵", "level": 4, "materials": [["string", 4], ["mithril", 1], ["silver_ore", 1]],
     "steps": ["选材", "锻打", "淬火", "成型"],
     "fishing_gear": {"slot": "line", "gear_id": "line3"}},
]


# ── 商店（按生活技能等级解锁商品）──────────────────────

def build_shop(life_level: int) -> List[Dict]:
    """构建商店商品列表：随生活技能整体等级解锁更多原材料"""
    shop = []
    for mat in RAW_MATERIALS:
        # 基础材料全解锁，等级高解锁高级材料
        if mat["id"] in ("mithril",):
            if life_level >= 4:
                shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                             "type": mat["type"], "price": mat["price"]})
        elif mat["id"] in ("magic_stone", "life_petal"):
            if life_level >= 2:
                shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                             "type": mat["type"], "price": mat["price"]})
        elif mat["id"] in ("fire_rune", "frost_rune", "storm_rune"):
            if life_level >= 3:
                shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                             "type": mat["type"], "price": mat["price"]})
        elif mat["id"] in ("soul_crystal", "dragon_scale"):
            if life_level >= 5:
                shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                             "type": mat["type"], "price": mat["price"]})
        elif mat["id"] in ("silver_ore", "gold_ore"):
            if life_level >= 3:
                shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                             "type": mat["type"], "price": mat["price"]})
        else:
            shop.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                         "type": mat["type"], "price": mat["price"]})
    return shop


# ── 生活技能等级与经验 ─────────────────────────────────

def get_level_xp(level: int) -> int:
    """升到下一级所需经验"""
    return level * 50


# ── 初始化 life_state ─────────────────────────────────

def init_life_state() -> Dict:
    """初始化生活技能状态（无数据迁移，纯新增）"""
    return {
        "skills": {
            "cooking": {"level": 1, "xp": 0, "name": "烹饪", "icon": "🍳"},
            "forging": {"level": 1, "xp": 0, "name": "锻造", "icon": "🔨"},
            "fishing": {"level": 1, "xp": 0, "name": "钓鱼", "icon": "🎣"},
        },
        "inventory": [],          # 原材料背包 [{id, name, icon, type, qty}]
        "recipes_known": [],       # 已掌握的固定菜谱 id
        "blueprints_known": [],    # 已掌握的设计图 id
        "foods": [],               # 已制作的食物（可食用）[{name, icon, buff, qty}]
        "equipment": [],           # 已锻造的装备（可穿戴）[{name, icon, type, bonus, damage_type, rarity}]
        "fish_caught": [],         # 已钓到的鱼 [{name, icon, family, rarity, weight, value, energy, qty}]
        "fish_dex": {},            # 收集图鉴 {fish_id: {name, family, rarity, color, silhouette, times, best}}
        "buffs": [],               # 当前生效的增益 [{type, value, turns, source}]
        "last_activity": "",       # 最近一次生活技能活动描述
        # ── 钓鱼专用状态 ──
        "fish_gear": {             # 钓鱼装备（杆/轮/线/饵）
            "equipped": {"rod": "rod1", "reel": "reel1", "line": "line1", "bait": "bait1"},
            "owned": ["rod1", "reel1", "line1", "bait1"],
            "zone": "pond",        # 当前水域
            "earnings": 0,         # 钓鱼累计收益（用于解锁水域）
        },
    }


def ensure_life_state(state: Dict) -> Dict:
    """确保 state 中存在 life_state（兼容旧存档）"""
    if not state.get("life_state"):
        state["life_state"] = init_life_state()
    return state["life_state"]


# ── 通用工具 ─────────────────────────────────────────

def _find_mat(id_: str) -> Optional[Dict]:
    for m in RAW_MATERIALS:
        if m["id"] == id_:
            return m
    # 鱼材料：fish_<fish_id> → 对应鱼类（作为独立食材，可自由烹饪）
    if id_.startswith("fish_"):
        fid = id_[5:]
        for f in FISH_TABLE:
            if f["id"] == fid:
                return {"id": id_, "name": f["name"], "type": "ingredient",
                        "price": max(1, int(f["value"])), "icon": f["icon"],
                        "rarity": f["rarity"]}
    return None


def material_grade(id_: str) -> int:
    """食材品质等级（1普通~5珍稀）：决定自由烹饪的加成与品质提升。

    鱼按稀有度分级；特殊附魔材料高等级；肉类/蛋类等优质食材略高。
    """
    m = _find_mat(id_)
    if not m:
        return 1
    if id_.startswith("fish_"):
        return {"common": 2, "rare": 3, "epic": 4, "legendary": 5}.get(m.get("rarity"), 2)
    if m.get("type") == "enchant":
        return {"magic_stone": 3, "life_petal": 4, "fire_rune": 4, "frost_rune": 4,
                "storm_rune": 4, "soul_crystal": 4, "dragon_scale": 5}.get(id_, 3)
    if id_ in ("meat", "egg", "milk", "honey"):
        return 2
    return 1


def add_materials(inv: List[Dict], mat_id: str, qty: int = 1, name: str = "", icon: str = "") -> None:
    """向原材料背包添加/累加材料"""
    if not name:
        m = _find_mat(mat_id)
        name = m["name"] if m else mat_id
        icon = m["icon"] if m else "❔"
    for it in inv:
        if it["id"] == mat_id:
            it["qty"] = it.get("qty", 0) + qty
            return
    inv.append({"id": mat_id, "name": name, "icon": icon, "qty": qty,
                "type": (_find_mat(mat_id) or {}).get("type", "misc")})


def remove_materials(inv: List[Dict], mat_id: str, qty: int = 1) -> bool:
    """从原材料背包扣除材料，足够则扣除返回 True"""
    for it in inv:
        if it["id"] == mat_id:
            if it["qty"] < qty:
                return False
            it["qty"] -= qty
            if it["qty"] <= 0:
                inv.remove(it)
            return True
    return False


def has_materials(inv: List[Dict], materials: List[List]) -> bool:
    """检查是否拥有指定材料组合 [[id, qty], ...]"""
    for mat_id, qty in materials:
        found = next((it for it in inv if it["id"] == mat_id), None)
        if not found or found["qty"] < qty:
            return False
    return True


def add_item_to_list(lst: List[Dict], item: Dict, qty: int = 1) -> None:
    """向食物/装备/鱼列表累加同名物品"""
    for it in lst:
        if it.get("name") == item.get("name"):
            it["qty"] = it.get("qty", 0) + qty
            return
    new = dict(item)
    new["qty"] = qty
    lst.append(new)


def add_xp(skills: Dict, skill_key: str, amount: int) -> Dict:
    """给生活技能加经验，处理升级，返回 {level_up, new_level}"""
    sk = skills.get(skill_key, {"level": 1, "xp": 0})
    sk["xp"] = sk.get("xp", 0) + amount
    level_up = False
    new_level = sk["level"]
    while sk["xp"] >= get_level_xp(sk["level"]):
        sk["xp"] -= get_level_xp(sk["level"])
        sk["level"] += 1
        level_up = True
        new_level = sk["level"]
    if level_up:
        sk["last_level_up"] = datetime.now().isoformat()
    skills[skill_key] = sk
    return {"level_up": level_up, "new_level": new_level}


# ── 判定系统：按步骤精确度分级 ─────────────────────────

def judge_step(step_index: int, total_steps: int, input_step: int, life_level: int) -> str:
    """步骤判定：输入步骤与预期步骤的偏差决定品质。
    完美(perfect) = 输入正确 良好(good) = 偏差1 普通(normal) = 其余 失败(fail) = 严重偏差
    返回品质关键字。
    """
    diff = abs(input_step - step_index)
    if diff == 0:
        return "perfect"
    if diff <= 1:
        return "good"
    return "normal"


def judge_overall(judgements: List[str], life_level: int) -> str:
    """综合所有步骤判定，得出最终品质：
    全完美 → 完美；完美≥半数 → 良好；有失败 → 普通；否则普通。
    """
    if not judgements:
        return "fail"
    perfects = judgements.count("perfect")
    goods = judgements.count("good")
    fails = judgements.count("fail")
    if fails > 0:
        return "fail"
    if perfects == len(judgements):
        return "perfect"
    if perfects + goods >= len(judgements) * 2 / 3:
        return "good"
    return "normal"


def quality_multiplier(quality: str) -> float:
    """品质 → 增益加成倍率"""
    return {"perfect": 1.5, "good": 1.2, "normal": 1.0, "bad": -0.5, "fail": 0.0}.get(quality, 1.0)


# ── 烹饪 ─────────────────────────────────────────────

def get_cook_recipe(recipe_id: str) -> Optional[Dict]:
    for r in COOK_RECIPES:
        if r["id"] == recipe_id:
            return r
    return None


def get_forge_blueprint(bp_id: str) -> Optional[Dict]:
    for b in FORGE_BLUEPRINTS:
        if b["id"] == bp_id:
            return b
    return None


def get_fish(fish_id: str) -> Optional[Dict]:
    for f in FISH_TABLE:
        if f["id"] == fish_id:
            return f
    return None


def mark_fish_dex(ls: Dict, fish_id: str, weight: float) -> None:
    """收集图鉴：记录首次钓到的鱼种（点亮图鉴）。"""
    dex = ls.setdefault("fish_dex", {})
    prev = dex.get(fish_id)
    if prev is None:
        fish = get_fish(fish_id)
        dex[fish_id] = {
            "name": fish["name"] if fish else fish_id,
            "icon": fish["icon"] if fish else "🐟",
            "family": fish["family"] if fish else "",
            "rarity": fish["rarity"] if fish else "common",
            "color": fish["color"] if fish else "#8b949e",
            "silhouette": fish["silhouette"] if fish else {"body": "oval", "tail": "fan", "fin": "none", "pattern": "none", "mark": "none"},
            "times": 1,
            "best": weight,
        }
    else:
        prev["times"] = prev.get("times", 1) + 1
        prev["best"] = max(prev.get("best", 0), weight)


def get_fish_dex(ls: Dict) -> Dict:
    """返回收集图鉴（fish_id -> 记录），兼容旧存档无 fish_dex 的情况。"""
    return ls.get("fish_dex", {})


# ── 钓鱼：装备 / 水域 / 选鱼 ─────────────────────────

def fish_gear_owner(slot: str) -> List[Dict]:
    """返回指定槽位的装备表（rod/reel/line/bait）"""
    return FISH_GEAR_LISTS.get(slot, [])


def get_zone(zone_id: str) -> Optional[Dict]:
    for z in FISH_ZONES:
        if z["id"] == zone_id:
            return z
    return None


def zone_unlocked(zone_id: str, earnings: int) -> bool:
    z = get_zone(zone_id)
    return bool(z) and earnings >= z["need"]


def unlocked_zones(earnings: int) -> List[str]:
    return [z["id"] for z in FISH_ZONES if earnings >= z["need"]]


def region_fish_zone(region_type: str, danger_level: int) -> str:
    """按异世界区域属性映射到可钓到鱼的水域（不同区域不同鱼）。

    区域类型 region_type：wild/town/dungeon/boss_lair/secret
    危险度 danger_level：1-5
    """
    rt = (region_type or "wild").lower()
    dl = danger_level or 1
    if rt in ("town", "village", "safe"):
        return "pond"
    if rt in ("boss_lair", "secret"):
        return "abyss"
    if rt == "dungeon":
        return "abyss" if dl >= 4 else "river"
    # 野外 wild：危险度越高，水域越高级
    if dl >= 4:
        return "abyss"
    if dl >= 3:
        return "river"
    if dl == 2:
        return "lake"
    return "pond"


def buy_fish_gear(ls: Dict, gear_id: str, gold: int) -> Dict:
    """购买钓鱼装备，返回 {success, gold, msg}"""
    gear = None
    slot = None
    for s, lst in FISH_GEAR_LISTS.items():
        for g in lst:
            if g["id"] == gear_id:
                gear = g
                slot = s
                break
        if gear:
            break
    if not gear:
        return {"success": False, "msg": "装备不存在"}
    fg = ls.setdefault("fish_gear", {})
    owned = fg.setdefault("owned", [])
    if gear["id"] in owned:
        return {"success": False, "msg": "已拥有该装备"}
    if gold < gear["price"]:
        return {"success": False, "msg": f"金币不足（需要{gear['price']}）"}
    owned.append(gear["id"])
    return {"success": True, "gold": gold - gear["price"], "slot": slot,
            "msg": f"购买了{gear['icon']} {gear['name']}"}


def equip_fish_gear(ls: Dict, gear_id: str) -> Dict:
    """穿戴（切换）钓鱼装备，返回 {success, msg}"""
    gear = None
    slot = None
    for s, lst in FISH_GEAR_LISTS.items():
        for g in lst:
            if g["id"] == gear_id:
                gear = g
                slot = s
                break
        if gear:
            break
    if not gear:
        return {"success": False, "msg": "装备不存在"}
    fg = ls.setdefault("fish_gear", {})
    if gear_id not in fg.get("owned", []):
        return {"success": False, "msg": "尚未拥有该装备"}
    fg.setdefault("equipped", {})[slot] = gear_id
    return {"success": True, "msg": f"已换上{gear['icon']} {gear['name']}"}


def damage_fish_gear(ls: Dict, slot: str) -> Dict:
    """钓鱼装备损坏（断线/爆杆）：从已拥有中移除该槽位装备，并回退到该槽位默认装备。

    返回 {broken, name, msg}。broken=False 表示该槽位无需损坏（如默认基础装备）。
    """
    if slot not in FISH_GEAR_LISTS or slot in ("bait", "reel"):
        return {"broken": False, "msg": ""}
    fg = ls.setdefault("fish_gear", {})
    owned = fg.setdefault("owned", [])
    eq = fg.setdefault("equipped", {})
    gid = eq.get(slot)
    default_id = FISH_GEAR_LISTS[slot][0]["id"]
    # 若当前装备是基础默认装备，则不损坏（避免把初始装备也弄坏）
    if not gid or gid == default_id:
        return {"broken": False, "msg": ""}
    if gid in owned:
        owned.remove(gid)
    eq[slot] = default_id
    gear = next((g for g in FISH_GEAR_LISTS[slot] if g["id"] == gid), None)
    name = gear["name"] if gear else gid
    return {"broken": True, "name": name, "msg": f"你的{name}已损坏，需重新购买"}


def equipped_fish_gear(ls: Dict) -> Dict:
    """返回当前穿戴装备的完整定义 {rod, reel, line, bait}"""
    fg = ls.setdefault("fish_gear", {})
    eq = fg.get("equipped", {})
    out = {}
    for slot, lst in FISH_GEAR_LISTS.items():
        gid = eq.get(slot) or lst[0]["id"]
        out[slot] = next((g for g in lst if g["id"] == gid), lst[0])
    return out


def pick_fish(zone_id: str, fishing_level: int, bait: Dict, cast: Optional[int] = None) -> Optional[Dict]:
    """按 水域 + 鱼饵家族偏好 + 攻击性 加权选鱼"""
    available = [f for f in FISH_TABLE if zone_id in f["zones"]]
    if not available:
        return available[0] if available else None
    weighted = []
    for f in available:
        w = f["aggress"]
        bf = bait.get("family", "杂鱼")
        if bf == f["family"]:
            w *= bait.get("bite", 1.15)
        elif bf == "传说" and f.get("legendary"):
            w *= bait.get("bite", 1.15)
        # 鱼竿抛投力：抛得越远，越容易勾到力量型大鱼（fight 高）
        if f["fight"] > 60:
            w *= 0.6 + (cast if cast is not None else 40) / 100
        weighted.append((f, max(0.05, w)))
    total = sum(w for _, w in weighted)
    r = random.uniform(0, total)
    for f, w in weighted:
        r -= w
        if r <= 0:
            return f
    return weighted[-1][0]


def fish_random_weight(fish: Dict) -> float:
    """随机体重kg：偏向中间，偶尔出大物"""
    if random.random() < 0.15:
        return round(fish["min"] + (fish["max"] - fish["min"]) * 0.9, 1)
    return round(fish["min"] + (fish["max"] - fish["min"]) * (random.random() ** 1.6), 1)


def fish_rarity_weight(fish: Dict) -> int:
    """按稀有度给钓鱼经验加成"""
    return {"common": 8, "rare": 16, "epic": 30, "legendary": 60}.get(fish.get("rarity", "common"), 8)


def resource_value(quality: str) -> int:
    """品质 → 经验值奖励"""
    return {"perfect": 30, "good": 20, "normal": 12, "bad": 4, "fail": 3}.get(quality, 3)


# ── 自由组合辅助（烹饪/锻造 LLM 动态生成）─────────────────

def material_value(inv: List[Dict], materials: List[List]) -> int:
    """材料组合的总价值（按商店单价×数量累计），用于平衡自由组合产出"""
    total = 0
    for mid, qty in materials:
        m = _find_mat(mid)
        if m:
            total += m["price"] * qty
    return total


def free_dish_base(level: int, mat_val: int) -> Dict:
    """自由烹饪：根据技能等级与材料价值推算基础 buff（hp/mp 回复或属性加成）"""
    # 材料价值越高、等级越高 → 基础效果越强
    base = 20 + level * 8 + mat_val // 2
    # 含附魔/特殊材料 → 更容易出属性类增益
    return {"type": "hp", "value": base, "turns": 0}


def cook_quality_by_heat(method: str, duration: str) -> str:
    """自由烹饪：由制作手法与火候时长匹配度得出品质（perfect/good/normal/bad）。

    手法分三类：急火快做（爆/炒/焯）、中火成型（煎/炸/焖/烧）、慢火细作（蒸/炖/烤/煮）。
    时长：短(急火)/中/长(慢火)。
      - 火候正好 → perfect（恢复×1.5 + 特殊效果）
      - 火候稍欠但可吃 → good / normal（恢复×1.2 / ×1.0）
      - 火候严重失控（焦糊/夹生/炒过头）→ bad（劣质，吃了食物中毒扣血×0.5）
    """
    fast = {"爆", "炒", "焯"}
    medium = {"煎", "炸", "焖", "烧"}
    slow = {"蒸", "炖", "烤", "煮"}
    if duration not in ("短", "中", "长"):
        duration = "中"
    if method in fast:
        return {"短": "perfect", "中": "good", "长": "bad"}.get(duration, "good")
    if method in medium:
        return {"短": "normal", "中": "perfect", "长": "bad"}.get(duration, "good")
    if method in slow:
        return {"短": "bad", "中": "good", "长": "perfect"}.get(duration, "good")
    return "good"


def cook_time_hint(method: str, duration: str) -> str:
    """自由烹饪：根据制作手法与火候时长判断是否得当，返回一句评语（LLM 失败时的规则兜底）。

    手法分三类：急火快做（爆/炒/焯）、中火成型（煎/炸/焖/烧）、慢火细作（蒸/炖/烤/煮）。
    时长：短(急火)/中/长(慢火)。手法与时长不匹配则出问题（糊/夹生/过老）。
    """
    fast = {"爆", "炒", "焯"}
    medium = {"煎", "炸", "焖", "烧"}
    slow = {"蒸", "炖", "烤", "煮"}
    # 时长语义归一
    if duration not in ("短", "中", "长"):
        duration = "中"
    if method in fast:
        if duration == "短":
            return "急火快炒，火候正好，锁住了食材本味，锅气十足"
        if duration == "中":
            return "火候略拖，食材有些发老，味道尚可，称不上完美"
        return "炒过了头，食材发黄疲软，隐约散发异味，吃了恐怕要闹肚子"
    if method in medium:
        if duration == "中":
            return "火候恰到好处，外香里嫩，焦香与嫩滑兼备"
        if duration == "短":
            return "火候偏急，表面焦了里面还带生，勉强能吃"
        return "火候太大、时间太长，食材焦糊发苦，吃了容易食物中毒"
    if method in slow:
        if duration == "长":
            return "慢火细作，火候到位，汤汁浓郁、软烂入味"
        if duration == "中":
            return "火候稍欠，不够软烂，要再等一等才够味"
        return "火候太短，里面还是夹生的，吃下去怕是要闹肚子"
    return "火候拿捏得当，味道不错"


def free_gear_base(level: int, mat_val: int) -> Dict:
    """自由锻造：根据技能等级与材料价值推算基础装备加成与类型"""
    bonus = 7 + level * 3 + mat_val // 10
    return {"bonus": bonus, "type": "weapon", "damage_type": "physical"}


def forge_fishing_gear(ls: Dict, slot: str, gear_id: str) -> bool:
    """锻造产出钓鱼装备：将 gear_id 加入已拥有列表（若尚未拥有）"""
    fg = ls.setdefault("fish_gear", {})
    owned = fg.setdefault("owned", [])
    if gear_id not in owned:
        owned.append(gear_id)
    return gear_id in owned


def apply_enchant(item: Dict, stat_type: str, stat_value: int, name: str) -> Dict:
    """附魔：为装备附加属性（写入 enchant 字段，并在 bonus 上体现）"""
    item.setdefault("enchant", {"name": name, "stat_type": stat_type, "stat_value": stat_value})
    # 攻击/防御类附魔直接叠加到 bonus；hp/mp 附魔记录到 enchant 供穿戴时结算
    if stat_type in ("attack", "defense"):
        item["bonus"] = item.get("bonus", 0) + stat_value
    return item


def enchant_materials() -> List[Dict]:
    """返回当前所有附魔材料定义（供前端渲染）"""
    return [m for m in RAW_MATERIALS if m["type"] == "enchant"]