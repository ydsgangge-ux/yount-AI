# 世界观生成 Prompt 模板

> **使用方法**：将下方 Prompt（从「你是一个」开始）复制到任意大模型对话中，根据你的需求修改 `【用户定制区域】` 的内容，发送后把生成的 JSON 保存为 `world_setting.json`。

---

## 通用世界观生成 Prompt

```
你是一个专业的奇幻世界观设计师。请根据以下要求，创建一个详细、自洽、经得起推敲的世界观设定。

【用户定制区域 — 请根据需要修改】
- 世界类型：{world_type}
- 核心主题：{core_theme}
- 参考风格：{reference_style}（可选，如"类似原神的提瓦特大陆"或"类似刀剑神域的艾恩葛朗特"）
- 希望突出的特色：{unique_features}
- 角色将在这个世界中做什么：{character_role_hint}

【设计要求】
1. 世界观必须自洽：地理、种族、力量体系、势力之间要有合理的因果关系
2. 细节要丰富：每个区域、种族、势力都要有独特性，不能千篇一律
3. 要有故事潜力：留出足够的冲突点和悬念，让角色的日常冒险有戏剧性
4. 数量适当：区域4-8个，种族3-6个，势力3-5个，副本3-5个，传说物品3-5个
5. 所有名称要有风格统一性：同一世界的命名体系应一致
6. 力量体系要有明确的规则和限制，不能是万能的
7. 【方格地图·重要】在 geography.grid 中标注3-6个主要区域在10x10方格地图上的坐标：
   - size 固定为 10
   - main_regions 数组中每个区域必须有：region_id（英文蛇形）、name、x（0-9）、y（0-9）、region_type、danger_level、description、is_start
   - 起始城镇放在 (0,0) 附近，BOSS区域放在 (5-9, 5-9) 附近，保证有足够的探索距离
   - 只标注主要区域（城镇、BOSS巢穴、关键地下城），中间的空白格子由游戏运行时动态生成
   - 区域之间的距离通过坐标间隔体现：相邻坐标差1=直接相邻可移动

【输出格式】
严格按照下面的 JSON 格式输出，不要添加任何其他文字说明。确保 JSON 格式正确，可以直接解析。

{
  "world_id": "英文id",
  "world_name": "世界名称",
  "world_type": "fantasy",
  "era": "时代背景",

  "communication": {
    "device": "通讯装置名称",
    "device_description": "装置外观和使用方式（2-3句）",
    "narrative_style": "通讯时的叙事风格描述（1句）"
  },
  "time_system": {
    "calendar": "日历体系",
    "time_unit": "时间单位",
    "special_dates": [
      {"name": "日期名", "date": "日期/周期", "description": "描述"}
    ]
  },

  "geography": {
    "overview": "整体地理（2-3段）",
    "world_map_description": "地图的文字描述",
    "regions": [
      {
        "name": "区域名",
        "description": "详细描述",
        "climate": "气候",
        "major_cities": ["城镇"],
        "landmarks": ["地标"],
        "danger_level": 1,
        "danger_level_description": "等级说明",
        "local_specialties": ["特产"]
      }
    ],
    "grid": {
      "size": 10,
      "main_regions": [
        {
          "region_id": "english_id",
          "name": "区域中文名",
          "x": 0,
          "y": 0,
          "region_type": "town",
          "danger_level": 0,
          "description": "2-3句话描述",
          "is_start": true,
          "is_main_quest": true,
          "completion_condition": "可选：如 boss_defeated:BOSS名"
        },
        {
          "region_id": "boss_id",
          "name": "BOSS区域名",
          "x": 7,
          "y": 7,
          "region_type": "boss_lair",
          "danger_level": 5,
          "description": "BOSS区域描述",
          "is_start": false,
          "is_main_quest": true,
          "completion_condition": "boss_defeated:BOSS名"
        }
      ]
    }
  },

  "races": [
    {
      "name": "种族名",
      "description": "描述",
      "average_lifespan": "寿命",
      "cultural_traits": ["特征"],
      "natural_abilities": ["天赋"],
      "relations_with_others": {"种族": "关系"},
      "preferred_locations": ["聚居地"]
    }
  ],

  "power_system": {
    "name": "体系名",
    "description": "描述（2-3段）",
    "principles": ["规则"],
    "limitations": ["限制"],
    "levels": [
      {"rank": "编号", "name": "等级名", "description": "能力范围", "typical_age_to_reach": "年限"}
    ],
    "specializations": [
      {"name": "专精名", "description": "描述", "strengths": ["擅长"], "weaknesses": ["弱点"]}
    ],
    "legendary_abilities": [
      {"name": "能力名", "description": "描述", "requirements": "条件"}
    ]
  },

  "factions": [
    {
      "name": "势力名",
      "type": "guild/kingdom/academy/religion/mercenary/other",
      "description": "描述",
      "territory": "领地",
      "leader": "首领描述",
      "member_count": "规模",
      "internal_structure": "架构",
      "relations": {"势力": "关系"},
      "notable_members": [
        {"name": "名", "role": "职位", "description": "描述"}
      ]
    }
  ],

  "history": {
    "creation_myth": "创世神话",
    "major_eras": [
      {
        "era_name": "时代名",
        "time_period": "时间段",
        "description": "概述",
        "key_events": [
          {"event": "事件", "description": "描述", "impact": "影响"}
        ]
      }
    ],
    "current_situation": "当前局势（2-3段）"
  },

  "daily_life": {
    "currency": {"name": "货币", "denominations": ["面额"], "exchange_hint": "购买力参考"},
    "transportation": ["交通方式"],
    "communication_methods": ["通讯方式"],
    "entertainment": ["娱乐"],
    "food": {"staples": ["主食"], "specialties": ["美食"], "drinks": ["饮品"]},
    "customs": ["习俗禁忌"],
    "technology_level": "技术/魔法水平描述"
  },

  "dangers": {
    "monster_types": [
      {"name": "怪物", "description": "描述", "habitat": "栖息地", "danger_level": 1, "weakness": "弱点", "loot": ["掉落"]}
    ],
    "dungeons": [
      {
        "name": "副本名",
        "location": "位置",
        "description": "描述",
        "floors_or_areas": "层数",
        "difficulty": "难度",
        "bosses": [{"name": "BOSS", "description": "描述", "abilities": ["技能"], "strategy_hint": "攻略"}],
        "rewards": ["奖励"],
        "lore": "背景故事"
      }
    ],
    "natural_hazards": ["自然危险"],
    "forbidden_zones": [{"name": "禁地", "description": "描述", "reason": "原因"}]
  },

  "items": {
    "equipment_tiers": ["品阶"],
    "equipment_slots": ["部位"],
    "legendary_items": [
      {"name": "物品", "type": "类型", "description": "描述", "ability": "能力", "origin": "来源", "current_location": "所在"}
    ],
    "consumables": [
      {"name": "消耗品", "type": "类型", "effect": "效果", "rarity": "稀有度"}
    ],
    "rare_resources": [
      {"name": "资源", "description": "描述", "where_to_find": "获取途径", "uses": ["用途"]}
    ]
  },

  "character_generation_guide": "角色卡生成的额外引导提示词",
  "activity_generation_guide": "日常活动描述的额外引导",
  "event_generation_guide": "事件生成的额外引导"
}
```

