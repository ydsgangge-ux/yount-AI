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


class WorldRegion:
    """单个区域"""

    def __init__(self, region_id: str, name: str, description: str,
                 danger_level: int = 1, region_type: str = "wild",
                 connections: List[str] = None):
        self.region_id = region_id
        self.name = name
        self.description = description
        self.danger_level = danger_level  # 1-5，越高越危险
        self.region_type = region_type    # wild/town/dungeon/boss_lair/secret
        self.connections = connections or []  # 相连区域的ID列表
        self.monsters: List[Dict] = []        # 该区域的怪物模板
        self.boss: Optional[Dict] = None      # 区域BOSS
        self.npcs: List[str] = []             # 该区域出现的NPC ID列表
        self.explored = False                  # 是否已被探索
        self.boss_defeated = False             # BOSS是否已被击败
        self.discoveries: List[Dict] = []      # 可发现的物品/事件

    def to_dict(self) -> Dict:
        return {
            "region_id": self.region_id,
            "name": self.name,
            "description": self.description,
            "danger_level": self.danger_level,
            "region_type": self.region_type,
            "connections": self.connections,
            "monsters": self.monsters,
            "boss": self.boss,
            "npcs": self.npcs,
            "explored": self.explored,
            "boss_defeated": self.boss_defeated,
            "discoveries": self.discoveries,
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
        )
        r.monsters = data.get("monsters", [])
        r.boss = data.get("boss")
        r.npcs = data.get("npcs", [])
        r.explored = data.get("explored", False)
        r.boss_defeated = data.get("boss_defeated", False)
        r.discoveries = data.get("discoveries", [])
        return r


class WorldMap:
    """世界地图"""

    def __init__(self):
        self.regions: Dict[str, WorldRegion] = {}
        self.current_region_id: Optional[str] = None  # 玩家当前所在区域
        self.start_region_id: Optional[str] = None     # 出生点

    def add_region(self, region: WorldRegion):
        self.regions[region.region_id] = region

    def get_region(self, region_id: str) -> Optional[WorldRegion]:
        return self.regions.get(region_id)

    def get_current_region(self) -> Optional[WorldRegion]:
        if self.current_region_id:
            return self.regions.get(self.current_region_id)
        return None

    def get_adjacent_regions(self, region_id: str = None) -> List[WorldRegion]:
        """获取相邻区域（已探索的显示详情，未探索的只显示名称）"""
        rid = region_id or self.current_region_id
        region = self.regions.get(rid) if rid else None
        if not region:
            return []
        return [self.regions[c] for c in region.connections if c in self.regions]

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

    def get_map_display(self, region_id: str = None) -> Dict:
        """获取前端地图显示数据，为相邻区域分配方向标签"""
        rid = region_id or self.current_region_id
        current = self.regions.get(rid) if rid else None
        if not current:
            return {"current": None, "adjacent": []}

        # 8个方向，按顺序分配给相邻区域
        directions = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]
        adjacent = []
        for i, cid in enumerate(current.connections):
            region = self.regions.get(cid)
            if not region:
                continue
            dir_label = directions[i % len(directions)] if i < len(directions) else "?"
            adjacent.append({
                "region_id": cid,
                "name": region.name if region.explored else "未知",
                "direction": dir_label,
                "explored": region.explored,
                "danger_level": region.danger_level if region.explored else 0,
                "region_type": region.region_type if region.explored else "unknown",
            })

        return {
            "current": {
                "region_id": current.region_id,
                "name": current.name,
                "description": current.description,
                "danger_level": current.danger_level,
                "region_type": current.region_type,
                "explored": current.explored,
            },
            "adjacent": adjacent,
        }

    def can_move_to(self, target_id: str) -> bool:
        """检查是否可以移动到目标区域（必须相邻且已探索）"""
        current = self.get_current_region()
        if not current:
            return False
        # 可以移动到相邻区域，或已探索的相邻区域
        return target_id in current.connections and target_id in self.regions

    def to_dict(self) -> Dict:
        return {
            "regions": {rid: r.to_dict() for rid, r in self.regions.items()},
            "current_region_id": self.current_region_id,
            "start_region_id": self.start_region_id,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "WorldMap":
        wm = cls()
        for rid, rdata in data.get("regions", {}).items():
            wm.regions[rid] = WorldRegion.from_dict(rdata)
        wm.current_region_id = data.get("current_region_id")
        wm.start_region_id = data.get("start_region_id")
        return wm


class MapGenerator:
    """根据世界观自动生成地图"""

    # 世界类型 → 区域模板
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
    @staticmethod
    def generate(world_setting: Dict, llm_client=None) -> WorldMap:
        """根据世界观生成地图。优先用LLM生成，失败则用模板。"""
        world_type = world_setting.get("world_type", "fantasy")
        templates = MapGenerator.REGION_TEMPLATES.get(world_type, MapGenerator.REGION_TEMPLATES["fantasy"])

        # 尝试 LLM 生成
        if llm_client:
            try:
                return MapGenerator._generate_with_llm(world_setting, llm_client)
            except Exception as e:
                print(f"[WorldMap] LLM生成失败，使用模板: {e}")

        # 模板生成
        return MapGenerator._generate_from_template(templates, world_setting)

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
