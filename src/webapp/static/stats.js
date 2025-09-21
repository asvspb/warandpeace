(function(){
  try {
    var b = document.body;
    if (!b || !b.dataset || b.dataset.sse !== '1') return;
  } catch(_) { return; }
  let source = null;
  let retry = 0;
  const maxDelay = 30000;
  const reloadOn = ['article_published'];
  const softRefreshCalendarOn = ['article_published','backfill_updated'];
  const softRefreshOn = ['metrics_updated'];

  function backoff(){
    retry = Math.min(retry + 1, 10);
    const delay = Math.min(1000 * Math.pow(2, retry - 1), maxDelay);
    try { console.warn('[SSE] reconnect in', delay, 'ms'); } catch(_){ }
    setTimeout(connect, delay);
  }

  function connect(){
    try { if (source) { try { source.close(); } catch(_) {} } } catch(_){}
    try { console.log('[SSE] connecting…'); } catch(_){ }
    // Same-origin: withCredentials не обязателен, но не мешает
    source = new EventSource('/events', { withCredentials: true });

    source.addEventListener('open', function(){
      try { console.log('[SSE] connected'); } catch(_) {}
      retry = 0;
    });

    source.addEventListener('message', function(e){
      try { console.log('[SSE] message raw:', e.data); } catch(_) {}
      try {
        const data = JSON.parse(e.data || '{}');
        if (!data || !data.type) return;
        if (data.type === 'hello') {
          try { console.log('[SSE] hello'); } catch(_) {}
          try { console.log('[SSE] → refreshStats()'); if (typeof refreshStats === 'function') refreshStats(); } catch(_) {}
          try { console.log('[SSE] → refreshBackfillProgress()'); if (typeof window.refreshBackfillProgress === 'function') window.refreshBackfillProgress(); } catch(_) {}
          try { console.log('[SSE] → refreshCalendarSection()'); if (typeof window.refreshCalendarSection === 'function') window.refreshCalendarSection(); } catch(_) {}
          // Fallback kick after 1.5s
          setTimeout(function(){
            try { if (typeof refreshStats === 'function') refreshStats(); } catch(_) {}
            try { if (typeof window.refreshBackfillProgress === 'function') window.refreshBackfillProgress(); } catch(_) {}
            try { if (typeof window.refreshCalendarSection === 'function') window.refreshCalendarSection(); } catch(_) {}
          }, 1500);
        } else if (reloadOn.includes(data.type)) {
          if (typeof window.refreshCalendarSection === 'function') {
            try { console.log('[SSE] article_published → refreshCalendarSection()'); } catch(_) {}
            window.refreshCalendarSection();
          } else {
            try { console.log('[SSE] article_published → reload'); } catch(_) {}
            location.reload();
          }
        } else if (softRefreshOn.includes(data.type)) {
          try { console.log('[SSE] metrics_updated → refreshStats()'); } catch(_) {}
          refreshStats();
        } else if (softRefreshCalendarOn.includes(data.type)) {
          if (typeof window.refreshCalendarSection === 'function') {
            try { console.log('[SSE] backfill_updated → refreshCalendarSection()'); } catch(_) {}
            window.refreshCalendarSection();
          }
          if (typeof window.refreshBackfillProgress === 'function') {
            try { console.log('[SSE] backfill_updated → refreshBackfillProgress()'); } catch(_) {}
            window.refreshBackfillProgress();
          }
        }
      } catch(_){ }
    });

    source.addEventListener('error', function(e){
      try {
        console.warn('[SSE] error', e);
        if (e && e.eventPhase === EventSource.CLOSED) console.warn('[SSE] connection closed');
      } catch(_) {}
      backoff();
    });
  }

  connect();

  const sessionStartEl = document.getElementById('session-start');
  const uptimeEl = document.getElementById('uptime');
  const httpEl = document.getElementById('http-count');
  const articlesEl = document.getElementById('articles-count');
  const tpEl = document.getElementById('tokens-prompt');
  const tcEl = document.getElementById('tokens-completion');
  const tbody = document.getElementById('token-keys-body');

  function renderUptime(seconds){
    const s = Math.max(0, parseInt(seconds || 0, 10));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}ч ${m}м`;
  }

  function renderTableRows(rows){
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!rows || !rows.length){
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 5;
      td.className = 'muted';
      td.style.padding = '8px';
      td.textContent = 'Ключи не использовались';
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    for (const row of rows){
      const tr = document.createElement('tr');
      const cols = [row.provider, row.key_id, (row.requests|0), (row.prompt|0), (row.completion|0)];
      for (const c of cols){
        const td = document.createElement('td');
        td.style.padding = '8px';
        td.textContent = c;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  async function refreshStats(){
    try {
      const resp = await fetch('/stats.json', {cache: 'no-store'});
      if (!resp.ok) return;
      const data = await resp.json();
      if (sessionStartEl && typeof data.session_start === 'string') sessionStartEl.textContent = data.session_start || '—';
      if (uptimeEl && typeof data.uptime_seconds !== 'undefined') uptimeEl.textContent = renderUptime(data.uptime_seconds || 0);
      if (httpEl && typeof data.external_http_requests !== 'undefined') httpEl.textContent = (data.external_http_requests|0);
      if (articlesEl && typeof data.articles_processed !== 'undefined') articlesEl.textContent = (data.articles_processed|0);
      if (tpEl && typeof data.tokens_prompt !== 'undefined') tpEl.textContent = (data.tokens_prompt|0);
      if (tcEl && typeof data.tokens_completion !== 'undefined') tcEl.textContent = (data.tokens_completion|0);
      if (tbody) renderTableRows(Array.isArray(data.token_keys) ? data.token_keys : []);
      try { console.log('[UI] stats refreshed', {
        external_http_requests: data.external_http_requests,
        articles_processed: data.articles_processed,
        tokens_prompt: data.tokens_prompt,
        tokens_completion: data.tokens_completion,
        token_keys_count: (data.token_keys||[]).length,
      }); } catch(_) {}
    } catch(_){ }
  }

  refreshStats();
  setInterval(refreshStats, 60 * 1000);
  if (typeof window.refreshBackfillProgress === 'function') {
    try { window.refreshBackfillProgress(); } catch(_) {}
    setInterval(function(){ try { window.refreshBackfillProgress(); } catch(_) {} }, 60 * 1000);
  }
})();
