// ===== 数据层：鱼种 / 装备 / 水域 =====
// 独立的数据定义，方便扩展与平衡调整。

const DATA = (() => {

  // ---------- 鱼种定义 ----------
  // strength: 力量(拉张力幅度)  aggress: 攻击性(咬钩率)  fight: 挣扎热情(耐力)
  // value:   每公斤价格   unlock: 解锁所需钓鱼等级(简化为在水域出现)
  const FISH = [
    // 老磨坊池塘 (新手)
    { id:'bream',      name:'太平鱼',   family:'杂鱼',   min:0.3,  max:1.2, value:8,  strength:14, aggress:0.9,  fight:22, color:'#b8a24e', zones:['pond'],      desc:'池塘里最常见的小鱼，胃口好。' },
    { id:'perch',      name:'河鲈',     family:'鲈鱼',   min:0.4,  max:1.8, value:14, strength:22, aggress:0.8,  fight:30, color:'#86a15a', zones:['pond','lake'], desc:'条纹漂亮，喜欢追活饵。' },
    { id:'roach',      name:'北欧鲤',   family:'鲤科',   min:0.5,  max:3.0, value:20, strength:30, aggress:0.7,  fight:40, color:'#c98b3d', zones:['pond','lake'], desc:'拉力不俗，是新手练手的好对手。' },
    { id:'trout',      name:'溪鳟',     family:'鳟鱼',   min:0.5,  max:2.5, value:32, strength:38, aggress:0.6,  fight:48, color:'#5f9ea0', zones:['pond','lake'], desc:'银色身段，力气很大。' },
    // 月光湖 (进阶)
    { id:'pike',       name:'北方梭鱼', family:'梭鱼', min:1.0, max:8.0, value:26, strength:52, aggress:0.5, fight:70, color:'#7a9b4e', zones:['lake','river'], desc:'牙齿锋利的掠食者，冲刺迅猛。' },
    { id:'zander',     name:'梭鲈',     family:'鲈鱼', min:0.8, max:6.0, value:30, strength:48, aggress:0.5, fight:62, color:'#8fbf6f', zones:['lake','river'], desc:'夜行性猎手，喜欢深水。' },
    { id:'carp',       name:'镜鲤',     family:'鲤科', min:1.5, max:12, value:22, strength:58, aggress:0.4, fight:90, color:'#d4a24a', zones:['lake','pond'], desc:'又大又沉，耐力惊人，考验遛鱼。' },
    { id:'asp',        name:'赤梢鱼',   family:'鲤科', min:0.6, max:4.0, value:34, strength:44, aggress:0.6, fight:55, color:'#b8c4d0', zones:['lake','river'], desc:'速度极快，喜欢在急流捕食。' },
    // 暗礁河 (困难)
    { id:'catfish',    name:'六须鲶',   family:'鲶鱼', min:2.0, max:30, value:18, strength:70, aggress:0.3, fight:120, color:'#6b5b4a', zones:['river'], desc:'水底巨怪，深潜拒收，极其难缠。' },
    { id:'sturgeon',   name:'欧洲鲟',   family:'鲟鱼', min:3.0, max:40, value:40, strength:80, aggress:0.25, fight:140, color:'#8a8a8a', zones:['river'], desc:'古老巨物，拉力能拉断普通鱼线。' },
    { id:'salmon',     name:'大西洋鲑', family:'鲑鱼', min:1.5, max:15, value:45, strength:62, aggress:0.5, fight:85, color:'#9ec6d0', zones:['river'], desc:'溯流勇士，会连续跳起挣扎。' },
    { id:'burbot',     name:'江鳕',     family:'鳕鱼', min:0.8, max:6.0, value:28, strength:50, aggress:0.45, fight:65, color:'#a08a5a', zones:['river','pond'], desc:'冬夜出没的冷水鱼。' },
    // 深渊之眼 (精英/赏金)
    { id:'tuna',       name:'蓝鳍金枪', family:'金枪鱼', min:10, max:200, value:38, strength:95, aggress:0.4, fight:200, color:'#3d5a80', zones:['abyss'], desc:'深海霸主，速度与力量兼备的饕餮。' },
    { id:'amberjack',  name:'琥珀鱼',   family:'鲹科', min:3.0, max:40, value:30, strength:72, aggress:0.5, fight:110, color:'#e0a04a', zones:['abyss'], desc:'强悍的深海斗士。' },
    { id:'swordfish',  name:'剑鱼',     family:'旗鱼', min:8.0, max:120, value:52, strength:88, aggress:0.35, fight:160, color:'#6a7a92', zones:['abyss'], desc:'长吻利剑，冲刺如闪电。' },
    { id:'goliath',    name:'巨型石斑', family:'石斑鱼', min:5.0, max:80, value:35, strength:78, aggress:0.4, fight:130, color:'#8a6a4a', zones:['abyss'], desc:'沉入水底死扛，最考验钓具。' },
    { id:'monster',    name:'湖中巨怪', family:'传说', min:20, max:500, value:88, strength:99, aggress:0.15, fight:300, color:'#5a4a8a', zones:['abyss'], desc:'传说级存在，钓到它即是传奇。', legendary:true },
  ];

  // ---------- 水域定义 ----------
  const ZONES = {
    pond:  { name:'老磨坊池塘', need:0,   difficulty:'新手', tint:'rgba(120,180,120,0.25)', breeze:'舒缓',  desc:'风平浪静的小池塘，适合入门。' },
    lake:  { name:'月光湖',     need:200, difficulty:'进阶', tint:'rgba(80,140,200,0.25)',  breeze:'微风',   desc:'明澈的湖面，藏着大鱼。' },
    river: { name:'暗礁河',     need:800, difficulty:'困难', tint:'rgba(60,120,160,0.30)',  breeze:'湍急',   desc:'水流湍急，物产凶猛。' },
    abyss: { name:'深渊之眼',   need:2500, difficulty:'精英', tint:'rgba(40,60,120,0.40)',   breeze:'深幽',   desc:'深海与深渊交汇之处，只容强者。' },
  };

  // ---------- 装备定义 ----------
  // 鱼竿 rods: cast(抛投力) fight(刺鱼/控鱼加成)
  const RODS = [
    { id:'rod1', name:'木竿',      icon:'🎣', price:0,   cast:40,  fight:10,  desc:'新手木竿，够用。',
      body:'#8a5a2a', tip:'#a8723a', len:90, lw:5, tipLen:24, tipLw:3,
      reel:'#7a6a55', hand:'#6b4e2e', style:'wood' },
    { id:'rod2', name:'碳素竿',   icon:'🎋', price:300, cast:60,  fight:20,  desc:'轻盈坚韧，抛得更远。',
      body:'#3b4450', tip:'#55606e', len:105, lw:3.5, tipLen:32, tipLw:2,
      reel:'#93a0ae', hand:'#2f3742', style:'carbon' },
    { id:'rod3', name:'鲟鱼重竿', icon:'⚓', price:1200,cast:80,  fight:35,  desc:'专为巨物打造的强竿。',
      body:'#5a4632', tip:'#7c6040', len:80, lw:8, tipLen:20, tipLw:4,
      reel:'#8a6b3f', hand:'#4a3826', style:'heavy' },
    { id:'rod4', name:'深渊神竿', icon:'🔱', price:4000,cast:100, fight:55,  desc:'传世神兵，无所不钓。',
      body:'#1a5a66', tip:'#2e8a99', len:120, lw:3, tipLen:40, tipLw:2,
      reel:'#3fd0e0', hand:'#0f3b44', style:'abyss' },
  ];
  // 卷线轮 reels: speed(收线速度) drag(泄力/张力吸收)
  const REELS = [
    { id:'reel1', name:'基础轮',   price:0,   speed:30, drag:0,  desc:'转起来有点涩。' },
    { id:'reel2', name:'轻量轮',   price:400, speed:50, drag:10, desc:'顺滑轻快。' },
    { id:'reel3', name:'强攻轮',   price:1500,speed:70, drag:25, desc:'大拖力，抗冲击。' },
    { id:'reel4', name:'星辰滑轮', price:5000,speed:95, drag:45, desc:'收线如行云流水。' },
  ];
  // 鱼线 lines: maxTension(强度/断线阈值)
  const LINES = [
    { id:'line1', name:'尼龙线',   price:0,   maxTension:90,   desc:'弹性好但强度一般。' },
    { id:'line2', name:'编织线',   price:500, maxTension:110,  desc:'高强低延展。' },
    { id:'line3', name:'氟碳线',   price:1800,maxTension:160, desc:'水下隐形，强度惊人。' },
    { id:'line4', name:'神之钓线', price:6000,maxTension:240, desc:'几乎不可能被拉断。' },
  ];
  // 鱼饵 baits: bite(咬钩加成) family(偏好鱼群)
  const BAITS = [
    { id:'bait1', name:'蚯蚓',     price:0,   family:'杂鱼', bite:1.15, desc:'万能饵，新手之友。' },
    { id:'bait2', name:'玉米粒',   price:80,  family:'鲤科', bite:1.30, desc:'鲤科的最爱。' },
    { id:'bait3', name:'活小鱼',   price:200, family:'鲈鱼', bite:1.35, desc:'吸引掠食鱼类。' },
    { id:'bait4', name:'香肠丁',   price:350, family:'鲶鱼', bite:1.40, desc:'鲶鱼和鳕鱼难以抗拒。' },
    { id:'bait5', name:'虾肉',     price:600, family:'深海', bite:1.45, desc:'深海鱼的美味。' },
    { id:'bait6', name:'黄金鱼饵', price:2000,family:'传说', bite:1.60, desc:'传说级诱饵，吸引巨物。' },
  ];

  return { FISH, ZONES, RODS, REELS, LINES, BAITS };
})();