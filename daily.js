/* AIRadix · LLM Radar · AI 大事记
 *
 * 数据源：data/daily.json（scripts/fetch_daily.py 抓 AIHOT 公开 API v1）。
 * 页面只做索引与引用：标题、摘要、来源、原文链接全部保留，点击跳回 AIHOT 或原始信源。
 *
 * 交互：搜索 / 分类筛选 / 排序 / 逐日展开，全部前端完成，无后端依赖。
 */
(function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));

  const state = {
    all: [],
    search: '',
    cat: 'all',
    sort: 'date-desc',
    date: null,          // 日历选中的日期；null = 不按日期筛选
    calMonth: '',        // 日历当前显示的月份 'YYYY-MM'
    expanded: new Set(),
    allExpanded: false,
  };

  const el = {
    search: $('#search'),
    sort: $('#sortSelect'),
    catChips: $('#catChips'),
    resultCount: $('#resultCount'),
    dateFocus: $('#dateFocus'),
    timeline: $('#timeline'),
    emptyState: $('#emptyState'),
    updatedAt: $('#updatedAt'),
    toggleAll: $('#toggleAll'),
    statDays: $('#statDays'),
    statRange: $('#statRange'),
    statEvents: $('#statEvents'),
    statAvg: $('#statAvg'),
    statSrc: $('#statSrc'),
    calIssue: $('#calIssue'),
    calBig: $('#calBig'),
    calYm: $('#calYm'),
    calWeek: $('#calWeek'),
    calMonth: $('#calMonth'),
    calCount: $('#calCount'),
    calGrid: $('#calGrid'),
    calPrev: $('#calPrev'),
    calNext: $('#calNext'),
  };

  const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

  // 分类配色：沿用工具页的分类色思路，颜色只作识别，不承载语义
  const CAT_COLOR = {
    '模型发布/更新': '#5b5bd6',
    '产品发布/更新': '#0e7490',
    '行业动态': '#c2760a',
    '论文研究': '#0f9d58',
    '技巧与观点': '#7c3aed',
  };

  function catColor(label) {
    return CAT_COLOR[label] || '#5c5c70';
  }

  /** 2026-10-27 → {d:'27', dn:27, week:'周二', y:2026, m:10}；用本地构造避免 UTC 偏移串日 */
  function dateParts(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
    if (!m) return { d: s || '—', dn: s || '—', week: '', y: 0, m: 0 };
    const dt = new Date(+m[1], +m[2] - 1, +m[3]);
    return { d: m[3], dn: +m[3], week: WEEK[dt.getDay()], y: +m[1], m: +m[2] };
  }

  function normalize(s) {
    return String(s || '').toLowerCase().replace(/\s+/g, '');
  }

  /** 一天内所有事件拍平，便于搜索与计数 */
  function flatEvents(day) {
    const out = [];
    (day.sections || []).forEach((sec) => {
      (sec.items || []).forEach((it) => {
        out.push({ ...it, label: sec.label });
      });
    });
    return out;
  }

  /** 按当前筛选条件裁剪每一天；返回 {day, events} 列表 */
  function filtered() {
    const q = normalize(state.search);
    const hasFilter = !!q || state.cat !== 'all' || !!state.date;
    const rows = [];
    state.all.forEach((day) => {
      // 日历选中某天后只保留那一天，与搜索、分类取交集
      if (state.date && day.date !== state.date) return;
      let events = flatEvents(day);
      if (state.cat !== 'all') {
        events = events.filter((e) => e.label === state.cat);
      }
      const leadHit = q && (normalize(day.lead.title).includes(q)
        || normalize(day.lead.paragraph).includes(q));
      if (q) {
        // 主标题命中就保留当天全部可见事件；否则只留命中的事件
        if (!leadHit) {
          events = events.filter((e) => normalize(e.title).includes(q)
            || normalize(e.summary).includes(q)
            || normalize(e.source).includes(q));
        }
      }
      // 无筛选时保留「今日无大事」的安静日 —— 它们是时间线的一部分，
      // 丢掉会让日期出现断档。有筛选时才把没有命中项的日子剔掉；
      // 但日历明确点了某天时不剔，否则点安静日会得到一片空白。
      if (hasFilter && !events.length && !leadHit && !state.date) return;
      rows.push({ day, events, leadHit: !!leadHit });
    });
    return rows;
  }

  function sortRows(rows) {
    const by = state.sort;
    return rows.slice().sort((a, b) => {
      if (by === 'date-asc') return a.day.date.localeCompare(b.day.date);
      if (by === 'count-desc') {
        return b.events.length - a.events.length || b.day.date.localeCompare(a.day.date);
      }
      return b.day.date.localeCompare(a.day.date);
    });
  }

  function eventHTML(e) {
    const orig = e.original
      ? `<a class="tl-orig" href="${esc(e.original)}" target="_blank" rel="noopener">原文</a>`
      : '';
    return `
      <div class="tl-item">
        <div class="tl-item-head">
          <a class="tl-item-title" href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.title)}</a>
          ${e.source ? `<span class="tl-src">${esc(e.source)}</span>` : ''}
          <span class="tl-links">
            <a class="tl-aihot" href="${esc(e.url)}" target="_blank" rel="noopener">AIHOT</a>${orig}
          </span>
        </div>
        ${e.summary ? `<p class="tl-summary">${esc(e.summary)}</p>` : ''}
      </div>`;
  }

  function sectionsHTML(events) {
    const groups = new Map();
    events.forEach((e) => {
      if (!groups.has(e.label)) groups.set(e.label, []);
      groups.get(e.label).push(e);
    });
    let html = '';
    groups.forEach((items, label) => {
      html += `
        <div class="tl-sec" style="--c:${catColor(label)}">
          <div class="tl-label">${esc(label)}<b>${items.length}</b></div>
          ${items.map(eventHTML).join('')}
        </div>`;
    });
    return html;
  }

  function dayHTML(row) {
    const { day, events } = row;
    const p = dateParts(day.date);
    const active = state.allExpanded || state.expanded.has(day.date);
    const n = events.length;
    const quiet = n === 0;
    return `
      <article class="tl-day${active ? ' is-open' : ''}${quiet ? ' is-quiet' : ''}" data-date="${esc(day.date)}">
        <div class="tl-rail"><span class="tl-dot"></span></div>
        <div class="tl-body">
          <header class="tl-head">
            <div class="tl-date"><b>${esc(p.d)}</b><span>${esc(p.week)}</span></div>
            <div class="tl-lead">
              <h3>${esc(day.lead.title || '当日无摘要')}</h3>
              ${day.lead.paragraph ? `<p>${esc(day.lead.paragraph)}</p>` : ''}
            </div>
            ${quiet ? '' : `<button class="tl-toggle" type="button" aria-expanded="${active}">
              <span>${n} 条</span>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
                   stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>
            </button>`}
          </header>
          ${quiet ? '' : `<div class="tl-events"${active ? '' : ' hidden'}>${sectionsHTML(events)}</div>`}
        </div>
      </article>`;
  }

  function render() {
    const rows = sortRows(filtered());

    // 月份分隔：只在按日期排序时插入，其它排序加会误导
    let html = '';
    let lastMonth = '';
    rows.forEach((row) => {
      if (state.sort !== 'count-desc') {
        const p = dateParts(row.day.date);
        const key = `${p.y}-${p.m}`;
        if (key !== lastMonth) {
          lastMonth = key;
          html += `<div class="tl-month"><span>${p.y} 年 ${p.m} 月</span></div>`;
        }
      }
      html += dayHTML(row);
    });

    el.timeline.innerHTML = html;
    const totalEvents = rows.reduce((s, r) => s + r.events.length, 0);
    el.resultCount.innerHTML = rows.length
      ? `共 <b>${rows.length}</b> 天 · <b>${totalEvents}</b> 条事件`
      : '没有匹配的事件';

    // 日期筛选标记：明确告诉用户当前只看某一天，点叉即可回到全部
    if (state.date) {
      const p = dateParts(state.date);
      el.dateFocus.hidden = false;
      el.dateFocus.innerHTML = `<span>${p.m} 月 ${p.dn} 日 · ${p.week}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
             stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>`;
    } else {
      el.dateFocus.hidden = true;
    }

    el.emptyState.innerHTML = rows.length ? '' : `
      <div class="empty">
        <h3>没有找到相关事件</h3>
        <p>换个关键词，或点「全部分类」看全部大事记。</p>
        <button class="btn-primary" id="resetFilter">清空筛选</button>
      </div>`;
    const reset = $('#resetFilter');
    if (reset) {
      reset.addEventListener('click', () => {
        state.search = '';
        state.cat = 'all';
        state.date = null;
        el.search.value = '';
        renderChips();
        render();
        renderCalendar();
      });
    }

    el.toggleAll.textContent = state.allExpanded ? '全部收起' : '全部展开';
  }

  function renderChips() {
    const cats = new Map();
    state.all.forEach((day) => {
      (day.sections || []).forEach((s) => {
        cats.set(s.label, (cats.get(s.label) || 0) + (s.items || []).length);
      });
    });
    const items = [
      { id: 'all', label: '全部分类', n: state.all.reduce((s, d) => s + (d.event_count || 0), 0) },
      ...[...cats.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([label, n]) => ({ id: label, label, n })),
    ];
    el.catChips.innerHTML = items.map((c) => `
      <button class="chip${state.cat === c.id ? ' on' : ''}" data-cat="${esc(c.id)}">
        ${esc(c.label)}<b>${c.n}</b>
      </button>`).join('');
  }

  function renderStats(data) {
    const days = data.days || [];
    const total = data.event_total || 0;
    const quiet = days.filter((d) => !d.event_count).length;
    el.statDays.textContent = days.length;
    el.statRange.textContent = `${data.earliest || '—'} ~ ${data.latest || '—'}`;
    el.statEvents.textContent = total;
    el.statAvg.textContent = days.length
      ? (total / days.length).toFixed(1)
      : '—';
    const srcs = new Set();
    days.forEach((d) => (d.sections || []).forEach((s) => (s.items || []).forEach((i) => {
      if (i.source) srcs.add(i.source.split('：')[0].trim());
    })));
    el.statSrc.textContent = srcs.size ? srcs.size + ' 家' : '—';
    el.statSrc.closest('.stat').querySelector('.stat-foot').textContent
      = quiet ? `AIHOT 日报 · ${quiet} 个安静日` : 'AIHOT 公开日报';
    el.updatedAt.innerHTML = `<span class="dot-live"></span>更新于 ${esc(data.fetched_at || '—')}`;
  }

  /* ---------------- 日历 ---------------- */

  const MONTH_CN = ['一月', '二月', '三月', '四月', '五月', '六月',
    '七月', '八月', '九月', '十月', '十一月', '十二月'];
  const pad2 = (n) => String(n).padStart(2, '0');

  const cal = {
    byDate: new Map(),   // 'YYYY-MM-DD' → 当天日报
    issue: new Map(),    // 'YYYY-MM-DD' → 本地收录期号（最早为第 1 期）
    min: '',
    max: '',
    minMonth: '',
    maxMonth: '',
  };

  /** 建索引：日期 → 日报、期号，以及可翻月份边界（超出范围不给翻） */
  function buildCalIndex() {
    const dates = state.all.map((d) => d.date).filter(Boolean).sort();
    cal.byDate.clear();
    cal.issue.clear();
    state.all.forEach((d) => { if (d.date) cal.byDate.set(d.date, d); });
    dates.forEach((d, i) => cal.issue.set(d, i + 1));
    cal.min = dates[0] || '';
    cal.max = dates[dates.length - 1] || '';
    cal.minMonth = cal.min.slice(0, 7);
    cal.maxMonth = cal.max.slice(0, 7);
    if (!state.calMonth) state.calMonth = cal.maxMonth;
  }

  function monthCount(ym) {
    let n = 0;
    cal.byDate.forEach((_, date) => { if (date.startsWith(ym)) n += 1; });
    return n;
  }

  /** 该月最后一期有数据的日期；没有则返回空串 */
  function monthLatest(ym) {
    let d = '';
    cal.byDate.forEach((_, date) => {
      if (date.startsWith(ym) && date > d) d = date;
    });
    return d;
  }

  function renderCalendar() {
    if (!cal.max) return;

    if (state.calMonth < cal.minMonth) state.calMonth = cal.minMonth;
    if (state.calMonth > cal.maxMonth) state.calMonth = cal.maxMonth;

    const ym = state.calMonth;
    const [y, m] = ym.split('-').map(Number);

    // 左半大日期：筛选日若在当前月就用它，否则跟随翻月显示该月最后一期。
    // 翻月不改变筛选（chip 仍在），只是左侧换成了当前视图的代表日期。
    const inView = state.date && state.date.startsWith(ym);
    const viewDate = (inView ? state.date : monthLatest(ym)) || cal.max;

    const vp = dateParts(viewDate);
    const issue = cal.issue.get(viewDate);
    el.calIssue.textContent = issue ? `第 ${issue} 期` : '未收录';
    el.calBig.textContent = vp.dn;
    el.calYm.textContent = `${vp.y} 年 ${vp.m} 月`;
    el.calWeek.textContent = vp.week;

    el.calMonth.textContent = MONTH_CN[m - 1];
    el.calCount.textContent = `本月 ${monthCount(ym)} 期`;
    el.calPrev.disabled = ym <= cal.minMonth;
    el.calNext.disabled = ym >= cal.maxMonth;

    // 重建点阵会丢掉键盘焦点，先记下是不是在日历里，建完再还回去
    const hadFocus = el.calGrid.contains(document.activeElement);

    // 周一为一周之始，前导空位对齐星期头
    const lead = (new Date(y, m - 1, 1).getDay() + 6) % 7;
    const total = new Date(y, m, 0).getDate();
    const cells = [];
    for (let i = 0; i < lead; i += 1) cells.push('<span class="cal-d is-out"></span>');
    for (let d = 1; d <= total; d += 1) {
      const date = `${y}-${pad2(m)}-${pad2(d)}`;
      const day = cal.byDate.get(date);
      const sel = date === viewDate ? ' is-sel' : '';
      if (!day) {
        // 数据未覆盖的日子：淡点，不可点
        cells.push(`<span class="cal-d is-out">${d}</span>`);
        continue;
      }
      const n = day.event_count || 0;
      const tip = n ? `${n} 条事件` : '今日安静';
      cells.push(`<button type="button" class="cal-d ${n ? 'is-has' : 'is-quiet'}${sel}"`
        + ` data-date="${date}" title="${esc(date)} · ${tip}"`
        + ` aria-pressed="${date === state.date}">${d}</button>`);
    }
    el.calGrid.innerHTML = cells.join('');

    if (hadFocus) {
      const back = el.calGrid.querySelector(`.cal-d[data-date="${viewDate}"]`);
      if (back) back.focus();
    }
  }

  /** 筛选后把当天卡片滚到可视区顶部（让开吸顶的工具条） */
  function scrollToDate(date) {
    // render() 已同步写完 DOM，这里直接量位置即可；不用 rAF，
    // 页面在后台时 rAF 会被暂停，反而漏掉滚动
    const card = el.timeline.querySelector(`.tl-day[data-date="${date}"]`);
    if (!card) return;
    const bar = document.querySelector('.toolbar');
    const offset = (bar ? bar.offsetHeight : 0) + 74;
    const target = card.getBoundingClientRect().top + window.scrollY - offset;
    // 已经在目标位置上方就不动，免得点一下屏幕凭空跳一段
    if (target > window.scrollY + 8) {
      window.scrollTo({ top: target, behavior: 'smooth' });
    }
  }

  function bindEvents() {
    el.search.addEventListener('input', (e) => {
      state.search = e.target.value.trim();
      // 搜索时自动展开命中内容，省一次点击
      if (state.search) state.allExpanded = true;
      else state.allExpanded = false;
      render();
    });

    el.sort.addEventListener('change', (e) => {
      state.sort = e.target.value;
      render();
    });

    el.catChips.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cat]');
      if (!btn) return;
      state.cat = btn.dataset.cat;
      renderChips();
      render();
    });

    el.timeline.addEventListener('click', (e) => {
      const head = e.target.closest('.tl-head');
      if (!head || e.target.closest('a')) return;
      const art = head.closest('.tl-day');
      const date = art.dataset.date;
      const box = art.querySelector('.tl-events');
      if (!box) return;
      const open = art.classList.toggle('is-open');
      box.hidden = !open;
      head.querySelector('.tl-toggle').setAttribute('aria-expanded', String(open));
      if (open) state.expanded.add(date);
      else state.expanded.delete(date);
    });

    el.toggleAll.addEventListener('click', () => {
      state.allExpanded = !state.allExpanded;
      render();
    });

    // 日历点某天：筛选到当天并滚动定位；再点同一天取消
    el.calGrid.addEventListener('click', (e) => {
      const btn = e.target.closest('button.cal-d[data-date]');
      if (!btn) return;
      const date = btn.dataset.date;
      state.date = state.date === date ? null : date;
      if (state.date) state.expanded.add(date);
      render();
      renderCalendar();
      if (state.date) scrollToDate(date);
    });

    el.calPrev.addEventListener('click', () => shiftMonth(-1));
    el.calNext.addEventListener('click', () => shiftMonth(1));

    el.dateFocus.addEventListener('click', () => {
      state.date = null;
      render();
      renderCalendar();
    });
  }

  /** 翻月：只在有数据的月份区间内移动 */
  function shiftMonth(step) {
    const [y, m] = state.calMonth.split('-').map(Number);
    const dt = new Date(y, m - 1 + step, 1);
    const ym = `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}`;
    if (ym < cal.minMonth || ym > cal.maxMonth) return;
    state.calMonth = ym;
    renderCalendar();
  }

  async function boot() {
    try {
      const res = await fetch(`data/daily.json?v=${Date.now()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`daily.json HTTP ${res.status}`);
      const data = await res.json();
      state.all = Array.isArray(data.days) ? data.days : [];
      if (!state.all.length) throw new Error('大事记为空');

      renderStats(data);
      buildCalIndex();
      renderChips();
      renderCalendar();
      render();
      bindEvents();
    } catch (err) {
      el.updatedAt.textContent = '数据加载失败';
      el.timeline.innerHTML = '';
      el.emptyState.innerHTML = `
        <div class="empty">
          <h3>大事记加载失败</h3>
          <p style="font-family:var(--mono);font-size:12px;color:var(--text-3)">${esc(err.message || err)}</p>
          <p>请确认 <code>data/daily.json</code> 存在，且通过 HTTP 服务访问。</p>
          <button class="btn-primary" onclick="location.reload()">重新加载</button>
        </div>`;
    }
  }

  boot();
})();
