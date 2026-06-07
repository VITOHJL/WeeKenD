// 周末旅行人格测试数据（从静态 HTML 移植，demo 精简版）
// 维度：P/R=计划/随机, C/E=充电/放电, X/W=体验/漫游, S/V=仪式/性价比, I/G=独处/多人

export type DimKey =
  | "P" | "R" | "C" | "E" | "X" | "W" | "S" | "V" | "I" | "G";

export interface QuizOption {
  label: string;
  innerOS: string;
  feedback: string;
  scores: Partial<Record<DimKey, number>>;
}

export interface QuizQuestion {
  id: number;
  type: "scoring" | "bonus";
  scene: string;
  mood: string;
  illustration: string;
  options: QuizOption[];
}

export const QUESTIONS: QuizQuestion[] = [
  {
    id: 1, type: "scoring",
    scene: "超市结账，你前面有个人在翻包找零钱——",
    mood: "你已经排了三分钟了。",
    illustration: "🛒",
    options: [
      { label: "A", innerOS: "你的钱已经攥在手里了。攥了三分钟。手心有点热。", feedback: "你为下一秒而生", scores: { P: 2 } },
      { label: "B", innerOS: "你在心里帮他数：5毛……1块……还差8毛……", feedback: "共情强到开始替陌生人焦虑", scores: { I: 1 } },
      { label: "C", innerOS: "你已经刷完四条视频了，他还在翻。", feedback: "两分钟也是两分钟，不能浪费", scores: { R: 1, E: 1 } },
      { label: "D", innerOS: "你在观察他包里有什么。目前发现：钥匙扣是个小熊猫。", feedback: "等待对你来说是田野调查", scores: { R: 1, W: 1 } },
    ],
  },
  {
    id: 2, type: "scoring",
    scene: "你口袋里掏出一张上个月的电影票根——",
    mood: "票根皱了，但你记得一些别的事。",
    illustration: "🎫",
    options: [
      { label: "A", innerOS: "想起来了。那天散场下雨，你等了很久，后来走回去的。", feedback: "你的记忆是一部慢镜头电影", scores: { S: 2, I: 1 } },
      { label: "B", innerOS: "想不起来看的什么，但清晰记得那天吃的是什么。", feedback: "吃永远比看更值得被记住", scores: { V: 2 } },
      { label: "C", innerOS: "它是怎么进我口袋的？皱一下，扔了。", feedback: "你的人生不留票根，干净利落", scores: { R: 1, V: 1 } },
      { label: "D", innerOS: "放回去。口袋里有历史感挺好的。", feedback: "你在随身携带一个小型博物馆", scores: { W: 1, C: 1 } },
    ],
  },
  {
    id: 3, type: "scoring",
    scene: "你做梦，梦到自己在一个不知道在哪的地方——",
    mood: "周围很陌生，但你并不害怕。",
    illustration: "🌌",
    options: [
      { label: "A", innerOS: "梦里的你掏出手机——没信号。开始想怎么办。", feedback: "连梦里都不允许失控", scores: { P: 1, C: 2 } },
      { label: "B", innerOS: "梦里的你：挺好的，先逛逛。", feedback: "梦是你唯一不需要做攻略的地方", scores: { R: 1, X: 1 } },
      { label: "C", innerOS: "旁边有个陌生人说「跟我来」。你跟了，没问去哪。", feedback: "你对「跟着走」有天然的信任", scores: { R: 1, G: 1, E: 1 } },
      { label: "D", innerOS: "你醒了。花了很久想记住那个地方长什么样。没记住。", feedback: "那个地方住进你脑子里了", scores: { W: 1, I: 1 } },
    ],
  },
  {
    id: 4, type: "scoring",
    scene: "你在宜家，走着走着，完全不知道自己在哪——",
    mood: "箭头指向各个方向，但都不是出口。",
    illustration: "🛋️",
    options: [
      { label: "A", innerOS: "找路线图，规划最短路径出去。损失最小化。", feedback: "迷路是需要被消灭的错误", scores: { P: 2, X: 1, E: 1 } },
      { label: "B", innerOS: "反正都迷路了，干脆把剩下的区域也全走完。", feedback: "迷路是可以被利用的机会", scores: { R: 1, X: 1 } },
      { label: "C", innerOS: "跟着前面一个看起来很有目的的人。", feedback: "你对「有人知道路」有本能的信赖", scores: { G: 1, E: 1 } },
      { label: "D", innerOS: "找到一个展示区的沙发，坐下来。这不就是目的地吗。", feedback: "你找到了宜家的正确打开方式", scores: { I: 2 } },
    ],
  },
  {
    id: 5, type: "bonus",
    scene: "你一个人去看了一个展，朋友回复「怎么不叫我！」——",
    mood: "消息通知亮了，你盯着屏幕。",
    illustration: "🎨",
    options: [
      { label: "A", innerOS: "真的忘了，下次一起。", feedback: "你是那种「朋友开心就开心」的人", scores: { G: 1 } },
      { label: "B", innerOS: "因为一个人看才能看得认真。（没说出口）", feedback: "有些体验，一个人才能沉浸", scores: { I: 1, C: 1 } },
      { label: "C", innerOS: "其实是故意的。", feedback: "承认这件事需要一点点勇气", scores: { I: 2 } },
      { label: "D", innerOS: "「下次叫你」，但心里想的是「下次也是一个人」。", feedback: "你的独处不是孤独，是充电", scores: { I: 1, C: 1 } },
    ],
  },
  {
    id: 6, type: "bonus",
    scene: "8人饭局，吃到一半有人提议去唱K——",
    mood: "你的杯子里还有半杯饮料。",
    illustration: "🎤",
    options: [
      { label: "A", innerOS: "去！继续！今晚不散！", feedback: "你能把局撑到最后", scores: { E: 1, G: 2 } },
      { label: "B", innerOS: "想走，但等别人先开口。", feedback: "你内心已经回家了，身体还在微笑", scores: { C: 1, I: 1 } },
      { label: "C", innerOS: "「你们去吧」，然后真的走了。", feedback: "能果断离开是一种超能力", scores: { C: 2, I: 1 } },
      { label: "D", innerOS: "去了，拿着话筒不唱，一直给别人打分。", feedback: "你在任何地方都能找到观察者视角", scores: { W: 1, G: 1 } },
    ],
  },
  {
    id: 7, type: "bonus",
    scene: "你刷到一家很想去的小店，在城市的另一头——",
    mood: "地图显示：公交47分钟，打车28块。",
    illustration: "📍",
    options: [
      { label: "A", innerOS: "查攻略、看评论、对比三篇小红书。周末去。", feedback: "不搜清楚不踏实，很正常", scores: { P: 1, X: 1 } },
      { label: "B", innerOS: "收藏。然后忘记。三个月后又翻到它。", feedback: "你的收藏夹通常超过200个", scores: { W: 1, R: 1 } },
      { label: "C", innerOS: "穿鞋出门。", feedback: "想去直接去，不需要收藏夹壮胆", scores: { R: 2, E: 1 } },
      { label: "D", innerOS: "截图发朋友：「改天去这里吧。」对方回：「好。」", feedback: "这家店和那个朋友都在等一个时机", scores: { G: 1, S: 1 } },
    ],
  },
  {
    id: 8, type: "bonus",
    scene: "周日晚上，你躺在床上——",
    mood: "明天要上班了。窗外有车经过的声音。",
    illustration: "🌙",
    options: [
      { label: "A", innerOS: "翻相册。这周末拍了127张照片，126张是吃的。", feedback: "你的周末以食物为单位计量", scores: { V: 1, S: 1 } },
      { label: "B", innerOS: "有一秒觉得自己周末很无聊。", feedback: "无聊的周末也是一种奢侈", scores: { C: 1, I: 1 } },
      { label: "C", innerOS: "开始计划下个周末去哪。已经打开三个App了。", feedback: "你永远活在下一个周末", scores: { P: 2, X: 1 } },
      { label: "D", innerOS: "觉得自己这周末挺牛的。具体哪牛说不上来。", feedback: "不需要理由的满足感最纯粹", scores: { R: 1, W: 1 } },
    ],
  },
];

