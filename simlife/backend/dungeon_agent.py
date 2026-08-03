"""
Dungeon Agent — 地下城副本生成与管理

核心设计（参考 Dungeon_Agent_设计文档.txt，精简实用版）：
- 只负责"布置和设定"，不负责剧情叙事
- 骨架层(Skeleton)：一次性生成锁定（房间拓扑+叙事身份+Boss位置）
- 内容层(Content)：懒加载，走到哪个房间生成哪个，生成后锁定
- 发现状态(DiscoveryState)：唯一运行时可变部分
- 持久化到 simlife/data/dungeons/{dungeon_id}.json

与现有系统集成：
- world_map.py 中 dungeon 类型区域 → 触发 DungeonAgent
- 战斗走 combat_system / death_mode._quick_combat
- 不做 Referee（LLM裁判），意外行动走现有 simlife_action
"""
import random
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── 路径 ──
DATA_DIR = Path(__file__).parent.parent / "data"
DUNGEON_DIR = DATA_DIR / "dungeons"


# ============================================================
# 数据结构
# ============================================================

class DungeonRoom:
    """单个房间（骨架+内容）"""

    def __init__(self, room_id: str, name: str, narrative_role: str,
                 connections: List[str] = None, is_entrance: bool = False,
                 is_boss: bool = False):
        self.room_id = room_id
        self.name = name                      # 房间名称（如"废弃守卫室"）
        self.narrative_role = narrative_role  # 叙事角色（如"曾经的守卫室，现已废弃"）
        self.connections = connections or []  # 相连房间ID
        self.is_entrance = is_entrance
        self.is_boss = is_boss

        # ── 内容层（懒加载）──
        self.generated = False
        self.enemies: List[Dict] = []     # 怪物配置 [{"name":..., "level":..., "type":...}]
        self.hazards: List[Dict] = []     # 陷阱 [{"id":..., "type":..., "damage":..., "description":...}]
        self.loot: List[Dict] = []        # 战利品 [{"name":..., "type":..., "rarity":...}]
        self.description: str = ""        # 房间详细描述（生成后锁定）

    def to_dict(self) -> Dict:
        return {
            "room_id": self.room_id,
            "name": self.name,
            "narrative_role": self.narrative_role,
            "connections": self.connections,
            "is_entrance": self.is_entrance,
            "is_boss": self.is_boss,
            "generated": self.generated,
            "enemies": self.enemies,
            "hazards": self.hazards,
            "loot": self.loot,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "DungeonRoom":
        r = cls(
            room_id=d["room_id"],
            name=d.get("name", ""),
            narrative_role=d.get("narrative_role", ""),
            connections=d.get("connections", []),
            is_entrance=d.get("is_entrance", False),
            is_boss=d.get("is_boss", False),
        )
        r.generated = d.get("generated", False)
        r.enemies = d.get("enemies", [])
        r.hazards = d.get("hazards", [])
        r.loot = d.get("loot", [])
        r.description = d.get("description", "")
        return r


class Dungeon:
    """一个完整的地下城实例"""

    def __init__(self, dungeon_id: str, region_id: str, world_type: str,
                 name: str = "", lore: str = ""):
        self.dungeon_id = dungeon_id
        self.region_id = region_id        # 关联的 world_map 区域ID
        self.world_type = world_type
        self.name = name                  # 地下城名称
        self.lore = lore                  # 叙事身份（谁建的/为什么存在/历史锚点）
        self.rooms: Dict[str, DungeonRoom] = {}
        self.entrance_id: Optional[str] = None
        self.boss_room_id: Optional[str] = None
        self.boss_defeated = False
        self.completed = False

        # ── 运行时状态（唯一可变部分）──
        self.current_room_id: Optional[str] = None
        self.visited_rooms: List[str] = []
        self.cleared_rooms: List[str] = []  # 怪物已清除的房间

    def add_room(self, room: DungeonRoom):
        self.rooms[room.room_id] = room
        if room.is_entrance:
            self.entrance_id = room.room_id
        if room.is_boss:
            self.boss_room_id = room.room_id

    def get_room(self, room_id: str) -> Optional[DungeonRoom]:
        return self.rooms.get(room_id)

    def get_current_room(self) -> Optional[DungeonRoom]:
        if self.current_room_id:
            return self.rooms.get(self.current_room_id)
        return None

    def get_adjacent_rooms(self, room_id: str = None) -> List[DungeonRoom]:
        rid = room_id or self.current_room_id
        room = self.rooms.get(rid) if rid else None
        if not room:
            return []
        return [self.rooms[c] for c in room.connections if c in self.rooms]

    def can_move_to_room(self, target_id: str) -> bool:
        current = self.get_current_room()
        if not current:
            return False
        return target_id in current.connections and target_id in self.rooms

    def to_dict(self) -> Dict:
        return {
            "dungeon_id": self.dungeon_id,
            "region_id": self.region_id,
            "world_type": self.world_type,
            "name": self.name,
            "lore": self.lore,
            "rooms": {rid: r.to_dict() for rid, r in self.rooms.items()},
            "entrance_id": self.entrance_id,
            "boss_room_id": self.boss_room_id,
            "boss_defeated": self.boss_defeated,
            "completed": self.completed,
            "current_room_id": self.current_room_id,
            "visited_rooms": self.visited_rooms,
            "cleared_rooms": self.cleared_rooms,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Dungeon":
        dg = cls(
            dungeon_id=d["dungeon_id"],
            region_id=d.get("region_id", ""),
            world_type=d.get("world_type", "fantasy"),
            name=d.get("name", ""),
            lore=d.get("lore", ""),
        )
        for rid, rdata in d.get("rooms", {}).items():
            dg.add_room(DungeonRoom.from_dict(rdata))
        dg.entrance_id = d.get("entrance_id")
        dg.boss_room_id = d.get("boss_room_id")
        dg.boss_defeated = d.get("boss_defeated", False)
        dg.completed = d.get("completed", False)
        dg.current_room_id = d.get("current_room_id")
        dg.visited_rooms = d.get("visited_rooms", [])
        dg.cleared_rooms = d.get("cleared_rooms", [])
        return dg


# ============================================================
# Dungeon Agent — 生成与管理
# ============================================================

class DungeonAgent:
    """地下城生成器和管理器"""

    # 房间叙事角色模板（按世界类型）
    ROOM_NARRATIVE_TEMPLATES = {
        "fantasy": [
            "废弃的守卫室，武器架早已锈蚀",
            "曾经的议事厅，长桌上布满灰尘",
            "地下墓穴，尸骨排列在墙边",
            "祭祀大厅，地上画着褪色的魔法阵",
            "储藏室，散落着腐朽的木箱",
            "天然溶洞，滴水声在黑暗中回荡",
            "图书馆废墟，书页散落一地",
            "监牢，铁栏后是无尽的黑暗",
            "武器库，架子上还挂着几把旧武器",
            "暗门后的密室，墙上刻着古老的符文",
        ],
        "xianxia": [
            "废弃的炼丹房，丹炉早已冰冷",
            "藏经阁残址，玉简碎片散落",
            "灵石矿洞，开采痕迹依稀可见",
            "妖兽巢穴，骨殖遍地",
            "阵法残骸，灵纹若隐若现",
            "宗门禁地，封印石碑已裂",
            "剑冢，无数残剑插在石壁上",
            "灵泉干涸的洞府，灵气稀薄",
            "演武场废墟，石桩断裂",
            "供奉殿，神像已经倾颓",
        ],
        "post_apocalyptic": [
            "废弃的安检站，扫描仪早已断电",
            "员工休息室，桌上有发霉的咖啡杯",
            "实验室残骸，玻璃器皿碎了一地",
            "通风管道 junction，风扇还在缓慢转动",
            "应急物资仓库，大部分已被搜刮",
            "配电室，电火花偶尔闪现",
            "隔离观察室，玻璃墙上有抓痕",
            "停车场废墟，车辆锈迹斑斑",
            "服务器机房，指示灯微弱闪烁",
            "紧急逃生通道，门被强行焊死",
        ],
        "modern_power": [
            "地下训练场，沙袋已经破损",
            "能力者检测室，仪器屏幕碎裂",
            "封锁的档案室，文件散落一地",
            "能量抑制室，墙壁上有烧灼痕迹",
            "废弃的休息区，自动售货机歪斜",
            "实验观察室，防弹玻璃有裂纹",
            "武器存放间，架子已空",
            "紧急 stairwell，应急灯闪烁",
            "监控中心，屏幕全部黑屏",
            "密室，墙上有能力者战斗的痕迹",
        ],
        "scifi": [
            "气闸舱，舱门半开",
            "船员宿舍，私人物品散落",
            "生命维持系统，管道在泄漏",
            "数据中心，服务器还在嗡嗡作响",
            "医疗舱，手术台上有不明污渍",
            "货舱，集装箱堆叠如山",
            "引擎室，散热片发着红光",
            "舰桥，导航台闪烁着警告",
            "逃生舱区，大部分已发射",
            "AI核心室，全息投影忽明忽暗",
        ],
    }

    # 陷阱模板
    HAZARD_TEMPLATES = [
        {"type": "spike_trap", "name": "尖刺陷阱", "damage": 8, "description": "地面的石板突然弹开，露出锋利的尖刺"},
        {"type": "poison_dart", "name": "毒镖机关", "damage": 6, "description": "墙壁孔洞中射出涂毒的飞镖"},
        {"type": "fire_rune", "name": "火焰符文", "damage": 10, "description": "踩到符文，火焰骤然升腾"},
        {"type": "falling_rocks", "name": "落石机关", "damage": 12, "description": "天花板松动，巨石砸落"},
        {"type": "magic_ward", "name": "魔法结界", "damage": 8, "description": "触碰结界，电流贯穿全身"},
        {"type": "ice_floor", "name": "冰霜地面", "damage": 4, "description": "地面覆满暗冰，难以站稳"},
        {"type": "gas_leak", "name": "毒气泄漏", "damage": 6, "description": "空气中弥漫着刺鼻的毒气"},
    ]

    def __init__(self, llm_client=None):
        self.llm = llm_client

    # ── 骨架生成 ──

    def generate_skeleton(self, region_id: str, region_name: str,
                          world_type: str, world_setting: Dict,
                          char_level: int = 1) -> Dungeon:
        """生成地下城骨架（一次性，永久锁定）

        优先用LLM生成叙事身份和房间拓扑，失败则用模板。
        """
        dungeon_id = f"dng_{region_id}_{world_type}"

        if self.llm:
            try:
                return self._generate_skeleton_with_llm(
                    dungeon_id, region_id, region_name, world_type, world_setting, char_level
                )
            except Exception as e:
                print(f"[DungeonAgent] LLM生成骨架失败，使用模板: {e}")

        return self._generate_skeleton_template(
            dungeon_id, region_id, region_name, world_type, char_level
        )

    def _generate_skeleton_with_llm(self, dungeon_id: str, region_id: str,
                                     region_name: str, world_type: str,
                                     world_setting: Dict, char_level: int) -> Dungeon:
        """用LLM生成骨架"""
        world_name = world_setting.get("world_name", "未知世界")
        monster_types = world_setting.get("dangers", {}).get("monster_types", [])

        monsters_text = ""
        if monster_types:
            mt_names = [m.get("name", str(m)) if isinstance(m, dict) else str(m)
                        for m in monster_types[:6]]
            monsters_text = f"常见怪物：{'、'.join(mt_names)}"

        room_templates = self.ROOM_NARRATIVE_TEMPLATES.get(
            world_type, self.ROOM_NARRATIVE_TEMPLATES["fantasy"]
        )
        rooms_hint = "；".join(random.sample(room_templates, min(6, len(room_templates))))

        prompt = f"""你是地下城设计Agent。请为以下世界生成一个地下城的骨架结构。

世界：{world_name}（类型：{world_type}）
地下城名称：{region_name}
玩家等级：{char_level}
{monsters_text}

设计要求：
1. 生成5-8个房间，包含：入口(1个)、普通房间(3-5个)、Boss房(1个)
2. 每个房间有：房间ID(room_001格式)、名称、叙事角色(1句话描述这个房间曾经是什么/为什么存在)
3. 房间之间有连接关系，形成可探索的路径（入口→...→Boss房）
4. 房间叙事角色参考：{rooms_hint}
5. 给地下城一个叙事身份（谁建的/为什么存在/1-2个历史锚点）

返回JSON格式：
{{
  "name": "地下城名称",
  "lore": "2-3句话的叙事身份描述",
  "rooms": [
    {{
      "id": "room_001",
      "name": "房间名称",
      "narrative_role": "叙事角色描述",
      "is_entrance": true/false,
      "is_boss": true/false,
      "connections": ["room_002", ...]
    }}
  ]
}}

只返回JSON，不要其他文字。"""

        response = self.llm.generate(prompt, max_tokens=1200, temperature=0.8, thinking=False)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        result = json.loads(response)

        dg = Dungeon(
            dungeon_id=dungeon_id,
            region_id=region_id,
            world_type=world_type,
            name=result.get("name", region_name),
            lore=result.get("lore", ""),
        )

        for rdata in result.get("rooms", []):
            room = DungeonRoom(
                room_id=rdata["id"],
                name=rdata.get("name", ""),
                narrative_role=rdata.get("narrative_role", ""),
                connections=rdata.get("connections", []),
                is_entrance=rdata.get("is_entrance", False),
                is_boss=rdata.get("is_boss", False),
            )
            dg.add_room(room)

        # 验证入口和Boss房存在
        if not dg.entrance_id and dg.rooms:
            first = list(dg.rooms.keys())[0]
            dg.rooms[first].is_entrance = True
            dg.entrance_id = first
        if not dg.boss_room_id and dg.rooms:
            last = list(dg.rooms.keys())[-1]
            dg.rooms[last].is_boss = True
            dg.boss_room_id = last

        return dg

    def _generate_skeleton_template(self, dungeon_id: str, region_id: str,
                                     region_name: str, world_type: str,
                                     char_level: int) -> Dungeon:
        """模板生成骨架（LLM不可用时）"""
        templates = self.ROOM_NARRATIVE_TEMPLATES.get(
            world_type, self.ROOM_NARRATIVE_TEMPLATES["fantasy"]
        )
        # 随机选5-7个房间
        room_count = random.randint(5, 7)
        selected = random.sample(templates, min(room_count, len(templates)))

        dg = Dungeon(
            dungeon_id=dungeon_id,
            region_id=region_id,
            world_type=world_type,
            name=region_name,
            lore=f"一座被遗忘的{region_name}，据说深处藏着强大的守护者。",
        )

        # 线性+分支结构
        room_ids = [f"room_{i+1:03d}" for i in range(len(selected))]
        for i, (rid, role) in enumerate(zip(room_ids, selected)):
            is_entrance = (i == 0)
            is_boss = (i == len(selected) - 1)
            # 连接：线性前后 + 随机分支
            conns = []
            if i + 1 < len(selected):
                conns.append(room_ids[i + 1])
            if i > 0:
                conns.append(room_ids[i - 1])
            room = DungeonRoom(
                room_id=rid,
                name=role.split("，")[0] if "，" in role else role[:8],
                narrative_role=role,
                connections=conns,
                is_entrance=is_entrance,
                is_boss=is_boss,
            )
            dg.add_room(room)

        return dg

    # ── 内容层生成（懒加载）──

    def generate_room_content(self, dungeon: Dungeon, room: DungeonRoom,
                              char_level: int, world_setting: Dict):
        """生成房间内容（懒加载，生成后锁定）"""
        if room.generated:
            return

        # 根据房间叙事角色推导内容
        role = room.narrative_role
        role_lower = role.lower()

        # ── 怪物配置 ──
        if room.is_boss:
            # Boss房：1个Boss
            boss_level = char_level + random.randint(2, 4)
            monster_types = world_setting.get("dangers", {}).get("monster_types", [])
            boss_name = self._pick_boss_name(dungeon.world_type, monster_types)
            room.enemies = [{
                "name": boss_name,
                "level": boss_level,
                "type": "boss",
            }]
        elif room.is_entrance:
            # 入口房：少量弱怪或无怪
            if random.random() < 0.4:
                room.enemies = [{
                    "name": self._pick_monster_name(dungeon.world_type, world_setting),
                    "level": max(1, char_level - random.randint(2, 3)),
                    "type": "normal",
                }]
            else:
                room.enemies = []
        else:
            # 普通房间：1-3个怪
            count = random.randint(1, 3)
            is_elite = random.random() < 0.2
            room.enemies = []
            for i in range(count):
                enemy_type = "elite" if is_elite and i == 0 else "normal"
                level = char_level + random.randint(-1, 1) if enemy_type == "elite" else char_level - random.randint(0, 2)
                room.enemies.append({
                    "name": self._pick_monster_name(dungeon.world_type, world_setting),
                    "level": max(1, level),
                    "type": enemy_type,
                })

        # ── 陷阱 ──
        if not room.is_entrance and not room.is_boss:
            # 30%概率有陷阱
            if random.random() < 0.3:
                hazard = random.choice(self.HAZARD_TEMPLATES).copy()
                hazard["id"] = f"hazard_{room.room_id}"
                room.hazards = [hazard]
            else:
                room.hazards = []
        else:
            room.hazards = []

        # ── 战利品 ──
        room.loot = self._generate_loot(room, char_level, dungeon.world_type)

        # ── 房间描述 ──
        room.description = self._generate_room_description(room, dungeon)

        room.generated = True

    def _pick_monster_name(self, world_type: str, world_setting: Dict) -> str:
        """从世界观中选取怪物名"""
        monster_types = world_setting.get("dangers", {}).get("monster_types", [])
        if monster_types:
            mt = random.choice(monster_types)
            if isinstance(mt, dict):
                return mt.get("name", "魔物")
            return str(mt)
        # 默认怪物名
        defaults = {
            "fantasy": ["哥布林", "骷髅兵", "暗影狼", "石像鬼"],
            "xianxia": ["妖兽", "魔修", "尸傀", "邪灵"],
            "post_apocalyptic": ["变异犬", "感染者", "掠夺者", "变异鼠"],
            "modern_power": ["暗影能力者", "失控者", "黑衣人", "精神污染体"],
            "scifi": ["故障机器人", "变异体", "叛变安保", "寄生体"],
        }
        names = defaults.get(world_type, defaults["fantasy"])
        return random.choice(names)

    def _pick_boss_name(self, world_type: str, monster_types: List) -> str:
        """选取Boss名"""
        # 优先从世界观的Boss怪
        for mt in monster_types:
            if isinstance(mt, dict) and mt.get("is_boss"):
                return mt.get("name", "地下城守护者")
        boss_names = {
            "fantasy": ["地下城领主", "远古守卫", "腐化骑士", "深渊之主"],
            "xianxia": ["魔修长老", "上古妖王", "阵法守护灵", "魔尊分身"],
            "post_apocalyptic": ["变异始祖", "虫巢守卫", "毁灭者", "终极兵器"],
            "modern_power": ["暗影之主", "堕落宗师", "能力者首领", "精神支配者"],
            "scifi": ["叛变AI核心", "异形母体", "机械暴君", "纳米集合体"],
        }
        names = boss_names.get(world_type, boss_names["fantasy"])
        return random.choice(names)

    def _generate_loot(self, room: DungeonRoom, char_level: int, world_type: str) -> List[Dict]:
        """生成战利品"""
        loot = []

        if room.is_boss:
            # Boss房必掉装备+金币
            loot.append({"name": "金币", "type": "gold", "amount": char_level * random.randint(15, 25)})
            loot.append({"name": "随机装备", "type": "equipment", "rarity": "rare",
                         "level": char_level + random.randint(0, 2)})
        elif room.is_entrance:
            # 入口房少量金币
            if random.random() < 0.5:
                loot.append({"name": "金币", "type": "gold", "amount": char_level * random.randint(2, 5)})
        else:
            # 普通房：概率掉落
            if random.random() < 0.4:
                loot.append({"name": "金币", "type": "gold", "amount": char_level * random.randint(3, 8)})
            if random.random() < 0.15:
                loot.append({"name": "药水", "type": "consumable", "rarity": "common"})

        return loot

    def _generate_room_description(self, room: DungeonRoom, dungeon: Dungeon) -> str:
        """生成房间描述（简短，不参与叙事）"""
        parts = [room.narrative_role]
        if room.is_entrance:
            parts.append("这是地下城的入口。")
        if room.is_boss:
            parts.append("空气中弥漫着压迫感，这里是最深处。")
        if room.enemies:
            count = len(room.enemies)
            if room.enemies[0].get("type") == "boss":
                parts.append(f"前方是{room.enemies[0]['name']}。")
            else:
                parts.append(f"这里有{count}个敌人。")
        if room.hazards:
            parts.append("似乎暗藏机关。")
        return " ".join(parts)

    # ── 持久化 ──

    @staticmethod
    def save_dungeon(dungeon: Dungeon):
        """保存地下城到文件"""
        DUNGEON_DIR.mkdir(parents=True, exist_ok=True)
        path = DUNGEON_DIR / f"{dungeon.dungeon_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dungeon.to_dict(), f, ensure_ascii=False, indent=2)

    @staticmethod
    def load_dungeon(dungeon_id: str) -> Optional[Dungeon]:
        """从文件加载地下城"""
        path = DUNGEON_DIR / f"{dungeon_id}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Dungeon.from_dict(data)
        except Exception as e:
            print(f"[DungeonAgent] 加载地下城失败: {e}")
            return None

    @staticmethod
    def dungeon_exists(dungeon_id: str) -> bool:
        """检查地下城文件是否存在"""
        return (DUNGEON_DIR / f"{dungeon_id}.json").exists()

    # ── 进入/移动 ──

    def enter_dungeon(self, region_id: str, region_name: str,
                      world_type: str, world_setting: Dict,
                      char_level: int) -> Dungeon:
        """进入地下城（不存在则生成骨架）"""
        dungeon_id = f"dng_{region_id}_{world_type}"

        # 尝试加载已有
        dungeon = self.load_dungeon(dungeon_id)
        if dungeon:
            # 已通关的地下城可以重进（游戏向，小怪刷新）
            if dungeon.completed:
                # 重置运行时状态，保留骨架和已生成内容
                dungeon.current_room_id = dungeon.entrance_id
                dungeon.visited_rooms = [dungeon.entrance_id] if dungeon.entrance_id else []
                dungeon.cleared_rooms = []
                dungeon.boss_defeated = False
                dungeon.completed = False
                # 刷新怪物：重置非Boss房的generated状态，让内容重新生成
                for room in dungeon.rooms.values():
                    if not room.is_boss:
                        room.generated = False
            return dungeon

        # 生成新骨架
        dungeon = self.generate_skeleton(
            region_id, region_name, world_type, world_setting, char_level
        )
        # 进入入口房间，生成入口内容
        if dungeon.entrance_id:
            entrance = dungeon.get_room(dungeon.entrance_id)
            if entrance:
                self.generate_room_content(dungeon, entrance, char_level, world_setting)
            dungeon.current_room_id = dungeon.entrance_id
            dungeon.visited_rooms = [dungeon.entrance_id]

        self.save_dungeon(dungeon)
        return dungeon

    def move_to_room(self, dungeon: Dungeon, target_room_id: str,
                     char_level: int, world_setting: Dict) -> Dict:
        """在地下城内移动到相邻房间"""
        if not dungeon.can_move_to_room(target_room_id):
            return {"error": "not_adjacent", "message": "无法到达该房间"}

        room = dungeon.get_room(target_room_id)
        if not room:
            return {"error": "room_not_found"}

        # 懒加载：首次进入时生成内容
        if not room.generated:
            self.generate_room_content(dungeon, room, char_level, world_setting)

        # 移动
        old_room_id = dungeon.current_room_id
        dungeon.current_room_id = target_room_id
        if target_room_id not in dungeon.visited_rooms:
            dungeon.visited_rooms.append(target_room_id)

        self.save_dungeon(dungeon)

        return {
            "success": True,
            "room_id": target_room_id,
            "room_name": room.name,
            "description": room.description,
            "has_enemies": bool(room.enemies) and target_room_id not in dungeon.cleared_rooms,
            "has_hazards": bool(room.hazards),
            "has_loot": bool(room.loot),
            "is_boss": room.is_boss,
            "adjacent": [{"id": r.room_id, "name": r.name,
                          "visited": r.room_id in dungeon.visited_rooms}
                         for r in dungeon.get_adjacent_rooms(target_room_id)],
        }

    def clear_room_enemies(self, dungeon: Dungeon, room_id: str):
        """标记房间怪物已清除"""
        if room_id not in dungeon.cleared_rooms:
            dungeon.cleared_rooms.append(room_id)
        # 如果是Boss房，标记通关
        room = dungeon.get_room(room_id)
        if room and room.is_boss:
            dungeon.boss_defeated = True
            dungeon.completed = True
        self.save_dungeon(dungeon)

    def get_dungeon_display(self, dungeon: Dungeon) -> Dict:
        """获取地下城展示信息（前端用）"""
        current = dungeon.get_current_room()
        if not current:
            return {"error": "no_current_room"}

        adjacent = dungeon.get_adjacent_rooms()

        return {
            "dungeon_id": dungeon.dungeon_id,
            "dungeon_name": dungeon.name,
            "lore": dungeon.lore,
            "current_room": {
                "room_id": current.room_id,
                "name": current.name,
                "description": current.description,
                "is_entrance": current.is_entrance,
                "is_boss": current.is_boss,
                "has_enemies": bool(current.enemies) and current.room_id not in dungeon.cleared_rooms,
                "enemy_count": len(current.enemies) if current.room_id not in dungeon.cleared_rooms else 0,
                "enemies": current.enemies if current.room_id not in dungeon.cleared_rooms else [],
                "has_hazards": bool(current.hazards),
                "has_loot": bool(current.loot),
            },
            "adjacent_rooms": [
                {
                    "room_id": r.room_id,
                    "name": r.name if r.room_id in dungeon.visited_rooms else "???",
                    "visited": r.room_id in dungeon.visited_rooms,
                    "is_boss": r.is_boss,
                    "cleared": r.room_id in dungeon.cleared_rooms,
                }
                for r in adjacent
            ],
            "visited_count": len(dungeon.visited_rooms),
            "total_rooms": len(dungeon.rooms),
            "boss_defeated": dungeon.boss_defeated,
            "completed": dungeon.completed,
        }
