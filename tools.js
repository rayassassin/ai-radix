/* LLM Radar · AI 工具导航
 *
 * 数据源：data/tools.json（人工维护）。
 * 与模型目录页的差异：工具没有公开聚合 API，抓别人导航站也不合适，
 * 所以这份清单走人工精选 + 版本化维护，页面只做展示与筛选。
 *
 * 交互：搜索 / 分类 / 标签 / 排序，全部在前端完成，无后端依赖。
 */
(function () {
  'use strict';

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));

  const state = {
    tools: [],
    cats: [],
    catMap: {},
    search: '',
    cat: 'all',
    tags: new Set(),
    sort: 'hot',
  };

  const el = {
    search: $('#search'),
    sort: $('#sortSelect'),
    catChips: $('#catChips'),
    tagChips: $('#tagChips'),
    resultCount: $('#resultCount'),
    activeFilters: $('#activeFilters'),
    hotSection: $('#hotSection'),
    hotGrid: $('#hotGrid'),
    toolGrid: $('#toolGrid'),
    emptyState: $('#emptyState'),
    allHead: $('#allHead'),
    allHeadNote: $('#allHeadNote'),
    updatedAt: $('#updatedAt'),
  };

  const ALL_TAGS = ['免费', '开源', '免费试用', '付费'];
  const TAG_CLASS = { '免费': 'tag-free', '开源': 'tag-open', '免费试用': 'tag-trial', '付费': 'tag-paid' };

  function normalize(s) {
    return String(s || '').toLowerCase().replace(/\s+/g, '');
  }

  function searchText(t) {
    return normalize([
      t.name, t.desc, t.id,
      state.catMap[t.cat]?.name || '',
      (t.tags || []).join(' '),
    ].join(' '));
  }

  function filtered() {
    const q = normalize(state.search);
    let list = state.tools.filter((t) => {
      if (state.cat !== 'all' && t.cat !== state.cat) return false;
      if (state.tags.size) {
        // 多标签取「或」：选免费+开源表示「免费或开源的都行」，更符合浏览习惯
        const has = (t.tags || []).some((x) => state.tags.has(x));
        if (!has) return false;
      }
      if (q && !searchText(t).includes(q)) return false;
      return true;
    });

    const catOrder = (t) => state.cats.findIndex((c) => c.id === t.cat);
    list.sort((a, b) => {
      if (state.sort === 'name') return a.name.localeCompare(b.name, 'zh-Hans-CN');
      if (state.sort === 'cat') {
        return catOrder(a) - catOrder(b)
          || Number(!!b.hot) - Number(!!a.hot)
          || a.name.localeCompare(b.name);
      }
      // hot：推荐位优先，其余按名称，保证每次打开顺序稳定
      return Number(!!b.hot) - Number(!!a.hot)
        || a.name.localeCompare(b.name);
    });
    return list;
  }

  function iconLetter(t) {
    const n = String(t.name || '').trim();
    return n ? n[0].toUpperCase() : '?';
  }

  function cardHTML(t, hot = false) {
    const cat = state.catMap[t.cat] || {};
    const color = cat.color || '#5b5bd6';
    const tags = (t.tags || []).map((x) =>
      `<span class="tool-tag ${TAG_CLASS[x] || ''}">${esc(x)}</span>`).join('');
    return `
      <a class="tool-card${hot ? ' is-hot' : ''}" href="${esc(t.url)}"
         target="_blank" rel="noopener" title="${esc(t.name)}：${esc(t.desc)}">
        <div class="tool-top">
          <span class="tool-icon" style="--c:${esc(color)}">${esc(iconLetter(t))}</span>
          <div class="tool-id">
            <div class="tool-name">
              ${esc(t.name)}
              <svg class="ext" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14 21 3"/></svg>
            </div>
            <div class="tool-cat" style="--c:${esc(color)}">${esc(cat.name || t.cat)}</div>
          </div>
          ${hot ? '<span class="hot-flag">推荐</span>' : ''}
        </div>
        <p class="tool-desc">${esc(t.desc)}</p>
        <div class="tool-tags">${tags}</div>
      </a>`;
  }

  function renderStats() {
    const total = state.tools.length;
    const free = state.tools.filter((t) =>
      (t.tags || []).some((x) => x === '免费' || x === '开源')).length;
    const hot = state.tools.filter((t) => t.hot).length;
    const used = new Set(state.tools.map((t) => t.cat)).size;
    $('#statTotal').textContent = total;
    $('#statTotalFoot').textContent = `覆盖 ${used} 个使用场景`;
    $('#statFree').textContent = free;
    $('#statHot').textContent = hot;
    $('#statCat').textContent = used;
  }

  function renderChips() {
    const counts = {};
    state.tools.forEach((t) => { counts[t.cat] = (counts[t.cat] || 0) + 1; });
    const chips = [`<button class="chip${state.cat === 'all' ? ' on' : ''}" data-cat="all">全部 ${state.tools.length}</button>`];
    state.cats.forEach((c) => {
      if (!counts[c.id]) return;   // 没工具的分类不显示，避免点了空
      chips.push(`<button class="chip${state.cat === c.id ? ' on' : ''}" data-cat="${esc(c.id)}">${esc(c.name)} ${counts[c.id]}</button>`);
    });
    el.catChips.innerHTML = chips.join('');

    el.tagChips.innerHTML = ALL_TAGS.map((t) =>
      `<button class="chip small${state.tags.has(t) ? ' on' : ''}" data-tag="${esc(t)}">${esc(t)}</button>`
    ).join('') + '<span class="chip-hint">标签可多选，取「或」</span>';
  }

  function renderActive() {
    const bits = [];
    if (state.cat !== 'all') bits.push(`分类：${state.catMap[state.cat]?.name || state.cat}`);
    if (state.tags.size) bits.push(`标签：${[...state.tags].join('、')}`);
    if (state.search) bits.push(`搜索：${state.search}`);
    el.activeFilters.innerHTML = bits.length
      ? bits.map((b) => `<span class="filter-pill">${esc(b)}</span>`).join('')
      : '';
  }

  function render() {
    const list = filtered();
    const hasFilter = state.cat !== 'all' || state.tags.size > 0 || !!state.search;

    el.resultCount.innerHTML = hasFilter
      ? `筛选出 <strong>${list.length}</strong> / ${state.tools.length} 个工具`
      : `共 <strong>${list.length}</strong> 个工具`;

    // 无筛选时才显示推荐位，避免和下面的结果重复占屏
    el.hotSection.style.display = hasFilter ? 'none' : '';
    if (!hasFilter) {
      const hot = state.tools.filter((t) => t.hot);
      el.hotGrid.innerHTML = hot.map((t) => cardHTML(t, true)).join('');
    }
    el.allHead.style.display = hasFilter ? 'none' : '';

    el.toolGrid.innerHTML = list.map((t) => cardHTML(t)).join('');
    el.emptyState.innerHTML = list.length ? '' : `
      <div class="empty">
        <h3>没有匹配的工具</h3>
        <p>换个关键词试试，或者清空筛选看全部。</p>
        <button class="btn-primary" id="emptyClear">清空筛选</button>
      </div>`;
    $('#emptyClear')?.addEventListener('click', clearAll);

    renderActive();
  }

  function clearAll() {
    state.cat = 'all';
    state.tags.clear();
    state.search = '';
    el.search.value = '';
    renderChips();
    render();
    syncHash();
  }

  function syncHash() {
    // 分类写进 hash，方便把某个分类页直接发给同事
    const h = state.cat === 'all' ? '' : `#cat=${state.cat}`;
    if (location.hash !== h) history.replaceState(null, '', h || location.pathname);
  }

  function bindEvents() {
    let timer = null;
    el.search.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        state.search = el.search.value.trim();
        render();
      }, 120);
    });

    el.sort.addEventListener('change', () => {
      state.sort = el.sort.value;
      render();
    });

    el.catChips.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-cat]');
      if (!btn) return;
      state.cat = btn.dataset.cat;
      renderChips();
      render();
      syncHash();
    });

    el.tagChips.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-tag]');
      if (!btn) return;
      const t = btn.dataset.tag;
      if (state.tags.has(t)) state.tags.delete(t); else state.tags.add(t);
      renderChips();
      render();
    });

    $('#clearFilters').addEventListener('click', clearAll);
  }

  async function boot() {
    try {
      const res = await fetch('data/tools.json', { cache: 'no-store' });
      if (!res.ok) throw new Error(`tools.json HTTP ${res.status}`);
      const data = await res.json();

      state.tools = Array.isArray(data.tools) ? data.tools : [];
      state.cats = Array.isArray(data.categories) ? data.categories : [];
      state.catMap = Object.fromEntries(state.cats.map((c) => [c.id, c]));
      if (!state.tools.length) throw new Error('工具清单为空');

      const m = location.hash.match(/cat=([a-z]+)/);
      if (m && state.catMap[m[1]]) state.cat = m[1];

      el.updatedAt.innerHTML = `<span class="dot-live"></span>人工精选 · 更新于 ${esc(data.updated_at || '—')}`;

      renderStats();
      renderChips();
      render();
      bindEvents();
    } catch (err) {
      el.updatedAt.textContent = '数据加载失败';
      el.toolGrid.innerHTML = '';
      el.emptyState.innerHTML = `
        <div class="empty">
          <h3>工具数据加载失败</h3>
          <p style="font-family:var(--mono);font-size:12px;color:var(--text-3)">${esc(err.message || err)}</p>
          <p>请确认 <code>data/tools.json</code> 存在，且通过 HTTP 服务访问（不要双击 HTML）。</p>
          <button class="btn-primary" onclick="location.reload()">重新加载</button>
        </div>`;
    }
  }

  boot();
})();