export interface Persona {
  name: string;
  emoji: string;
  tagline: string;
  desc: string;
  traits: string[];
  nightmare: string;
}

// demo：按社交维度(I/G)给两个代表人格，简化映射
export const PERSONAS: Record<string, Persona> = {
  PCXSI: {
    name: "孤狼策展人", emoji: "🎯",
    tagline: "你的周末有目标、有预算、有时间表，就差一个队友——但你不想要队友。",
    desc: "提前一周知道去哪、几点到、穿什么。你不是出去玩，你是在执行一项有审美要求的户外项目。",
    traits: ["提前规划", "独立行动", "审美在线", "不等人"],
    nightmare: "一个说「到了再说」的人。",
  },
  PCWSI: {
    name: "精致流浪汉", emoji: "☕",
    tagline: "出门前会研究路线，但路线只精确到「那条街」。剩下的交给直觉和天气。",
    desc: "你会一个人走进好看的咖啡馆坐两小时，享受「有计划的无目的」。手机里有37张路边猫的照片。",
    traits: ["有计划地闲逛", "咖啡馆质检", "一个人精致", "看猫不看人"],
    nightmare: "一个说「走啦走啦别墨迹了」的人。",
  },
  RCXSI: {
    name: "反攻略战士", emoji: "🍃",
    tagline: "出门的时候不知道目的地。你相信好东西会自己出现。",
    desc: "你撞见了从没听过的Livehouse、藏在三楼的独立书店。你的周末是薛定谔的周末。",
    traits: ["不做攻略", "相信缘分", "偶尔奢侈", "一个人精彩"],
    nightmare: "一个提前三天发你Excel行程表的人。",
  },
  RCWSI: {
    name: "苏东坡转世", emoji: "🍂",
    tagline: "没有目的地，就这样走着。路过好看的就停下来。",
    desc: "你会因为一家店门头好看就进去，会在公园长椅上看鸽子——那半小时很值。",
    traits: ["无目的地", "审美驱动", "偶尔精致", "当下即一切"],
    nightmare: "一个拿着Excel行程表的人。",
  },
  PEXSG: {
    name: "朋友圈CEO", emoji: "📋",
    tagline: "周三确认人数，周四发行程，周五发「明天见」。",
    desc: "你不是控制狂——你只是知道，一个好的周末不能交给「到时候再说」。没有你，局根本组不起来。",
    traits: ["组织大师", "提前规划", "多人快乐", "准时是美德"],
    nightmare: "一个说「我可能来可能不来」的人。",
  },
  REXSG: {
    name: "局の灵魂", emoji: "🎉",
    tagline: "你不需要提前规划——你本身就是规划。有你在，任何局都会自动升温。",
    desc: "朋友说「好无聊」，你说「走，出去」。然后一小时后你们在某个地方玩疯了。",
    traits: ["随时约", "气氛担当", "即兴行动", "快乐传染"],
    nightmare: "一个说「我要考虑一下」然后两天后才回消息的人。",
  },
  REWVG: {
    name: "专业鸽子", emoji: "🕊️",
    tagline: "可出可不出。有人约就去，没人约就躺。",
    desc: "你不会主动组局，但也不拒绝任何局。你是「都可以」这个词的人形化身。",
    traits: ["随叫随到", "去哪都行", "不花钱", "好伺候"],
    nightmare: "一个让你「快点做决定」的人。",
  },
  PEXVG: {
    name: "人均不过百会长", emoji: "🤝",
    tagline: "你的存在让朋友们省了很多钱。",
    desc: "你会提前算好AA金额、找好停车优惠、甚至记得谁不吃香菜。人均永远不过百，体验永远超预期。",
    traits: ["薅券带师", "AA公平", "多人组团", "提前比价"],
    nightmare: "一个说「各付各的好麻烦，你请吧」的人。",
  },
};

