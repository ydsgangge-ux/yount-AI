"""
区域管理 Agent — 区域数据管理、方向移动、区域状态更新

职责：
1. 管理方格坐标和区域文件数据的合并与缓存
2. 处理方向移动（用户说"南下"时计算新区域）
3. 为StoryAgent提供当前区域上下文数据
4. 接收StoryAgent写回的区域状态更新（剧情进度、完成状态等）

数据流：
  RegionAgent ←→ WorldMap (方格坐标)
  RegionAgent ←→ world_manager (区域文件)
  RegionAgent → StoryAgent (区域上下文)
  StoryAgent → RegionAgent (区域状态写入)
"""
import json
import random
import re
from typing import Dict, Optional, List
from simlife.backend.world_map import WorldMap, WorldRegion


class RegionAgent:
    """区域管理 Agent"""

    def __init__(self, world_map: WorldMap, world_id: str):
        self.world_map = world_map
        self.world_id = world_id
        self._region_cache: Dict[str, Dict] = {}

    # ── 方向移动 ──────────────────────────────────────

    def move_by_direction(self, direction: str) -> Dict:
        """
        根据方向移动（基于方格坐标）。
        direction: "北"/"南"/"东"/"西"
        如果目标坐标已有区域 → 直接移动
        如果目标坐标为空白 → 调用LLM生成新区域后移动
        如果方向超出grid范围 → 返回失败 + 可用方向
        """
        current = self.world_map.get_current_region()
        if not current:
            return {"moved": False, "reason": "no_current_region"}

        # 检查方向是否在grid范围内
        if not self.world_map.can_move_direction(direction):
            return {
                "moved": False,
                "reason": "out_of_bounds",
                "direction": direction,
                "available_directions": self.world_map.get_available_directions(),
            }

        # 计算目标坐标
        deltas = {"北": (0, -1), "南": (0, 1), "东": (1, 0), "西": (-1, 0)}
        dx, dy = deltas.get(direction, (0, 0))
        new_x = current.x + dx
        new_y = current.y + dy

        # 检查目标位置是否有区域
        target = self.world_map.get_region_at(new_x, new_y)
        if target is None:
            # 空白格子 → 生成新区域
            target = self._generate_blank_region(new_x, new_y, direction, current)
            if target is None:
                return {"moved": False, "reason": "generation_failed", "direction": direction}

        old_region_name = current.name
        # 执行移动
        self.world_map.current_region_id = target.region_id
        target.explored = True
        # 加载区域文件数据
        region_file = self._load_region_file(target.region_id)

        return {
            "moved": True,
            "region": target,
            "region_file": region_file or {},
            "direction": direction,
            "old_region_name": old_region_name,
        }

    def _generate_blank_region(self, x: int, y: int, direction: str,
                                adjacent_region: WorldRegion) -> Optional[WorldRegion]:
        """为空白坐标生成新区域（调用LLM，基于相邻区域和世界设定）"""
        try:
            from simlife.backend.generator import get_llm_client
            llm_client = get_llm_client()
        except Exception:
            return None

        # 收集相邻已有区域信息
        adj_info = []
        deltas = [("北", 0, -1), ("南", 0, 1), ("东", 1, 0), ("西", -1, 0)]
        for dir_name, dx, dy in deltas:
            nx, ny = x + dx, y + dy
            r = self.world_map.get_region_at(nx, ny)
            if r:
                adj_info.append(f"{dir_name}方：{r.name}（{r.region_type}，危险等级{r.danger_level}）")

        # 危险等级：以距出生点的距离为主（近易远难，形成开放世界梯度），
        # 参考相邻区域协调，再加入随机波动 → 全图危险等级有起伏，不再是单一值
        base_danger = adjacent_region.danger_level or 1
        origin = None
        if self.world_map.start_region_id:
            _start = self.world_map.get_region(self.world_map.start_region_id)
            if _start is not None and _start.x is not None and _start.y is not None:
                origin = (_start.x, _start.y)
        if origin:
            dist = max(abs(x - origin[0]), abs(y - origin[1]))  # Chebyshev 距离
            dist_danger = max(1, min(5, 1 + dist // 2))  # 每约2格危险+1级
        else:
            dist_danger = base_danger
        # 距离为主(2/3)、相邻为辅(1/3)，再随机浮动±1，保证梯度又不单调
        suggested_danger = max(1, min(5, (dist_danger * 2 + base_danger) // 3 + random.randint(-1, 1)))

        # 世界设定信息
        ws = self._get_world_setting()
        world_name = ws.get("world_name", "未知世界")
        world_type = ws.get("world_type", "fantasy")
        monster_types = ws.get("dangers", {}).get("monster_types", [])
        mt_names = ""
        if monster_types:
            mt_list = [m.get("name", str(m)) if isinstance(m, dict) else str(m) for m in monster_types[:6]]
            mt_names = "世界观怪物类型：" + "、".join(mt_list)

        # 势力信息（供NPC归属势力）
        factions = ws.get("factions", []) or []
        ft_names = ""
        if factions:
            f_list = [f.get("name", "") for f in factions[:5] if isinstance(f, dict) and f.get("name")]
            ft_names = "世界观势力：" + "、".join(f_list)

        # 空白区域类型多样化：低/中危险区有机会生成城镇（带NPC），高危险区更偏向地下城/隐秘，
        # 整体仍以野外为主（约六成），避免地图全是同一种类型
        if suggested_danger <= 2 and random.random() < 0.35:
            suggested_type = "town"
        elif suggested_danger >= 4 and random.random() < 0.30:
            suggested_type = "dungeon"
        elif suggested_danger >= 3 and random.random() < 0.20:
            suggested_type = "secret"
        else:
            suggested_type = "wild"

        prompt = f"""你是地图生成Agent。请在{world_name}（{world_type}）的世界中，为以下坐标生成一个新区域。
该区域必须是一份完整的"迷你世界设定"：包含【NPC】【怪物】【资源】【本地剧情】【势力据点】以及它们之间的【关系】，像一个小世界一样自洽。

坐标：({x}, {y})，从{adjacent_region.name}向{direction}方向移动到达。
相邻区域：{'; '.join(adj_info) if adj_info else '无'}
建议危险等级：{suggested_danger}
建议区域类型：{suggested_type}
{mt_names}
{ft_names}

要求：
1. 区域名称要符合{world_type}世界观风格
2. 区域类型优先建议为 {suggested_type}（可微调；town=城镇/村落，wild=野外，dungeon=地下城，secret=隐秘区域；相邻是城镇时优先生成野外或地下城）
3. 描述2-3句话，包含环境特征、其中的人物和潜在危险
4. 若区域类型是 town，必须生成 1-3 个 NPC（如村长/商人/旅店老板）；wild/dungeon/secret 也可有 0-2 个流民、猎人或巡逻者
5. 怪物要符合世界观设定，0-3种（城镇通常没有怪物，野外/地下城1-3种），带战斗数据与行为描述
6. 生成 1-3 种本区域特有的资源（符合区域环境：森林区配木材/草药，矿区配矿石，水域配鱼群/水产）
7. 生成 1-2 个本地小剧情，由本区域的 NPC 发布
8. 生成 2-4 条元素关系，把 NPC/怪物/资源/势力/剧情串起来：如怪物守护资源、NPC 隶属势力、NPC 发布剧情
9. 若该区域有某个势力的据点或势力人物驻留，给对应 NPC 填上该势力的英文 id 或中文名（从世界观势力中选择），否则留空

返回JSON：
{{
  "region_id": "英文蛇形id",
  "name": "区域中文名",
  "description": "2-3句话描述",
  "danger_level": {suggested_danger},
  "region_type": "town/wild/dungeon/secret",
  "monsters": [
    {{"name": "怪物名", "level": 等级, "hp": 生命值, "attack_power": 攻击力, "defense_power": 防御力, "exp_reward": 经验, "gold_reward": 金币, "type": "normal/elite", "behavior": "行为/攻击特性（一句话）", "skills": ["技能名"]}}
  ],
  "npcs": [{{"name": "NPC名", "role": "身份（如：村长/铁匠/猎人）", "description": "性格/背景（一句话）", "faction_id": "所属势力id或空"}}],
  "resources": [
    {{"name": "资源名", "type": "矿石/草药/木材/石材/食物/魔力/遗迹/兽材", "rarity": "common/uncommon/rare/epic", "amount": "储量描述", "description": "用途（可锻造/附魔/交易）", "guard": "守护此资源的怪物名（从monsters里选）或空"}}
  ],
  "quests": [
    {{"title": "剧情名", "description": "剧情内容", "giver": "发布者NPC名（从npcs里选）", "objectives": [{{"type": "kill/collect/visit/talk", "target_keyword": "目标", "count": 数量}}], "rewards": {{"exp": 经验, "gold": 金币}}}}
  ],
  "relationships": [
    {{"from": "元素名", "from_type": "npc/monster/faction/resource/quest", "to": "元素名", "to_type": "npc/monster/faction/resource/quest", "relation": "守护/控制/隶属/发布/敌对/依赖/交易", "description": "一句话说明关系"}}
  ],
  "factions": ["驻留本区域的势力id，最多2个"]
}}

只返回JSON，不要其他文字。"""

        try:
            from simlife.backend.generator import _llm_json
            data = _llm_json(llm_client, prompt, max_tokens=700, temperature=0.8,
                             attempts=2, label=f"空白区域生成({x},{y})")
        except Exception as e:
            print(f"[RegionAgent] LLM生成空白区域失败: {e}")
            return None

        if not isinstance(data, dict):
            print(f"[RegionAgent] LLM生成空白区域失败: 无法获取有效JSON结构")
            return None

        region = WorldRegion(
            region_id=data.get("region_id", f"region_{x}_{y}"),
            name=data.get("name", f"未知区域{x},{y}"),
            description=data.get("description", ""),
            danger_level=data.get("danger_level", suggested_danger),
            region_type=data.get("region_type", suggested_type),
            x=x,
            y=y,
        )
        region.is_blank = True

        # 怪物（0-3种）：兼容对象数组与字符串数组，保留战斗数据
        monster_objs = []
        for m in data.get("monsters", [])[:3]:
            if isinstance(m, dict):
                mname = m.get("name", "")
                if mname:
                    monster_objs.append(m)
            elif isinstance(m, str) and m:
                monster_objs.append({"name": m, "type": "normal"})
        region.monsters = monster_objs

        # NPC：兼容字符串数组与对象数组两种格式
        npc_names = []
        npc_objs = []
        for npc in data.get("npcs", []) or []:
            if isinstance(npc, dict):
                nm = npc.get("name", "")
                if nm:
                    npc_names.append(nm)
                    npc_objs.append({
                        "id": f"npc_{region.region_id}_{len(npc_objs)}",
                        "name": nm,
                        "role": npc.get("role", ""),
                        "description": npc.get("description", ""),
                        "faction_id": npc.get("faction_id", ""),
                        "is_key": bool(npc.get("is_key", False)),
                    })
            elif isinstance(npc, str) and npc:
                npc_names.append(npc)
                npc_objs.append({
                    "id": f"npc_{region.region_id}_{len(npc_objs)}",
                    "name": npc,
                    "role": "",
                    "description": "",
                    "faction_id": "",
                    "is_key": False,
                })
        region.npcs = npc_names
        factions = data.get("factions", []) or []
        if isinstance(factions, str):
            factions = [factions]

        # 城镇必须有NPC，否则补默认村民（避免出现无人的空城）
        if region.region_type == "town" and not npc_names:
            npc_names.append("当地村民")
            npc_objs.append({
                "id": f"npc_{region.region_id}_0",
                "name": "当地村民",
                "role": "村民",
                "description": "世代居住于此的村民，熟悉本地的一切。",
                "faction_id": "",
            })
            region.npcs = npc_names

        # 添加到地图
        self.world_map.add_region(region)

        # 保存区域文件（迷你世界设定：人/怪物/资源/势力/剧情/关系 齐全）
        try:
            from simlife.backend import world_schema
            from simlife.worlds import world_manager as wm
            region_data = {
                "id": region.region_id,
                "name": region.name,
                "description": region.description,
                "danger_level": region.danger_level,
                "biome": region.region_type,
                "level_range": [max(1, region.danger_level * 3 - 2), region.danger_level * 3 + 2],
                "x": region.x,
                "y": region.y,
                "monsters": monster_objs,
                "npcs": npc_objs,
                "factions": factions,
                # 迷你世界设定：资源 / 本地剧情 / 元素关系
                "resources": data.get("resources", []) or [],
                "quests": data.get("quests", []) or [],
                "relationships": data.get("relationships", []) or [],
            }
            if region.danger_level > 0:
                region_data["dangers"] = [m.get("name", "") for m in monster_objs if m.get("name")]
            # 完整性兜底：LLM 遗漏的资源/剧情/关系用规则模板补齐
            ws = self._get_world_setting()
            region_data = world_schema.ensure_region_completeness(region_data, ws)
            wm.save_region(self.world_id, region_data)
        except Exception as e:
            print(f"[RegionAgent] 保存空白区域文件失败: {e}")

        print(f"[RegionAgent] 生成空白区域：({x},{y}) → {region.name}（{region.region_type}，危险{region.danger_level}，NPC {len(npc_names)} 个）")
        return region

    def _get_world_setting(self) -> Dict:
        """加载世界设定"""
        try:
            from simlife.worlds import world_manager as wm
            return wm.load_world_setting(self.world_id) or {}
        except Exception:
            return {}

    def move_to_region_id(self, region_id: str) -> Dict:
        """直接移动到指定区域ID"""
        region = self.world_map.get_region(region_id)
        if not region:
            return {"moved": False, "reason": "region_not_found"}
        old_region_name = ""
        current = self.world_map.get_current_region()
        if current:
            old_region_name = current.name
        self.world_map.current_region_id = region_id
        region.explored = True
        region_file = self._load_region_file(region_id)
        return {
            "moved": True,
            "region": region,
            "region_file": region_file or {},
            "direction": "",
            "old_region_name": old_region_name,
        }

    # ── 区域数据 ──────────────────────────────────────

    def get_current_region_data(self) -> Dict:
        """获取当前区域合并数据（方格 + 区域文件）"""
        current = self.world_map.get_current_region()
        if not current:
            return {}
        region_file = self._load_region_file(current.region_id) or {}
        return {
            "grid": current.to_dict(),
            "file": region_file,
            "merged": {**region_file, **current.to_dict()},
        }

    def get_region_context(self, state: Dict) -> str:
        """
        构建当前区域的完整上下文，供 StoryAgent 注入。
        优先使用区域文件数据，回退到方格数据。
        """
        current = self.world_map.get_current_region()
        if not current:
            return ""

        region_file = self._load_region_file(current.region_id)
        if region_file:
            # 使用 world_manager 的标准格式化
            try:
                from simlife.worlds import world_manager as wm
                ws = state.get("world_setting", {})
                ctx = wm.build_region_context(region_file, ws)
                if ctx:
                    return ctx
            except Exception:
                pass

        # 回退：手动构建
        type_label = {"town": "城镇", "wild": "野外", "dungeon": "地下城",
                      "boss_lair": "Boss巢穴", "secret": "隐秘区域"}.get(
            current.region_type, current.region_type)
        parts = [
            f"【当前区域】{current.name}（{type_label}，危险等级{current.danger_level}）",
            current.description or "",
        ]
        # 可移动方向（包含空白格子）
        avail_dirs = self.world_map.get_available_directions()
        if avail_dirs:
            dirs = []
            for d in avail_dirs:
                if d["has_region"]:
                    name = d["region_name"] if d["explored"] else "未知"
                    dirs.append(f"{name}（{d['direction']}）")
                else:
                    dirs.append(f"未知区域（{d['direction']}）")
            parts.append(f"可移动方向：{'、'.join(dirs)}")

        # 怪物
        if current.monsters:
            m_names = [m.get("name", "") for m in current.monsters if m.get("name")]
            if m_names:
                parts.append(f"本区怪物：{'、'.join(m_names[:4])}")

        return "\n".join(p for p in parts if p)

    def get_adjacent_with_directions(self) -> List[Dict]:
        """获取可移动方向及区域信息（包含空白格子）"""
        current = self.world_map.get_current_region()
        if not current:
            return []
        result = []
        for d in self.world_map.get_available_directions():
            if d["has_region"]:
                r = self.world_map.get_region_at(d["target_x"], d["target_y"])
                result.append({
                    "region_id": r.region_id,
                    "name": r.name,
                    "direction": d["direction"],
                    "region_type": r.region_type,
                    "explored": r.explored,
                    "danger_level": r.danger_level,
                })
            else:
                result.append({
                    "region_id": "",
                    "name": "未知",
                    "direction": d["direction"],
                    "region_type": "unknown",
                    "explored": False,
                    "danger_level": 0,
                })
        return result

    # ── 区域状态写入 ──────────────────────────────────

    def update_region_state(self, region_id: str, updates: Dict) -> list:
        """
        更新区域状态（剧情进度、完成状态、追加新NPC/新地点），写入区域文件。
        由 StoryAgent 调用，用于保存叙事产生的区域变化。
        updates 支持字段：
          - story_state: 探索进度文本描述
          - story_progress: 剧情推进文本描述
          - completed: bool（标记区域完成）
          - discoveries: list（新发现）— 覆盖语义
          - new_npcs: list[dict]（行动中新遇到并要落盘的可交互人物）— 追加语义，按名去重
          - new_locations: list[str]（行动中发现的新地点名）— 追加语义，按名去重
        返回实际追加成功的新 NPC 列表（供调用方注册进运行时 npc_system）。
        """
        from simlife.worlds import world_manager as wm
        region = wm.load_region(self.world_id, region_id)
        if not region:
            return []
        changed = False
        appended_npcs: list = []
        overwrite_keys = {"story_state", "story_progress", "completed", "discoveries"}
        for key, value in updates.items():
            if value is None:
                continue
            if key in ("new_npcs", "new_locations"):
                appended_npcs += self._append_region_content(region, key, value)
                changed = True
            elif key in overwrite_keys:
                region[key] = value
                changed = True
        if changed:
            wm.save_region(self.world_id, region)
            self._region_cache.pop(region_id, None)
        return appended_npcs

    def _append_region_content(self, region: Dict, kind: str, value) -> list:
        """
        把新 NPC / 新地点追加进区域 JSON（追加语义，按名称去重，设上限防无界膨胀）。
        kind == "new_npcs"     → 并入 region["npcs"]（list[dict]），返回新增 dict 列表
        kind == "new_locations"→ 并入 region["key_locations"]（list[str]），返回空列表
        """
        appended_npcs: list = []
        if kind == "new_locations":
            items = [str(x) for x in (value or []) if isinstance(x, (str, dict))]
            if not items:
                return []
            existing_names = set()
            for loc in region.get("key_locations", []) or []:
                if isinstance(loc, dict):
                    existing_names.add(str(loc.get("name", "")).strip())
                else:
                    existing_names.add(str(loc).strip())
            slots = 12 - len(region.get("key_locations", []) or [])
            added = 0
            for name in items:
                name = (name if isinstance(name, str) else (name.get("name") if isinstance(name, dict) else "")).strip()
                if not name or name in existing_names or added >= slots:
                    continue
                region.setdefault("key_locations", []).append(name)
                existing_names.add(name)
                added += 1
            return appended_npcs

        # new_npcs
        raw_npcs = value if isinstance(value, list) else []
        existing = region.get("npcs", []) or []
        existing_names = set()
        for n in existing:
            nm = str((n.get("name") if isinstance(n, dict) else n) or "").strip()
            if nm:
                existing_names.add(nm)
        slots = 15 - len(existing)  # 单区常驻人口上限，防无限增长
        for raw in raw_npcs:
            if not isinstance(raw, dict):
                name = str(raw or "").strip()
                entry = {"name": name, "role": "旅人", "personality": "随和"} if name else None
            else:
                name = str(raw.get("name", "") or "").strip()
                entry = dict(raw)
            if not name or name in existing_names or len(appended_npcs) >= slots:
                continue
            entry.setdefault("role", "旅人")
            entry.setdefault("personality", "随和")
            entry.setdefault("faction", "")
            existing.append(entry)
            existing_names.add(name)
            appended_npcs.append(entry)
        if appended_npcs:
            region["npcs"] = existing
        return appended_npcs

    def update_current_region_state(self, updates: Dict) -> list:
        """更新当前区域的剧情状态，返回追加的新NPC列表（供注册进运行时npc_system）"""
        current = self.world_map.get_current_region()
        if current:
            return self.update_region_state(current.region_id, updates)
        return []

    # ── 内部 ──────────────────────────────────────────

    def _load_region_file(self, region_id: str) -> Optional[Dict]:
        """加载区域文件（带缓存）"""
        if region_id in self._region_cache:
            return self._region_cache[region_id]
        try:
            from simlife.worlds import world_manager as wm
            region = wm.load_region(self.world_id, region_id)
            if region:
                self._region_cache[region_id] = region
            return region
        except Exception:
            return None

    def clear_cache(self):
        """清除区域文件缓存（区域文件被外部修改后调用）"""
        self._region_cache.clear()