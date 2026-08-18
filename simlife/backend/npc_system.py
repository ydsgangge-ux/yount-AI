"""
NPC系统 — 管理世界中的人物、关系、交互、死亡记录

核心设计：
- NPC有独立属性：名字、职业、性格、位置、状态
- NPC与玩家有关系值（友好/中立/敌对）
- NPC可以交互：对话、交易、任务、战斗
- NPC死亡会记录到英雄殿/死亡记录
- NPC会随剧情移动（位置变化）
"""
import random
from typing import Dict, List, Optional
from datetime import datetime


class NPC:
    """单个NPC"""

    def __init__(self, npc_id: str, name: str, role: str = "村民",
                 personality: str = "友善", location: str = "",
                 faction: str = ""):
        self.npc_id = npc_id
        self.name = name
        self.role = role            # 职业/身份：商人/守卫/猎人/法师/村民/反派等
        self.personality = personality  # 性格关键词
        self.location = location    # 当前所在区域ID
        self.faction = faction      # 所属势力
        self.alive = True
        self.relationship = 0       # 与玩家关系：-100~100（负=敌对，0=中立，正=友好）
        self.fear = 0               # 对玩家的恐惧：0~100（越高越怕你，越可能跪/逃/让路）
        self.level = 1
        self.hp = 50
        self.max_hp = 50
        self.can_trade = False      # 是否可交易
        self.can_quest = False      # 是否有任务
        self.quest_given = False    # 是否已给过任务
        self.dialogue_hint = ""     # 对话提示（简短描述NPC会说什么）
        self.death_record = None    # 死亡记录

    def to_dict(self) -> Dict:
        return {
            "npc_id": self.npc_id,
            "name": self.name,
            "role": self.role,
            "personality": self.personality,
            "location": self.location,
            "faction": self.faction,
            "alive": self.alive,
            "relationship": self.relationship,
            "fear": self.fear,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "can_trade": self.can_trade,
            "can_quest": self.can_quest,
            "quest_given": self.quest_given,
            "dialogue_hint": self.dialogue_hint,
            "death_record": self.death_record,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "NPC":
        npc = cls(
            npc_id=data["npc_id"],
            name=data["name"],
            role=data.get("role", "村民"),
            personality=data.get("personality", "友善"),
            location=data.get("location", ""),
            faction=data.get("faction", ""),
        )
        npc.alive = data.get("alive", True)
        npc.relationship = data.get("relationship", 0)
        npc.fear = data.get("fear", 0)
        npc.level = data.get("level", 1)
        npc.hp = data.get("hp", 50)
        npc.max_hp = data.get("max_hp", 50)
        npc.can_trade = data.get("can_trade", False)
        npc.can_quest = data.get("can_quest", False)
        npc.quest_given = data.get("quest_given", False)
        npc.dialogue_hint = data.get("dialogue_hint", "")
        npc.death_record = data.get("death_record")
        return npc

    def get_relation_label(self) -> str:
        """获取关系标签"""
        if self.relationship >= 50:
            return "挚友"
        elif self.relationship >= 20:
            return "友好"
        elif self.relationship >= -20:
            return "中立"
        elif self.relationship >= -50:
            return "敌对"
        else:
            return "死敌"

    def change_relationship(self, delta: int):
        """改变关系值"""
        self.relationship = max(-100, min(100, self.relationship + delta))

    def get_fear_label(self) -> str:
        """获取恐惧标签"""
        if self.fear >= 90:
            return "魂飞魄散"
        elif self.fear >= 75:
            return "惊惧"
        elif self.fear >= 55:
            return "畏惧"
        elif self.fear >= 35:
            return "紧张"
        else:
            return "无所畏惧"

    def change_fear(self, delta: int):
        """改变恐惧值（0~100）"""
        self.fear = max(0, min(100, self.fear + delta))


class NPCSystem:
    """NPC管理系统"""

    # 世界类型 → NPC角色模板
    NPC_ROLES = {
        "fantasy": [
            {"role": "商人", "personality": "精明", "can_trade": True, "dialogue": "欢迎光临！看看有什么需要的？"},
            {"role": "守卫", "personality": "严肃", "can_quest": True, "dialogue": "最近附近不太平，要小心。"},
            {"role": "猎人", "personality": "沉默寡言", "can_quest": True, "dialogue": "森林里有些不对劲…"},
            {"role": "药师", "personality": "温和", "can_trade": True, "dialogue": "受伤了？我这里有药。"},
            {"role": "老者", "personality": "睿智", "can_quest": True, "dialogue": "年轻人，这个世界比你想象的要危险。"},
            {"role": "盗贼", "personality": "狡猾", "can_trade": True, "dialogue": "嘿嘿，有些好东西你要不要看看？"},
            {"role": "女巫", "personality": "神秘", "can_quest": True, "dialogue": "命运之线已经交织…"},
        ],
        "xianxia": [
            {"role": "炼丹师", "personality": "严谨", "can_trade": True, "dialogue": "道友需要丹药？"},
            {"role": "长老", "personality": "严厉", "can_quest": True, "dialogue": "修炼不可懈怠！"},
            {"role": "散修", "personality": "自由", "can_quest": True, "dialogue": "天地之间，何处不可去？"},
            {"role": "掌柜", "personality": "市侩", "can_trade": True, "dialogue": "灵石面前，概不赊账！"},
            {"role": "师兄", "personality": "关怀", "can_quest": True, "dialogue": "师弟小心，最近妖兽出没频繁。"},
            {"role": "魔修", "personality": "阴冷", "can_trade": True, "dialogue": "嘿嘿，想要力量吗？"},
            {"role": "隐士", "personality": "超然", "can_quest": True, "dialogue": "天道无常…"},
        ],
        "wuxia": [
            {"role": "客栈掌柜", "personality": "圆滑", "can_trade": True, "dialogue": "客官住店还是打尖？"},
            {"role": "铁匠", "personality": "豪爽", "can_trade": True, "dialogue": "好刀配好汉，看看这把！"},
            {"role": "镖师", "personality": "稳重", "can_quest": True, "dialogue": "这趟镖不好走啊…"},
            {"role": "江湖郎中", "personality": "热心", "can_trade": True, "dialogue": "祖传秘方，药到病除！"},
            {"role": "丐帮弟子", "personality": "机灵", "can_quest": True, "dialogue": "嘿嘿，我知道些小道消息…"},
            {"role": "侠客", "personality": "正义", "can_quest": True, "dialogue": "路见不平，拔刀相助！"},
            {"role": "隐世高手", "personality": "超然", "can_quest": True, "dialogue": "功夫…不在招式，在心。"},
        ],
        "post_apocalyptic": [
            {"role": "交易商", "personality": "谨慎", "can_trade": True, "dialogue": "以物换物，童叟无欺。"},
            {"role": "医生", "personality": "疲惫", "can_trade": True, "dialogue": "又一个受伤的…躺下吧。"},
            {"role": "佣兵", "personality": "冷酷", "can_quest": True, "dialogue": "有活干？钱到位什么都行。"},
            {"role": "拾荒者", "personality": "机警", "can_quest": True, "dialogue": "我知道一些好地方…"},
            {"role": "领袖", "personality": "坚定", "can_quest": True, "dialogue": "保护大家是我唯一的责任。"},
            {"role": "叛徒", "personality": "狡诈", "can_trade": True, "dialogue": "嘿嘿，情报要买吗？"},
        ],
        "modern_power": [
            {"role": "教官", "personality": "严厉", "can_quest": True, "dialogue": "训练！再训练！"},
            {"role": "情报商", "personality": "神秘", "can_trade": True, "dialogue": "消息都是有价的。"},
            {"role": "同学", "personality": "热血", "can_quest": True, "dialogue": "一起变强吧！"},
            {"role": "医生", "personality": "温柔", "can_trade": True, "dialogue": "受伤了？我来处理。"},
            {"role": "暗线", "personality": "冷漠", "can_quest": True, "dialogue": "…有事说事。"},
            {"role": "古武传人", "personality": "沉稳", "can_quest": True, "dialogue": "武道之路，永无止境。"},
        ],
        "scifi": [
            {"role": "机械师", "personality": "细致", "can_trade": True, "dialogue": "需要改装？我擅长这个。"},
            {"role": "舰长", "personality": "果断", "can_quest": True, "dialogue": "太空不等人。"},
            {"role": "黑客", "personality": "古怪", "can_quest": True, "dialogue": "数据不会说谎…"},
            {"role": "商人", "personality": "精明", "can_trade": True, "dialogue": "星际贸易，利润无限！"},
            {"role": "研究员", "personality": "执着", "can_quest": True, "dialogue": "实验还没有结束…"},
            {"role": "叛军", "personality": "激进", "can_quest": True, "dialogue": "AI不该统治人类！"},
        ],
    }

    def __init__(self):
        self.npcs: Dict[str, NPC] = {}
        self.death_records: List[Dict] = []  # NPC死亡记录

    def add_npc(self, npc: NPC):
        self.npcs[npc.npc_id] = npc

    def get_npc(self, npc_id: str) -> Optional[NPC]:
        return self.npcs.get(npc_id)

    def get_npcs_in_location(self, location_id: str) -> List[NPC]:
        """获取某区域的所有NPC（活着的）"""
        return [n for n in self.npcs.values() if n.location == location_id and n.alive]

    def get_alive_npcs(self) -> List[NPC]:
        """获取所有活着的NPC"""
        return [n for n in self.npcs.values() if n.alive]

    def get_dead_npcs(self) -> List[NPC]:
        """获取所有已死亡的NPC"""
        return [n for n in self.npcs.values() if not n.alive]

    def kill_npc(self, npc_id: str, cause: str, killer: str = "未知"):
        """NPC死亡"""
        npc = self.npcs.get(npc_id)
        if npc and npc.alive:
            npc.alive = False
            record = {
                "npc_id": npc.npc_id,
                "name": npc.name,
                "role": npc.role,
                "level": npc.level,
                "location": npc.location,
                "cause": cause,
                "killer": killer,
                "died_at": datetime.now().isoformat(),
            }
            npc.death_record = record
            self.death_records.append(record)

    def interact(self, npc_id: str, interaction_type: str = "talk") -> Dict:
        """
        与NPC交互
        interaction_type: talk/trade/quest/help/attack
        """
        npc = self.npcs.get(npc_id)
        if not npc or not npc.alive:
            return {"success": False, "message": "此人已不在"}

        result = {"success": True, "npc_name": npc.name, "type": interaction_type}

        if interaction_type == "talk":
            result["message"] = npc.dialogue_hint
            npc.change_relationship(1)
            result["relationship"] = npc.relationship

        elif interaction_type == "trade":
            if npc.can_trade:
                result["message"] = f"与{npc.name}交易"
                result["can_trade"] = True
                npc.change_relationship(2)
            else:
                result["message"] = f"{npc.name}不进行交易"
                result["can_trade"] = False

        elif interaction_type == "quest":
            if npc.can_quest and not npc.quest_given:
                result["message"] = f"{npc.name}给了你一个任务"
                result["has_quest"] = True
                npc.quest_given = True
                npc.change_relationship(5)
            elif npc.quest_given:
                result["message"] = f"{npc.name}的任务已完成或正在进行"
                result["has_quest"] = False
            else:
                result["message"] = f"{npc.name}没有任务可给"
                result["has_quest"] = False

        elif interaction_type == "help":
            result["message"] = f"你帮助了{npc.name}"
            npc.change_relationship(10)
            result["relationship"] = npc.relationship

        elif interaction_type == "intimidate":
            # 实际判定在 death_mode（需玩家属性），此处仅返回基础信息
            result["message"] = f"你威吓了{npc.name}"
            result["intimidate"] = True
            result["fear"] = npc.fear
            result["relationship"] = npc.relationship

        elif interaction_type == "attack":
            result["message"] = f"你攻击了{npc.name}！"
            npc.change_relationship(-30)
            result["relationship"] = npc.relationship

        return result

    def to_dict(self) -> Dict:
        return {
            "npcs": {nid: n.to_dict() for nid, n in self.npcs.items()},
            "death_records": self.death_records,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "NPCSystem":
        system = cls()
        for nid, ndata in data.get("npcs", {}).items():
            system.npcs[nid] = NPC.from_dict(ndata)
        system.death_records = data.get("death_records", [])
        return system


class NPCGenerator:
    """NPC生成器"""

    @staticmethod
    def generate_for_world(world_setting: Dict, world_map, llm_client=None) -> NPCSystem:
        """根据世界观生成NPC。优先用LLM，失败则用模板。
        生成后同步写入区域文件的 npcs 字段，消除内存/文件双轨制。
        """
        if llm_client:
            try:
                system = NPCGenerator._generate_with_llm(world_setting, world_map, llm_client)
            except Exception as e:
                print(f"[NPC] LLM生成失败，使用模板: {e}")
                system = NPCGenerator._generate_from_template(world_setting, world_map)
        else:
            system = NPCGenerator._generate_from_template(world_setting, world_map)

        # 同步 NPC 到区域文件（消除双轨制：文件 npcs 字段 = npc_system 数据源）
        try:
            from simlife.worlds import world_manager as wm
            world_id = world_setting.get("world_id", "")
            if world_id:
                NPCGenerator._sync_npcs_to_region_files(system, world_id, world_map)
        except Exception as e:
            print(f"[NPC] 同步到区域文件失败: {e}")

        return system

    @staticmethod
    def _sync_npcs_to_region_files(npc_system, world_id: str, world_map):
        """把 npc_system 中的 NPC 同步写入对应区域文件的 npcs 字段"""
        # 按 location 分组
        region_npcs = {}  # region_id -> [npc_dict]
        for npc in npc_system.npcs.values():
            loc = npc.location or ""
            if loc not in region_npcs:
                region_npcs[loc] = []
            region_npcs[loc].append({
                "id": npc.npc_id,
                "name": npc.name,
                "role": npc.role,
                "description": npc.personality,
                "faction_id": npc.faction or "",
                "is_key": False,
            })

        # 写入每个区域文件
        from simlife.worlds import world_manager as wm
        for rid, npcs in region_npcs.items():
            try:
                region = wm.load_region(world_id, rid)
                if not region:
                    continue
                # 只在文件没有 npcs 或 npcs 为空时写入（不覆盖 generator 已生成的）
                if not region.get("npcs"):
                    region["npcs"] = npcs
                    wm.save_region(world_id, region)
                    print(f"[NPC] 区域 {rid} 写入 {len(npcs)} 个 NPC")
            except Exception as e:
                print(f"[NPC] 写入区域 {rid} 失败: {e}")

    @staticmethod
    def _generate_from_template(world_setting: Dict, world_map) -> NPCSystem:
        """从模板生成NPC"""
        system = NPCSystem()
        world_type = world_setting.get("world_type", "fantasy")
        roles = NPCSystem.NPC_ROLES.get(world_type, NPCSystem.NPC_ROLES["fantasy"])

        # 获取世界观的势力
        factions = world_setting.get("factions", [])
        faction_names = [f.get("name", "") for f in factions[:4] if isinstance(f, dict)]

        # 名字池
        name_pool = {
            "fantasy": ["艾琳", "加尔", "莉娜", "奥德", "索菲", "卡尔", "薇拉", "赫克托"],
            "xianxia": ["云逸", "青鸾", "墨尘", "紫萱", "风无痕", "月瑶", "剑心", "灵均"],
            "wuxia": ["李逍遥", "柳如烟", "铁无双", "白展堂", "慕容秋", "风清扬", "令狐冲", "东方未明"],
            "post_apocalyptic": ["老周", "阿铁", "小七", "影子", "银狐", "铁锤", "零号", "灰烬"],
            "modern_power": ["陈教官", "林曦", "赵暗", "苏瑶", "王铁山", "周灵", "叶飞", "方晴"],
            "scifi": ["诺娃", "泽罗", "艾达", "凯恩", "露娜", "阿特拉斯", "薇安", "奥丁"],
        }
        names = name_pool.get(world_type, name_pool["fantasy"])
        random.shuffle(names)

        # 为每个城镇区域生成2-3个NPC，野外1个
        npc_idx = 0
        for region_id, region in world_map.regions.items():
            if region.region_type == "town":
                count = random.randint(2, 3)
            elif region.region_type == "wild" and region.danger_level <= 2:
                count = 1
            else:
                continue  # 高危区域不生成常驻NPC

            for _ in range(count):
                if npc_idx >= len(names):
                    break
                role_data = random.choice(roles)
                faction = random.choice(faction_names) if faction_names and random.random() < 0.4 else ""

                npc = NPC(
                    npc_id=f"npc_{region_id}_{npc_idx}",
                    name=names[npc_idx],
                    role=role_data["role"],
                    personality=role_data["personality"],
                    location=region_id,
                    faction=faction,
                )
                npc.can_trade = role_data.get("can_trade", False)
                npc.can_quest = role_data.get("can_quest", False)
                npc.dialogue_hint = role_data.get("dialogue", "…")
                npc.level = max(1, region.danger_level * 2 + random.randint(0, 2))
                npc.hp = 30 + npc.level * 10
                npc.max_hp = npc.hp

                system.add_npc(npc)
                # 注册到区域的NPC列表
                region.npcs.append(npc.name)
                npc_idx += 1

        return system

    @staticmethod
    def _generate_with_llm(world_setting: Dict, world_map, llm_client) -> NPCSystem:
        """用LLM生成NPC"""
        from simlife.backend.generator import get_llm_client
        if llm_client is None:
            llm_client = get_llm_client()

        world_name = world_setting.get("world_name", "未知世界")
        world_type = world_setting.get("world_type", "fantasy")

        # 收集区域信息
        region_info = []
        for rid, region in world_map.regions.items():
            if region.region_type in ("town", "wild") and region.danger_level <= 2:
                region_info.append(f"{region.name}({region.region_type})")

        factions = world_setting.get("factions", [])
        faction_names = [f.get("name", "") for f in factions[:4] if isinstance(f, dict)]
        factions_text = "势力：" + "、".join(faction_names) if faction_names else ""

        prompt = f"""你是死亡模式人生模拟器的NPC设计Agent。请为以下世界生成NPC。

世界：{world_name}（类型：{world_type}）
区域：{'、'.join(region_info)}
{factions_text}

设计要求：
1. 生成6-10个NPC，分布在各区域
2. 每个NPC有：名字、职业、性格、一句话口头禅
3. 城镇区域2-3个NPC，低危险野外1个
4. NPC名字要符合世界观设定
5. 部分NPC可以交易，部分有任务

返回JSON格式：
{{
  "npcs": [
    {{
      "name": "NPC名字",
      "role": "职业",
      "personality": "性格",
      "location": "所在区域名称",
      "can_trade": true/false,
      "can_quest": true/false,
      "dialogue": "一句话口头禅",
      "faction": "所属势力或空"
    }}
  ]
}}

只返回JSON，不要其他文字。"""

        response = llm_client.generate(prompt, max_tokens=1000, temperature=0.8, thinking=False)
        response = response.strip()
        if response.startswith("```"):
            lines = response.split("\n")
            response = "\n".join(lines[1:])
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

        import json
        result = json.loads(response)
        if isinstance(result, list):
            result = result[0] if result and isinstance(result[0], dict) else {}

        system = NPCSystem()

        # 建立区域名称到ID的映射
        name_to_id = {}
        for rid, region in world_map.regions.items():
            name_to_id[region.name] = rid

        for i, ndata in enumerate(result.get("npcs", [])):
            # 匹配区域
            loc_name = ndata.get("location", "")
            loc_id = name_to_id.get(loc_name, "")
            if not loc_id:
                # 找不到精确匹配，放到第一个城镇
                for rid, region in world_map.regions.items():
                    if region.region_type == "town":
                        loc_id = rid
                        break

            npc = NPC(
                npc_id=f"npc_{i}",
                name=ndata.get("name", f"NPC{i}"),
                role=ndata.get("role", "村民"),
                personality=ndata.get("personality", "普通"),
                location=loc_id,
                faction=ndata.get("faction", ""),
            )
            npc.can_trade = ndata.get("can_trade", False)
            npc.can_quest = ndata.get("can_quest", False)
            npc.dialogue_hint = ndata.get("dialogue", "…")
            npc.level = random.randint(1, 5)
            npc.hp = 30 + npc.level * 10
            npc.max_hp = npc.hp

            system.add_npc(npc)

            # 注册到区域
            if loc_id and loc_id in world_map.regions:
                world_map.regions[loc_id].npcs.append(npc.name)

        return system

    @staticmethod
    def get_npc_summary(npc_system: NPCSystem, location_id: str = None) -> str:
        """获取NPC摘要文本"""
        if location_id:
            npcs = npc_system.get_npcs_in_location(location_id)
        else:
            npcs = npc_system.get_alive_npcs()

        if not npcs:
            return "附近无人"

        parts = []
        for npc in npcs:
            relation = npc.get_relation_label()
            trade_flag = "💰" if npc.can_trade else ""
            quest_flag = "📋" if npc.can_quest and not npc.quest_given else ""
            parts.append(f"{npc.name}（{npc.role}，{relation}）{trade_flag}{quest_flag}")

        return "👥 " + "、".join(parts)

    @staticmethod
    def get_death_records_summary(npc_system: NPCSystem) -> str:
        """获取死亡记录摘要"""
        records = npc_system.death_records
        if not records:
            return ""

        parts = ["💀 已故："]
        for r in records[-5:]:  # 最近5条
            parts.append(f"  {r['name']}（{r.get('role', '?')}）— {r.get('cause', '未知原因')}")

        return "\n".join(parts)
