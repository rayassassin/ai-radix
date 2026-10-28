#!/usr/bin/env node
/*
 * AIRadix · LLM Radar · 折扣展示文案回归测试
 *
 * 跑法：node scripts/selftest_discount.js
 *
 * 为什么不能只靠肉眼：折扣文案有两条硬约束，改代码很容易破掉——
 *   1. 同一行里不能出现两个不同的「折数」（当前价一个、规律价一个），会互相打架
 *   2. 样本只有 1 天时不能写「每日」——那是承诺，我们只知道「观察到」
 * 这里直接从 app.js 里抽出函数执行，测的就是线上那份代码，不养副本。
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');

/** 从 app.js 抠出指定函数/常量（对象常量、函数、标量常量三种写法） */
function grab(name) {
  const pats = [
    '(?:const ' + name + ' = \\{[\\s\\S]*?\\n  \\};)',
    '(?:function ' + name + '\\([\\s\\S]*?\\n  \\})',
    '(?:const ' + name + ' = [^;\\n]+;)',
  ];
  for (const p of pats) {
    const m = src.match(new RegExp(p, 'm'));
    if (m) return m[0];
  }
  throw new Error('app.js 里找不到 ' + name);
}

const names = [
  'KIND_TEXT', 'DISC_ICON', 'DISCOUNT_SHOW', 'fmtRatio', 'discountLabel', 'hhmm', 'rangeText', 'scopeText',
  'discountCycleText', 'discountRangeSentence', 'discountOf', 'discountKindOf',
  'patternOf', 'discountBadge', 'discountCycleLine',
];
// 依赖浏览器环境的两个小工具，测里给等价替身
const stubs = `
  const esc = (s) => String(s == null ? '' : s);
  const priceStr = (v) => (v == null ? '' : (v === 0 ? '免费' : '¥' + (v * 7.15).toFixed(2)));
`;
const api = new Function(
  stubs + names.map(grab).join('\n') + '\nreturn {' + names.join(',') + '};'
)();

let failed = 0;
function eq(label, got, exp) {
  const ok = got === exp;
  if (!ok) failed += 1;
  console.log((ok ? '  ✅ ' : '  ❌ ') + label + (ok ? '' : `\n      实际: ${got}\n      期望: ${exp}`));
}
function ok(label, cond) {
  if (!cond) failed += 1;
  console.log((cond ? '  ✅ ' : '  ❌ ') + label);
}

console.log('① 时段区间（跨零点要合并，不能拆两段）');
eq('20-24 与 0-8 合并', api.rangeText([[0, 8], [20, 24]]), '20:00–次日 08:00');
eq('白天两段', api.rangeText([[9, 13], [15, 18]]), '09:00–13:00、15:00–18:00');
eq('只到当日结束', api.rangeText([[18, 24]]), '18:00–24:00');
eq('从零点开始', api.rangeText([[0, 6]]), '00:00–06:00');
eq('空输入', api.rangeText([]), '');

console.log('\n② 周期行（只讲时段，折数归徽章）');
const strong = { ratio: 0.5, offRanges: [[0, 8], [20, 24]], onRanges: [[8, 20]],
                 scope: 'daily', peak: { confidence: 'high', days: 3 } };
eq('规律已确认', api.discountCycleText(strong), '每日 08:00–20:00 原价，20:00–次日 08:00 低谷');
const weak = { ratio: 0.5, offRanges: [[13, 15]], onRanges: [[9, 13]],
               scope: 'unknown', peak: { confidence: 'low', days: 1 } };
eq('单日样本不写「每日」', api.discountCycleText(weak), '近 1 天 13:00–15:00 出现低谷（待确认）');
eq('无时段可说', api.discountCycleText({ ratio: 0.3, offRanges: [], onRanges: [], scope: 'unknown', peak: null }),
   '限时优惠，无固定时段');
ok('周期行不含「折」字', !api.discountCycleText(strong).includes('折'));

console.log('\n③ 详情句式（照着「高峰原价 / 其余时段 N 折」的读法）');
eq('规律已确认', api.discountRangeSentence(strong), '每日 08:00–20:00 属高峰原价，其余时段 5 折');
eq('工作日周期',
   api.discountRangeSentence({ ratio: 0.5, offRanges: [[18, 24]], onRanges: [[9, 18]],
                               scope: 'weekday', peak: { confidence: 'high', days: 5 } }),
   '周一至周五 09:00–18:00 属高峰原价，其余时段 5 折');
eq('单日样本用「观察到」',
   api.discountRangeSentence(weak),
   '近 1 天观察到 13:00–15:00 为低谷，约 5 折（样本不足，规律待确认）');
eq('此刻是原价时只说时段',
   api.discountRangeSentence({ ratio: 1, offRanges: [[11, 15]], onRanges: [], scope: 'unknown',
                               peak: { confidence: 'low', days: 1 } }),
   '近 1 天观察到 11:00–15:00 为低谷时段（样本不足，规律待确认）');
eq('无时段时不自相矛盾',
   api.discountRangeSentence({ ratio: 0.41, offRanges: [], onRanges: [], scope: 'unknown', peak: null }),
   '限时 4.1 折，无固定时段');

console.log('\n④ 徽章结构');
const withPat = { id: 'x/y', name: 'X', price: { in: 0.15 },
  discount: { ratio: 0.5, base: 0.3, base_out: 1.2, ratio_out: 0.5, samples: 24 },
  off_peak: { low: 0.15, high: 0.3, discount: 0.5, off_ranges: [[0, 8], [20, 24]],
              on_ranges: [[8, 20]], scope: 'daily', days: 3, samples: 24, confidence: 'high' } };
const html = api.discountBadge(withPat);
ok('徽章内嵌图标', html.includes('<svg'));
ok('徽章只放类型名', /<span>(夜间|限时)(折扣|免费)<\/span><\/span>/.test(html));
ok('系数外置为 .disc-ratio', html.includes('class="disc-ratio"'));
ok('tooltip 带时段与依据', html.includes('属高峰原价') && html.includes('次采样'));

const atBase = { id: 'a/b', name: 'A', price: { in: 0.3 },
  off_peak: { low: 0.15, high: 0.3, discount: 0.5, off_ranges: [[20, 24]],
              on_ranges: [[8, 20]], scope: 'daily', days: 3, confidence: 'high' } };
ok('原价时不出徽章', api.discountBadge(atBase) === '');
ok('原价时仍有周期行（压淡）', api.discountCycleLine(atBase).includes('at-base'));

console.log();
if (failed) {
  console.log(`❌ ${failed} 项失败`);
  process.exit(1);
}
console.log('✅ 全部通过');
