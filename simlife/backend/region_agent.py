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
from typing import Dict, Optional, List
from simlife.backend.world_map import WorldMap


class RegionAgent:
    """区域管理 Agent"""

    def __init__(self, world_map: WorldMap, world_id: str):
        self.world_map = world_map
        self.world_id = world_id
        self._region_cache: Dict[str, Dict] = {}

    # ── 方向移动 ──────────────────────────────────────

    def move_by_direction(self, direction: str) -> Dict:
        """
        根据方向移动，返回移动结果。
        direction: "北"/"南"/"东"/"西"/"东北"/"西北"/"东南"/"西南"
        返回: {"moved": bool, "region": ..., "direction": ..., "old_region": ..., "reason": str}
        """
        current = self.world_map.get_current_region()
        if not current:
            return {"moved": False, "reason": "no_current_region"}

        adjacent = self.world_map.get_adjacent_regions()
        # 按方向筛选
        candidates = []
        for r in adjacent:
            d = WorldMap._get_direction_label(current.x, current.y, r.x, r.y)
            if d == direction:
                candidates.append(r)

        if not candidates:
            return {"moved": False, "reason": "no_direction_match", "direction": direction}

        # 优先选野外区域，其次 dungeon，最后任意
        target = None
        for r in candidates:
            if r.region_type == "wild":
                target = r
                break
        if not target:
            for r in candidates:
                if r.region_type != "town":
                    target = r
                    break
        if not target:
            target = candidates[0]

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
        # 相邻区域方向
        adj = self.world_map.get_adjacent_regions()
        if adj:
            dirs = []
            for r in adj:
                d = WorldMap._get_direction_label(current.x, current.y, r.x, r.y)
                name = r.name if r.explored else "未知"
                dirs.append(f"{name}（{d}）")
            parts.append(f"可达区域：{'、'.join(dirs)}")

        # 怪物
        if current.monsters:
            m_names = [m.get("name", "") for m in current.monsters if m.get("name")]
            if m_names:
                parts.append(f"本区怪物：{'、'.join(m_names[:4])}")

        return "\n".join(p for p in parts if p)

    def get_adjacent_with_directions(self) -> List[Dict]:
        """获取相邻区域及方向标签"""
        current = self.world_map.get_current_region()
        if not current:
            return []
        result = []
        for r in self.world_map.get_adjacent_regions():
            d = WorldMap._get_direction_label(current.x, current.y, r.x, r.y)
            result.append({
                "region_id": r.region_id,
                "name": r.name,
                "direction": d,
                "region_type": r.region_type,
                "explored": r.explored,
                "danger_level": r.danger_level,
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