---

## 快速示例（直接复制使用）

### 原神风格奇幻世界

```
你是一个专业的奇幻世界观设计师。请创建一个类似原神「提瓦特大陆」风格的奇幻世界观。

核心设计理念：
- 世界由七个元素（风、岩、雷、草、水、火、冰）构成
- 七国各信仰一位神明，各有独特的文化和建筑风格
- 存在「深渊」这一共同威胁
- 有「神之眼」和「神之心」的核心设定
- 角色是蒙德城的一名冒险者

请严格按照上面的 JSON 格式输出。参考原神的风格但不要照搬，创建一个原创但氛围相似的世界。
```

### 刀剑神域风格

```
你是一个专业的奇幻世界观设计师。请创建一个类似「刀剑神域·艾恩葛朗特」风格的虚拟现实世界。

核心设计理念：
- 这是一个 VRMMO 游戏世界，但有真实感
- 100 层浮空城堡，每层有不同主题
- 存在死亡游戏的紧张感（已被打破，现在是安全时期）
- 有剑技、魔法两大战斗系统
- 有PK区域和安全区域
- 角色是一名正在攻略50层的独行剑士

请严格按照上面的 JSON 格式输出。
```

### 完全原创魔法世界

```
你是一个专业的奇幻世界观设计师。请创建一个完全原创的魔法世界。

核心设计理念：
- 世界建立在巨兽的背上（如龟背、蛇身）
- 魔法来源于「星尘」——一种从天空降落的发光物质
- 人类通过雕刻「星纹」来使用魔法
- 存在一种叫做「蚀」的黑暗力量在侵蚀世界的边缘
- 角色是一名「星纹师」，正在调查蚀的来源

请严格按照上面的 JSON 格式输出。世界要自洽、细节丰富、有故事深度。
```
