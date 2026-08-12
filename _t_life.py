from simlife.backend import life_skills as LS
from simlife.backend.life_skills import init_life_state, ensure_life_state

# 初始化
ls = init_life_state()
assert ls['skills']['cooking']['level'] == 1

# 加材料与扣除
LS.add_materials(ls['inventory'], 'wheat', 5)
assert LS.has_materials(ls['inventory'], [['wheat', 3]])
assert LS.remove_materials(ls['inventory'], 'wheat', 3)
assert not LS.has_materials(ls['inventory'], [['wheat', 3]])

# 判定系统
assert LS.judge_step(0, 3, 0, 1) == 'perfect'
assert LS.judge_step(0, 3, 1, 1) == 'good'
assert LS.judge_overall(['perfect', 'good', 'normal'], 1) == 'good'
assert LS.judge_overall(['perfect', 'perfect', 'perfect'], 1) == 'perfect'
assert LS.judge_overall(['normal', 'normal', 'normal'], 1) == 'normal'

# 商店
shop = LS.build_shop(1)
ids = [s['id'] for s in shop]
assert 'wheat' in ids
assert 'mithril' not in ids
shop4 = LS.build_shop(4)
assert 'mithril' in [s['id'] for s in shop4]

# 经验升级
up = LS.add_xp(ls['skills'], 'cooking', 60)
assert up['level_up'] is True
assert ls['skills']['cooking']['level'] == 2

# 菜谱/设计图/鱼
assert LS.get_cook_recipe('bread')['steps'] == ['和面', '揉面', '烘烤']
assert LS.get_forge_blueprint('iron_sword')['steps'][3] == '折叠锻打'
assert len(LS.FISH_TABLE) >= 10

print('LIFE_SKILLS OK')