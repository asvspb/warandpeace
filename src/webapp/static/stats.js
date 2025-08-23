(function(){
  const source = new EventSource('/events');
  const reloadOn = ['article_published'];
  const softRefreshOn = ['metrics_updated'];
  source.addEventListener('message', function(e){
    try { console.log('[SSE] message raw:', e.data); } catch(_) {}
    try {
      const data = JSON.parse(e.data || '{}');
      if (!data || !data.type) return;
      if (reloadOn.includes(data.type)) {
        try { console.log('[SSE] article_published → reload'); } catch(_) {}
        location.reload();
      } else if (softRefreshOn.includes(data.type)) {
        try { console.log('[SSE] metrics_updated → refreshStats()'); } catch(_) {}
        refreshStats();
      }
    } catch(_){ }
  });
  source.addEventListener('open', function(){ try { console.log('[SSE] connected'); } catch(_) {} });
  source.addEventListener('error', function(e){ try { console.warn('[SSE] error', e); } catch(_) {} });

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
})();
