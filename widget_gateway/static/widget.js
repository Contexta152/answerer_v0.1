/* Grounded Answers — embeddable Q&A widget
 *
 * Usage:
 *   <script src="https://<gateway>/widget.js"
 *     data-tenant-id="YOUR-TENANT-UUID"
 *     data-widget-key="YOUR-WIDGET-KEY">
 *   </script>
 *
 * Optional attributes:
 *   data-accent-color   e.g. "#1a56db"  (default #1a56db)
 *   data-position       "bottom-center" | "bottom-left" | "bottom-right"  (default bottom-center)
 *   data-placeholder    Input placeholder text
 *   data-label          Bubble button and panel header label
 *   data-gateway-url    Override the gateway base URL (useful for local dev)
 */
(function () {
  'use strict';

  /* ── Config ──────────────────────────────────────────────────────────────── */
  var sc = document.currentScript;
  var TENANT_ID   = sc && sc.getAttribute('data-tenant-id');
  var WIDGET_KEY  = sc && sc.getAttribute('data-widget-key');
  var ACCENT      = (sc && sc.getAttribute('data-accent-color'))  || '#1a56db';
  var POSITION    = (sc && sc.getAttribute('data-position'))      || 'bottom-center';
  var PLACEHOLDER = (sc && sc.getAttribute('data-placeholder'))   || 'Ask a question\u2026';
  var LABEL       = (sc && sc.getAttribute('data-label'))         || 'Ask a question';
  var GATEWAY     = (sc && sc.getAttribute('data-gateway-url'))   || 'https://widget-gateway-848760828618.us-central1.run.app';

  if (!TENANT_ID || !WIDGET_KEY) {
    console.warn('[Grounded Answers] data-tenant-id and data-widget-key are required.');
    return;
  }

  /* ── CSS ─────────────────────────────────────────────────────────────────── */
  var css = document.createElement('style');
  css.textContent = [
    '.ga-btn{display:flex;align-items:center;gap:8px;padding:11px 20px;',
    'background:' + ACCENT + ';color:#fff;border:none;border-radius:24px;',
    'font-size:.875rem;font-weight:600;',
    'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;',
    'cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.20);white-space:nowrap;',
    'transition:opacity .15s;}',
    '.ga-btn:hover{opacity:.88;}',
    '.ga-btn.ga-off{opacity:0;pointer-events:none;}',

    '.ga-panel{display:flex;flex-direction:column;overflow:hidden;',
    'background:rgba(255,255,255,.93);',
    'backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);',
    'border-radius:14px 14px 0 0;',
    'box-shadow:0 -4px 32px rgba(0,0,0,.15),0 0 0 1px rgba(0,0,0,.06);',
    'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;',
    'transition:opacity .2s;}',
    '.ga-panel.ga-off{opacity:0;pointer-events:none;}',

    '.ga-hdr{background:' + ACCENT + ';color:#fff;',
    'padding:13px 16px;display:flex;align-items:center;',
    'justify-content:space-between;flex-shrink:0;}',
    '.ga-hdr-title{font-size:.875rem;font-weight:600;}',
    '.ga-x{background:rgba(255,255,255,.18);border:none;border-radius:6px;',
    'color:#fff;width:28px;height:28px;cursor:pointer;font-size:1rem;',
    'display:flex;align-items:center;justify-content:center;transition:background .15s;}',
    '.ga-x:hover{background:rgba(255,255,255,.28);}',

    '.ga-body{flex:1;overflow-y:auto;padding:16px;display:none;}',
    '.ga-body.ga-on{display:block;}',

    '.ga-dots-wrap{display:flex;align-items:center;gap:8px;',
    'color:#888;font-size:.84rem;}',
    '.ga-dots span{display:inline-block;width:6px;height:6px;border-radius:50%;',
    'background:' + ACCENT + ';animation:ga-pulse 1.2s infinite ease-in-out;}',
    '.ga-dots span:nth-child(2){animation-delay:.2s;}',
    '.ga-dots span:nth-child(3){animation-delay:.4s;}',
    '@keyframes ga-pulse{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}',

    '.ga-ans{font-size:.875rem;line-height:1.65;color:#1a1a2e;}',
    '.ga-ans p{margin:0 0 10px;}.ga-ans p:last-child{margin-bottom:0;}',
    '.ga-ans strong{font-weight:600;}.ga-ans em{font-style:italic;}',
    '.ga-ans ul,.ga-ans ol{margin:6px 0 10px 18px;}',
    '.ga-ans li{margin-bottom:3px;}',

    '.ga-err{font-size:.84rem;color:#c0392b;}',

    '.ga-srcs{border-top:1px solid rgba(0,0,0,.08);margin-top:14px;padding-top:12px;}',
    '.ga-srcs-lbl{font-size:.7rem;font-weight:700;text-transform:uppercase;',
    'letter-spacing:.07em;color:#aaa;margin-bottom:8px;}',
    '.ga-srcs ul{list-style:none;margin:0;padding:0;display:flex;',
    'flex-direction:column;gap:4px;}',
    '.ga-srcs li{display:flex;align-items:flex-start;gap:6px;font-size:.78rem;}',
    '.ga-src-n{flex-shrink:0;width:18px;height:18px;border-radius:50%;',
    'background:rgba(0,0,0,.07);color:' + ACCENT + ';font-size:.65rem;font-weight:700;',
    'display:flex;align-items:center;justify-content:center;margin-top:1px;}',
    '.ga-srcs a{color:' + ACCENT + ';word-break:break-all;text-decoration:none;}',
    '.ga-srcs a:hover{text-decoration:underline;}',

    '.ga-foot{padding:10px 12px;border-top:1px solid rgba(0,0,0,.07);',
    'display:flex;gap:8px;flex-shrink:0;background:rgba(255,255,255,.6);}',
    '.ga-inp{flex:1;border:1.5px solid rgba(0,0,0,.13);border-radius:8px;',
    'padding:9px 12px;font-size:.875rem;font-family:inherit;color:#1a1a2e;',
    'background:#fff;outline:none;transition:border-color .15s;}',
    '.ga-inp:focus{border-color:' + ACCENT + ';}',
    '.ga-inp::placeholder{color:#bbb;}',
    '.ga-sub{padding:9px 16px;background:' + ACCENT + ';color:#fff;border:none;',
    'border-radius:8px;font-size:.84rem;font-weight:600;font-family:inherit;',
    'cursor:pointer;white-space:nowrap;transition:opacity .15s;}',
    '.ga-sub:hover{opacity:.88;}.ga-sub:disabled{opacity:.4;cursor:not-allowed;}',

    '.ga-brand{text-align:center;font-size:.66rem;color:#ccc;',
    'padding:4px 0 7px;flex-shrink:0;}',
    '.ga-brand a{color:inherit;text-decoration:none;}',
    '.ga-brand a:hover{color:#999;}',

    '.ga-demo{padding:14px 16px 8px;}',
    '.ga-demo-lbl{font-size:.7rem;font-weight:700;text-transform:uppercase;',
    'letter-spacing:.07em;color:#aaa;margin-bottom:8px;}',
    '.ga-demo-chips{display:flex;flex-direction:column;gap:6px;}',
    '.ga-demo-chip{background:rgba(0,0,0,.04);border:1.5px solid rgba(0,0,0,.08);',
    'border-radius:8px;padding:8px 12px;font-size:.84rem;color:#1a1a2e;',
    'cursor:pointer;text-align:left;font-family:inherit;',
    'transition:background .12s,border-color .12s;}',
    '.ga-demo-chip:hover{background:rgba(26,86,219,.07);border-color:' + ACCENT + ';}',
  ].join('');
  document.head.appendChild(css);

  /* ── Helpers ─────────────────────────────────────────────────────────────── */
  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function renderMarkdown(raw) {
    var s = raw.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
    return s.split(/\n{2,}/).map(function (p) {
      p = p.trim();
      if (!p) return '';
      if (/^[-\u2022]\s/.test(p)) {
        var items = p.split('\n').filter(function (l) { return /^[-\u2022]\s/.test(l); });
        return '<ul>' + items.map(function (l) { return '<li>' + l.replace(/^[-\u2022]\s/, '') + '</li>'; }).join('') + '</ul>';
      }
      if (/^\d+\.\s/.test(p)) {
        var items = p.split('\n').filter(function (l) { return /^\d+\.\s/.test(l); });
        return '<ol>' + items.map(function (l) { return '<li>' + l.replace(/^\d+\.\s/, '') + '</li>'; }).join('') + '</ol>';
      }
      return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
    }).join('');
  }

  function setPos(el, isPanel) {
    el.style.position = 'fixed';
    el.style.zIndex   = '2147483647';
    if (isPanel) {
      el.style.bottom = '0';
      el.style.maxHeight = '520px';
      el.style.width  = 'min(480px, calc(100vw - 32px))';
    } else {
      el.style.bottom = '20px';
    }
    if (POSITION === 'bottom-left') {
      el.style.left = isPanel ? '16px' : '20px';
    } else if (POSITION === 'bottom-right') {
      el.style.right = isPanel ? '16px' : '20px';
    } else {
      // bottom-center (default)
      el.style.left      = '50%';
      el.style.transform = 'translateX(-50%)';
    }
  }

  /* ── Build DOM ───────────────────────────────────────────────────────────── */
  // Bubble button
  var btn = document.createElement('button');
  btn.className = 'ga-btn';
  btn.setAttribute('aria-label', LABEL);
  btn.innerHTML =
    '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
    '<path d="M8 1C4.13 1 1 3.91 1 7.5c0 1.74.72 3.32 1.9 4.48L2 14l2.2-1.1C5.3 13.6 6.62 14 8 14c3.87 0 7-2.91 7-6.5S11.87 1 8 1z" fill="currentColor"/>' +
    '</svg>' + esc(LABEL);
  setPos(btn, false);
  document.body.appendChild(btn);

  // Panel
  var panel = document.createElement('div');
  panel.className = 'ga-panel ga-off';
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-label', esc(LABEL));
  panel.innerHTML =
    '<div class="ga-hdr">' +
      '<span class="ga-hdr-title">' + esc(LABEL) + '</span>' +
      '<button class="ga-x" aria-label="Close">\u00d7</button>' +
    '</div>' +
    '<div class="ga-body" id="ga-body">' +
      '<div class="ga-dots-wrap" id="ga-load" style="display:none">' +
        '<div class="ga-dots"><span></span><span></span><span></span></div>' +
        '<span>Searching\u2026</span>' +
      '</div>' +
      '<div class="ga-ans" id="ga-ans" style="display:none"></div>' +
      '<div class="ga-err" id="ga-err" style="display:none"></div>' +
      '<div class="ga-srcs" id="ga-srcs" style="display:none">' +
        '<div class="ga-srcs-lbl">Sources</div>' +
        '<ul id="ga-srcs-list"></ul>' +
      '</div>' +
    '</div>' +
    '<div id="ga-demo" style="display:none">' +
      '<div class="ga-demo">' +
        '<div class="ga-demo-lbl">Try asking</div>' +
        '<div class="ga-demo-chips" id="ga-demo-chips"></div>' +
      '</div>' +
    '</div>' +
    '<div class="ga-foot">' +
      '<input class="ga-inp" id="ga-inp" type="text" placeholder="' + esc(PLACEHOLDER) + '" autocomplete="off" autocorrect="off">' +
      '<button class="ga-sub" id="ga-sub">Ask</button>' +
    '</div>' +
    '<div class="ga-brand">' +
      '<a href="https://groundedanswers.co" target="_blank" rel="noopener">Powered by Grounded Answers</a>' +
    '</div>';
  setPos(panel, true);
  document.body.appendChild(panel);

  /* ── Element refs ────────────────────────────────────────────────────────── */
  var bodyEl     = document.getElementById('ga-body');
  var loadEl     = document.getElementById('ga-load');
  var ansEl      = document.getElementById('ga-ans');
  var errEl      = document.getElementById('ga-err');
  var srcsEl     = document.getElementById('ga-srcs');
  var srcsListEl = document.getElementById('ga-srcs-list');
  var demoEl     = document.getElementById('ga-demo');
  var demoChips  = document.getElementById('ga-demo-chips');
  var inpEl      = document.getElementById('ga-inp');
  var subBtn     = document.getElementById('ga-sub');
  var closeBtn   = panel.querySelector('.ga-x');

  var demoLoaded = false;

  function loadDemoQuestions() {
    if (demoLoaded) return;
    demoLoaded = true;
    fetch(GATEWAY + '/v1/demo-questions/' + TENANT_ID)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.questions || !d.questions.length) return;
        demoChips.innerHTML = '';
        d.questions.forEach(function (q) {
          var btn = document.createElement('button');
          btn.className   = 'ga-demo-chip';
          btn.textContent = q;
          btn.addEventListener('click', function () {
            inpEl.value = q;
            demoEl.style.display = 'none';
            ask(q);
          });
          demoChips.appendChild(btn);
        });
        demoEl.style.display = 'block';
      })
      .catch(function () {});
  }

  /* ── Open / close ────────────────────────────────────────────────────────── */
  function openPanel() {
    panel.classList.remove('ga-off');
    btn.classList.add('ga-off');
    inpEl.focus();
    loadDemoQuestions();
  }

  function closePanel() {
    panel.classList.add('ga-off');
    btn.classList.remove('ga-off');
  }

  btn.addEventListener('click', openPanel);
  closeBtn.addEventListener('click', closePanel);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !panel.classList.contains('ga-off')) closePanel();
  });

  /* ── Ask flow ────────────────────────────────────────────────────────────── */
  var rawAnswer = '';

  function resetState() {
    rawAnswer = '';
    loadEl.style.display  = 'none';
    ansEl.style.display   = 'none';
    ansEl.innerHTML       = '';
    errEl.style.display   = 'none';
    errEl.textContent     = '';
    srcsEl.style.display  = 'none';
    srcsListEl.innerHTML  = '';
    bodyEl.classList.remove('ga-on');
  }

  function appendDelta(text) {
    if (loadEl.style.display !== 'none') {
      loadEl.style.display = 'none';
      ansEl.style.display  = 'block';
    }
    rawAnswer += text;
    ansEl.innerHTML = renderMarkdown(rawAnswer);
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function showSources(sources) {
    if (!sources || !sources.length) return;
    srcsListEl.innerHTML = '';
    sources.forEach(function (src, i) {
      var li  = document.createElement('li');
      var num = document.createElement('span');
      num.className   = 'ga-src-n';
      num.textContent = i + 1;
      var a = document.createElement('a');
      a.href      = src;
      a.target    = '_blank';
      a.rel       = 'noopener noreferrer';
      a.textContent = src;
      li.appendChild(num);
      li.appendChild(a);
      srcsListEl.appendChild(li);
    });
    srcsEl.style.display = 'block';
  }

  function showError(msg) {
    loadEl.style.display = 'none';
    errEl.style.display  = 'block';
    errEl.textContent    = 'Something went wrong: ' + msg;
  }

  async function ask(question) {
    demoEl.style.display = 'none';
    resetState();
    loadEl.style.display = 'flex';
    bodyEl.classList.add('ga-on');
    subBtn.disabled = true;

    try {
      var res = await fetch(GATEWAY + '/v1/ask/' + TENANT_ID + '/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Widget-Key': WIDGET_KEY,
        },
        body: JSON.stringify({ question: question }),
      });

      if (!res.ok) {
        var errBody = await res.json().catch(function () { return {}; });
        showError(errBody.message || errBody.detail || res.statusText);
        return;
      }

      var reader  = res.body.getReader();
      var decoder = new TextDecoder();
      var buf     = '';
      var event   = '';

      while (true) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buf += decoder.decode(chunk.value, { stream: true });
        var lines = buf.split('\n');
        buf = lines.pop();

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          if (line.startsWith('event: ')) {
            event = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            var data;
            try { data = JSON.parse(line.slice(6)); } catch (e) { continue; }
            if (event === 'delta') {
              appendDelta(data.text || '');
            } else if (event === 'done') {
              showSources(data.sources);
              if (loadEl.style.display !== 'none') {
                loadEl.style.display = 'none';
                ansEl.style.display  = 'block';
                ansEl.innerHTML      = '<em>No answer returned.</em>';
              }
            } else if (event === 'error') {
              showError(data.message || 'Unknown error');
            }
          } else if (line === '') {
            event = '';
          }
        }
      }
    } catch (e) {
      showError(e.message);
    } finally {
      subBtn.disabled = false;
      inpEl.value     = '';
      inpEl.focus();
    }
  }

  function submit() {
    var q = inpEl.value.trim();
    if (q) ask(q);
  }

  subBtn.addEventListener('click', submit);
  inpEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') submit();
  });

})();
