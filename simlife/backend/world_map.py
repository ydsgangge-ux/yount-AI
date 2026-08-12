"""
世界地图系统 — 管理区域、怪物分布、BOSS、NPC位置

核心设计：
- 根据世界观自动生成区域地图（区域+连接关系）
- 每个区域有：危险等级、怪物类型、BOSS、NPC
- 区域之间有连通关系，玩家只能移动到相邻区域
- 探索过的区域会记录，未探索区域显示为"未知"
- BOSS被击杀后标记为已击败，不再刷新
"""
import random
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from simlife.backend.world_schema import WORLD_BOSS_LEVELS


class WorldRegion:
    """单个区域（方格坐标版）"""

    def __init__(self, region_id: str, name: str, description: str,
                 danger_level: int = 1, region_type: str = "wild",
                 connections: List[str] = None,
                 x: int = 0, y: int = 0):
        self.region_id = region_id
        self.name = name
        self.description = description
        self.danger_level = danger_level  # 1-5，越高越危险
        self.region_type = region_type    # wild/town/dungeon/boss_lair/secret
        self.connections = connections or []  # 相连区域的ID列表
        self.x = x  # 方格坐标X（正方向为东）
        self.y = y  # 方格坐标Y（正方向为南）
        self.monsters: List[Dict] = []        # 该区域的怪物模板
        self.boss: Optional[Dict] = None      # 区域BOSS
        self.npcs: List[str] = []             # 该区域出现的NPC ID列表
        self.explored = False                  # 是否已被探索
        self.boss_defeated = False             # BOSS是否已被击败
        self.discoveries: List[Dict] = []      # 可发现的物品/事件
        self.completion_condition: str = ""    # 区域完成条件，如"boss_defeated: 矿脉之心"
        self.completed: bool = False            # 区域是否已完成（完成后LLM不再续写新内容）
        self.is_blank: bool = False             # 是否为空白区域（待LLM生成）
        self.world_boss_id: Optional[str] = None  # 所属世界BOSS id（若本区域是世界BOSS领地）
        self.world_boss_stage: str = ""         # 领地阶段：铺垫/势力/对峙（供叙事区分）

    def to_dict(self) -> Dict:
        return {
            "region_id": self.region_id,
            "name": self.name,
            "description": self.description,
            "danger_level": self.danger_level,
            "region_type": self.region_type,
            "connections": self.connections,
            "x": self.x,
            "y": self.y,
            "monsters": self.monsters,
            "boss": self.boss,
            "npcs": self.npcs,
            "explored": self.explored,
            "boss_defeated": self.boss_defeated,
            "discoveries": self.discoveries,
            "completion_condition": self.completion_condition,
            "completed": self.completed,
            "is_blank": self.is_blank,
            "world_boss_id": self.world_boss_id,
            "world_boss_stage": self.world_boss_stage,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WorldRegion":
        r = cls(
            region_id=data["region_id"],
            name=data["name"],
            description=data.get("description", ""),
            danger_level=data.get("danger_level", 1),
            region_type=data.get("region_type", "wild"),
            connections=data.get("connections", []),
            x=data.get("x", 0),
            y=data.get("y", 0),
        )
        r.monsters = data.get("monsters", [])
        r.boss = data.get("boss")
        r.npcs = data.get("npcs", [])
        r.explored = data.get("explored", False)
        r.boss_defeated = data.get("boss_defeated", False)
        r.discoveries = data.get("discoveries", [])
        r.completion_condition = data.get("completion_condition", "")
        r.completed = data.get("completed", False)
        r.is_blank = data.get("is_blank", False)
        r.world_boss_id = data.get("world_boss_id")
        r.world_boss_stage = data.get("world_boss_stage", "")
        return r


class WorldMap:
    """世界地图（10x10方格坐标版）"""

    def __init__(self):
        self.regions: Dict[str, WorldRegion] = {}
        self.current_region_id: Optional[str] = None  # 玩家当前所在区域
        self.start_region_id: Optional[str] = None     # 出生点
        self.grid_size: int = 10                        # 方格地图大小

    def add_region(self, region: WorldRegion):
        self.regions[region.region_id] = region

    def get_region(self, region_id: str) -> Optional[WorldRegion]:
        return self.regions.get(region_id)

    def get_current_region(self) -> Optional[WorldRegion]:
        if self.current_region_id:
            return self.regions.get(self.current_region_id)
        return None

    def get_region_at(self, x: int, y: int) -> Optional[WorldRegion]:
        """获取指定坐标的区域"""
        for r in self.regions.values():
            if r.x == x and r.y == y:
                return r
        return None

    def get_adjacent_regions(self, region_id: str = None) -> List[WorldRegion]:
        """获取相邻区域（基于坐标，曼哈顿距离=1，上下左右四方向）"""
        rid = region_id or self.current_region_id
        region = self.regions.get(rid) if rid else None
        if not region:
            return []
        result = []
        for other in self.regions.values():
            if other.region_id == region.region_id:
                continue
            dx = abs(other.x - region.x)
            dy = abs(other.y - region.y)
            if (dx == 1 and dy == 0) or (dx == 0 and dy == 1):
                result.append(other)
        return result

    def can_move_direction(self, direction: str) -> bool:
        """检查指定方向是否可移动（在grid范围内）"""
        current = self.get_current_region()
        if not current:
            return False
        deltas = {"北": (0, -1), "南": (0, 1), "东": (1, 0), "西": (-1, 0)}
        dx, dy = deltas.get(direction, (0, 0))
        new_x = current.x + dx
        new_y = current.y + dy
        return 0 <= new_x < self.grid_size and 0 <= new_y < self.grid_size

    def get_available_directions(self) -> List[Dict]:
        """获取当前可移动的方向（4方向，包含空白格子信息）"""
        current = self.get_current_region()
        if not current:
            return []
        deltas = [("北", 0, -1), ("南", 0, 1), ("东", 1, 0), ("西", -1, 0)]
        result = []
        for dir_name, dx, dy in deltas:
            new_x = current.x + dx
            new_y = current.y + dy
            if 0 <= new_x < self.grid_size and 0 <= new_y < self.grid_size:
                region = self.get_region_at(new_x, new_y)
                result.append({
                    "direction": dir_name,
                    "target_x": new_x,
                    "target_y": new_y,
                    "has_region": region is not None,
                    "region_name": region.name if region else "未知",
                    "explored": region.explored if region else False,
                })
        return result

    def explore_region(self, region_id: str):
        """标记区域为已探索"""
        region = self.regions.get(region_id)
        if region:
            region.explored = True

    def defeat_boss(self, region_id: str):
        """标记BOSS为已击败"""
        region = self.regions.get(region_id)
        if region:
            region.boss_defeated = True

    @staticmethod
    def _get_direction_label(from_x: int, from_y: int, to_x: int, to_y: int) -> str:
        """根据坐标计算真实方向（8方向，用于显示）"""
        dx = to_x - from_x
        dy = to_y - from_y
        if dx == 0 and dy < 0: return "北"
        if dx > 0 and dy < 0: return "东北"
        if dx > 0 and dy == 0: return "东"
        if dx > 0 and dy > 0: return "东南"
        if dx == 0 and dy > 0: return "南"
        if dx < 0 and dy > 0: return "西南"
        if dx < 0 and dy == 0: return "西"
        if dx < 0 and dy < 0: return "西北"
        return "?"

    def get_map_display(self, region_id: str = None) -> Dict:
        """获取前端地图显示数据（3x3九宫格 + 全图数据）"""
        rid = region_id or self.current_region_id
        current = self.regions.get(rid) if rid else None
        if not current:
            return {"current": None, "adjacent": [], "grid_size": self.grid_size, "all_regions": []}

        # 8方向：4个直向（可移动）+ 4个对角（仅显示不可达）
        deltas = [
            ("西北", -1, -1, False), ("北", 0, -1, True), ("东北", 1, -1, False),
            ("西", -1, 0, True),                              ("东", 1, 0, True),
            ("西南", -1, 1, False),  ("南", 0, 1, True),  ("东南", 1, 1, False),
        ]
        adjacent = []
        for dir_name, dx, dy, can_move in deltas:
            new_x = current.x + dx
            new_y = current.y + dy
            if 0 <= new_x < self.grid_size and 0 <= new_y < self.grid_size:
                region = self.get_region_at(new_x, new_y)
                if region:
                    adjacent.append({
                        "region_id": region.region_id,
                        "name": region.name if region.explored else "未知",
                        "direction": dir_name,
                        "explored": region.explored,
                        "danger_level": region.danger_level if region.explored else 0,
                        "region_type": region.region_type if region.explored else "unknown",
                        "x": region.x,
                        "y": region.y,
                        "can_move": can_move,
                    })
                else:
                    # 空白格子
                    adjacent.append({
                        "region_id": "",
                        "name": "未知",
                        "direction": dir_name,
                        "explored": False,
                        "danger_level": 0,
                        "region_type": "unknown",
                        "x": new_x,
                        "y": new_y,
                        "can_move": can_move,
                    })

        # 全图数据：所有已生成的区域（供弹窗预览）
        all_regions = []
        for r in self.regions.values():
            all_regions.append({
                "region_id": r.region_id,
                "name": r.name,
                "x": r.x,
                "y": r.y,
                "explored": r.explored,
                "danger_level": r.danger_level,
                "region_type": r.region_type,
            })

        return {
            "current": {
                "region_id": current.region_id,
                "name": current.name,
                "description": current.description,
                "danger_level": current.danger_level,
                "region_type": current.region_type,
                "explored": current.explored,
                "x": current.x,
                "y": current.y,
            },
            "adjacent": adjacent,
            "grid_size": self.grid_size,
            "all_regions": all_regions,
        }

    def can_move_to(self, target_id: str) -> bool:
        """检查是否可以移动到目标区域（必须坐标相邻）"""
        current = self.get_current_region()
        if not current:
            return False
        target = self.regions.get(target_id)
        if not target:
            return False
        dx = abs(target.x - current.x)
        dy = abs(target.y - current.y)
        return (dx == 1 and dy == 0) or (dx == 0 and dy == 1)

    def to_dict(self) -> Dict:
        return {
            "regions": {rid: r.to_dict() for rid, r in self.regions.items()},
            "current_region_id": self.current_region_id,
            "start_region_id": self.start_region_id,
            "grid_size": self.grid_size,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WorldMap":
        wm = cls()
        for rid, rdata in data.get("regions", {}).items():
            wm.regions[rid] = WorldRegion.from_dict(rdata)
        wm.current_region_id = data.get("current_region_id")
        wm.start_region_id = data.get("start_region_id")
        wm.grid_size = data.get("grid_size", 10)
        return wm


class MapGenerator:
    """根据世界观自动生成地图（方格坐标版）"""

    # 世界类型 → 区域模板（带坐标）
    GRID_LAYOUTS = {
        "fantasy": [
            #  列0   列1   列2   列3   列4
            #  guild village plains forest mines
            #                    |       |
            #                  swamp   ruins
            #                    |
            #                 mountain
            #                    |
            #               dark_castle
            #  sacred_grove 连接 swamp
            {"id": "guild", "name": "冒险者公会", "type": "town", "danger": 0, "desc": "冒险者聚集之地，可以接取任务", "x": 0, "y": 0},
            {"id": "village", "name": "起始村庄", "type": "town", "danger": 0, "desc": "宁静的小村庄，冒险者的起点", "x": 1, "y": 0},
            {"id": "plains", "name": "广阔平原", "type": "wild", "danger": 1, "desc": "一望无际的草原，偶有低级魔物出没", "x": 2, "y": 0},
            {"id": "forest", "name": "暗影森林", "type": "wild", "danger": 2, "desc": "茂密的古树遮天蔽日，充满未知的危险", "x": 3, "y": 0},
            {"id": "mines", "name": "废弃矿洞", "type": "dungeon", "danger": 3, "desc": "曾经繁华的矿场，如今被怪物占据", "x": 4, "y": 0},
            {"id": "swamp", "name": "毒沼泽地", "type": "wild", "danger": 3, "desc": "瘴气弥漫的沼泽，暗藏杀机", "x": 2, "y": 1},
            {"id": "ruins", "name": "古代遗迹", "type": "dungeon", "danger": 4, "desc": "远古文明的遗迹，守护着强大的力量", "x": 3, "y": 1},
            {"id": "mountain", "name": "龙脊山脉", "type": "wild", "danger": 4, "desc": "险峻的山脉，传说巨龙栖息于此", "x": 2, "y": 2},
            {"id": "dark_castle", "name": "暗黑城堡", "type": "boss_lair", "danger": 5, "desc": "魔王盘踞的城堡，黑暗力量的中心", "x": 2, "y": 3},
            {"id": "sacred_grove", "name": "圣灵秘境", "type": "secret", "danger": 2, "desc": "隐藏在森林深处的神圣之地", "x": 1, "y": 2},
        ],
        "xianxia": [
            {"id": "market", "name": "仙市坊", "type": "town", "danger": 0, "desc": "修仙者交易之地，丹药法器齐全", "x": 0, "y": 0},
            {"id": "village", "name": "凡人小镇", "type": "town", "danger": 0, "desc": "凡人聚居之地，修仙者下山的起点", "x": 1, "y": 0},
            {"id": "outer_sect", "name": "外门区域", "type": "wild", "danger": 1, "desc": "宗门外门弟子修炼之地", "x": 2, "y": 0},
            {"id": "bamboo_forest", "name": "幽竹秘境", "type": "wild", "danger": 2, "desc": "青竹如海，灵气充沛", "x": 3, "y": 0},
            {"id": "cave", "name": "灵矿洞府", "type": "dungeon", "danger": 3, "desc": "蕴含灵石的矿洞，妖兽出没", "x": 4, "y": 0},
            {"id": "blood_wasteland", "name": "血荒原", "type": "wild", "danger": 3, "desc": "上古战场遗迹，阴气森森", "x": 2, "y": 1},
            {"id": "inner_sect", "name": "内门禁地", "type": "dungeon", "danger": 4, "desc": "宗门核心区域，藏有上古传承", "x": 3, "y": 1},
            {"id": "lotus_pond", "name": "碧莲池", "type": "secret", "danger": 2, "desc": "传说中洗髓伐毛的圣池", "x": 1, "y": 1},
            {"id": "thunder_peak", "name": "雷劫峰", "type": "wild", "danger": 4, "desc": "雷云密布，渡劫圣地", "x": 2, "y": 2},
            {"id": "demon_realm", "name": "魔域深渊", "type": "boss_lair", "danger": 5, "desc": "魔尊盘踞之地，修仙者的终焉", "x": 2, "y": 3},
        ],
        "wuxia": [
            {"id": "market", "name": "集市", "type": "town", "danger": 0, "desc": "江湖人士聚集交易之地，消息灵通", "x": 0, "y": 0},
            {"id": "village", "name": "新手村", "type": "town", "danger": 0, "desc": "偏僻的小村庄，武林新人的起点", "x": 1, "y": 0},
            {"id": "provincial_road", "name": "官道", "type": "wild", "danger": 1, "desc": "连接各大城镇的官道，偶有山贼出没", "x": 2, "y": 0},
            {"id": "bamboo_forest", "name": "翠竹林", "type": "wild", "danger": 2, "desc": "茂密的竹林深处，常有武林人士切磋", "x": 3, "y": 0},
            {"id": "ancient_tomb", "name": "古墓秘境", "type": "dungeon", "danger": 3, "desc": "前朝高手的陵墓，藏有绝世武学", "x": 4, "y": 0},
            {"id": "bandit_fort", "name": "山寨", "type": "wild", "danger": 3, "desc": "山贼盘踞的寨子，祸害一方", "x": 2, "y": 1},
            {"id": "sect", "name": "武林门派", "type": "dungeon", "danger": 4, "desc": "隐世门派的驻地，藏有武林秘辛", "x": 3, "y": 1},
            {"id": "waterfall", "name": "瀑布秘境", "type": "secret", "danger": 2, "desc": "瀑布后的隐秘洞穴，内有前辈遗刻", "x": 1, "y": 1},
            {"id": "ice_peak", "name": "冰封雪峰", "type": "wild", "danger": 4, "desc": "终年积雪的险峰，传说有绝世高手隐居", "x": 2, "y": 2},
            {"id": "dark_palace", "name": "魔教总坛", "type": "boss_lair", "danger": 5, "desc": "魔教盘踞之地，武林浩劫的根源", "x": 2, "y": 3},
        ],
        "post_apocalyptic": [
            {"id": "shelter", "name": "地下避难所", "type": "town", "danger": 0, "desc": "幸存者的庇护所，相对安全", "x": 0, "y": 0},
            {"id": "trading_post", "name": "交易站", "type": "town", "danger": 0, "desc": "各路幸存者的交易点", "x": 1, "y": 0},
            {"id": "ruins_city", "name": "废弃城区", "type": "wild", "danger": 1, "desc": "残破的摩天楼，搜刮物资的好去处", "x": 2, "y": 0},
            {"id": "subway", "name": "地铁隧道", "type": "dungeon", "danger": 2, "desc": "黑暗的地下通道，变异生物出没", "x": 3, "y": 0},
            {"id": "toxic_zone", "name": "辐射污染区", "type": "wild", "danger": 3, "desc": "高辐射区域，危险但资源丰富", "x": 2, "y": 1},
            {"id": "bandit_camp", "name": "掠夺者营地", "type": "wild", "danger": 3, "desc": "暴徒据点，物资充裕", "x": 3, "y": 1},
            {"id": "lab", "name": "生化实验室", "type": "dungeon", "danger": 4, "desc": "灾难的源头，隐藏着变异的真相", "x": 4, "y": 1},
            {"id": "bunker", "name": "秘密地堡", "type": "secret", "danger": 2, "desc": "军方遗留的秘密设施", "x": 1, "y": 1},
            {"id": "no_mans_land", "name": "无人区", "type": "wild", "danger": 4, "desc": "最危险的荒原，顶级变异体出没", "x": 2, "y": 2},
            {"id": "hive", "name": "虫巢母穴", "type": "boss_lair", "danger": 5, "desc": "变异虫族的女王巢穴", "x": 2, "y": 3},
        ],
        "modern_power": [
            {"id": "academy", "name": "能力者学院", "type": "town", "danger": 0, "desc": "培养能力者的机构", "x": 0, "y": 0},
            {"id": "downtown", "name": "城市中心", "type": "town", "danger": 0, "desc": "繁华的都市，能力者的日常", "x": 1, "y": 0},
            {"id": "old_district", "name": "旧城区", "type": "wild", "danger": 1, "desc": "老旧的街区，暗流涌动", "x": 2, "y": 0},
            {"id": "dark_alley", "name": "暗巷", "type": "wild", "danger": 2, "desc": "信息交易的黑市", "x": 3, "y": 0},
            {"id": "abandoned_factory", "name": "废弃工厂区", "type": "wild", "danger": 3, "desc": "犯罪组织的据点", "x": 2, "y": 1},
            {"id": "underground", "name": "地下竞技场", "type": "dungeon", "danger": 2, "desc": "能力者比武的地下场所", "x": 3, "y": 1},
            {"id": "research_center", "name": "超能研究所", "type": "dungeon", "danger": 3, "desc": "能力者实验的秘密基地", "x": 4, "y": 1},
            {"id": "rooftop", "name": "天台瞭望点", "type": "secret", "danger": 1, "desc": "城市最高点，俯瞰全局", "x": 1, "y": 1},
            {"id": "mountain_temple", "name": "深山古寺", "type": "wild", "danger": 4, "desc": "隐世高手修炼之地", "x": 2, "y": 2},
            {"id": "demon_gate", "name": "魔门总坛", "type": "boss_lair", "danger": 5, "desc": "暗势力的大本营", "x": 2, "y": 3},
        ],
        "scifi": [
            {"id": "bar", "name": "星际酒吧", "type": "town", "danger": 0, "desc": "各类旅客的社交场所", "x": 0, "y": 0},
            {"id": "station", "name": "太空站核心区", "type": "town", "danger": 0, "desc": "空间站的中心，居民聚集地", "x": 1, "y": 0},
            {"id": "docking_bay", "name": "停靠港", "type": "wild", "danger": 1, "desc": "飞船停靠区，各类人等混杂", "x": 2, "y": 0},
            {"id": "cargo_hold", "name": "货舱区", "type": "wild", "danger": 2, "desc": "物资仓储区，走私者活跃", "x": 3, "y": 0},
            {"id": "maintenance", "name": "维护通道", "type": "dungeon", "danger": 2, "desc": "复杂的管道系统，常有故障机器人", "x": 2, "y": 1},
            {"id": "lab_deck", "name": "实验层", "type": "dungeon", "danger": 3, "desc": "生物实验区，变异体出没", "x": 3, "y": 1},
            {"id": "ai_core", "name": "AI核心区", "type": "dungeon", "danger": 4, "desc": "中央AI控制区，安保森严", "x": 4, "y": 1},
            {"id": "escape_pod", "name": "逃生舱区", "type": "secret", "danger": 1, "desc": "隐藏的紧急逃生通道", "x": 1, "y": 1},
            {"id": "outer_hull", "name": "外层甲板", "type": "wild", "danger": 4, "desc": "太空行走区域，极度危险", "x": 2, "y": 2},
            {"id": "command_bridge", "name": "指挥舰桥", "type": "boss_lair", "danger": 5, "desc": "被叛变AI占据的指挥中心", "x": 2, "y": 3},
        ],
    }

    # 旧版模板（兼容，无坐标，用于 LLM 生成后分配坐标）
    REGION_TEMPLATES = {
        "fantasy": [
            {"id": "village", "name": "起始村庄", "type": "town", "danger": 0, "desc": "宁静的小村庄，冒险者的起点"},
            {"id": "plains", "name": "广阔平原", "type": "wild", "danger": 1, "desc": "一望无际的草原，偶有低级魔物出没"},
            {"id": "forest", "name": "暗影森林", "type": "wild", "danger": 2, "desc": "茂密的古树遮天蔽日，充满未知的危险"},
            {"id": "mines", "name": "废弃矿洞", "type": "dungeon", "danger": 3, "desc": "曾经繁华的矿场，如今被怪物占据"},
            {"id": "swamp", "name": "毒沼泽地", "type": "wild", "danger": 3, "desc": "瘴气弥漫的沼泽，暗藏杀机"},
            {"id": "ruins", "name": "古代遗迹", "type": "dungeon", "danger": 4, "desc": "远古文明的遗迹，守护着强大的力量"},
            {"id": "mountain", "name": "龙脊山脉", "type": "wild", "danger": 4, "desc": "险峻的山脉，传说巨龙栖息于此"},
            {"id": "dark_castle", "name": "暗黑城堡", "type": "boss_lair", "danger": 5, "desc": "魔王盘踞的城堡，黑暗力量的中心"},
            {"id": "guild", "name": "冒险者公会", "type": "town", "danger": 0, "desc": "冒险者聚集之地，可以接取任务"},
            {"id": "sacred_grove", "name": "圣灵秘境", "type": "secret", "danger": 2, "desc": "隐藏在森林深处的神圣之地"},
        ],
        "xianxia": [
            {"id": "village", "name": "凡人小镇", "type": "town", "danger": 0, "desc": "凡人聚居之地，修仙者下山的起点"},
            {"id": "outer_sect", "name": "外门区域", "type": "wild", "danger": 1, "desc": "宗门外门弟子修炼之地"},
            {"id": "bamboo_forest", "name": "幽竹秘境", "type": "wild", "danger": 2, "desc": "青竹如海，灵气充沛"},
            {"id": "cave", "name": "灵矿洞府", "type": "dungeon", "danger": 3, "desc": "蕴含灵石的矿洞，妖兽出没"},
            {"id": "blood_wasteland", "name": "血荒原", "type": "wild", "danger": 3, "desc": "上古战场遗迹，阴气森森"},
            {"id": "inner_sect", "name": "内门禁地", "type": "dungeon", "danger": 4, "desc": "宗门核心区域，藏有上古传承"},
            {"id": "thunder_peak", "name": "雷劫峰", "type": "wild", "danger": 4, "desc": "雷云密布，渡劫圣地"},
            {"id": "demon_realm", "name": "魔域深渊", "type": "boss_lair", "danger": 5, "desc": "魔尊盘踞之地，修仙者的终焉"},
            {"id": "market", "name": "仙市坊", "type": "town", "danger": 0, "desc": "修仙者交易之地，丹药法器齐全"},
            {"id": "lotus_pond", "name": "碧莲池", "type": "secret", "danger": 2, "desc": "传说中洗髓伐毛的圣池"},
        ],
        "wuxia": [
            {"id": "village", "name": "新手村", "type": "town", "danger": 0, "desc": "偏僻的小村庄，武林新人的起点"},
            {"id": "provincial_road", "name": "官道", "type": "wild", "danger": 1, "desc": "连接各大城镇的官道，偶有山贼出没"},
            {"id": "bamboo_forest", "name": "翠竹林", "type": "wild", "danger": 2, "desc": "茂密的竹林深处，常有武林人士切磋"},
            {"id": "ancient_tomb", "name": "古墓秘境", "type": "dungeon", "danger": 3, "desc": "前朝高手的陵墓，藏有绝世武学"},
            {"id": "bandit_fort", "name": "山寨", "type": "wild", "danger": 3, "desc": "山贼盘踞的寨子，祸害一方"},
            {"id": "sect", "name": "武林门派", "type": "dungeon", "danger": 4, "desc": "隐世门派的驻地，藏有武林秘辛"},
            {"id": "ice_peak", "name": "冰封雪峰", "type": "wild", "danger": 4, "desc": "终年积雪的险峰，传说有绝世高手隐居"},
            {"id": "dark_palace", "name": "魔教总坛", "type": "boss_lair", "danger": 5, "desc": "魔教盘踞之地，武林浩劫的根源"},
            {"id": "market", "name": "集市", "type": "town", "danger": 0, "desc": "江湖人士聚集交易之地，消息灵通"},
            {"id": "waterfall", "name": "瀑布秘境", "type": "secret", "danger": 2, "desc": "瀑布后的隐秘洞穴，内有前辈遗刻"},
        ],
        "post_apocalyptic": [
            {"id": "shelter", "name": "地下避难所", "type": "town", "danger": 0, "desc": "幸存者的庇护所，相对安全"},
            {"id": "ruins_city", "name": "废弃城区", "type": "wild", "danger": 1, "desc": "残破的摩天楼，搜刮物资的好去处"},
            {"id": "subway", "name": "地铁隧道", "type": "dungeon", "danger": 2, "desc": "黑暗的地下通道，变异生物出没"},
            {"id": "toxic_zone", "name": "辐射污染区", "type": "wild", "danger": 3, "desc": "高辐射区域，危险但资源丰富"},
            {"id": "bandit_camp", "name": "掠夺者营地", "type": "wild", "danger": 3, "desc": "暴徒据点，物资充裕"},
            {"id": "lab", "name": "生化实验室", "type": "dungeon", "danger": 4, "desc": "灾难的源头，隐藏着变异的真相"},
            {"id": "no_mans_land", "name": "无人区", "type": "wild", "danger": 4, "desc": "最危险的荒原，顶级变异体出没"},
            {"id": "hive", "name": "虫巢母穴", "type": "boss_lair", "danger": 5, "desc": "变异虫族的女王巢穴"},
            {"id": "trading_post", "name": "交易站", "type": "town", "danger": 0, "desc": "各路幸存者的交易点"},
            {"id": "bunker", "name": "秘密地堡", "type": "secret", "danger": 2, "desc": "军方遗留的秘密设施"},
        ],
        "modern_power": [
            {"id": "downtown", "name": "城市中心", "type": "town", "danger": 0, "desc": "繁华的都市，能力者的日常"},
            {"id": "old_district", "name": "旧城区", "type": "wild", "danger": 1, "desc": "老旧的街区，暗流涌动"},
            {"id": "underground", "name": "地下竞技场", "type": "dungeon", "danger": 2, "desc": "能力者比武的地下场所"},
            {"id": "abandoned_factory", "name": "废弃工厂区", "type": "wild", "danger": 3, "desc": "犯罪组织的据点"},
            {"id": "research_center", "name": "超能研究所", "type": "dungeon", "danger": 3, "desc": "能力者实验的秘密基地"},
            {"id": "dark_alley", "name": "暗巷", "type": "wild", "danger": 2, "desc": "信息交易的黑市"},
            {"id": "mountain_temple", "name": "深山古寺", "type": "wild", "danger": 4, "desc": "隐世高手修炼之地"},
            {"id": "demon_gate", "name": "魔门总坛", "type": "boss_lair", "danger": 5, "desc": "暗势力的大本营"},
            {"id": "academy", "name": "能力者学院", "type": "town", "danger": 0, "desc": "培养能力者的机构"},
            {"id": "rooftop", "name": "天台瞭望点", "type": "secret", "danger": 1, "desc": "城市最高点，俯瞰全局"},
        ],
        "scifi": [
            {"id": "station", "name": "太空站核心区", "type": "town", "danger": 0, "desc": "空间站的中心，居民聚集地"},
            {"id": "docking_bay", "name": "停靠港", "type": "wild", "danger": 1, "desc": "飞船停靠区，各类人等混杂"},
            {"id": "maintenance", "name": "维护通道", "type": "dungeon", "danger": 2, "desc": "复杂的管道系统，常有故障机器人"},
            {"id": "lab_deck", "name": "实验层", "type": "dungeon", "danger": 3, "desc": "生物实验区，变异体出没"},
            {"id": "cargo_hold", "name": "货舱区", "type": "wild", "danger": 2, "desc": "物资仓储区，走私者活跃"},
            {"id": "ai_core", "name": "AI核心区", "type": "dungeon", "danger": 4, "desc": "中央AI控制区，安保森严"},
            {"id": "outer_hull", "name": "外层甲板", "type": "wild", "danger": 4, "desc": "太空行走区域，极度危险"},
            {"id": "command_bridge", "name": "指挥舰桥", "type": "boss_lair", "danger": 5, "desc": "被叛变AI占据的指挥中心"},
            {"id": "bar", "name": "星际酒吧", "type": "town", "danger": 0, "desc": "各类旅客的社交场所"},
            {"id": "escape_pod", "name": "逃生舱区", "type": "secret", "danger": 1, "desc": "隐藏的紧急逃生通道"},
        ],
    }

    # 区域连接图（每个世界类型通用的连接逻辑）
    # town → wild → dungeon → wild → boss_lair
    # 分支：secret 从某些 wild/dungeon 可达
    # 中文世界类型 → 英文key映射
    WORLD_TYPE_MAP = {
        "奇幻魔法": "fantasy", "仙侠修真": "xianxia", "武侠江湖": "wuxia",
        "末世废土": "post_apocalyptic", "现世超武": "modern_power", "科幻未来": "scifi",
    }

    @staticmethod
    def generate(world_setting: Dict, llm_client=None) -> WorldMap:
        """根据世界观生成地图。优先从世界设定的grid字段初始化。"""
        # 优先从世界设定的 grid 字段生成（10x10方格，只放主要区域）
        grid_config = world_setting.get("geography", {}).get("grid", {})
        if grid_config and grid_config.get("main_regions"):
            wm = MapGenerator._generate_from_world_grid(grid_config, world_setting)
            print(f"[WorldMap] 从世界设定grid生成地图：{len(wm.regions)}个主要区域，grid_size={wm.grid_size}")
        elif llm_client:
            # 兼容旧版：尝试 LLM 生成
            try:
                wm = MapGenerator._generate_with_llm(world_setting, llm_client)
                MapGenerator._assign_llm_grid_positions(wm)
                wm.grid_size = 10
            except Exception as e:
                print(f"[WorldMap] LLM生成失败，使用模板: {e}")
                wm = MapGenerator._generate_from_any_template(world_setting)
        else:
            # 最终回退：模板生成
            wm = MapGenerator._generate_from_any_template(world_setting)

        # 世界 BOSS 领地区域生成（任何世界都自动生成，保证通用性）
        try:
            MapGenerator._generate_world_boss_territories(wm, world_setting)
        except Exception as e:
            print(f"[WorldMap] 世界BOSS领地生成失败: {e}")

        return wm

    @staticmethod
    def _generate_from_any_template(world_setting: Dict) -> WorldMap:
        """从世界类型模板生成地图（grid模板优先，否则旧版模板）"""
        world_type = world_setting.get("world_type", "fantasy")
        world_type = MapGenerator.WORLD_TYPE_MAP.get(world_type, world_type)
        grid_templates = MapGenerator.GRID_LAYOUTS.get(world_type, MapGenerator.GRID_LAYOUTS["fantasy"])
        wm = MapGenerator._generate_from_grid(grid_templates, world_setting)
        wm.grid_size = 10
        return wm

    @staticmethod
    def _generate_from_world_grid(grid_config: Dict, world_setting: Dict) -> WorldMap:
        """从世界设定的 grid 配置生成地图（10x10方格，只放置主要区域，空白格子在游戏中动态生成）"""
        wm = WorldMap()
        wm.grid_size = grid_config.get("size", 10)
        monster_types = world_setting.get("dangers", {}).get("monster_types", [])

        for r_def in grid_config.get("main_regions", []):
            region = WorldRegion(
                region_id=r_def["region_id"],
                name=r_def["name"],
                description=r_def.get("description", ""),
                danger_level=r_def.get("danger_level", 1),
                region_type=r_def.get("region_type", "wild"),
                x=r_def.get("x", 0),
                y=r_def.get("y", 0),
            )
            # 分配怪物
            if region.danger_level > 0 and region.region_type != "town":
                region.monsters = MapGenerator._assign_monsters(
                    region.danger_level, monster_types, world_setting
                )
            # BOSS区域
            if region.region_type == "boss_lair":
                region.boss = MapGenerator._generate_boss(
                    region.danger_level, monster_types, world_setting
                )
            # 完成条件
            if r_def.get("completion_condition"):
                region.completion_condition = r_def["completion_condition"]

            wm.add_region(region)

            # 起始点
            if r_def.get("is_start"):
                wm.start_region_id = region.region_id
                wm.current_region_id = region.region_id
                region.explored = True

        # 如果没有标记起始点，用第一个town
        if not wm.start_region_id and wm.regions:
            for r in wm.regions.values():
                if r.region_type == "town":
                    wm.start_region_id = r.region_id
                    wm.current_region_id = r.region_id
                    r.explored = True
                    break
            if not wm.start_region_id:
                first = next(iter(wm.regions.values()))
                wm.start_region_id = first.region_id
                wm.current_region_id = first.region_id
                first.explored = True

        return wm

    @staticmethod
    def _generate_from_template(templates: List[Dict], world_setting: Dict) -> WorldMap:
        """从模板生成地图"""
        wm = WorldMap()
        monster_types = []
        if world_setting:
            dangers = world_setting.get("dangers", {})
            monster_types = dangers.get("monster_types", [])

        # 用世界观的怪物类型替换模板中的默认怪物
        for t in templates:
            region = WorldRegion(
                region_id=t["id"],
                name=t["name"],
                description=t["desc"],
                danger_level=t["danger"],
                region_type=t["type"],
            )

            # 根据危险等级分配怪物
            if t["danger"] > 0 and t["type"] != "town":
                region.monsters = MapGenerator._assign_monsters(
                    t["danger"], monster_types, world_setting
                )

            # BOSS区域
            if t["type"] == "boss_lair":
                region.boss = MapGenerator._generate_boss(
                    t["danger"], monster_types, world_setting
                )

            wm.add_region(region)

            # 第一个town作为起始点
            if t["type"] == "town" and wm.start_region_id is None:
                wm.start_region_id = t["id"]
                wm.current_region_id = t["id"]
                region.explored = True  # 出生点已探索

        # 建立连接关系
        MapGenerator._build_connections(wm)

        return wm

    @staticmethod
    def _generate_from_grid(grid_templates: List[Dict], world_setting: Dict) -> WorldMap:
        """从方格坐标模板生成地图（带坐标区域）"""
        wm = WorldMap()
        monster_types = []
        if world_setting:
            dangers = world_setting.get("dangers", {})
            monster_types = dangers.get("monster_types", [])

        for t in grid_templates:
            region = WorldRegion(
                region_id=t["id"],
                name=t["name"],
                description=t["desc"],
                danger_level=t["danger"],
                region_type=t["type"],
                x=t["x"],
                y=t["y"],
            )
            if t["danger"] > 0 and t["type"] != "town":
                region.monsters = MapGenerator._assign_monsters(
                    t["danger"], monster_types, world_setting
                )
            if t["type"] == "boss_lair":
                region.boss = MapGenerator._generate_boss(
                    t["danger"], monster_types, world_setting
                )
            wm.add_region(region)
            if t["type"] == "town" and wm.start_region_id is None:
                wm.start_region_id = t["id"]
                wm.current_region_id = t["id"]
                region.explored = True

        # 根据坐标自动建立连接（相邻格子互连）
        MapGenerator._build_grid_connections(wm)
        return wm

    @staticmethod
    def _build_grid_connections(wm: WorldMap):
        """根据方格坐标自动建立相邻区域的连接（上下左右四个方向）"""
        regions = list(wm.regions.values())
        for r in regions:
            for other in regions:
                if r.region_id == other.region_id:
                    continue
                dx = abs(r.x - other.x)
                dy = abs(r.y - other.y)
                # 曼哈顿距离=1 视为相邻（上下左右）
                if (dx == 1 and dy == 0) or (dx == 0 and dy == 1):
                    if other.region_id not in r.connections:
                        r.connections.append(other.region_id)
                    if r.region_id not in other.connections:
                        other.connections.append(r.region_id)

    @staticmethod
    def _assign_llm_grid_positions(wm: WorldMap):
        """LLM生成的地图坐标分配：用BFS分配坐标，起始点在(0,0)"""
        if not wm.start_region_id or wm.start_region_id not in wm.regions:
            return
        # 先清除已有坐标
        for r in wm.regions.values():
            r.x = 0
            r.y = 0
        # BFS分配坐标
        visited = set()
        from collections import deque
        q = deque()
        q.append((wm.start_region_id, 0, 0))
        visited.add(wm.start_region_id)
        # 方向：东、南、西、北
        dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        while q:
            rid, cx, cy = q.popleft()
            region = wm.regions[rid]
            region.x = cx
            region.y = cy
            d_idx = 0
            for cid in region.connections:
                if cid in wm.regions and cid not in visited:
                    visited.add(cid)
                    # 按方向队列分配相邻坐标
                    dx, dy = dirs[d_idx % 4]
                    q.append((cid, cx + dx, cy + dy))
                    d_idx += 1

    @staticmethod
    def _generate_with_llm(world_setting: Dict, llm_client) -> WorldMap:
        """用LLM生成地图"""
        from simlife.backend.generator import get_llm_client
        if llm_client is None:
            llm_client = get_llm_client()

        world_name = world_setting.get("world_name", "未知世界")
        world_type = world_setting.get("world_type", "fantasy")
        regions_info = world_setting.get("geography", {}).get("regions", [])
        monster_types = world_setting.get("dangers", {}).get("monster_types", [])

        regions_text = ""
        if regions_info:
            regions_text = "世界观中的区域：" + "、".join(
                r.get("name", str(r)) for r in regions_info[:10] if isinstance(r, dict)
            )

        monsters_text = ""
        if monster_types:
            mt_names = [m.get("name", str(m)) if isinstance(m, dict) else str(m) for m in monster_types[:8]]
            monsters_text = "世界观中的怪物类型：" + "、".join(mt_names)

        prompt = f"""你是死亡模式人生模拟器的地图设计Agent。请为以下世界生成一张区域地图。

世界：{world_name}（类型：{world_type}）
{regions_text}
{monsters_text}

设计要求：
1. 生成6-10个区域，包含：起始安全区(1-2个)、野外区域(2-3个)、地下城(1-2个)、BOSS区域(1个)、隐藏区域(0-1个)
2. 每个区域有：区域ID、名称、描述、危险等级(0-5)、类型(town/wild/dungeon/boss_lair/secret)
3. 区域之间有连接关系，玩家只能走相邻区域
4. 高危险区域放置高级怪物和BOSS
5. 怪物名称要符合世界观设定

返回JSON格式：
{{
  "regions": [
    {{
      "id": "英文id",
      "name": "区域名称",
      "description": "2-3句话描述",
      "danger_level": 0-5,
      "region_type": "town/wild/dungeon/boss_lair/secret",
      "connections": ["相邻区域id列表"],
      "monsters": ["怪物名称1", "怪物名称2"],
      "boss": null 或 {{"name": "BOSS名称", "description": "BOSS描述"}},
      "npcs": ["NPC名称1", "NPC名称2"]
    }}
  ],
  "start_region": "起始区域id"
}}

只返回JSON，不要其他文字。"""

        response = llm_client.generate(prompt, max_tokens=1500, temperature=0.8, thinking=False)
        response = response.strip()

        # 清理markdown代码块包裹
        if response.startswith("```"):
            lines = response.split("\n")
            # 去掉第一行(如```json)和最后的```
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines).strip()

        # 去掉LLM可能在JSON前后添加的文字
        first_brace = response.find("{")
        last_brace = response.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            response = response[first_brace:last_brace + 1]

        import json
        import re

        # 去掉JSON中的单行注释 (// ...)
        response = re.sub(r'//[^\n]*', '', response)
        # 去掉多行注释 (/* ... */)
        response = re.sub(r'/\*.*?\*/', '', response, flags=re.DOTALL)
        # 去掉尾逗号（,紧跟}或]）
        response = re.sub(r',\s*([}\]])', r'\1', response)

        result = json.loads(response)
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else {}

        wm = WorldMap()
        for rdata in result.get("regions", []):
            region = WorldRegion(
                region_id=rdata["id"],
                name=rdata["name"],
                description=rdata.get("description", ""),
                danger_level=rdata.get("danger_level", 1),
                region_type=rdata.get("region_type", "wild"),
                connections=rdata.get("connections", []),
            )
            # 怪物列表
            for mname in rdata.get("monsters", []):
                region.monsters.append({"name": mname, "type": "normal"})

            # BOSS
            if rdata.get("boss"):
                region.boss = {
                    "name": rdata["boss"].get("name", "未知BOSS"),
                    "description": rdata["boss"].get("description", ""),
                }

            # NPC
            region.npcs = rdata.get("npcs", [])

            wm.add_region(region)

        wm.start_region_id = result.get("start_region")
        wm.current_region_id = wm.start_region_id
        if wm.start_region_id and wm.start_region_id in wm.regions:
            wm.regions[wm.start_region_id].explored = True

        return wm

    @staticmethod
    def _assign_monsters(danger_level: int, monster_types: List, world_setting: Dict) -> List[Dict]:
        """根据危险等级分配怪物"""
        monsters = []
        if monster_types:
            # 从世界观中选取合适等级的怪物
            available = []
            for mt in monster_types:
                if isinstance(mt, dict):
                    mt_danger = mt.get("danger_level", mt.get("level", 1))
                    # 匹配危险等级±1的怪物
                    if abs(mt_danger - danger_level) <= 1:
                        available.append(mt)
            if not available:
                available = monster_types[:5]

            count = min(len(available), 2 + danger_level)
            for mt in random.sample(available, min(count, len(available))):
                name = mt.get("name", str(mt)) if isinstance(mt, dict) else str(mt)
                monsters.append({
                    "name": name,
                    "type": "elite" if danger_level >= 4 and random.random() < 0.3 else "normal",
                })
        else:
            # 没有世界观怪物，用默认
            default_names = {
                1: ["小史莱姆", "野鼠", "飞虫"],
                2: ["哥布林", "野狼", "毒蛇"],
                3: ["骷髅兵", "暗影狼", "石像鬼"],
                4: ["暗黑骑士", "亡灵法师", "石化蜥蜴"],
                5: ["远古巨龙", "深渊领主", "死亡骑士"],
            }
            names = default_names.get(danger_level, ["魔物"])
            for name in random.sample(names, min(2, len(names))):
                monsters.append({"name": name, "type": "normal"})

        return monsters

    @staticmethod
    def _generate_boss(danger_level: int, monster_types: List, world_setting: Dict) -> Dict:
        """生成区域BOSS"""
        boss_names = {
            "fantasy": ["暗黑魔王", "远古巨龙", "死亡领主", "深渊之主"],
            "xianxia": ["魔尊", "上古妖王", "天魔", "血海魔神"],
            "wuxia": ["魔教教主", "天下第一高手", "隐世宗师", "武林至尊"],
            "post_apocalyptic": ["虫族女王", "变异始祖", "毁灭者", "终极兵器"],
            "modern_power": ["暗影之主", "魔门门主", "暗黑导师", "堕落古武宗师"],
            "scifi": ["叛变AI·奥米伽", "异形母体", "机械暴君", "纳米瘟疫"],
        }
        world_type = world_setting.get("world_type", "fantasy")
        names = boss_names.get(world_type, boss_names["fantasy"])
        boss_name = random.choice(names)

        # 如果世界观有BOSS相关设定
        if monster_types:
            for mt in monster_types:
                if isinstance(mt, dict) and mt.get("is_boss"):
                    boss_name = mt.get("name", boss_name)
                    break

        return {
            "name": boss_name,
            "description": f"镇守此地的终极强敌，危险等级{danger_level}",
            "level": danger_level * 5 + 5,
            "type": "boss",
        }

    @staticmethod
    def _generate_world_boss_territories(wm: WorldMap, world_setting: Dict):
        """根据世界设定的 dangers.world_bosses 生成世界 BOSS 领地区域（通用框架，任何世界自动生成）。

        每个 BOSS 生成 2-3 个领地区域（铺垫/势力/对峙），其中对峙阶段为 boss_lair，
        放置 BOSS 本体（Lv65）及其直属手下（Lv64）；其余领地放置精英（Lv62）/小兵（Lv60）。
        等级固定使用 WORld_BOSS_LEVELS，保证通用且高于玩家上限（60）。
        """
        dangers = world_setting.get("dangers", {}) if world_setting else {}
        bosses = dangers.get("world_bosses", [])
        if not bosses:
            return

        monster_types = dangers.get("monster_types", [])
        world_type = world_setting.get("world_type", "fantasy")

        # 已占用的格子坐标（避免与主要区域重叠）
        occupied = {(r.x, r.y) for r in wm.regions.values()}

        def next_free_cell():
            for y in range(wm.grid_size):
                for x in range(wm.grid_size):
                    if (x, y) not in occupied:
                        occupied.add((x, y))
                        return x, y
            return None

        for boss in bosses:
            if not isinstance(boss, dict):
                continue
            boss_name = boss.get("name") or "世界之敌"
            boss_id = boss_name.lower().replace(" ", "_").replace("·", "_").strip("_")
            if not boss_id:
                boss_id = "world_enemy"

            # 领地区域名：优先用 boss.territories，补齐到 2-3 个
            territories = [t for t in boss.get("territories", []) if t]
            territories = territories[:3]
            while len(territories) < 2:
                territories.append(f"{boss_name}领地")
            territories = territories[:3]

            minions = boss.get("minions", []) or []
            elites = boss.get("elites", []) or []
            subordinates = boss.get("subordinates", []) or []
            type_name = boss.get("identity") or ""
            desc = boss.get("description") or ""

            for idx, terr_name in enumerate(territories):
                cell = next_free_cell()
                if cell is None:
                    break
                x, y = cell
                is_final = (idx == len(territories) - 1)
                stage = "对峙" if is_final else ("势力" if idx == 1 else "铺垫")
                rtype = "boss_lair" if is_final else "wild"
                danger = 5 if is_final else (4 if idx == 1 else 3)

                region = WorldRegion(
                    region_id=f"{boss_id}_t{idx}",
                    name=terr_name,
                    description=f"{boss_name}的领地之一。「{desc}」" if desc else f"{boss_name}的领地之一。",
                    danger_level=danger,
                    region_type=rtype,
                    x=x,
                    y=y,
                )
                region.world_boss_id = boss_id
                region.world_boss_stage = stage
                region.boss_defeated = False
                region.completion_condition = f"world_boss_defeated:{boss_id}"

                # 怪物分配：铺垫放小兵、势力放精英、对峙放直属手下
                region.monsters = []
                if idx == 0:
                    for n in minions:
                        region.monsters.append({"name": n, "level": WORLD_BOSS_LEVELS["minion"], "type": "normal"})
                elif idx == 1:
                    for n in elites:
                        region.monsters.append({"name": n, "level": WORLD_BOSS_LEVELS["elite"], "type": "elite"})
                else:
                    for n in subordinates:
                        region.monsters.append({"name": n, "level": WORLD_BOSS_LEVELS["subordinate"], "type": "elite"})

                # 对峙阶段放入 BOSS 本体
                if is_final:
                    region.boss = {
                        "name": boss_name,
                        "description": desc,
                        "identity": type_name,
                        "level": WORLD_BOSS_LEVELS["boss"],
                        "type": "boss",
                        "can_surrender": bool(boss.get("can_surrender", True)),
                        "can_join": bool(boss.get("can_join", True)),
                        "world_boss_id": boss_id,
                    }

                wm.add_region(region)

        # 重新建立格子连接，让 BOSS 领地区域与周边区域互通
        MapGenerator._build_grid_connections(wm)

    @staticmethod
    def _build_connections(wm: WorldMap):
        """构建区域连接关系"""
        region_ids = list(wm.regions.keys())
        if len(region_ids) < 2:
            return

        # 按类型分组
        towns = [r for r in region_ids if wm.regions[r].region_type == "town"]
        wilds = [r for r in region_ids if wm.regions[r].region_type == "wild"]
        dungeons = [r for r in region_ids if wm.regions[r].region_type == "dungeon"]
        boss_lairs = [r for r in region_ids if wm.regions[r].region_type == "boss_lair"]
        secrets = [r for r in region_ids if wm.regions[r].region_type == "secret"]

        # town → wild（每个城镇连接1-2个野外）
        for town in towns:
            connected = random.sample(wilds, min(2, len(wilds))) if wilds else []
            for w in connected:
                if w not in wm.regions[town].connections:
                    wm.regions[town].connections.append(w)
                if town not in wm.regions[w].connections:
                    wm.regions[w].connections.append(town)

        # wild → wild（相邻野外互连）
        for i, w in enumerate(wilds):
            if i + 1 < len(wilds):
                next_w = wilds[i + 1]
                if next_w not in wm.regions[w].connections:
                    wm.regions[w].connections.append(next_w)
                if w not in wm.regions[next_w].connections:
                    wm.regions[next_w].connections.append(w)

        # wild → dungeon（每个地下城连接1个野外）
        for d in dungeons:
            if wilds:
                connected_wild = random.choice(wilds)
                if d not in wm.regions[connected_wild].connections:
                    wm.regions[connected_wild].connections.append(d)
                if connected_wild not in wm.regions[d].connections:
                    wm.regions[d].connections.append(connected_wild)

        # dungeon/wild → boss_lair
        high_danger = [r for r in region_ids if wm.regions[r].danger_level >= 3 and r not in boss_lairs]
        for bl in boss_lairs:
            if high_danger:
                connected = random.choice(high_danger)
                if bl not in wm.regions[connected].connections:
                    wm.regions[connected].connections.append(bl)
                if connected not in wm.regions[bl].connections:
                    wm.regions[bl].connections.append(connected)

        # secret → 随机一个 wild 或 dungeon
        for s in secrets:
            candidates = wilds + dungeons
            if candidates:
                connected = random.choice(candidates)
                if s not in wm.regions[connected].connections:
                    wm.regions[connected].connections.append(s)
                if connected not in wm.regions[s].connections:
                    wm.regions[s].connections.append(connected)

    @staticmethod
    def get_map_summary(wm: WorldMap) -> str:
        """获取地图摘要文本（用于状态展示）"""
        current = wm.get_current_region()
        if not current:
            return "🗺️ 未知区域"

        parts = [f"🗺️ {current.name}（危险度{'★' * current.danger_level or '安全'}）"]

        # 相邻区域
        adjacent = wm.get_adjacent_regions()
        if adjacent:
            adj_names = []
            for r in adjacent:
                if r.explored:
                    adj_names.append(f"{r.name}({'★' * r.danger_level or '安全'})")
                else:
                    adj_names.append("❓未知区域")
            parts.append(f"可达：{'、'.join(adj_names)}")

        # 当前区域的怪物
        if current.monsters:
            m_names = [m.get("name", "?") for m in current.monsters]
            parts.append(f"出没：{'、'.join(m_names)}")

        # BOSS
        if current.boss and not current.boss_defeated:
            parts.append(f"💀 BOSS：{current.boss.get('name', '?')}")

        # NPC
        if current.npcs:
            parts.append(f"👥 居民：{'、'.join(current.npcs)}")

        return "\n".join(parts)