export const DIM_LABELS: { left: string; right: string; lp: DimKey; rp: DimKey }[] = [
  { left: "计划控", right: "随机派", lp: "P", rp: "R" },
  { left: "充电型", right: "放电型", lp: "C", rp: "E" },
  { left: "体验派", right: "漫游派", lp: "X", rp: "W" },
  { left: "仪式感", right: "性价比", lp: "S", rp: "V" },
  { left: "独处型", right: "多人型", lp: "I", rp: "G" },
];

export type Scores = Record<DimKey, number>;

export const emptyScores = (): Scores => ({
  P: 0, R: 0, C: 0, E: 0, X: 0, W: 0, S: 0, V: 0, I: 0, G: 0,
});

const DIMS: { left: DimKey; right: DimKey }[] = [
  { left: "P", right: "R" },
  { left: "C", right: "E" },
  { left: "X", right: "W" },
  { left: "S", right: "V" },
  { left: "I", right: "G" },
];

export function computeCode(scores: Scores): string {
  let code = "";
  for (const d of DIMS) {
    const l = scores[d.left] || 0;
    const r = scores[d.right] || 0;
    code += l >= r ? d.left : d.right;
  }
  return code;
}

export function resolvePersona(code: string): { key: string; persona: Persona } {
  if (PERSONAS[code]) return { key: code, persona: PERSONAS[code] };
  // 退化：按社交维度找一个最接近的
  const social = code[4];
  const candidates = Object.keys(PERSONAS).filter((k) => k[4] === social);
  const key = candidates[0] ?? Object.keys(PERSONAS)[0]!;
  return { key, persona: PERSONAS[key]! };
}

// 某维度「左极」百分比（用于画像条）
export function dimPercent(scores: Scores, left: DimKey, right: DimKey): number {
  const l = scores[left] || 0;
  const r = scores[right] || 0;
  const total = l + r;
  if (total === 0) return 50;
  return Math.round((l / total) * 100);
}
