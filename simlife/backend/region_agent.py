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

        # 根据相邻区域推断合理的危险等级
        base_danger = adjacent_region.danger_level
        suggested_danger = max(1, min(5, base_danger))

        # 世界设定信息
        ws = self._get_world_setting()
        world_name = ws.get("world_name", "未知世界")
        world_type = ws.get("world_type", "fantasy")
        monster_types = ws.get("dangers", {}).get("monster_types", [])
        mt_names = ""
        if monster_types:
            mt_list = [m.get("name", str(m)) if isinstance(m, dict) else str(m) for m in monster_types[:6]]
            mt_names = "世界观怪物类型：" + "、".join(mt_list)

        prompt = f"""你是地图生成Agent。请在{world_name}（{world_type}）的世界中，为以下坐标生成一个新区域。

坐标：({x}, {y})，从{adjacent_region.name}向{direction}方向移动到达。
相邻区域：{'; '.join(adj_info) if adj_info else '无'}
建议危险等级：{suggested_danger}
{mt_names}

要求：
1. 区域名称要符合{world_type}世界观风格
2. 区域类型从 wild/dungeon/secret 中选一个（不能是town或boss_lair）
3. 描述2-3句话，包含环境特征和潜在危险
4. 怪物名称要符合世界观设定，2-3种
5. 危险等级应与相邻区域协调（±1以内）

返回JSON：
{{
  "region_id": "英文蛇形id",
  "name": "区域中文名",
  "description": "2-3句话描述",
  "danger_level": {suggested_danger},
  "region_type": "wild/dungeon/secret",
  "monsters": ["怪物名1", "怪物名2"],
  "npcs": []
}}

只返回JSON，不要其他文字。"""

        try:
            response = llm_client.generate(prompt, max_tokens=500, temperature=0.8, thinking=False)
            response = response.strip()

            # 清理markdown
            if response.startswith("```"):
                lines = response.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                response = "\n".join(lines).strip()

            first_brace = response.find("{")
            last_brace = response.rfind("}")
            if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
                response = response[first_brace:last_brace + 1]

            response = re.sub(r',\s*([}\]])', r'\1', response)
            data = json.loads(response)
        except Exception as e:
            print(f"[RegionAgent] LLM生成空白区域失败: {e}")
            return None

        region = WorldRegion(
            region_id=data.get("region_id", f"region_{x}_{y}"),
            name=data.get("name", f"未知区域{x},{y}"),
            description=data.get("description", ""),
            danger_level=data.get("danger_level", suggested_danger),
            region_type=data.get("region_type", "wild"),
            x=x,
            y=y,
        )
        for mname in data.get("monsters", []):
            region.monsters.append({"name": mname, "type": "normal"})
        region.npcs = data.get("npcs", [])

        # 添加到地图
        self.world_map.add_region(region)

        # 保存区域文件
        try:
            from simlife.worlds import world_manager as wm
            region_data = {
                "region_id": region.region_id,
                "name": region.name,
                "description": region.description,
                "danger_level": region.danger_level,
                "region_type": region.region_type,
                "x": region.x,
                "y": region.y,
                "monsters": region.monsters,
                "npcs": region.npcs,
            }
            wm.save_region(self.world_id, region_data)
        except Exception as e:
            print(f"[RegionAgent] 保存空白区域文件失败: {e}")

        print(f"[RegionAgent] 生成空白区域：({x},{y}) → {region.name}（{region.region_type}，危险{region.danger_level}）")
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

    def update_region_state(self, region_id: str, updates: Dict):
        """
        更新区域状态（剧情进度、完成状态等），写入区域文件。
        由 StoryAgent 调用，用于保存叙事产生的区域变化。
        updates 支持字段：
          - story_state: 探索进度文本描述
          - story_progress: 剧情推进文本描述
          - completed: bool（标记区域完成）
          - discoveries: list（新发现）
        """
        from simlife.worlds import world_manager as wm
        region = wm.load_region(self.world_id, region_id)
        if not region:
            return
        changed = False
        allowed_keys = {"story_state", "story_progress", "completed", "discoveries"}
        for key, value in updates.items():
            if key in allowed_keys and value is not None:
                region[key] = value
                changed = True
        if changed:
            wm.save_region(self.world_id, region)
            self._region_cache.pop(region_id, None)

    def update_current_region_state(self, updates: Dict):
        """更新当前区域的剧情状态"""
        current = self.world_map.get_current_region()
        if current:
            self.update_region_state(current.region_id, updates)

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