/* Grounded Answers — embeddable Q&A widget
 *
 * Usage:
 *   <script src="https://<gateway>/widget.js"
 *     data-tenant-id="YOUR-TENANT-UUID"
 *     data-widget-key="YOUR-WIDGET-KEY">
 *   </script>
 *
 * Optional attributes:
 *   data-widget-variant  "classic" (default) | "pills"
 *   data-accent-color    e.g. "#1a56db"  (default #1a56db)
 *   data-position        "bottom-center" | "bottom-left" | "bottom-right"  (default bottom-center)
 *   data-placeholder     Input placeholder text
 *   data-label           Bubble button and panel header label
 *   data-gateway-url     Override the gateway base URL (useful for local dev)
 */
(function () {
  'use strict';

  /* ── Shared config ───────────────────────────────────────────────────────── */
  var sc          = document.currentScript;
  var TENANT_ID   = sc && sc.getAttribute('data-tenant-id');
  var WIDGET_KEY  = sc && sc.getAttribute('data-widget-key');
  var ACCENT      = (sc && sc.getAttribute('data-accent-color'))   || '#1a56db';
  var POSITION    = (sc && sc.getAttribute('data-position'))       || 'bottom-center';
  var PLACEHOLDER = (sc && sc.getAttribute('data-placeholder'))    || 'Ask a question…';
  var LABEL       = (sc && sc.getAttribute('data-label'))          || 'Ask a question';
  var GATEWAY     = (sc && sc.getAttribute('data-gateway-url'))    || 'https://widget-gateway-848760828618.us-central1.run.app';
  var VARIANT     = (sc && sc.getAttribute('data-widget-variant')) || 'classic';

  if (!TENANT_ID || !WIDGET_KEY) {
    console.warn('[Grounded Answers] data-tenant-id and data-widget-key are required.');
    return;
  }

  /* ── Shared helpers ──────────────────────────────────────────────────────── */
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
    s = s.replace(/\[(\d+(?:,\s*\d+)*)\]/g, function(_, nums) {
      return nums.split(/,\s*/).map(function(n) {
        return '<sup class="ga-cite">[' + n + ']</sup>';
      }).join('');
    });
    return s.split(/\n{2,}/).map(function (p) {
      p = p.trim();
      if (!p) return '';
      if (/^[-•]\s/.test(p)) {
        var items = p.split('\n').filter(function (l) { return /^[-•]\s/.test(l); });
        return '<ul>' + items.map(function (l) { return '<li>' + l.replace(/^[-•]\s/, '') + '</li>'; }).join('') + '</ul>';
      }
      if (/^\d+\.\s/.test(p)) {
        var items = p.split('\n').filter(function (l) { return /^\d+\.\s/.test(l); });
        return '<ol>' + items.map(function (l) { return '<li>' + l.replace(/^\d+\.\s/, '') + '</li>'; }).join('') + '</ol>';
      }
      return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
    }).join('');
  }

  function applyPos(el, isPanel) {
    el.style.position = 'fixed';
    el.style.zIndex   = '2147483647';
    if (isPanel) {
      el.style.bottom = '0';
      el.style.width  = 'min(480px, calc(100vw - 32px))';
    } else {
      el.style.bottom = '0';
    }
    if (POSITION === 'bottom-left') {
      el.style.left = isPanel ? '16px' : '20px';
    } else if (POSITION === 'bottom-right') {
      el.style.right = isPanel ? '16px' : '20px';
    } else {
      el.style.left      = '50%';
      el.style.transform = 'translateX(-50%)';
    }
  }

  /* ── Shared SSE streamer ─────────────────────────────────────────────────── */
  function makeAsker(opts) {
    return async function ask(question) {
      opts.onReset();
      try {
        var res = await fetch(GATEWAY + '/v1/ask/' + TENANT_ID + '/stream', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Widget-Key': WIDGET_KEY },
          body: JSON.stringify({ question: question }),
        });
        if (!res.ok) {
          var errBody = await res.json().catch(function () { return {}; });
          opts.onError(errBody.message || errBody.detail || res.statusText);
          return;
        }
        var reader  = res.body.getReader();
        var decoder = new TextDecoder();
        var buf = '', event = '';
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
              if (event === 'delta')      opts.onDelta(data.text || '');
              else if (event === 'done')  opts.onDone(data.sources || []);
              else if (event === 'error') opts.onError(data.message || 'Unknown error');
            } else if (line === '') {
              event = '';
            }
          }
        }
      } catch (e) {
        opts.onError(e.message);
      } finally {
        opts.onFinally();
      }
    };
  }

  function citedNums(raw) {
    var cited = {};
    (raw.match(/\[(\d+(?:,\s*\d+)*)\]/g) || []).forEach(function (m) {
      m.match(/\d+/g).forEach(function (n) { cited[+n] = true; });
    });
    return cited;
  }

  /* ── Classic variant ─────────────────────────────────────────────────────── */
  function initClassic() {
    var css = document.createElement('style');
    css.textContent = [
      'sup.ga-cite{font-size:.68em;font-weight:700;color:' + ACCENT + ';line-height:0;vertical-align:super;}',

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

      '.ga-dots-wrap{display:flex;align-items:center;gap:8px;color:#888;font-size:.84rem;}',
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
      '.ga-srcs ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;}',
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

    var btn = document.createElement('button');
    btn.className = 'ga-btn';
    btn.setAttribute('aria-label', LABEL);
    btn.innerHTML =
      '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M8 1C4.13 1 1 3.91 1 7.5c0 1.74.72 3.32 1.9 4.48L2 14l2.2-1.1C5.3 13.6 6.62 14 8 14c3.87 0 7-2.91 7-6.5S11.87 1 8 1z" fill="currentColor"/>' +
      '</svg>' + esc(LABEL);
    btn.style.position = 'fixed';
    btn.style.zIndex   = '2147483647';
    btn.style.bottom   = '20px';
    if (POSITION === 'bottom-left')       btn.style.left  = '20px';
    else if (POSITION === 'bottom-right') btn.style.right = '20px';
    else { btn.style.left = '50%'; btn.style.transform = 'translateX(-50%)'; }
    document.body.appendChild(btn);

    var panel = document.createElement('div');
    panel.className = 'ga-panel ga-off';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', esc(LABEL));
    panel.innerHTML =
      '<div class="ga-hdr">' +
        '<span class="ga-hdr-title">' + esc(LABEL) + '</span>' +
        '<button class="ga-x" aria-label="Close">×</button>' +
      '</div>' +
      '<div class="ga-body" id="ga-body">' +
        '<div class="ga-dots-wrap" id="ga-load" style="display:none">' +
          '<div class="ga-dots"><span></span><span></span><span></span></div>' +
          '<span>Searching…</span>' +
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
    applyPos(panel, true);
    panel.style.maxHeight = '520px';
    document.body.appendChild(panel);

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
    var rawAnswer  = '';
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
            var b = document.createElement('button');
            b.className   = 'ga-demo-chip';
            b.textContent = q;
            b.addEventListener('click', function () {
              inpEl.value = q;
              demoEl.style.display = 'none';
              ask(q);
            });
            demoChips.appendChild(b);
          });
          demoEl.style.display = 'block';
        })
        .catch(function () {});
    }

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

    var ask = makeAsker({
      onReset: function () {
        rawAnswer = '';
        demoEl.style.display  = 'none';
        loadEl.style.display  = 'flex';
        ansEl.style.display   = 'none'; ansEl.innerHTML  = '';
        errEl.style.display   = 'none'; errEl.textContent = '';
        srcsEl.style.display  = 'none'; srcsListEl.innerHTML = '';
        bodyEl.classList.add('ga-on');
        subBtn.disabled = true;
      },
      onDelta: function (text) {
        if (loadEl.style.display !== 'none') {
          loadEl.style.display = 'none';
          ansEl.style.display  = 'block';
        }
        rawAnswer += text;
        ansEl.innerHTML = renderMarkdown(rawAnswer);
        bodyEl.scrollTop = bodyEl.scrollHeight;
      },
      onDone: function (sources) {
        if (sources && sources.length) {
          var cited = citedNums(rawAnswer);
          var hasCited = Object.keys(cited).length > 0;
          srcsListEl.innerHTML = '';
          sources.forEach(function (src, i) {
            var n = i + 1;
            if (hasCited && !cited[n]) return;
            var li = document.createElement('li');
            var num = document.createElement('span');
            num.className = 'ga-src-n'; num.textContent = n;
            var a = document.createElement('a');
            a.href = src; a.target = '_blank'; a.rel = 'noopener noreferrer';
            a.textContent = src;
            li.appendChild(num); li.appendChild(a);
            srcsListEl.appendChild(li);
          });
          if (srcsListEl.children.length) srcsEl.style.display = 'block';
        }
        if (loadEl.style.display !== 'none') {
          loadEl.style.display = 'none';
          ansEl.style.display  = 'block';
          ansEl.innerHTML      = '<em>No answer returned.</em>';
        }
      },
      onError: function (msg) {
        loadEl.style.display = 'none';
        errEl.style.display  = 'block';
        errEl.textContent    = 'Something went wrong: ' + msg;
      },
      onFinally: function () {
        subBtn.disabled = false;
        inpEl.value     = '';
        inpEl.focus();
      },
    });

    function submit() { var q = inpEl.value.trim(); if (q) ask(q); }
    subBtn.addEventListener('click', submit);
    inpEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });
  }

  /* ── Pills variant (glass black) ────────────────────────────────────────── */
  function initPills() {
    var css = document.createElement('style');
    css.textContent = [
      'sup.ga-cite{font-size:.68em;font-weight:700;color:' + ACCENT + ';line-height:0;vertical-align:super;}',

      '.gp-trigger{display:flex;align-items:center;justify-content:center;gap:8px;',
      'padding:10px 22px;border-radius:24px 24px 0 0;border:none;cursor:pointer;',
      'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;',
      'font-size:.875rem;font-weight:600;color:#d8d8d8;',
      'background:rgba(15,15,15,.85);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);',
      'border:1px solid rgba(255,255,255,.09);border-bottom:none;',
      'box-shadow:0 -4px 24px rgba(0,0,0,.45);transition:background .15s,color .15s;}',
      '.gp-trigger:hover{background:rgba(28,28,28,.95);color:#fff;}',
      '.gp-trigger.gp-off{opacity:0;pointer-events:none;}',

      '.gp-panel{display:flex;flex-direction:column;overflow:hidden;',
      'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;',
      'background:rgba(14,14,14,.88);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);',
      'border-radius:16px 16px 0 0;',
      'border:1px solid rgba(255,255,255,.09);border-bottom:none;',
      'box-shadow:0 -8px 40px rgba(0,0,0,.6);transition:opacity .2s;}',
      '.gp-panel.gp-off{opacity:0;pointer-events:none;}',

      '.gp-hdr{padding:14px 16px;display:flex;align-items:center;justify-content:space-between;',
      'flex-shrink:0;border-bottom:1px solid rgba(255,255,255,.07);}',
      '.gp-hdr-title{font-size:.875rem;font-weight:600;color:#e8e8e8;}',
      '.gp-x{background:rgba(255,255,255,.08);border:none;border-radius:6px;color:#888;',
      'width:28px;height:28px;cursor:pointer;font-size:1rem;',
      'display:flex;align-items:center;justify-content:center;transition:background .15s,color .15s;}',
      '.gp-x:hover{background:rgba(255,255,255,.15);color:#e8e8e8;}',

      '.gp-pills-area{padding:14px 14px 10px;}',
      '.gp-pills-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.08em;color:#484848;margin-bottom:10px;}',
      '.gp-pills-list{display:flex;flex-direction:column;gap:7px;}',
      '.gp-pill{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.10);',
      'border-radius:99px;padding:9px 16px;font-size:.84rem;color:#c8c8c8;',
      'cursor:pointer;text-align:left;font-family:inherit;',
      'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;',
      'transition:background .12s,border-color .12s,color .12s;}',
      '.gp-pill:hover{background:rgba(255,255,255,.13);border-color:' + ACCENT + ';color:#fff;}',

      '.gp-body{flex:1;overflow-y:auto;padding:14px 16px;display:none;}',
      '.gp-body.gp-on{display:block;}',

      '.gp-dots-wrap{display:flex;align-items:center;gap:8px;color:#555;font-size:.84rem;}',
      '.gp-dots span{display:inline-block;width:6px;height:6px;border-radius:50%;',
      'background:' + ACCENT + ';animation:gp-pulse 1.2s infinite ease-in-out;}',
      '.gp-dots span:nth-child(2){animation-delay:.2s;}',
      '.gp-dots span:nth-child(3){animation-delay:.4s;}',
      '@keyframes gp-pulse{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}',

      '.gp-ans{font-size:.875rem;line-height:1.65;color:#d0d0d0;}',
      '.gp-ans p{margin:0 0 10px;}.gp-ans p:last-child{margin-bottom:0;}',
      '.gp-ans strong{font-weight:600;color:#f0f0f0;}.gp-ans em{font-style:italic;}',
      '.gp-ans ul,.gp-ans ol{margin:6px 0 10px 18px;}',
      '.gp-ans li{margin-bottom:3px;}',

      '.gp-err{font-size:.84rem;color:#e05c4b;}',

      '.gp-srcs{border-top:1px solid rgba(255,255,255,.07);margin-top:14px;padding-top:12px;}',
      '.gp-srcs-lbl{font-size:.7rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.07em;color:#444;margin-bottom:8px;}',
      '.gp-srcs ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;}',
      '.gp-srcs li{display:flex;align-items:flex-start;gap:6px;font-size:.78rem;}',
      '.gp-src-n{flex-shrink:0;width:18px;height:18px;border-radius:50%;',
      'background:rgba(255,255,255,.08);color:' + ACCENT + ';font-size:.65rem;font-weight:700;',
      'display:flex;align-items:center;justify-content:center;margin-top:1px;}',
      '.gp-srcs a{color:#6a9fd8;word-break:break-all;text-decoration:none;}',
      '.gp-srcs a:hover{color:#8ab4f8;text-decoration:underline;}',

      '.gp-sugg{border-top:1px solid rgba(255,255,255,.07);margin-top:14px;padding-top:12px;}',
      '.gp-sugg-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.08em;color:#484848;margin-bottom:9px;}',
      '.gp-sugg-list{display:flex;flex-direction:column;gap:7px;}',

      '.gp-foot{padding:10px 12px;border-top:1px solid rgba(255,255,255,.07);',
      'display:flex;gap:8px;flex-shrink:0;}',
      '.gp-inp{flex:1;border:1.5px solid rgba(255,255,255,.12);border-radius:8px;',
      'padding:9px 12px;font-size:.875rem;font-family:inherit;color:#e8e8e8;',
      'background:rgba(255,255,255,.07);outline:none;transition:border-color .15s;}',
      '.gp-inp:focus{border-color:' + ACCENT + ';}',
      '.gp-inp::placeholder{color:#3a3a3a;}',
      '.gp-sub{padding:9px 16px;background:' + ACCENT + ';color:#fff;border:none;',
      'border-radius:8px;font-size:.84rem;font-weight:600;font-family:inherit;',
      'cursor:pointer;white-space:nowrap;transition:opacity .15s;}',
      '.gp-sub:hover{opacity:.88;}.gp-sub:disabled{opacity:.4;cursor:not-allowed;}',

      '.gp-brand{text-align:center;font-size:.66rem;color:#2a2a2a;',
      'padding:4px 0 7px;flex-shrink:0;}',
      '.gp-brand a{color:inherit;text-decoration:none;}',
      '.gp-brand a:hover{color:#555;}',
    ].join('');
    document.head.appendChild(css);

    var trigger = document.createElement('button');
    trigger.className = 'gp-trigger';
    trigger.setAttribute('aria-label', LABEL);
    trigger.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M8 1C4.13 1 1 3.91 1 7.5c0 1.74.72 3.32 1.9 4.48L2 14l2.2-1.1C5.3 13.6 6.62 14 8 14c3.87 0 7-2.91 7-6.5S11.87 1 8 1z" fill="currentColor"/>' +
      '</svg>' + esc(LABEL);
    trigger.style.position = 'fixed';
    trigger.style.zIndex   = '2147483647';
    trigger.style.bottom   = '0';
    if (POSITION === 'bottom-left')       trigger.style.left  = '20px';
    else if (POSITION === 'bottom-right') trigger.style.right = '20px';
    else { trigger.style.left = '50%'; trigger.style.transform = 'translateX(-50%)'; }
    document.body.appendChild(trigger);

    var panel = document.createElement('div');
    panel.className = 'gp-panel gp-off';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-label', esc(LABEL));
    panel.innerHTML =
      '<div class="gp-hdr">' +
        '<span class="gp-hdr-title">' + esc(LABEL) + '</span>' +
        '<button class="gp-x" aria-label="Close">×</button>' +
      '</div>' +
      '<div id="gp-pills" class="gp-pills-area">' +
        '<div class="gp-pills-lbl">Try asking</div>' +
        '<div class="gp-pills-list" id="gp-pills-list"></div>' +
      '</div>' +
      '<div class="gp-body" id="gp-body">' +
        '<div class="gp-dots-wrap" id="gp-load" style="display:none">' +
          '<div class="gp-dots"><span></span><span></span><span></span></div>' +
          '<span>Searching…</span>' +
        '</div>' +
        '<div class="gp-ans" id="gp-ans" style="display:none"></div>' +
        '<div class="gp-err" id="gp-err" style="display:none"></div>' +
        '<div class="gp-srcs" id="gp-srcs" style="display:none">' +
          '<div class="gp-srcs-lbl">Sources</div>' +
          '<ul id="gp-srcs-list"></ul>' +
        '</div>' +
        '<div class="gp-sugg" id="gp-sugg" style="display:none">' +
          '<div class="gp-sugg-lbl">You might also ask</div>' +
          '<div class="gp-sugg-list" id="gp-sugg-list"></div>' +
        '</div>' +
      '</div>' +
      '<div class="gp-foot">' +
        '<input class="gp-inp" id="gp-inp" type="text" placeholder="' + esc(PLACEHOLDER) + '" autocomplete="off" autocorrect="off">' +
        '<button class="gp-sub" id="gp-sub">Ask</button>' +
      '</div>' +
      '<div class="gp-brand">' +
        '<a href="https://groundedanswers.co" target="_blank" rel="noopener">Powered by Grounded Answers</a>' +
      '</div>';
    applyPos(panel, true);
    panel.style.maxHeight = '540px';
    document.body.appendChild(panel);

    var pillsAreaEl = document.getElementById('gp-pills');
    var pillsListEl = document.getElementById('gp-pills-list');
    var bodyEl      = document.getElementById('gp-body');
    var loadEl      = document.getElementById('gp-load');
    var ansEl       = document.getElementById('gp-ans');
    var errEl       = document.getElementById('gp-err');
    var srcsEl      = document.getElementById('gp-srcs');
    var srcsListEl  = document.getElementById('gp-srcs-list');
    var suggEl      = document.getElementById('gp-sugg');
    var suggListEl  = document.getElementById('gp-sugg-list');
    var inpEl       = document.getElementById('gp-inp');
    var subBtn      = document.getElementById('gp-sub');
    var closeBtn    = panel.querySelector('.gp-x');

    var allQuestions = [];
    var shownPills   = [];
    var lastQuestion = '';
    var rawAnswer    = '';
    var pillsLoaded  = false;

    function makePill(q) {
      var b = document.createElement('button');
      b.className   = 'gp-pill';
      b.textContent = q;
      b.addEventListener('click', function () { inpEl.value = q; ask(q); });
      return b;
    }

    function showSuggestions() {
      var candidates = allQuestions.filter(function (q) {
        return shownPills.indexOf(q) === -1 && q !== lastQuestion;
      });
      if (candidates.length < 3) {
        candidates = allQuestions.filter(function (q) { return q !== lastQuestion; });
      }
      for (var i = candidates.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1));
        var t = candidates[i]; candidates[i] = candidates[j]; candidates[j] = t;
      }
      var picks = candidates.slice(0, 3);
      if (!picks.length) return;
      suggListEl.innerHTML = '';
      picks.forEach(function (q) { suggListEl.appendChild(makePill(q)); });
      suggEl.style.display = 'block';
    }

    var ask = makeAsker({
      onReset: function () {
        rawAnswer = '';
        pillsAreaEl.style.display = 'none';
        suggEl.style.display = 'none'; suggListEl.innerHTML = '';
        loadEl.style.display = 'flex';
        ansEl.style.display  = 'none'; ansEl.innerHTML   = '';
        errEl.style.display  = 'none'; errEl.textContent = '';
        srcsEl.style.display = 'none'; srcsListEl.innerHTML = '';
        bodyEl.classList.add('gp-on');
        subBtn.disabled = true;
      },
      onDelta: function (text) {
        if (loadEl.style.display !== 'none') {
          loadEl.style.display = 'none';
          ansEl.style.display  = 'block';
        }
        rawAnswer += text;
        ansEl.innerHTML = renderMarkdown(rawAnswer);
        bodyEl.scrollTop = bodyEl.scrollHeight;
      },
      onDone: function (sources) {
        if (sources && sources.length) {
          var cited = citedNums(rawAnswer);
          var hasCited = Object.keys(cited).length > 0;
          srcsListEl.innerHTML = '';
          sources.forEach(function (src, i) {
            var n = i + 1;
            if (hasCited && !cited[n]) return;
            var li = document.createElement('li');
            var num = document.createElement('span');
            num.className = 'gp-src-n'; num.textContent = n;
            var a = document.createElement('a');
            a.href = src; a.target = '_blank'; a.rel = 'noopener noreferrer';
            a.textContent = src;
            li.appendChild(num); li.appendChild(a);
            srcsListEl.appendChild(li);
          });
          if (srcsListEl.children.length) srcsEl.style.display = 'block';
        }
        if (loadEl.style.display !== 'none') {
          loadEl.style.display = 'none';
          ansEl.style.display  = 'block';
          ansEl.innerHTML      = '<em>No answer returned.</em>';
        }
        showSuggestions();
      },
      onError: function (msg) {
        loadEl.style.display = 'none';
        errEl.style.display  = 'block';
        errEl.textContent    = 'Something went wrong: ' + msg;
      },
      onFinally: function () {
        subBtn.disabled = false;
        inpEl.value     = '';
        inpEl.focus();
      },
    });

    var _baseAsk = ask;
    ask = function (q) { lastQuestion = q; return _baseAsk(q); };

    function submit() { var q = inpEl.value.trim(); if (q) ask(q); }
    subBtn.addEventListener('click', submit);
    inpEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });

    function loadPills() {
      if (pillsLoaded) return;
      pillsLoaded = true;
      fetch(GATEWAY + '/v1/demo-questions/' + TENANT_ID)
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.questions || !d.questions.length) return;
          allQuestions = d.questions;
          shownPills   = allQuestions.slice(0, 5);
          pillsListEl.innerHTML = '';
          shownPills.forEach(function (q) { pillsListEl.appendChild(makePill(q)); });
        })
        .catch(function () {});
    }

    function openPanel() {
      panel.classList.remove('gp-off');
      trigger.classList.add('gp-off');
      loadPills();
      inpEl.focus();
    }
    function closePanel() {
      panel.classList.add('gp-off');
      trigger.classList.remove('gp-off');
    }
    trigger.addEventListener('click', openPanel);
    closeBtn.addEventListener('click', closePanel);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !panel.classList.contains('gp-off')) closePanel();
    });
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */
  if (VARIANT === 'pills') {
    initPills();
  } else {
    initClassic();
  }

})();
