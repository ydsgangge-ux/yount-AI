"""
死亡模式独立环境系统：昼夜+天气+室内/室外
- 完全不依赖真实天气API（区别于 simlife.main 的 WeatherService）
- 幻想世界随机，按当前区域地貌加权（林地多雨，冰原下雪，矿区多霾...）
- 随游戏天数和真实时间流逝推进，符合"世界持续运转"理念
- 室内削弱天气影响，室外完整暴露
"""

import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# ── 昼夜分段定义 ──────────────────────────────────────
# 按游戏内小时（0-23）分段，每个分段有自然语言名称和情绪权重
DAY_PHASES = [
    (0, 5, "深夜", "dark_night"),
    (5, 7, "清晨", "dawn"),
    (7, 17, "白天", "daytime"),
    (17, 19, "黄昏", "dusk"),
    (19, 24, "夜晚", "night"),
]

def get_day_phase(hour: int) -> Tuple[str, str]:
    """根据当前小时获取昼夜阶段名称和代码"""
    for start, end, name, code in DAY_PHASES:
        if start <= hour < end:
            return name, code
    return "白天", "daytime"

# ── 天气定义和地貌权重 ──────────────────────────────────────
# 天气：(名称代码, 中文名称, 基础情绪delta, 地貌权重字典)
WEATHER_DEFS = [
    # 晴天：大部分地区常见
    ("clear", "晴朗", 0, {
        "default": 50,
        "desert": 70, "grassland": 60, "tundra": 40, "mountain": 45,
    }),
    # 阴天
    ("cloudy", "阴云", -1, {
        "default": 25,
        "forest": 30, "hills": 30, "coast": 35,
    }),
    # 雾
    ("fog", "雾", -2, {
        "default": 5,
        "forest": 20, "mountain": 15, "valley": 25, "coast": 20, "swamp": 30,
    }),
    # 小雨
    ("rain_light", "小雨", -1, {
        "default": 10,
        "forest": 25, "swamp": 20, "coast": 20, "hills": 15,
    }),
    # 大雨
    ("rain_heavy", "大雨", -3, {
        "default": 3,
        "forest": 15, "jungle": 25, "swamp": 20, "plains": 10,
    }),
    # 雪
    ("snow", "下雪", -2, {
        "default": 1,
        "arctic": 60, "tundra": 40, "mountain": 25, "glacier": 70,
    }),
    # 大风
    ("wind", "大风", -2, {
        "default": 5,
        "plains": 20, "grassland": 15, "coastal_cliffs": 25, "mountain": 20,
    }),
    # 霾
    ("haze", "霾", -2, {
        "default": 1,
        "mine": 40, "mining": 35, "desert": 20, "volcanic": 45,
    }),
]

# 地貌→类型名正则映射（匹配 biome 关键词）
BIOME_WEIGHT_MAP = {
    "forest": ("forest", "rain_light", 15),
    "wood": ("forest", "rain_light", 10),
    "jungle": ("jungle", "rain_heavy", 15),
    "swamp": ("swamp", "fog", 20),
    "desert": ("desert", "clear", 20),
    "arctic": ("arctic", "snow", 40),
    "ice": ("arctic", "snow", 30),
    "mine": ("mine", "haze", 20),
    "mining": ("mine", "haze", 15),
    "mountain": ("mountain", "fog", 10),
    "coast": ("coast", "fog", 10),
    "water": ("coast", "rain_light", 10),
    "plains": ("plains", "wind", 5),
    "grass": ("grassland", "wind", 5),
    "tundra": ("tundra", "snow", 20),
}

def _get_weather_weight_for_biome(biome: str) -> Dict[str, int]:
    """根据biome返回各天气的权重"""
    weights = {w[0]: w[3].get("default", 10) for w in WEATHER_DEFS}
    biome_lower = biome.lower()
    for keyword, (biome_type, weather_type, extra_weight) in BIOME_WEIGHT_MAP.items():
        if keyword in biome_lower:
            if weather_type in weights:
                weights[weather_type] += extra_weight
    return weights

def random_weather(biome: str, seed: Optional[int] = None) -> Tuple[str, str, int]:
    """按biome随机天气，返回(代码,中文名称,情绪delta)"""
    if seed is not None:
        random.seed(seed)
    weights = _get_weather_weight_for_biome(biome)
    weather_codes = list(weights.keys())
    weights_list = list(weights.values())
    # 加权随机
    total = sum(weights_list)
    r = random.randint(1, total)
    cumulative = 0
    for i, w in enumerate(weights_list):
        cumulative += w
        if r <= cumulative:
            code = weather_codes[i]
            # 找定义
            for wc, name, mood, _ in WEATHER_DEFS:
                if wc == code:
                    return code, name, mood
    # fallback
    return "clear", "晴朗", 0

