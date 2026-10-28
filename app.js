/* ============================================================
   AIRadix · LLM Radar · 前端逻辑
   纯原生 JS，无构建、无依赖。数据由 scripts/fetch_models.py 生成。
   ============================================================ */

(() => {
  'use strict';

  // ---------------- 常量 ----------------

  const CAPS = [
    { key: 'reasoning', label: '推理', hint: '支持思维链 / reasoning 参数' },
    { key: 'tools', label: '工具', hint: '支持 function calling' },
    { key: 'json', label: 'JSON', hint: '支持结构化输出' },
    { key: 'open_weights', label: '开放权重', hint: '权重可下载本地部署', cls: 'green' },
    { key: 'vision', label: '视觉', hint: '可输入图片' },
    { key: 'audio_in', label: '音频', hint: '可输入音频' },
    { key: 'video_in', label: '视频', hint: '可输入视频' },
    { key: 'file_in', label: '文件', hint: '可输入 PDF 等文档' },
    { key: 'cache', label: '缓存', hint: '支持 prompt 缓存计费' },
  ];

  const MOD_ICON = {
    text: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 6h16M4 12h11M4 18h7"/></svg>',
    image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.4"/><path d="m21 15-5-5L7 19"/></svg>',
    audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/></svg>',
    video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="6" width="13" height="12" rx="2"/><path d="m15 11 7-3.5v9L15 13z"/></svg>',
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7z"/><path d="M14 2v5h5"/></svg>',
  };

  const MOD_LABEL = { text: '文字', image: '图片', audio: '音频', video: '视频', file: '文件' };

  const STORE_KEY = 'ai-radix-prefs';
  const MAX_COMPARE = 4;

  // ---------------- 状态 ----------------

  const state = {
    models: [],
    meta: null,
    rate: 7.15,
    live: false,          // true=实时接口数据，false=本地缓存兜底
    newModelDays: 30,
    q: '',
    types: new Set(),
    caps: new Set(),
    vendor: '',
    ctx: '',
    price: '',
    discount: '',         // 折扣类型筛选：'' | any | night | limited | free
    vendorIcons: {},      // 厂商 → 工具集 favicon 映射（data/vendor_icons.json）
    sort: 'newest',
    view: 'table',
    currency: 'CNY',
    page: 1,
    pageSize: 50,
    _sig: '',             // 筛选条件指纹，变了就自动回到第 1 页
    selected: new Set(),
    drawerId: null,
    loading: true,
    error: null,
  };

  // ---------------- DOM ----------------

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const el = {
    tbody: $('#tbody'),
    cardView: $('#cardView'),
    tableWrap: $('#tableWrap'),
    emptyState: $('#emptyState'),
    pager: $('#pager'),
    search: $('#search'),
    typeChips: $('#typeChips'),
    capChips: $('#capChips'),
    discChips: $('#discChips'),
    vendorSelect: $('#vendorSelect'),
    ctxSelect: $('#ctxSelect'),
    priceSelect: $('#priceSelect'),
    sortSelect: $('#sortSelect'),
    currencySelect: $('#currencySelect'),
    viewSeg: $('#viewSeg'),
    resultCount: $('#resultCount'),
    activeFilters: $('#activeFilters'),
    checkAll: $('#checkAll'),
    overlay: $('#overlay'),
    drawer: $('#drawer'),
    drawerHead: $('#drawerHead'),
    drawerBody: $('#drawerBody'),
    drawerFoot: $('#drawerFoot'),
    compareBar: $('#compareBar'),
    compareText: $('#compareText'),
    compareThumbs: $('#compareThumbs'),
    compareModal: $('#compareModal'),
    compareBody: $('#compareBody'),
    toastWrap: $('#toastWrap'),
    updatedAt: $('#updatedAt'),
  };

  // ---------------- 工具函数 ----------------

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  /** 数字紧凑显示：1048576 → {v:"1.05", u:"M"} */
  function fmtCtx(n) {
    if (!n || n <= 0) return { v: '—', u: '' };
    if (n >= 1048576) return { v: trim((n / 1048576).toFixed(2)), u: 'M' };
    if (n >= 1000) return { v: Math.round(n / 1000), u: 'K' };
    return { v: n, u: '' };
  }

  function trim(s) {
    return String(s).replace(/\.?0+$/, '') || '0';
  }

  /** 价格数值美化，保留有效位但不啰嗦 */
  function fmtMoney(v) {
    if (v === 0) return '0';
    if (v >= 100) return v.toFixed(0);
    if (v >= 10) return trim(v.toFixed(1));
    if (v >= 1) return trim(v.toFixed(2));
    if (v >= 0.01) return trim(v.toFixed(3));
    return trim(v.toFixed(4)) || '0.0001';
  }

  /** 美元单价（/1M tokens）→ 当前币种展示字符串 */
  function priceStr(usd) {
    if (usd === null || usd === undefined) return null;
    const sym = state.currency === 'CNY' ? '¥' : '$';
    const v = state.currency === 'CNY' ? usd * state.rate : usd;
    return sym + fmtMoney(v);
  }

  /** 内部统一按人民币比较（筛选阈值固定为 ¥） */
  const toCny = (usd) => (usd === null || usd === undefined ? null : usd * state.rate);

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  function toast(msg, type = 'info') {
    const icon = type === 'warn'
      ? '<svg viewBox="0 0 24 24" fill="none" stroke="#f5b942" stroke-width="2.2" stroke-linecap="round"><path d="M12 9v5M12 17.5v.5"/><circle cx="12" cy="12" r="9"/></svg>'
      : '<svg viewBox="0 0 24 24" fill="none" stroke="#4ade80" stroke-width="2.4" stroke-linecap="round"><path d="m4 12 5 5L20 6"/></svg>';
    const d = document.createElement('div');
    d.className = 'toast';
    d.innerHTML = icon + `<span>${esc(msg)}</span>`;
    el.toastWrap.appendChild(d);
    setTimeout(() => {
      d.style.transition = 'opacity .2s, transform .2s';
      d.style.opacity = '0';
      d.style.transform = 'translateX(14px)';
      setTimeout(() => d.remove(), 220);
    }, 2200);
  }

  function savePrefs() {
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify({
        view: state.view, currency: state.currency, sort: state.sort,
        pageSize: state.pageSize,
      }));
    } catch (_) { /* 隐私模式下忽略 */ }
  }

  function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem(STORE_KEY) || '{}');
      if (p.view === 'card' || p.view === 'table') state.view = p.view;
      if (p.currency === 'USD' || p.currency === 'CNY') state.currency = p.currency;
      if (p.sort) state.sort = p.sort;
      if ([25, 50, 100].includes(p.pageSize)) state.pageSize = p.pageSize;
    } catch (_) { /* 忽略损坏数据 */ }
  }

  // ---------------- 数据加载 ----------------

  /* OpenRouter 公开接口，CORS 全开（access-control-allow-origin: *），
     浏览器可直连。这意味着站点数据永远是最新的，不依赖定时重新发布静态文件。
     接口异常时回落本地 data/models.json 缓存，保证可用性。 */
  const API_URL = 'https://openrouter.ai/api/v1/models';
  const PALETTE = ['#5b5bd6', '#0ea5e9', '#14b8a6', '#f59e0b', '#ef4444',
    '#8b5cf6', '#ec4899', '#22c55e', '#f97316', '#6366f1'];

  async function fetchJSON(url, timeout = 20000) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(url, { signal: ctrl.signal, cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } finally {
      clearTimeout(timer);
    }
  }

  /** 类型判定：只看产出。与 scripts/fetch_models.py 的 classify 同规则。 */
  function classifyModel(raw) {
    const arch = raw.architecture || {};
    const outs = new Set(arch.output_modalities || []);
    const blob = `${raw.id || ''} ${raw.name || ''}`.toLowerCase();
    if (blob.includes('embed')) return '嵌入';
    if (blob.includes('rerank') || blob.includes('reranker')) return '重排序';
    if (blob.includes('moderation')) return '审核';
    if (outs.has('video')) return '视频生成';
    if (outs.has('image')) return '图像生成';
    if (outs.has('audio')) return '语音合成';
    return '文本';
  }

  function capsOf(raw) {
    const sp = new Set(raw.supported_parameters || []);
    const arch = raw.architecture || {};
    const ins = new Set(arch.input_modalities || []);
    const outs = new Set(arch.output_modalities || []);
    const pricing = raw.pricing || {};
    return {
      reasoning: !!(sp.has('reasoning') || sp.has('include_reasoning') || raw.reasoning),
      tools: sp.has('tools'),
      structured: sp.has('structured_outputs'),
      json: !!(sp.has('response_format') || sp.has('structured_outputs')),
      temperature: sp.has('temperature'),
      open_weights: !!raw.hugging_face_id,
      vision: ins.has('image'),
      audio_in: ins.has('audio'),
      video_in: ins.has('video'),
      file_in: ins.has('file'),
      image_out: outs.has('image'),
      audio_out: outs.has('audio'),
      cache: !!(parseFloat(pricing.input_cache_read) > 0),
      seed: sp.has('seed'),
      logprobs: sp.has('logprobs'),
    };
  }

  const toNum = (v) => {
    const f = parseFloat(v);
    return (!isFinite(f) || f < 0) ? null : f;   // -1 表示动态定价，视为未知
  };
  const perM = (v) => {
    const f = toNum(v);
    return f === null ? null : Math.round(f * 1e6 * 10000) / 10000;
  };

  function vendorOf(vendorRaw, providers) {
    const base = vendorRaw.replace(/^~/, '');
    const info = providers[base];
    if (info) return { name: info.name || base, cn: info.cn || base, color: info.color || PALETTE[0] };
    const color = PALETTE[base.split('').reduce((s, c) => s + c.charCodeAt(0), 0) % PALETTE.length];
    return { name: base, cn: base, color };
  }

  /** 把 OpenRouter 原始条目标准化成前端消费结构（与 Python 输出字段保持一致） */
  function normalizeModel(raw, providers, newDays) {
    if (!raw || !raw.id || !raw.id.includes('/')) return null;
    const [vendorRaw, ...rest] = raw.id.split('/');
    const slug = rest.join('/');
    const v = vendorOf(vendorRaw, providers);

    const fullName = (raw.name || raw.id).trim();
    const name = fullName.includes(': ') ? fullName.split(': ').slice(1).join(': ') : fullName;

    const ts = Number(raw.created) || 0;
    // 统一按 UTC+8 出日期，与抓取脚本一致
    const createdDate = ts ? new Date((ts + 8 * 3600) * 1000) : null;
    const created = createdDate ? createdDate.toISOString().slice(0, 10) : null;
    const ageDays = createdDate
      ? Math.floor((Date.now() + 8 * 3600 * 1000 - createdDate.getTime()) / 86400000)
      : null;

    const bench = raw.benchmarks || {};
    const aa = bench.artificial_analysis || {};
    const pricing = raw.pricing || {};
    const top = raw.top_provider || {};
    const arch = raw.architecture || {};

    return {
      id: raw.id,
      slug,
      name,
      full_name: fullName,
      vendor: vendorRaw.replace(/^~/, ''),
      vendor_alias: vendorRaw.startsWith('~'),
      vendor_name: v.name,
      vendor_cn: v.cn,
      vendor_color: v.color,
      type: classifyModel(raw),
      context: raw.context_length || 0,
      max_output: top.max_completion_tokens ?? null,
      input_modalities: arch.input_modalities || [],
      output_modalities: arch.output_modalities || [],
      modality: arch.modality || null,
      tokenizer: arch.tokenizer || null,
      caps: capsOf(raw),
      iq: typeof aa.intelligence_index === 'number' ? aa.intelligence_index : null,
      iq_coding: typeof aa.coding_index === 'number' ? aa.coding_index : null,
      iq_agentic: typeof aa.agentic_index === 'number' ? aa.agentic_index : null,
      arena: (bench.design_arena || []).map((a) => ({
        category: a.category, elo: a.elo, rank: a.rank, win_rate: a.win_rate,
      })),
      price: {
        in: perM(pricing.prompt),
        out: perM(pricing.completion),
        cache_read: perM(pricing.input_cache_read),
        cache_write: perM(pricing.input_cache_write),
        image: perM(pricing.image),
        audio: perM(pricing.audio),
        audio_out: perM(pricing.audio_output),
        web_search: perM(pricing.web_search),
        internal_reasoning: perM(pricing.internal_reasoning),
      },
      created,
      created_ts: ts,
      age_days: ageDays,
      is_new: ageDays !== null && ageDays >= 0 && ageDays <= newDays,
      knowledge_cutoff: raw.knowledge_cutoff || null,
      expiration: raw.expiration_date || null,
      hf_id: raw.hugging_face_id || null,
      moderated: top.is_moderated ?? null,
      provider_ctx: top.context_length ?? null,
      description: (raw.description || '').trim(),
      supported_parameters: (raw.supported_parameters || []).slice().sort(),
      per_request_limits: raw.per_request_limits || null,
    };
  }

  function buildMeta(models, rate, newDays) {
    const vendors = {};
    const types = {};
    for (const m of models) {
      vendors[m.vendor_cn || m.vendor] = (vendors[m.vendor_cn || m.vendor] || 0) + 1;
      types[m.type] = (types[m.type] || 0) + 1;
    }
    const sortDesc = (o) => Object.fromEntries(Object.entries(o).sort((a, b) => b[1] - a[1]));
    const d = new Date(Date.now() + 8 * 3600 * 1000);
    const pad = (n) => String(n).padStart(2, '0');
    return {
      updated_at: `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} `
        + `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`,
      updated_ts: Math.floor(Date.now() / 1000),
      total: models.length,
      vendors: Object.keys(vendors).length,
      recent_new: models.filter((m) => m.is_new).length,
      open_weights: models.filter((m) => m.caps.open_weights).length,
      with_iq: models.filter((m) => typeof m.iq === 'number').length,
      vendor_stats: sortDesc(vendors),
      type_stats: sortDesc(types),
      usd_to_cny: rate,
      new_model_days: newDays,
      source: API_URL,
    };
  }

  async function loadData() {
    state.loading = true;
    state.error = null;
    renderSkeleton();

    const rate = Number(state.rate) || 7.15;
    const newDays = Number(state.newModelDays) || 30;

    try {
      // ---- 路径 1：直连 OpenRouter 实时数据 ----
      // 厂商图标：复用工具集已抓好的 favicon（scripts/build_vendor_icons.py 映射），
      // 只有 1.7KB，串行等一下不影响体感，胜在渲染时一定已就绪。
      const vIcons = await fetchJSON('data/vendor_icons.json').catch(() => null);
      state.vendorIcons = (vIcons && vIcons.icons) || {};

      let models = null;
      let meta = null;
      let providers = {};
      try {
        const [raw, prov] = await Promise.all([
          fetchJSON(API_URL),
          fetchJSON('data/providers.json').catch(() => ({})),
        ]);
        providers = prov || {};
        models = (raw.data || []).map((m) => normalizeModel(m, providers, newDays)).filter(Boolean);
        if (models.length === 0) throw new Error('实时接口返回空数据');
        meta = buildMeta(models, rate, newDays);
        state.live = true;
      } catch (liveErr) {
        console.warn('[AIRadix · LLM Radar] 实时接口不可用，回落本地缓存：', liveErr.message);
      }

      // ---- 路径 2：本地缓存兜底 ----
      if (!models) {
        const cache = await fetchJSON('data/models.json').catch(() => null);
        if (!Array.isArray(cache) || cache.length === 0) {
          throw new Error('实时接口不可用，本地缓存也读取失败');
        }
        models = cache;
        meta = await fetchJSON('data/meta.json').catch(() => null);
        state.live = false;
      }

      // 折扣是我方采样算出来的，实时接口里没有 → 用本地缓存按 id 回填。
      // 注意只回填「基准价/时段/样本数」，系数必须用实时价重算：
      // 否则价格早就变了，徽章还挂着缓存那一刻的折扣，纯误导。
      if (state.live) {
        const cache = await fetchJSON('data/models.json').catch(() => null);
        if (Array.isArray(cache)) {
          const dMap = new Map();
          const opMap = new Map();
          cache.forEach((m) => {
            if (!m) return;
            if (m.discount) dMap.set(m.id, m.discount);
            if (m.off_peak) opMap.set(m.id, m.off_peak);
          });
          models.forEach((m) => {
            const d = dMap.get(m.id);
            const cur = m.price?.in;
            if (d && typeof d.base === 'number' && d.base > 0 && typeof cur === 'number') {
              m.discount = { ...d, ratio: cur / d.base };
            }
            const op = opMap.get(m.id);
            if (op) m.off_peak = op;
          });
        }
      }

      state.models = models;
      state.meta = meta;
      state.rate = Number(meta?.usd_to_cny) || rate;
      state.newModelDays = newDays;
      state.loading = false;

      buildFilterOptions();
      renderStats();
      render();
      renderUpdatedAt();
    } catch (err) {
      state.loading = false;
      state.error = err.message || String(err);
      renderError();
    }
  }

  function renderUpdatedAt() {
    const m = state.meta;
    if (!m) { el.updatedAt.textContent = ''; return; }
    const label = state.live ? '实时同步' : '本地缓存';
    el.updatedAt.innerHTML = `<span class="dot-live"></span>${label} · ${esc(m.updated_at || '—')}`;
  }

  // ---------------- 统计与筛选器 ----------------

  function renderStats() {
    const models = state.models;
    const meta = state.meta || {};
    const withIq = models.filter((m) => typeof m.iq === 'number');
    const bestIq = withIq.length ? Math.max(...withIq.map((m) => m.iq)) : null;
    const bestIqModel = withIq.find((m) => m.iq === bestIq);

    $('#statTotal').textContent = models.length;
    $('#statTotalFoot').innerHTML = `共 <span data-live="vendors">${meta.vendors ?? '—'}</span> 家厂商`;
    $('#statOpen').textContent = models.filter((m) => m.caps?.open_weights).length;
    $('#statOpenFoot').textContent = `占比 ${((models.filter((m) => m.caps?.open_weights).length / models.length) * 100).toFixed(0)}% · 可本地部署`;
    $('#statNew').textContent = meta.recent_new ?? models.filter((m) => m.is_new).length;
    $('#statIq').textContent = bestIq !== null ? bestIq.toFixed(1) : '—';
    $('#statIqFoot').textContent = bestIqModel
      ? `${bestIqModel.vendor_cn} · ${bestIqModel.name.slice(0, 22)}`
      : 'Artificial Analysis';
  }

  function buildFilterOptions() {
    // 类型 chips
    const typeCount = {};
    state.models.forEach((m) => { typeCount[m.type] = (typeCount[m.type] || 0) + 1; });
    const types = Object.entries(typeCount).sort((a, b) => b[1] - a[1]);
    el.typeChips.innerHTML = types.map(([t, c]) => `
      <button class="chip" data-type="${esc(t)}">${esc(t)}<span class="cnt">${c}</span></button>
    `).join('');

    // 能力 chips
    el.capChips.innerHTML = CAPS.map((c) => {
      const n = state.models.filter((m) => m.caps?.[c.key]).length;
      return `<button class="chip" data-cap="${c.key}" title="${esc(c.hint)}">${esc(c.label)}<span class="cnt">${n}</span></button>`;
    }).join('');

    // 折扣 chips：按类型单选取筛。整组无数据时不渲染，避免空筛选项污染工具栏
    const discCount = { any: 0, night: 0, limited: 0, free: 0 };
    const kindSet = new Set();
    state.models.forEach((m) => {
      const kind = discountKindOf(discountOf(m));
      if (!kind) return;
      kindSet.add(kind);
      discCount.any += 1;
      if (kind === 'night' || kind === 'free-night') discCount.night += 1;
      else discCount.limited += 1;
      if (kind.startsWith('free')) discCount.free += 1;
    });
    // 只有一种折扣类型时，「全部折扣」和它完全等价，再摆一个同数字的 chip 只是噪音
    const showAny = kindSet.size > 1;
    const DISC_CHIPS = [
      { k: 'any', label: '全部折扣', hint: '当前价低于平时基准价（近 3 天采样众数）的模型' },
      { k: 'night', label: '夜间折扣', hint: '已识别出固定低谷时段，且此刻正处在低谷时段内' },
      { k: 'limited', label: '限时折扣', hint: '有折扣但不在已识别的低谷时段，多为限时促销或调价' },
      { k: 'free', label: '免费', hint: '当前 0 价，但原先收费' },
    ];
    el.discChips.innerHTML = discCount.any
      ? DISC_CHIPS.filter((c) => discCount[c.k] && (c.k !== 'any' || showAny)).map((c) =>
          `<button class="chip chip-disc${state.discount === c.k ? ' on' : ''}" data-disc="${c.k}" ` +
          `title="${esc(c.hint)}">${c.label}<span class="cnt">${discCount[c.k]}</span></button>`
        ).join('')
      : '';

    // 厂商下拉（按数量降序）
    const vendorCount = {};
    state.models.forEach((m) => {
      const k = m.vendor_cn || m.vendor;
      vendorCount[k] = (vendorCount[k] || 0) + 1;
    });
    const vendors = Object.entries(vendorCount).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    el.vendorSelect.innerHTML = `<option value="">全部厂商（${vendors.length}）</option>` +
      vendors.map(([v, c]) => `<option value="${esc(v)}">${esc(v)} · ${c}</option>`).join('');

    // 恢复 UI 状态
    el.sortSelect.value = state.sort;
    el.currencySelect.value = state.currency;
    $$('#viewSeg button').forEach((b) => b.classList.toggle('on', b.dataset.view === state.view));
  }

  // ---------------- 筛选与排序 ----------------

  function applyFilters() {
    const q = state.q.trim().toLowerCase();
    let arr = state.models.filter((m) => {
      // 关键词
      if (q) {
        const hay = `${m.name} ${m.full_name} ${m.id} ${m.vendor_cn} ${m.vendor_name} ${m.description || ''}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      // 类型
      if (state.types.size && !state.types.has(m.type)) return false;
      // 能力（多选为「且」）
      for (const c of state.caps) {
        if (!m.caps?.[c]) return false;
      }
      // 厂商
      if (state.vendor && (m.vendor_cn || m.vendor) !== state.vendor) return false;
      // 上下文
      if (state.ctx && (m.context || 0) < Number(state.ctx)) return false;
      // 折扣（单选）：any 看有没有折扣，night/limited/free 看具体类型
      if (state.discount) {
        const kind = discountKindOf(discountOf(m));
        if (state.discount === 'any') {
          if (!kind) return false;
        } else if (state.discount === 'free') {
          if (!kind || !kind.startsWith('free')) return false;
        } else if (kind !== state.discount && kind !== `free-${state.discount}`) {
          return false;
        }
      }
      // 价格（统一按人民币阈值比较）
      if (state.price) {
        const pin = toCny(m.price?.in);
        if (state.price === 'free') {
          if (!(pin === 0 || pin === null)) return false;
        } else if (state.price === '20-') {
          if (pin === null || pin < 20) return false;
        } else {
          const [lo, hi] = state.price.split('-').map(Number);
          if (pin === null || pin < lo || pin >= hi) return false;
        }
      }
      return true;
    });

    // 排序
    const s = state.sort;
    const numOr = (v, fallback) => (typeof v === 'number' ? v : fallback);
    arr.sort((a, b) => {
      switch (s) {
        case 'iq':
          return numOr(b.iq, -1) - numOr(a.iq, -1) || numOr(b.created_ts, 0) - numOr(a.created_ts, 0);
        case 'price-asc':
          return numOr(a.price?.in, Infinity) - numOr(b.price?.in, Infinity) || numOr(b.iq, -1) - numOr(a.iq, -1);
        case 'price-desc':
          return numOr(b.price?.in, -1) - numOr(a.price?.in, -1);
        case 'context':
          return numOr(b.context, 0) - numOr(a.context, 0);
        case 'discount':
          // 折扣力度大的排前面（系数越小越便宜），无折扣的沉底
          {
            const ra = discountOf(a)?.ratio;
            const rb = discountOf(b)?.ratio;
            const ka = discountKindOf(discountOf(a)) ? 0 : 1;
            const kb = discountKindOf(discountOf(b)) ? 0 : 1;
            return ka - kb || numOr(ra, 9) - numOr(rb, 9)
                || numOr(a.price?.in, Infinity) - numOr(b.price?.in, Infinity);
          }
        case 'name':
          return a.name.localeCompare(b.name, 'en');
        case 'vendor':
          return (a.vendor_cn || '').localeCompare(b.vendor_cn || '', 'zh') || a.name.localeCompare(b.name, 'en');
        case 'newest':
        default:
          return numOr(b.created_ts, 0) - numOr(a.created_ts, 0) || a.id.localeCompare(b.id);
      }
    });
    return arr;
  }

  // ---------------- 渲染：主流程 ----------------

  function render() {
    if (state.loading || state.error) return;

    const all = applyFilters();

    // 筛选指纹变化（含排序）→ 回到第 1 页；翻页本身不改变指纹
    const sig = JSON.stringify([
      state.q,
      [...state.types].sort().join(','),
      [...state.caps].sort().join(','),
      state.vendor, state.ctx, state.price, state.discount, state.sort,
    ]);
    if (sig !== state._sig) {
      state._sig = sig;
      state.page = 1;
    }

    const totalPages = Math.max(1, Math.ceil(all.length / state.pageSize));
    if (state.page > totalPages) state.page = totalPages;
    if (state.page < 1) state.page = 1;
    const start = (state.page - 1) * state.pageSize;
    const rows = all.slice(start, start + state.pageSize);

    el.resultCount.innerHTML = all.length === state.models.length
      ? `共 <strong>${all.length}</strong> 个模型`
      : `筛选出 <strong>${all.length}</strong> / ${state.models.length} 个模型`;

    renderActiveFilters();

    if (all.length === 0) {
      el.tableWrap.style.display = 'none';
      el.cardView.style.display = 'none';
      el.pager.innerHTML = '';
      renderEmpty();
    } else {
      el.emptyState.innerHTML = '';
      if (state.view === 'table') {
        el.tableWrap.style.display = '';
        el.cardView.style.display = 'none';
        renderTable(rows);
      } else {
        el.tableWrap.style.display = 'none';
        el.cardView.style.display = '';
        renderCards(rows);
      }
      renderPager(all.length, totalPages);
    }
    updateCompareBar();
    $$('#viewSeg button').forEach((b) => b.classList.toggle('on', b.dataset.view === state.view));
    const hint = $('#compareHint');
    if (hint) hint.textContent = state.view === 'table' ? '勾选左侧方框可加入对比' : '点击卡片查看详情';
  }

  // ---------------- 分页 ----------------

  function renderPager(total, totalPages) {
    if (totalPages <= 1) { el.pager.innerHTML = ''; return; }

    const p = state.page;
    const from = (p - 1) * state.pageSize + 1;
    const to = Math.min(p * state.pageSize, total);

    // 页码序列：首尾固定 + 当前页左右各一页，中间用省略号
    const wanted = new Set([1, totalPages]);
    for (let i = p - 1; i <= p + 1; i++) {
      if (i > 1 && i < totalPages) wanted.add(i);
    }
    const pages = [...wanted].sort((a, b) => a - b);

    let nav = '';
    let prev = 0;
    for (const n of pages) {
      if (prev && n - prev > 1) nav += '<span class="pager-gap">…</span>';
      nav += `<button class="pager-btn ${n === p ? 'on' : ''}" data-page="${n}">${n}</button>`;
      prev = n;
    }

    el.pager.innerHTML = `
      <span class="pager-info">第 <strong>${from}</strong>–<strong>${to}</strong> 条，共 <strong>${total}</strong> 条</span>
      <button class="pager-btn" data-page="${p - 1}" ${p === 1 ? 'disabled' : ''} title="上一页" aria-label="上一页">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m15 18-6-6 6-6"/></svg>
      </button>
      ${nav}
      <button class="pager-btn" data-page="${p + 1}" ${p === totalPages ? 'disabled' : ''} title="下一页" aria-label="下一页">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="m9 18 6-6-6-6"/></svg>
      </button>
      <select class="pager-size" id="pageSizeSel" aria-label="每页条数">
        ${[25, 50, 100].map((n) => `<option value="${n}" ${n === state.pageSize ? 'selected' : ''}>${n} 条/页</option>`).join('')}
      </select>`;
  }

  function goPage(n) {
    const totalPages = Math.max(1, Math.ceil(applyFilters().length / state.pageSize));
    const target = Math.min(Math.max(1, n), totalPages);
    if (target === state.page) return;
    state.page = target;
    render();
    // 翻页后回到列表顶部，避开吸顶的顶栏与工具条
    const anchor = el.tableWrap.getBoundingClientRect().top + window.scrollY - 118;
    window.scrollTo({ top: Math.max(0, anchor), behavior: 'smooth' });
  }

  function renderActiveFilters() {
    const tags = [];
    if (state.q.trim()) tags.push({ k: 'q', label: `搜索：${state.q.trim()}` });
    state.types.forEach((t) => tags.push({ k: 'type', v: t, label: `类型：${t}` }));
    state.caps.forEach((c) => {
      const meta = CAPS.find((x) => x.key === c);
      tags.push({ k: 'cap', v: c, label: `能力：${meta?.label || c}` });
    });
    if (state.discount) {
      const map = { any: '有折扣', night: '夜间折扣', limited: '限时折扣', free: '免费' };
      tags.push({ k: 'discount', label: `折扣：${map[state.discount] || state.discount}` });
    }
    if (state.vendor) tags.push({ k: 'vendor', label: `厂商：${state.vendor}` });
    if (state.ctx) tags.push({ k: 'ctx', label: `上下文 ≥ ${fmtCtx(Number(state.ctx)).v}${fmtCtx(Number(state.ctx)).u}` });
    if (state.price) {
      const map = { free: '免费', '0-1': '输入 < ¥1', '1-5': '¥1–5', '5-20': '¥5–20', '20-': '¥20 以上' };
      tags.push({ k: 'price', label: `价格：${map[state.price] || state.price}` });
    }

    if (!tags.length) { el.activeFilters.innerHTML = ''; return; }

    el.activeFilters.innerHTML = `<span class="af-label">已选条件</span>` +
      tags.map((t) => `<span class="af-tag">${esc(t.label)}<button data-remove="${t.k}" data-val="${esc(t.v || '')}" title="移除">×</button></span>`).join('') +
      `<button class="af-clear" id="clearFilters">全部清除</button>`;
  }

  function modIcons(mods, kind = 'in') {
    const order = kind === 'in' ? ['text', 'image', 'audio', 'video', 'file'] : ['text', 'image', 'audio', 'video'];
    const set = new Set(mods || []);
    return order.map((k) => {
      const on = set.has(k);
      if (!on && k !== 'text') return '';
      const cls = k === 'audio' ? 'audio' : k === 'video' ? 'video' : k === 'file' ? 'file' : '';
      return `<span class="mod-ico ${on ? 'on ' + cls : ''}" title="${kind === 'in' ? '输入' : '输出'}：${MOD_LABEL[k] || k}${on ? ' ✓' : ' ✕'}">${MOD_ICON[k]}</span>`;
    }).join('');
  }

  function capTags(m) {
    const list = [];
    if (m.caps?.reasoning) list.push(['推理', '']);
    if (m.caps?.tools) list.push(['工具', '']);
    if (m.caps?.json) list.push(['JSON', '']);
    if (m.caps?.open_weights) list.push(['开源', 'green']);
    return list.slice(0, 4).map(([t, cls]) => `<span class="cap on ${cls}">${t}</span>`).join('') ||
      '<span class="cap">—</span>';
  }

  function iqCell(m) {
    if (typeof m.iq !== 'number') return '<span class="iq-none">—</span>';
    const pct = Math.max(4, Math.min(100, (m.iq / 60) * 100));
    const cls = m.iq >= 50 ? 'hi' : 'mid';
    return `<div class="iq-cell" title="Artificial Analysis 智力指数 ${m.iq}">
      <span class="iq-val ${cls}">${m.iq.toFixed(1)}</span>
      <span class="iq-bar"><i style="width:${pct}%"></i></span>
    </div>`;
  }

  function priceCell(m) {
    const pin = m.price?.in;
    const pout = m.price?.out;
    const note = discountPriceNote(m);
    if (pin === null && pout === null) return '<div class="price-cell"><span class="num muted">暂无定价</span></div>';
    // 原本收费、现在 0 价 —— 这是「限时免费/夜间免费」，得把原价划出来
    if (pin === 0 && pout === 0) {
      return `<div class="price-cell"><span class="price-free">免费</span>${note}</div>`;
    }
    const a = priceStr(pin);
    const b = priceStr(pout);
    return `<div class="price-cell">
      <span class="price-main">${a || '—'} ${note} <span class="price-io">/ ${b || '—'}</span></span>
      <span class="price-sub">输入 / 输出 每 1M tokens</span>
    </div>`;
  }

  function isNewBadge(m) {
    if (typeof m.age_days === 'number' && m.age_days <= 7) return '<span class="badge-new">NEW</span>';
    return '';
  }

  function aliasBadge(m) {
    return m.vendor_alias ? '<span class="badge-alias" title="浮动别名路由，自动指向最新版本">路由</span>' : '';
  }

  function freeBadge(m) {
    return (m.price?.in === 0 && m.price?.out === 0) ? '<span class="badge-free">FREE</span>' : '';
  }

  // ---------------- 折扣 ----------------
  // 两个数据来源，合成一个「折扣」概念对外展示：
  //   m.discount  实时系数 = 当前价 / 基准价（基准价 = 采样众数，即「平时那个价」）
  //   m.off_peak  采样识别出的周期性错峰规律（低谷时段、置信度）
  // 有 off_hours 且当前小时落在里面 → 叫「夜间折扣」，否则叫「限时折扣」。
  // 这样既能标出「现在便宜多少」，也能标出「几点会更便宜」。

  const DISCOUNT_SHOW = 0.95;   // 低于基准价 5% 以上才显示徽章，之内视为持平

  function fmtRatio(r) {
    if (typeof r !== 'number' || !isFinite(r)) return '—';
    // 0.302 -> "0.30x"，0.0453/0.15=0.302；整数不带小数尾巴
    const s = r >= 0.995 ? '1.00' : r.toFixed(2);
    return `${s}x`;
  }

  function discountLabel(d) {
    // 0.5 -> "5 折"，0.85 -> "8.5 折"
    if (typeof d !== 'number' || d <= 0 || d >= 1) return '';
    const zhe = (d * 10).toFixed(1).replace(/\.0$/, '');
    return `${zhe} 折`;
  }

  function hoursLabel(hours) {
    if (!hours?.length) return '';
    const sorted = [...hours].sort((a, b) => a - b);
    return sorted.map((h) => `${String(h).padStart(2, '0')}:00`).join(' / ');
  }

  /** 取统一的折扣视图；没有折扣返回 null。 */
  function discountOf(m) {
    const cur = m.price?.in;
    if (typeof cur !== 'number') return null;

    if (m.discount) {
      const d = m.discount;
      return {
        ratio: typeof d.ratio === 'number' ? d.ratio : cur / (d.base || 1),
        base: d.base,
        baseOut: d.base_out,
        ratioOut: d.ratio_out,
        offHours: d.off_hours || [],
        samples: d.samples,
        peak: m.off_peak || null,
      };
    }
    // 兼容只有 off_peak 的旧数据：用当前价对高峰价现算系数，
    // 这样当前价已经回到原价时不会误显示折扣。
    const op = m.off_peak;
    if (op && typeof op.high === 'number' && op.high > 0) {
      return {
        ratio: cur / op.high,
        base: op.high,
        baseOut: null,
        ratioOut: null,
        offHours: op.off_hours || [],
        samples: op.samples,
        peak: op,
      };
    }
    return null;
  }

  /** 折扣类型 → 文案与样式键。 */
  function discountKindOf(d) {
    if (!d) return null;
    const hour = new Date().getHours();
    const offNow = Array.isArray(d.offHours) && d.offHours.includes(hour);
    if (d.ratio <= 0.001) return offNow ? 'free-night' : 'free-limited';
    if (d.ratio <= DISCOUNT_SHOW) return offNow ? 'night' : 'limited';
    return null;
  }

  const KIND_TEXT = {
    'night': '夜间折扣',
    'limited': '限时折扣',
    'free-night': '夜间免费',
    'free-limited': '限时免费',
  };

  function discountBadge(m) {
    const d = discountOf(m);
    const kind = discountKindOf(d);
    if (!kind) return '';
    const text = KIND_TEXT[kind];
    const parts = [
      `${text} ${fmtRatio(d.ratio)}`,
      d.base ? `基准价 ${priceStr(d.base) || '—'}` : '',
      d.offHours?.length ? `低谷时段 ${hoursLabel(d.offHours)}` : '',
      typeof d.samples === 'number' ? `${d.samples} 次采样` : '',
      d.peak?.confidence === 'low' ? '样本偏少，规律待确认' : '',
    ].filter(Boolean);
    return `<span class="badge-disc disc-${kind}" title="${esc(parts.join('｜'))}">` +
      `${text}<b>${fmtRatio(d.ratio)}</b></span>`;
  }

  /** 价格列里附加的折扣注记：原价划线 + 系数。 */
  function discountPriceNote(m) {
    const d = discountOf(m);
    const kind = discountKindOf(d);
    if (!kind) return '';
    if (d.ratio <= 0.001) {
      return `<span class="price-strike">${priceStr(d.base) || '—'}</span>`;
    }
    return `<span class="price-disc-note">原价 ${priceStr(d.base) || '—'}</span>`;
  }

  /** 详情抽屉里的折扣区块。 */
  function discountSectionHtml(m) {
    const d = discountOf(m);
    const peak = m.off_peak;
    if (!d && !peak) return '';

    const kind = discountKindOf(d);
    const head = d
      ? `${fmtRatio(d.ratio)}${kind ? ' · ' + KIND_TEXT[kind] : ' · 当前即基准价'}`
      : (discountLabel(peak.discount) || '有折扣');

    const detail = [];
    if (d) {
      detail.push(`基准价 ${priceStr(d.base) || '—'} → 当前 ${priceStr(m.price?.in) || '—'}` +
        (d.ratioOut != null ? `（输出价 ${fmtRatio(d.ratioOut)}）` : ''));
      detail.push('基准价取近 3 天采样的众数，即「平时那个价」');
    }
    if (peak?.off_hours?.length) detail.push(`低谷时段：${hoursLabel(peak.off_hours)}（按每日采样推断）`);
    if (peak?.on_hours?.length) detail.push(`原价时段：${hoursLabel(peak.on_hours)}`);
    const n = d?.samples ?? peak?.samples;
    if (typeof n === 'number') {
      detail.push(`依据：${n} 次价格采样${peak?.days ? ` / ${peak.days} 天` : ''}`);
    }
    if (peak?.confidence === 'low') detail.push('样本不足 2 天，时段规律待确认');

    return `<div class="section">
      <div class="section-title">折扣</div>
      <div class="offpeak-panel">
        <div class="offpeak-main"><span class="offpeak-zhe">${head}</span></div>
        <div class="offpeak-meta">${detail.join('<br>')}</div>
      </div>
    </div>`;
  }

  /**
   * 厂商图标：有映射就用工具集已抓好的 favicon，没有就退回原来的色点。
   * 色点预先叠在图标底下（.has-img 时隐藏），图片加载失败就去掉这个类让它露出来，
   * 所以无论图标在不在，这一格都不会出现破图或空白。
   */
  function vendorIcon(m) {
    const ico = state.vendorIcons?.[m.vendor];
    const color = esc(m.vendor_color || '#999');
    if (!ico) return `<span class="vendor-dot" style="background:${color}"></span>`;
    const dark = ico.t === 'light' ? ' on-dark' : '';
    return `<span class="vendor-ico has-img${dark}" style="--c:${color}">`
      + `<span class="vendor-dot" style="background:${color}"></span>`
      + `<img src="assets/icons/${esc(ico.f)}" alt="" width="16" height="16"`
      + ` loading="lazy" decoding="async" referrerpolicy="no-referrer"`
      + ` onerror="this.parentNode.classList.remove('has-img');this.remove()">`
      + `</span>`;
  }

  function renderTable(rows) {
    const frag = [];
    for (const m of rows) {
      const ctx = fmtCtx(m.context);
      const out = fmtCtx(m.max_output);
      const sel = state.selected.has(m.id);
      frag.push(`<tr data-id="${esc(m.id)}" class="${sel ? 'selected' : ''}">
        <td class="col-check"><input type="checkbox" data-check="${esc(m.id)}" ${sel ? 'checked' : ''}></td>
        <td class="col-model">
          <div class="model-cell">
            <span class="model-name">${esc(m.name)}${isNewBadge(m)}${aliasBadge(m)}${freeBadge(m)}${discountBadge(m)}</span>
            <span class="model-id" title="${esc(m.id)}">${esc(m.id)}</span>
          </div>
        </td>
        <td>
          <div class="vendor-cell">
            ${vendorIcon(m)}
            <span class="vendor-name">${esc(m.vendor_cn || m.vendor)}</span>
          </div>
        </td>
        <td class="hide-xs"><span class="type-tag t-${esc(m.type)}">${esc(m.type)}</span></td>
        <td class="hide-sm"><span class="num ${m.context ? '' : 'muted'}">${ctx.v}<span class="unit">${ctx.u}</span></span></td>
        <td class="hide-md"><span class="num ${m.max_output ? '' : 'muted'}">${out.v}<span class="unit">${out.u}</span></span></td>
        <td class="hide-sm"><div class="mods">${modIcons(m.input_modalities, 'in')}</div></td>
        <td class="hide-md"><div class="mods">${modIcons(m.output_modalities, 'out')}</div></td>
        <td class="hide-sm"><div class="cap-row">${capTags(m)}</div></td>
        <td>${iqCell(m)}</td>
        <td>${priceCell(m)}</td>
        <td class="hide-xs"><span class="date-cell">${esc(m.created || '—')}<span class="rel">${relDays(m.age_days)}</span></span></td>
      </tr>`);
    }
    el.tbody.innerHTML = frag.join('');
  }

  function relDays(d) {
    if (typeof d !== 'number' || d < 0) return '';
    if (d === 0) return '今天';
    if (d === 1) return '昨天';
    if (d < 30) return `${d} 天前`;
    if (d < 365) return `${Math.floor(d / 30)} 个月前`;
    return `${(d / 365).toFixed(1)} 年前`;
  }

  function renderCards(rows) {
    el.cardView.innerHTML = rows.map((m) => {
      const sel = state.selected.has(m.id);
      const ctx = fmtCtx(m.context);
      return `<div class="card ${sel ? 'selected' : ''}" data-id="${esc(m.id)}">
        <div class="card-head">
          <div style="flex:1;min-width:0">
            <div class="card-title">${esc(m.name)}</div>
            <div class="card-id">${esc(m.id)}</div>
          </div>
          ${isNewBadge(m)}${freeBadge(m)}${discountBadge(m)}
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span class="vendor-cell">${vendorIcon(m)}<span class="vendor-name">${esc(m.vendor_cn || m.vendor)}</span></span>
          <span class="type-tag t-${esc(m.type)}">${esc(m.type)}</span>
          ${aliasBadge(m)}
        </div>
        <div class="card-desc">${esc((m.description || '暂无描述').slice(0, 150))}</div>
        <div class="card-metrics">
          <div class="card-metric">
            <span class="card-metric-label">上下文</span>
            <span class="card-metric-value">${ctx.v}${ctx.u}</span>
          </div>
          <div class="card-metric">
            <span class="card-metric-label">智力</span>
            <span class="card-metric-value">${typeof m.iq === 'number' ? m.iq.toFixed(1) : '—'}</span>
          </div>
          <div class="card-metric">
            <span class="card-metric-label">输入 / 输出</span>
            <span class="card-metric-value" style="font-size:11.5px">${
              m.price?.in === 0 && m.price?.out === 0 ? '免费'
                : `${priceStr(m.price?.in) || '—'}${discountPriceNote(m)}<span style="color:var(--text-3);font-weight:400"> / </span>${priceStr(m.price?.out) || '—'}`
            }</span>
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;justify-content:space-between">
          <div class="mods">${modIcons(m.input_modalities, 'in')}</div>
          <span style="font-size:10.5px;color:var(--text-3)">${esc(m.created || '')}</span>
        </div>
      </div>`;
    }).join('');
  }

  function renderEmpty() {
    const hasFilter = state.q || state.types.size || state.caps.size || state.vendor || state.ctx || state.price || state.discount;
    el.emptyState.innerHTML = `<div class="table-wrap"><div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/></svg>
      <h3>没有匹配的模型</h3>
      <p>${hasFilter ? '当前筛选条件下没有结果，试试放宽条件。' : '数据为空，请先运行抓取脚本。'}</p>
      ${hasFilter ? '<button class="btn-primary" id="resetEmpty" style="margin:0 auto">清除所有筛选</button>' : ''}
    </div></div>`;
    const btn = $('#resetEmpty');
    if (btn) btn.onclick = clearAllFilters;
  }

  function renderError() {
    el.tableWrap.style.display = 'none';
    el.cardView.style.display = 'none';
    el.resultCount.textContent = '';
    el.emptyState.innerHTML = `<div class="table-wrap"><div class="empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="#d63b3b" stroke-width="1.6"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/></svg>
      <h3>数据加载失败</h3>
      <p style="font-family:var(--mono);font-size:12px;color:var(--text-3)">${esc(state.error)}</p>
      <p style="font-size:12.5px">实时接口与本地缓存均不可用。检查网络连通性，或运行 <code style="font-family:var(--mono);background:var(--panel-2);padding:1px 5px;border-radius:4px">python3 scripts/fetch_models.py</code> 生成缓存后再试。</p>
      <button class="btn-primary" id="retryBtn" style="margin:0 auto">重新加载</button>
    </div></div>`;
    const b = $('#retryBtn');
    if (b) b.onclick = loadData;
  }

  function renderSkeleton() {
    el.emptyState.innerHTML = '';
    el.tableWrap.style.display = '';
    el.cardView.style.display = 'none';
    el.resultCount.textContent = '加载中…';
  }

  // ---------------- 交互：筛选 ----------------

  function clearAllFilters() {
    state.q = '';
    state.types.clear();
    state.caps.clear();
    state.vendor = '';
    state.ctx = '';
    state.price = '';
    state.discount = '';
    el.search.value = '';
    el.vendorSelect.value = '';
    el.ctxSelect.value = '';
    el.priceSelect.value = '';
    $$('#typeChips .chip').forEach((c) => c.classList.remove('on'));
    $$('#capChips .chip').forEach((c) => c.classList.remove('on'));
    $$('#discChips .chip').forEach((c) => c.classList.remove('on'));
    syncFilterSelectState();
    render();
  }

  function syncFilterSelectState() {
    el.vendorSelect.classList.toggle('active', !!state.vendor);
    el.ctxSelect.classList.toggle('active', !!state.ctx);
    el.priceSelect.classList.toggle('active', !!state.price);
  }

  // ---------------- 交互：详情抽屉 ----------------

  function openDrawer(id) {
    const m = state.models.find((x) => x.id === id);
    if (!m) return;
    state.drawerId = id;

    el.drawerHead.innerHTML = `
      <button class="drawer-close" id="drawerClose">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>
      </button>
      <div class="drawer-vendor">
        ${vendorIcon(m)}
        <span style="font-size:12.5px;color:var(--text-2);font-weight:550">${esc(m.vendor_cn || m.vendor)}</span>
        <span class="type-tag t-${esc(m.type)}">${esc(m.type)}</span>
        ${isNewBadge(m)}${freeBadge(m)}${aliasBadge(m)}
      </div>
      <div class="drawer-title">${esc(m.name)}</div>
      <div class="drawer-id">
        <span>${esc(m.id)}</span>
        <button class="copy-btn" data-copy="${esc(m.id)}" title="复制模型 ID">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>
        </button>
      </div>`;

    const kv = [];
    kv.push(['上下文窗口', m.context ? `${fmtCtx(m.context).v}${fmtCtx(m.context).u} <small>tokens</small>` : '—']);
    kv.push(['最大输出', m.max_output ? `${fmtCtx(m.max_output).v}${fmtCtx(m.max_output).u} <small>tokens</small>` : '—']);
    kv.push(['智力指数', typeof m.iq === 'number' ? m.iq.toFixed(1) : '—']);
    kv.push(['编码指数', typeof m.iq_coding === 'number' ? m.iq_coding.toFixed(1) : '—']);
    kv.push(['发布日期', m.created || '—']);
    kv.push(['距今', relDays(m.age_days) || '—']);
    kv.push(['知识截止', m.knowledge_cutoff || '—']);
    kv.push(['开放权重', m.caps?.open_weights ? '是' : '否']);
    kv.push(['输入模态', (m.input_modalities || []).map((x) => MOD_LABEL[x] || x).join(' / ') || '—']);
    kv.push(['输出模态', (m.output_modalities || []).map((x) => MOD_LABEL[x] || x).join(' / ') || '—']);

    const isFree = m.price?.in === 0 && m.price?.out === 0;
    const priceRows = isFree
      ? [['输入 (prompt)', 0], ['输出 (completion)', 0]]
      : [
        ['输入 (prompt)', m.price?.in],
        ['输出 (completion)', m.price?.out],
        ['缓存读取', m.price?.cache_read],
        ['缓存写入', m.price?.cache_write],
        ['图片生成', m.price?.image],
        ['音频输入', m.price?.audio],
        ['联网搜索', m.price?.web_search],
      ].filter(([, v]) => v !== null && v !== undefined && v !== 0);

    const capsHtml = CAPS.map((c) => {
      const on = !!m.caps?.[c.key];
      return `<span class="cap-pill ${on ? 'on' : ''}" title="${esc(c.hint)}">${esc(c.label)}</span>`;
    }).join('');

    const arenaHtml = (m.arena || []).length
      ? `<div class="section">
          <div class="section-title">Design Arena 竞技场</div>
          <div class="arena-list">${m.arena.map((a) => `
            <div class="arena-item">
              <span class="arena-cat">${esc(a.category || '—')}</span>
              <span class="arena-elo">${a.elo ?? '—'}</span>
              <span class="arena-rank">${a.rank ? '#' + a.rank : ''}</span>
            </div>`).join('')}</div>
        </div>`
      : '';

    el.drawerBody.innerHTML = `
      <div class="section">
        <div class="section-title">核心指标</div>
        <div class="kv-grid">
          ${kv.map(([k, v]) => `<div class="kv"><span class="kv-label">${esc(k)}</span><span class="kv-value">${v}</span></div>`).join('')}
        </div>
      </div>

      ${priceRows.length ? `<div class="section">
        <div class="section-title">定价（每 100 万 tokens，${state.currency === 'CNY' ? '人民币' : '美元'}）</div>
        <table class="price-table">
          ${priceRows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v === 0 ? '免费' : (priceStr(v) || '—')}</td></tr>`).join('')}
        </table>
        <div style="font-size:10.5px;color:var(--text-3);margin-top:6px">
          汇率 ${state.rate} ${state.currency === 'CNY' ? '（美元 → 人民币）' : ''}，仅供参考，以厂商账单为准
        </div>
      </div>` : ''}

      ${discountSectionHtml(m)}

      <div class="section">
        <div class="section-title">能力支持</div>
        <div class="cap-grid">${capsHtml}</div>
      </div>

      ${arenaHtml}

      ${m.description ? `<div class="section">
        <div class="section-title">模型简介</div>
        <div class="desc-text">${esc(m.description)}</div>
      </div>` : ''}

      ${(m.supported_parameters || []).length ? `<div class="section">
        <div class="section-title">支持的请求参数（${m.supported_parameters.length}）</div>
        <div class="param-tags">${m.supported_parameters.map((p) => `<span class="param-tag">${esc(p)}</span>`).join('')}</div>
      </div>` : ''}

      <div class="section">
        <div class="section-title">数据源</div>
        <div style="font-size:11.5px;color:var(--text-3);line-height:1.6">
          模型标识 <code style="font-family:var(--mono)">${esc(m.canonical_slug || m.id)}</code>
          ${m.hf_id ? `<br>Hugging Face <code style="font-family:var(--mono)">${esc(m.hf_id)}</code>` : ''}
          ${m.moderated ? '<br>该模型输出经过内容审核' : ''}
        </div>
      </div>`;

    const isSel = state.selected.has(m.id);
    el.drawerFoot.innerHTML = `
      <button class="btn-ghost" style="flex:1;justify-content:center;height:34px" data-toggle-compare="${esc(m.id)}">
        ${isSel ? '移出对比' : '加入对比'}
      </button>
      <a class="btn-primary" style="flex:1;justify-content:center;height:34px;display:inline-flex;align-items:center;gap:6px"
         href="https://openrouter.ai/${esc(m.id)}" target="_blank" rel="noopener">
        查看上游
        <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M7 17 17 7M9 7h8v8"/></svg>
      </a>`;

    el.drawer.classList.add('show');
    el.drawer.setAttribute('aria-hidden', 'false');
    el.overlay.classList.add('show');
    document.body.classList.add('locked');
    el.drawerBody.scrollTop = 0;
  }

  function closeDrawer() {
    state.drawerId = null;
    el.drawer.classList.remove('show');
    el.drawer.setAttribute('aria-hidden', 'true');
    el.overlay.classList.remove('show');
    document.body.classList.remove('locked');
  }

  // ---------------- 交互：对比 ----------------

  function toggleCompare(id) {
    if (state.selected.has(id)) {
      state.selected.delete(id);
    } else {
      if (state.selected.size >= MAX_COMPARE) {
        toast(`最多同时对比 ${MAX_COMPARE} 个模型`, 'warn');
        return;
      }
      state.selected.add(id);
    }
    syncSelectionUI();
  }

  /** 只更新选择相关 DOM，避免整表重绘丢失滚动位置 */
  function syncSelectionUI() {
    $$('tr[data-id]').forEach((tr) => {
      const on = state.selected.has(tr.dataset.id);
      tr.classList.toggle('selected', on);
      const cb = tr.querySelector('input[data-check]');
      if (cb) cb.checked = on;
    });
    $$('.card[data-id]').forEach((c) => c.classList.toggle('selected', state.selected.has(c.dataset.id)));
    updateCompareBar();
    // 抽屉底部按钮状态
    if (state.drawerId) {
      const btn = el.drawerFoot.querySelector('[data-toggle-compare]');
      if (btn) btn.textContent = state.selected.has(state.drawerId) ? '移出对比' : '加入对比';
    }
    if (state.selected.size === 0) el.checkAll.checked = false;
  }

  function updateCompareBar() {
    const n = state.selected.size;
    el.compareBar.classList.toggle('show', n > 0);
    el.compareText.textContent = `已选 ${n} 个模型`;
    el.compareThumbs.innerHTML = Array.from(state.selected).map((id) => {
      const m = state.models.find((x) => x.id === id);
      const initial = (m?.vendor_cn || m?.vendor || '?').slice(0, 1);
      return `<span class="compare-thumb" style="background:${esc(m?.vendor_color || '#555')}" title="${esc(m?.name || id)}">${esc(initial)}</span>`;
    }).join('');
  }

  function openCompareModal() {
    const list = Array.from(state.selected).map((id) => state.models.find((m) => m.id === id)).filter(Boolean);
    if (list.length < 2) { toast('至少选择 2 个模型才能对比', 'warn'); return; }

    const rows = [
      { label: '厂商', get: (m) => esc(m.vendor_cn || m.vendor) },
      { label: '类型', get: (m) => esc(m.type) },
      { label: '上下文', get: (m) => `${fmtCtx(m.context).v}${fmtCtx(m.context).u}`, raw: (m) => m.context || 0, better: 'max' },
      { label: '最大输出', get: (m) => `${fmtCtx(m.max_output).v}${fmtCtx(m.max_output).u}`, raw: (m) => m.max_output || 0, better: 'max' },
      { label: '智力指数', get: (m) => (typeof m.iq === 'number' ? m.iq.toFixed(1) : '—'), raw: (m) => m.iq ?? -1, better: 'max' },
      { label: '编码指数', get: (m) => (typeof m.iq_coding === 'number' ? m.iq_coding.toFixed(1) : '—'), raw: (m) => m.iq_coding ?? -1, better: 'max' },
      { label: '输入价格', get: (m) => priceStr(m.price?.in) || '—', raw: (m) => (m.price?.in === null ? Infinity : m.price?.in), better: 'min', hint: '每 100 万 tokens' },
      { label: '输出价格', get: (m) => priceStr(m.price?.out) || '—', raw: (m) => (m.price?.out === null ? Infinity : m.price?.out), better: 'min', hint: '每 100 万 tokens' },
      { label: '推理', get: (m) => (m.caps?.reasoning ? '✓' : '—') },
      { label: '工具调用', get: (m) => (m.caps?.tools ? '✓' : '—') },
      { label: '结构化输出', get: (m) => (m.caps?.json ? '✓' : '—') },
      { label: '视觉输入', get: (m) => (m.caps?.vision ? '✓' : '—') },
      { label: '音频输入', get: (m) => (m.caps?.audio_in ? '✓' : '—') },
      { label: '视频输入', get: (m) => (m.caps?.video_in ? '✓' : '—') },
      { label: '开放权重', get: (m) => (m.caps?.open_weights ? '✓' : '—') },
      { label: '发布日期', get: (m) => esc(m.created || '—') },
    ];

    const head = list.map((m) => `
      <th style="min-width:150px">
        <div class="cmp-head-inner">
          ${vendorIcon(m)}
          <div>
            <div style="font-size:12.5px;font-weight:650;color:var(--text);text-transform:none;letter-spacing:0">${esc(m.name)}</div>
            <div style="font-family:var(--mono);font-size:9.5px;color:var(--text-3);font-weight:400;text-transform:none;letter-spacing:0">${esc(m.id)}</div>
          </div>
        </div>
      </th>`).join('');

    const body = rows.map((r) => {
      let bestIdx = -1;
      if (r.better && r.raw) {
        const vals = list.map(r.raw);
        const target = r.better === 'max' ? Math.max(...vals) : Math.min(...vals);
        if (isFinite(target) && vals.filter((v) => v === target).length === 1) {
          bestIdx = vals.indexOf(target);
        }
      }
      const cells = list.map((m, i) => `<td class="${i === bestIdx ? 'best' : ''}">${r.get(m)}</td>`).join('');
      return `<tr><th>${esc(r.label)}${r.hint ? `<div style="font-size:9px;opacity:.7;font-weight:400">${esc(r.hint)}</div>` : ''}</th>${cells}</tr>`;
    }).join('');

    el.compareBody.innerHTML = `<table><thead><tr><th></th>${head}</tr></thead><tbody>${body}</tbody></table>`;
    el.compareModal.classList.add('show');
    el.compareBar.classList.remove('show');   // 弹窗盖住浮条，别让两套 UI 打架
    document.body.classList.add('locked');
  }

  function closeCompareModal() {
    el.compareModal.classList.remove('show');
    updateCompareBar();                        // 恢复底部浮条显示
    if (!el.drawer.classList.contains('show')) document.body.classList.remove('locked');
  }

  // ---------------- 事件绑定 ----------------

  function bindEvents() {
    // 搜索
    const onSearch = debounce(() => { state.q = el.search.value; render(); }, 130);
    el.search.addEventListener('input', onSearch);
    el.search.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { el.search.value = ''; state.q = ''; render(); el.search.blur(); }
    });

    // 类型 chips
    el.typeChips.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-type]');
      if (!btn) return;
      const t = btn.dataset.type;
      if (state.types.has(t)) state.types.delete(t); else state.types.add(t);
      btn.classList.toggle('on', state.types.has(t));
      render();
    });

    // 能力 chips
    el.capChips.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cap]');
      if (!btn) return;
      const c = btn.dataset.cap;
      if (state.caps.has(c)) state.caps.delete(c); else state.caps.add(c);
      btn.classList.toggle('on', state.caps.has(c));
      render();
    });

    // 折扣 chips：单选，再点一次同一个即取消
    el.discChips.addEventListener('click', (e) => {
      const btn = e.target.closest('.chip[data-disc]');
      if (!btn) return;
      const k = btn.dataset.disc;
      state.discount = state.discount === k ? '' : k;
      $$('#discChips .chip').forEach((c) => c.classList.toggle('on', c.dataset.disc === state.discount));
      render();
    });

    // 下拉筛选
    el.vendorSelect.addEventListener('change', () => {
      state.vendor = el.vendorSelect.value;
      syncFilterSelectState();
      render();
    });
    el.ctxSelect.addEventListener('change', () => {
      state.ctx = el.ctxSelect.value;
      syncFilterSelectState();
      render();
    });
    el.priceSelect.addEventListener('change', () => {
      state.price = el.priceSelect.value;
      syncFilterSelectState();
      render();
    });
    el.currencySelect.addEventListener('change', () => {
      state.currency = el.currencySelect.value;
      savePrefs();
      render();
      if (state.drawerId) openDrawer(state.drawerId);
    });

    // 排序
    el.sortSelect.addEventListener('change', () => {
      state.sort = el.sortSelect.value;
      savePrefs();
      render();
      syncSortHeaders();
    });

    // 视图切换
    el.viewSeg.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-view]');
      if (!btn) return;
      state.view = btn.dataset.view;
      savePrefs();
      render();
    });

    // 表头排序（点击表头联动下拉）
    $$('table.models thead th.sortable').forEach((th) => {
      th.addEventListener('click', () => {
        const s = th.dataset.sort;
        state.sort = (state.sort === s && (s === 'iq' || s === 'context' || s === 'newest')) ? s : s;
        el.sortSelect.value = state.sort;
        render();
        syncSortHeaders();
      });
    });

    // 行点击 → 详情
    el.tbody.addEventListener('click', (e) => {
      const cb = e.target.closest('input[data-check]');
      if (cb) {
        e.stopPropagation();
        toggleCompare(cb.dataset.check);
        return;
      }
      const tr = e.target.closest('tr[data-id]');
      if (tr) openDrawer(tr.dataset.id);
    });

    // 卡片点击
    el.cardView.addEventListener('click', (e) => {
      const card = e.target.closest('.card[data-id]');
      if (card) openDrawer(card.dataset.id);
    });

    // 全选（对比上限 4）
    el.checkAll.addEventListener('click', (e) => {
      e.stopPropagation();
      const rows = applyFilters();
      if (state.selected.size > 0) {
        state.selected.clear();
        el.checkAll.checked = false;
      } else {
        rows.slice(0, MAX_COMPARE).forEach((m) => state.selected.add(m.id));
        if (rows.length > MAX_COMPARE) toast(`对比上限 ${MAX_COMPARE} 个，已选前 ${MAX_COMPARE} 个`, 'warn');
      }
      syncSelectionUI();
    });

    // 移除单个筛选条件
    el.activeFilters.addEventListener('click', (e) => {
      if (e.target.id === 'clearFilters') { clearAllFilters(); return; }
      const btn = e.target.closest('[data-remove]');
      if (!btn) return;
      const k = btn.dataset.remove;
      const v = btn.dataset.val;
      if (k === 'q') { state.q = ''; el.search.value = ''; }
      if (k === 'type') {
        state.types.delete(v);
        $$('#typeChips .chip').forEach((c) => {
          if (c.dataset.type === v) c.classList.remove('on');
        });
      }
      if (k === 'cap') {
        state.caps.delete(v);
        $$('#capChips .chip').forEach((c) => {
          if (c.dataset.cap === v) c.classList.remove('on');
        });
      }
      if (k === 'vendor') { state.vendor = ''; el.vendorSelect.value = ''; }
      if (k === 'ctx') { state.ctx = ''; el.ctxSelect.value = ''; }
      if (k === 'price') { state.price = ''; el.priceSelect.value = ''; }
      if (k === 'discount') state.discount = '';
      syncFilterSelectState();
      render();
    });

    // 抽屉
    el.overlay.addEventListener('click', closeDrawer);
    el.drawerHead.addEventListener('click', (e) => {
      if (e.target.closest('#drawerClose')) closeDrawer();
    });
    el.drawerBody.addEventListener('click', (e) => {
      const copyBtn = e.target.closest('[data-copy]');
      if (copyBtn) {
        const text = copyBtn.dataset.copy;
        navigator.clipboard?.writeText(text).then(
          () => toast('模型 ID 已复制'),
          () => toast('复制失败，请手动选择', 'warn'),
        );
      }
    });
    el.drawerFoot.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-toggle-compare]');
      if (btn) { toggleCompare(btn.dataset.toggleCompare); }
    });

    // 对比
    $('#clearCompare').addEventListener('click', () => {
      state.selected.clear();
      el.checkAll.checked = false;
      syncSelectionUI();
    });
    $('#openCompare').addEventListener('click', openCompareModal);
    $('#closeCompare').addEventListener('click', closeCompareModal);
    el.compareModal.addEventListener('click', (e) => {
      if (e.target === el.compareModal) closeCompareModal();
    });

    // 分页
    el.pager.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-page]');
      if (!btn || btn.disabled) return;
      const n = parseInt(btn.dataset.page, 10);
      if (Number.isFinite(n)) goPage(n);
    });
    el.pager.addEventListener('change', (e) => {
      if (e.target.id !== 'pageSizeSel') return;
      const size = parseInt(e.target.value, 10);
      if (!Number.isFinite(size)) return;
      state.pageSize = size;
      state.page = 1;
      savePrefs();
      render();
    });

    // 全局键盘
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (el.compareModal.classList.contains('show')) { closeCompareModal(); return; }
        if (el.drawer.classList.contains('show')) { closeDrawer(); return; }
        if (document.activeElement === el.search) { el.search.value = ''; state.q = ''; render(); }
      }
      // "/" 聚焦搜索；带修饰键时不拦截
      if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        const tag = document.activeElement?.tagName;
        if (tag !== 'INPUT' && tag !== 'SELECT' && tag !== 'TEXTAREA') {
          e.preventDefault();
          el.search.focus();
        }
      }
    });

    // 刷新按钮
    $('#reloadBtn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      await loadData();
      btn.disabled = false;
      toast('已重新读取本地数据');
    });
  }

  function syncSortHeaders() {
    $$('table.models thead th.sortable').forEach((th) => {
      const s = th.dataset.sort;
      const active = state.sort === s || (s === 'price-asc' && state.sort === 'price-desc');
      th.classList.toggle('sorted', active);
      const arrow = th.querySelector('.sort-arrow');
      if (arrow) arrow.remove();
      if (active) {
        const span = document.createElement('span');
        span.className = 'sort-arrow';
        span.textContent = (th.dataset.sort === 'price-asc' && state.sort === 'price-desc') ? '↓' : '↓';
        th.appendChild(span);
      }
    });
  }

  // ---------------- 启动 ----------------

  function init() {
    loadPrefs();
    bindEvents();
    el.sortSelect.value = state.sort;
    el.currencySelect.value = state.currency;
    loadData().then(syncSortHeaders);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
