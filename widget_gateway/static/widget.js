/* Grounded Answers — embeddable Q&A widget
 *
 * Usage:
 *   <script src="https://<gateway>/widget.js"
 *     data-tenant-id="YOUR-TENANT-UUID"
 *     data-widget-key="YOUR-WIDGET-KEY">
 *   </script>
 *
 * Optional attributes:
 *   data-widget-variant  "nhs_blue" (default) | "black_glass"
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
  var VARIANT     = (sc && sc.getAttribute('data-widget-variant')) || 'nhs_blue';

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

  /* ── NHS Blue variant ────────────────────────────────────────────────────── */
  function initNhsBlue() {
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

  /* ── Black Glass variant ─────────────────────────────────────────────────── */
  function initBlackGlass() {
    var css = document.createElement('style');
    css.textContent = [
      'sup.ga-cite{font-size:.68em;font-weight:700;color:rgba(255,255,255,.85);line-height:0;vertical-align:super;}',

      /* Shell — dark floor behind the blur */
      '.bg-shell{position:fixed;top:28px;right:24px;width:268px;border-radius:22px;',
      'background:rgba(0,0,0,.70);',
      'box-shadow:0 0 0 1px rgba(255,255,255,.10),0 2px 0 0 rgba(255,255,255,.18) inset,',
      '0 -1px 0 0 rgba(0,0,0,.60) inset,0 20px 60px rgba(0,0,0,.50);',
      'z-index:9999;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;transition:opacity .2s;}',
      '.bg-shell.bg-off{opacity:0;pointer-events:none;}',

      /* Face — frosted glass layer on top of the dark floor */
      '.bg-face{background:rgba(255,255,255,.03);border-radius:22px;padding:18px;',
      'backdrop-filter:blur(40px) saturate(150%);-webkit-backdrop-filter:blur(40px) saturate(150%);}',

      /* Header row */
      '.bg-hdr{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:2px;}',
      '.bg-title{font-size:14px;font-weight:600;color:rgba(255,255,255,.95);letter-spacing:-.01em;}',
      '.bg-close{color:rgba(255,255,255,.22);cursor:pointer;font-size:15px;line-height:1;',
      'padding:0 0 0 8px;user-select:none;transition:color .15s;}',
      '.bg-close:hover{color:rgba(255,255,255,.65);}',

      /* Subtitle */
      '.bg-subtitle{font-size:11px;color:rgba(255,255,255,.32);margin-bottom:14px;letter-spacing:.01em;}',

      /* Pills */
      '.bg-pills{margin-bottom:12px;}',
      '.bg-pills-lbl{font-size:.68rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.08em;color:rgba(255,255,255,.30);margin-bottom:8px;}',
      '.bg-pills-list{display:flex;flex-wrap:wrap;gap:6px;}',
      '.bg-pill{background:rgba(255,255,255,.07);border:.5px solid rgba(255,255,255,.14);',
      'border-radius:99px;padding:5px 11px;font-size:.78rem;color:rgba(255,255,255,.68);',
      'cursor:pointer;font-family:inherit;transition:background .12s,border-color .12s,color .12s;}',
      '.bg-pill:hover{background:rgba(255,255,255,.13);border-color:rgba(255,255,255,.26);color:#fff;}',

      /* Scrollable answer body */
      '.bg-body{display:none;max-height:190px;overflow-y:auto;margin-bottom:12px;',
      'scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.14) transparent;}',
      '.bg-body.bg-on{display:block;}',

      /* Loading dots */
      '.bg-dots-wrap{display:flex;align-items:center;gap:8px;color:rgba(255,255,255,.32);font-size:.82rem;}',
      '.bg-dots span{display:inline-block;width:5px;height:5px;border-radius:50%;',
      'background:rgba(255,255,255,.55);animation:bg-pulse 1.2s infinite ease-in-out;}',
      '.bg-dots span:nth-child(2){animation-delay:.2s;}',
      '.bg-dots span:nth-child(3){animation-delay:.4s;}',
      '@keyframes bg-pulse{0%,80%,100%{transform:scale(.6);opacity:.4}40%{transform:scale(1);opacity:1}}',

      /* Answer text */
      '.bg-ans{font-size:.8rem;line-height:1.6;color:rgba(255,255,255,.82);}',
      '.bg-ans p{margin:0 0 8px;}.bg-ans p:last-child{margin-bottom:0;}',
      '.bg-ans strong{font-weight:600;color:rgba(255,255,255,.95);}.bg-ans em{font-style:italic;}',
      '.bg-ans ul,.bg-ans ol{margin:4px 0 8px 16px;}',
      '.bg-ans li{margin-bottom:2px;}',

      /* Error */
      '.bg-err{font-size:.78rem;color:rgba(255,120,100,.90);}',

      /* Sources */
      '.bg-srcs{border-top:.5px solid rgba(255,255,255,.08);margin-top:10px;padding-top:8px;}',
      '.bg-srcs-lbl{font-size:.65rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.07em;color:rgba(255,255,255,.24);margin-bottom:6px;}',
      '.bg-srcs ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px;}',
      '.bg-srcs li{display:flex;align-items:flex-start;gap:5px;font-size:.72rem;}',
      '.bg-src-n{flex-shrink:0;width:15px;height:15px;border-radius:50%;',
      'background:rgba(255,255,255,.07);color:rgba(255,255,255,.55);font-size:.60rem;font-weight:700;',
      'display:flex;align-items:center;justify-content:center;margin-top:1px;}',
      '.bg-srcs a{color:rgba(255,255,255,.42);word-break:break-all;text-decoration:none;}',
      '.bg-srcs a:hover{color:rgba(255,255,255,.72);text-decoration:underline;}',

      /* Suggestions */
      '.bg-sugg{border-top:.5px solid rgba(255,255,255,.08);margin-top:10px;padding-top:8px;}',
      '.bg-sugg-lbl{font-size:.65rem;font-weight:700;text-transform:uppercase;',
      'letter-spacing:.08em;color:rgba(255,255,255,.24);margin-bottom:7px;}',
      '.bg-sugg-list{display:flex;flex-wrap:wrap;gap:6px;}',

      /* Input — glass-input spec */
      '.bg-glass-input{width:100%;border:none;border-radius:12px;padding:9px 13px;font-size:13px;',
      'color:rgba(255,255,255,.85);font-family:inherit;outline:none;margin-bottom:10px;box-sizing:border-box;',
      'background:linear-gradient(170deg,rgba(255,255,255,.09) 0%,rgba(255,255,255,.02) 50%,rgba(0,0,0,.15) 100%);',
      'box-shadow:0 1.5px 0 rgba(255,255,255,.18) inset,0 -1px 0 rgba(0,0,0,.45) inset,',
      '0 0 0 .5px rgba(255,255,255,.11),0 3px 10px rgba(0,0,0,.25);}',
      '.bg-glass-input::placeholder{color:rgba(255,255,255,.18);}',

      /* Button row */
      '.bg-btn-row{display:flex;gap:7px;}',

      /* Primary button — spec btn-primary, div not button */
      '.bg-btn-ask{flex:1;border-radius:100px;padding:9px 0;font-size:12px;font-weight:600;',
      'color:#ffffff!important;-webkit-text-fill-color:#ffffff;cursor:pointer;font-family:inherit;',
      'text-align:center;letter-spacing:.01em;user-select:none;',
      'background:linear-gradient(160deg,rgba(255,255,255,.22) 0%,rgba(255,255,255,.08) 50%,rgba(0,0,0,.15) 100%);',
      'box-shadow:0 1.5px 0 rgba(255,255,255,.40) inset,0 -1px 0 rgba(0,0,0,.50) inset,',
      '0 0 0 .5px rgba(255,255,255,.20),0 4px 18px rgba(255,255,255,.08),0 1px 3px rgba(0,0,0,.40);',
      'text-shadow:0 0 14px rgba(255,255,255,.60);}',
      '.bg-btn-ask.bg-disabled{opacity:.38;cursor:not-allowed;}',

      /* Ghost button — spec btn-ghost, div not button */
      '.bg-btn-clear{border-radius:100px;padding:9px 16px;font-size:12px;font-weight:500;',
      'color:#ffffff!important;-webkit-text-fill-color:#ffffff;cursor:pointer;font-family:inherit;',
      'user-select:none;',
      'background:linear-gradient(160deg,rgba(255,255,255,.08) 0%,rgba(255,255,255,.02) 50%,rgba(0,0,0,.20) 100%);',
      'box-shadow:0 1.5px 0 rgba(255,255,255,.14) inset,0 -1px 0 rgba(0,0,0,.45) inset,',
      '0 0 0 .5px rgba(255,255,255,.08),0 3px 10px rgba(0,0,0,.25);}',

      /* Divider */
      '.bg-divider{height:.5px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.10),transparent);margin:13px 0;}',

      /* Status row */
      '.bg-status-row{display:flex;align-items:center;gap:6px;}',
      '.bg-status-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;',
      'background:radial-gradient(circle at 35% 35%,rgba(255,255,255,.95),rgba(180,255,200,.70));',
      'box-shadow:0 0 6px rgba(255,255,255,.45),0 0 2px rgba(255,255,255,.80);}',
      '.bg-status-text{font-size:11px;color:rgba(255,255,255,.25);}',

      /* Brand */
      '.bg-brand{text-align:center;font-size:.60rem;color:rgba(255,255,255,.17);padding-top:10px;}',
      '.bg-brand a{color:inherit;text-decoration:none;}',
      '.bg-brand a:hover{color:rgba(255,255,255,.38);}',

      /* Restore trigger — shown only when widget is closed */
      '.bg-trigger{position:fixed;top:28px;right:24px;z-index:9999;display:flex;align-items:center;gap:7px;',
      'padding:9px 16px;border-radius:22px;cursor:pointer;',
      'font-family:system-ui,-apple-system,"Segoe UI",sans-serif;',
      'font-size:.82rem;font-weight:600;color:rgba(255,255,255,.85);',
      'background:rgba(0,0,0,.70);',
      'box-shadow:0 0 0 1px rgba(255,255,255,.10),0 2px 0 0 rgba(255,255,255,.18) inset,',
      '0 -1px 0 0 rgba(0,0,0,.60) inset,0 20px 60px rgba(0,0,0,.50);',
      'transition:opacity .15s;user-select:none;}',
      '.bg-trigger:hover{background:rgba(10,10,10,.80);}',
      '.bg-trigger.bg-off{opacity:0;pointer-events:none;}',
    ].join('');
    document.head.appendChild(css);

    var trigger = document.createElement('div');
    trigger.className = 'bg-trigger bg-off';
    trigger.setAttribute('role', 'button');
    trigger.setAttribute('aria-label', LABEL);
    trigger.setAttribute('tabindex', '0');
    trigger.innerHTML =
      '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
      '<path d="M8 1C4.13 1 1 3.91 1 7.5c0 1.74.72 3.32 1.9 4.48L2 14l2.2-1.1C5.3 13.6 6.62 14 8 14c3.87 0 7-2.91 7-6.5S11.87 1 8 1z" fill="currentColor"/>' +
      '</svg>' + esc(LABEL);
    document.body.appendChild(trigger);

    var shell = document.createElement('div');
    shell.className = 'bg-shell';
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.setAttribute('aria-label', esc(LABEL));
    shell.innerHTML =
      '<div class="bg-face">' +
        '<div class="bg-hdr">' +
          '<div class="bg-title">' + esc(LABEL) + '</div>' +
          '<div class="bg-close" id="bg-close" role="button" aria-label="Close" tabindex="0">×</div>' +
        '</div>' +
        '<div class="bg-subtitle">' + esc(PLACEHOLDER) + '</div>' +
        '<div id="bg-pills" style="display:none">' +
          '<div class="bg-pills">' +
            '<div class="bg-pills-lbl">Try asking</div>' +
            '<div class="bg-pills-list" id="bg-pills-list"></div>' +
          '</div>' +
        '</div>' +
        '<div class="bg-body" id="bg-body">' +
          '<div class="bg-dots-wrap" id="bg-load" style="display:none">' +
            '<div class="bg-dots"><span></span><span></span><span></span></div>' +
            '<span>Searching…</span>' +
          '</div>' +
          '<div class="bg-ans" id="bg-ans" style="display:none"></div>' +
          '<div class="bg-err" id="bg-err" style="display:none"></div>' +
          '<div class="bg-srcs" id="bg-srcs" style="display:none">' +
            '<div class="bg-srcs-lbl">Sources</div>' +
            '<ul id="bg-srcs-list"></ul>' +
          '</div>' +
          '<div class="bg-sugg" id="bg-sugg" style="display:none">' +
            '<div class="bg-sugg-lbl">You might also ask</div>' +
            '<div class="bg-sugg-list" id="bg-sugg-list"></div>' +
          '</div>' +
        '</div>' +
        '<input class="bg-glass-input" id="bg-inp" type="text" placeholder="' + esc(PLACEHOLDER) + '" autocomplete="off" autocorrect="off">' +
        '<div class="bg-btn-row">' +
          '<div class="bg-btn-ask" id="bg-sub" role="button" tabindex="0">Ask</div>' +
          '<div class="bg-btn-clear" id="bg-clear" role="button" tabindex="0">Clear</div>' +
        '</div>' +
        '<div class="bg-divider"></div>' +
        '<div class="bg-status-row">' +
          '<div class="bg-status-dot"></div>' +
          '<div class="bg-status-text" id="bg-status">Ready</div>' +
        '</div>' +
        '<div class="bg-brand">' +
          '<a href="https://groundedanswers.co" target="_blank" rel="noopener">Powered by Grounded Answers</a>' +
        '</div>' +
      '</div>';
    document.body.appendChild(shell);

    var pillsWrapEl = document.getElementById('bg-pills');
    var pillsListEl = document.getElementById('bg-pills-list');
    var bodyEl      = document.getElementById('bg-body');
    var loadEl      = document.getElementById('bg-load');
    var ansEl       = document.getElementById('bg-ans');
    var errEl       = document.getElementById('bg-err');
    var srcsEl      = document.getElementById('bg-srcs');
    var srcsListEl  = document.getElementById('bg-srcs-list');
    var suggEl      = document.getElementById('bg-sugg');
    var suggListEl  = document.getElementById('bg-sugg-list');
    var inpEl       = document.getElementById('bg-inp');
    var subBtn      = document.getElementById('bg-sub');
    var clearBtn    = document.getElementById('bg-clear');
    var closeBtn    = document.getElementById('bg-close');
    var statusEl    = document.getElementById('bg-status');

    var allQuestions = [];
    var shownPills   = [];
    var lastQuestion = '';
    var rawAnswer    = '';
    var pillsLoaded  = false;

    function setStatus(text) { statusEl.textContent = text; }

    function makePill(q) {
      var b = document.createElement('div');
      b.className = 'bg-pill';
      b.setAttribute('role', 'button');
      b.setAttribute('tabindex', '0');
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

    function clearWidget() {
      rawAnswer = '';
      bodyEl.classList.remove('bg-on');
      ansEl.style.display  = 'none'; ansEl.innerHTML   = '';
      errEl.style.display  = 'none'; errEl.textContent = '';
      srcsEl.style.display = 'none'; srcsListEl.innerHTML = '';
      suggEl.style.display = 'none'; suggListEl.innerHTML = '';
      loadEl.style.display = 'none';
      subBtn.classList.remove('bg-disabled');
      if (allQuestions.length) pillsWrapEl.style.display = 'block';
      setStatus('Ready');
      inpEl.value = '';
      inpEl.focus();
    }

    var ask = makeAsker({
      onReset: function () {
        rawAnswer = '';
        pillsWrapEl.style.display = 'none';
        suggEl.style.display = 'none'; suggListEl.innerHTML = '';
        loadEl.style.display = 'flex';
        ansEl.style.display  = 'none'; ansEl.innerHTML   = '';
        errEl.style.display  = 'none'; errEl.textContent = '';
        srcsEl.style.display = 'none'; srcsListEl.innerHTML = '';
        bodyEl.classList.add('bg-on');
        subBtn.classList.add('bg-disabled');
        setStatus('Searching…');
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
            num.className = 'bg-src-n'; num.textContent = n;
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
        setStatus('Verified · just now');
        showSuggestions();
      },
      onError: function (msg) {
        loadEl.style.display = 'none';
        errEl.style.display  = 'block';
        errEl.textContent    = 'Something went wrong: ' + msg;
        setStatus('Error');
      },
      onFinally: function () {
        subBtn.classList.remove('bg-disabled');
        inpEl.value = '';
        inpEl.focus();
      },
    });

    var _baseAsk = ask;
    ask = function (q) { lastQuestion = q; return _baseAsk(q); };

    function submit() {
      var q = inpEl.value.trim();
      if (q && !subBtn.classList.contains('bg-disabled')) ask(q);
    }
    subBtn.addEventListener('click', submit);
    clearBtn.addEventListener('click', clearWidget);
    inpEl.addEventListener('keydown', function (e) { if (e.key === 'Enter') submit(); });

    function openWidget() {
      shell.classList.remove('bg-off');
      trigger.classList.add('bg-off');
      inpEl.focus();
    }
    function closeWidget() {
      shell.classList.add('bg-off');
      trigger.classList.remove('bg-off');
    }
    closeBtn.addEventListener('click', closeWidget);
    closeBtn.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') closeWidget(); });
    trigger.addEventListener('click', openWidget);
    trigger.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') openWidget(); });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !shell.classList.contains('bg-off')) closeWidget();
    });

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
          pillsWrapEl.style.display = 'block';
        })
        .catch(function () {});
    }

    loadPills();
    inpEl.focus();
  }

  /* ── Boot ────────────────────────────────────────────────────────────────── */
  if (VARIANT === 'black_glass') {
    initBlackGlass();
  } else {
    initNhsBlue();
  }

})();