# ── 环境状态结构 ──────────────────────────────────────

class DeathModeEnvironment:
    """死亡模式环境状态，持久化到state"""
    def __init__(
        self,
        current_weather_code: str = "clear",
        current_weather_name: str = "晴朗",
        day_phase_name: str = "白天",
        day_phase_code: str = "daytime",
        is_indoor: bool = False,
        mood_delta: int = 0,
        last_updated_at: str = "",
    ):
        self.current_weather_code = current_weather_code
        self.current_weather_name = current_weather_name
        self.day_phase_name = day_phase_name
        self.day_phase_code = day_phase_code
        self.is_indoor = is_indoor
        self.mood_delta = mood_delta
        self.last_updated_at = last_updated_at or datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            "current_weather_code": self.current_weather_code,
            "current_weather_name": self.current_weather_name,
            "day_phase_name": self.day_phase_name,
            "day_phase_code": self.day_phase_code,
            "is_indoor": self.is_indoor,
            "mood_delta": self.mood_delta,
            "last_updated_at": self.last_updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DeathModeEnvironment":
        return cls(**data)

def from_state_env(data) -> DeathModeEnvironment:
    """从 state 里的 environment dict 构造对象；兼容空/异常数据"""
    if not isinstance(data, dict):
        data = {}
    return DeathModeEnvironment.from_dict(data)

def init_environment(start_time_str: str, biome: str = "wild") -> DeathModeEnvironment:
    """初始化环境：从游戏开始时间算当前小时，随机初始天气"""
    start_time = datetime.fromisoformat(start_time_str)
    # 游戏时间流逝速度：1真实日 = 1游戏日（符合玩家感受）
    # 游戏内小时 = 真实小时（自然同步，玩家不用适应"时间加速"）
    now = datetime.now()
    elapsed_hours = int((now - start_time).total_seconds() / 3600)
    game_hour = elapsed_hours % 24
    phase_name, phase_code = get_day_phase(game_hour)
    # 随机天气，种子用当前天保证同一天天气一致
    day_seed = int((now - start_time).total_seconds() // 86400)
    w_code, w_name, w_mood = random_weather(biome, seed=day_seed)
    return DeathModeEnvironment(
        current_weather_code=w_code,
        current_weather_name=w_name,
        day_phase_name=phase_name,
        day_phase_code=phase_code,
        is_indoor=False,
        mood_delta=w_mood,
        last_updated_at=now.isoformat(),
    )

def update_environment(
    env: DeathModeEnvironment,
    start_time_str: str,
    current_biome: str = "wild",
    force_reevaluate: bool = False,
) -> DeathModeEnvironment:
    """更新环境。
    - 昼夜总是按真实时间重算（玩家隔多久上线都能感知当前白昼/夜晚）
    - 天气只在跨天/换区域/强制时重新随机，避免频繁跳动
    """
    now = datetime.now()
    last_update = datetime.fromisoformat(env.last_updated_at)

    start_time = datetime.fromisoformat(start_time_str)
    elapsed_hours = int((now - start_time).total_seconds() / 3600)
    game_hour = elapsed_hours % 24
    phase_name, phase_code = get_day_phase(game_hour)

    # 天气：跨天/换区域/强制时重新随机（其它时候保持稳定，减少扰动）
    old_day = int((last_update - start_time).total_seconds() // 86400)
    new_day = int((now - start_time).total_seconds() // 86400)
    if old_day != new_day or current_biome != getattr(env, "_last_biome", "") or force_reevaluate:
        day_seed = new_day
        w_code, w_name, w_mood = random_weather(current_biome, seed=day_seed)
        env.current_weather_code = w_code
        env.current_weather_name = w_name
        env.mood_delta = w_mood

    env.day_phase_name = phase_name
    env.day_phase_code = phase_code
    env.last_updated_at = now.isoformat()
    # 保存last biome用于判断
    setattr(env, "_last_biome", current_biome)
    return env

def set_indoor(env: DeathModeEnvironment, is_indoor: bool) -> DeathModeEnvironment:
    """设置是否在室内——室内削弱天气情绪影响"""
    env.is_indoor = is_indoor
    # 室内天气情绪减半
    if is_indoor:
        env.mood_delta = int(env.mood_delta / 2)
    return env

def get_environment_description(env: DeathModeEnvironment) -> str:
    """生成自然语言描述，注入场景"""
    indoor_desc = "室内" if env.is_indoor else "室外"
    return f"{env.day_phase_name} · {env.current_weather_name} · {indoor_desc}"

def get_effective_mood_delta(env: DeathModeEnvironment) -> int:
    """获取最终情绪修正值：室内会削弱"""
    if env.is_indoor:
        return int(env.mood_delta / 2)
    return env.mood_delta
