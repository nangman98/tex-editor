// TeX 편집기 약어 기능 (2026-11-09).
// - "/" 를 치면 Notion처럼 약어 목록이 열린다. 이어서 치는 글자로 검색하고 ↑↓ · Enter(또는 Tab)로 넣는다. esc로 닫는다.
//   글자 바로 뒤의 "/"(경로 04_결과/…, 단위 V/s, 식 e^2/2a)에서는 열리지 않는다. 어디서든 열려면 ⌘/.
// - 약어를 치고 Tab을 누르면 바로 펼쳐진다(psi → \psi). 수식 밖이면 수식 항목은 $ $로 감싼다.
// - 펼친 뒤 빈칸(${1}, ${2} …)은 Tab / ⇧Tab으로 옮겨 다닌다. esc로 빈칸 이동을 끝낸다.
// - snippets.json 에 "key"가 있는 항목은 그 단축키로도 넣는다(⌘B 굵게, ⌘I 기울임, ⌘E 인라인 수식).
// 목록은 snippets.json (README "약어 목록 고치기").
(function () {
  'use strict';
  const MATH_ENVS = /^(equation|align|gather|multline|eqnarray|displaymath|math|split|aligned)\*?$/;
  let cm = null, items = [], groups = [], session = null, menu = null;

  // ---------- 넣을 글 해석: ${n:기본값} ${n} $n $0 ${SEL} ----------
  function parseBody(body, sel) {
    let out = '';
    const stops = new Map();
    let i = 0;
    while (i < body.length) {
      const c = body[i];
      if (c === '$' && body[i + 1] === '{') {
        let j = i + 2, depth = 1;
        while (j < body.length && depth) { if (body[j] === '{') depth++; else if (body[j] === '}') depth--; j++; }
        const inner = body.slice(i + 2, j - 1);
        const m = /^(\d+)(?::([\s\S]*))?$/.exec(inner);
        if (inner === 'SEL') {
          const from = out.length; out += sel || '';
          if (!stops.has('SEL')) stops.set('SEL', {from, to: out.length});
        } else if (m) {
          const from = out.length; out += m[2] || '';
          if (!stops.has(+m[1])) stops.set(+m[1], {from, to: out.length});
        } else out += body.slice(i, j);
        i = j;
      } else if (c === '$' && /\d/.test(body[i + 1] || '')) {
        const n = +body[i + 1];
        if (!stops.has(n)) stops.set(n, {from: out.length, to: out.length});
        i += 2;
      } else { out += c; i++; }
    }
    const nums = [...stops.keys()].filter(k => k !== 'SEL' && k !== 0).sort((a, b) => a - b);
    const order = nums.map(k => stops.get(k));
    const s = stops.get('SEL');
    if (!order.length && s && s.from === s.to) order.push(s);           // 고른 글자가 없으면 그 자리에 커서
    if (order.length) order.push(stops.get(0) || {from: out.length, to: out.length});  // 마지막 자리
    else if (stops.has(0)) order.push(stops.get(0));
    return {text: out, stops: order};
  }

  // ---------- 커서가 수식 안인지 ($ $, $$ $$, \( \), \[ \], equation 류 환경) ----------
  function inMath(pos) {
    let inline = false, display = false, paren = false, brack = false, env = 0;
    for (let ln = Math.max(0, pos.line - 300); ln <= pos.line; ln++) {
      let s = cm.getLine(ln);
      if (ln === pos.line) s = s.slice(0, pos.ch);
      if (!s.trim()) { inline = false; continue; }
      for (let i = 0; i < s.length; i++) {
        const c = s[i];
        if (c === '%') break;
        if (c === '\\') {
          const r = s.slice(i + 1), n = r[0];
          let m;
          if (n === '(') paren = true; else if (n === ')') paren = false;
          else if (n === '[') brack = true; else if (n === ']') brack = false;
          else if ((m = /^begin\{([^}]*)\}/.exec(r)) && MATH_ENVS.test(m[1])) { env++; i += m[0].length; continue; }
          else if ((m = /^end\{([^}]*)\}/.exec(r)) && MATH_ENVS.test(m[1])) { env = Math.max(0, env - 1); i += m[0].length; continue; }
          i++; continue;
        }
        if (c === '$') { if (s[i + 1] === '$') { display = !display; i++; } else inline = !inline; }
      }
    }
    return inline || display || paren || brack || env > 0;
  }

  // ---------- 넣기와 빈칸 이동 ----------
  function insertItem(it, from, to) {
    const selText = from ? '' : cm.getSelection();
    if (!from) { from = cm.getCursor('from'); to = cm.getCursor('to'); }
    let body = it.body;
    if (it.math && !inMath(from)) body = '$' + body + '$';
    const indent = /^\s*/.exec(cm.getLine(from.line))[0];
    body = body.replace(/\n/g, '\n' + indent);
    const {text, stops} = parseBody(body, selText);
    endSession();
    cm.operation(() => {
      cm.replaceRange(text, from, to, '+snippet');
      const base = cm.indexFromPos(from), P = k => cm.posFromIndex(base + k);
      if (!stops.length) { cm.setCursor(P(text.length)); return; }
      const opt = {className: 'cm-snip', inclusiveLeft: true, inclusiveRight: true, clearWhenEmpty: false};
      session = {
        marks: stops.map(s => cm.markText(P(s.from), P(s.to), opt)),
        outer: cm.markText(P(0), P(text.length), {inclusiveLeft: true, inclusiveRight: true, clearWhenEmpty: false}),
        idx: -1,
      };
      gotoStop(0);
    });
    cm.focus();
  }
  function gotoStop(i) {
    const s = session;
    if (!s) return;
    i = Math.max(0, i);
    const r = s.marks[i] && s.marks[i].find();
    if (!r) { endSession(); return; }
    s.idx = i;
    cm.setSelection(r.from, r.to);
    if (i === s.marks.length - 1) endSession();
  }
  function endSession() {
    if (!session) return;
    session.marks.forEach(m => m.clear()); session.outer.clear(); session = null;
  }
  function onCursor() {
    if (session) {
      const o = session.outer.find(), c = cm.getCursor();
      if (!o || CodeMirror.cmpPos(c, o.from) < 0 || CodeMirror.cmpPos(c, o.to) > 0) endSession();
    }
    if (menu) refreshMenu();
  }

  // ---------- 약어 + Tab ----------
  function expandTrigger() {
    if (cm.somethingSelected()) return false;
    const cur = cm.getCursor(), line = cm.getLine(cur.line).slice(0, cur.ch);
    const m = /[A-Za-z][A-Za-z0-9]*$/.exec(line);
    if (!m) return false;
    const start = cur.ch - m[0].length;
    if (start > 0 && line[start - 1] === '\\') return false;
    const it = items.find(x => x.trigger === m[0]);
    if (!it) return false;
    insertItem(it, {line: cur.line, ch: start}, cur);
    return true;
  }

  // ---------- "/" 메뉴 ----------
  const keyLabel = k => k.replace(/Cmd-/g, '⌘').replace(/Shift-/g, '⇧').replace(/Alt-/g, '⌥').replace(/Ctrl-/g, '⌃');
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

  function search(q) {
    if (!q) return items.slice();
    const ql = q.toLowerCase(), res = [];
    const subseq = (a, b) => { let k = 0; for (const ch of b) if (ch === a[k]) k++; return k === a.length; };
    items.forEach((it, n) => {
      const t = it.trigger.toLowerCase(), nm = it.name.toLowerCase();
      let s = 0;
      if (it.trigger === q) s = 100;
      else if (t === ql) s = 95;
      else if (t.startsWith(ql)) s = 80 - (t.length - ql.length);
      else if (nm.startsWith(ql)) s = 60;
      else if (nm.includes(ql)) s = 50;
      else if (it.group.toLowerCase().includes(ql)) s = 35;
      else if ((it.desc || '').toLowerCase().includes(ql) || it.body.toLowerCase().includes(ql)) s = 30;
      else if (subseq(ql, t)) s = 20;
      if (s) res.push({it, s, n});
    });
    res.sort((a, b) => b.s - a.s || a.n - b.n);
    return res.map(r => r.it);
  }

  function buildDom() {
    const box = document.createElement('div');
    box.className = 'snip-menu';
    box.innerHTML = '<div class="snip-list"></div><div class="snip-foot"><span>닫기</span><span>esc</span></div>';
    const prev = document.createElement('div');
    prev.className = 'snip-prev';
    prev.innerHTML = '<div class="snip-card"></div><div class="snip-code"></div><div class="snip-desc"></div>';
    document.body.append(box, prev);
    box.addEventListener('mousedown', e => e.preventDefault());
    prev.addEventListener('mousedown', e => e.preventDefault());
    box.addEventListener('mousemove', e => {
      const r = e.target.closest('.snip-row');
      if (r && menu && +r.dataset.i !== menu.sel) { menu.sel = +r.dataset.i; markSel(false); }
    });
    box.addEventListener('click', e => { const r = e.target.closest('.snip-row'); if (r) pick(+r.dataset.i); });
    return {box, prev, list: box.querySelector('.snip-list')};
  }
  let dom = null;

  function openMenu(anchor, forced) {
    if (!items.length) return;
    dom = dom || buildDom();
    menu = {anchor, forced, sel: 0, q: null, list: [], hitLen: 0, ghost: null};
    cm.addKeyMap(menuKeys);
    refreshMenu();
  }
  function closeMenu() {
    if (!menu) return;
    if (menu.ghost) menu.ghost.clear();
    cm.removeKeyMap(menuKeys);
    menu = null;
    dom.box.style.display = dom.prev.style.display = 'none';
  }
  function refreshMenu() {
    const a = menu.anchor, c = cm.getCursor();
    const slash = cm.getRange(a, {line: a.line, ch: a.ch + 1});
    if (c.line !== a.line || c.ch <= a.ch || slash !== '/' || cm.somethingSelected()) { closeMenu(); return; }
    const q = cm.getRange({line: a.line, ch: a.ch + 1}, c);
    if (/\s/.test(q)) { closeMenu(); return; }
    if (q === menu.q) return;
    const list = search(q);
    if (list.length) menu.hitLen = q.length;
    else if (q.length - menu.hitLen >= 3) { closeMenu(); return; }
    menu.q = q; menu.list = list; menu.sel = 0;
    if (menu.ghost) { menu.ghost.clear(); menu.ghost = null; }
    if (!q) {
      const g = document.createElement('span');
      g.className = 'snip-ghost'; g.textContent = '약어나 이름으로 검색';
      menu.ghost = cm.setBookmark({line: a.line, ch: a.ch + 1}, {widget: g});
    }
    render();
  }
  function render() {
    const {list, q} = menu;
    let h = '', lastGroup = null;
    if (!list.length) h = '<div class="snip-none">맞는 항목이 없습니다</div>';
    list.forEach((it, i) => {
      if (!q && it.group !== lastGroup) { h += `<div class="snip-grp">${esc(it.group)}</div>`; lastGroup = it.group; }
      const sc = esc(it.trigger) + ' ⇥' + (it.key ? '  ' + keyLabel(it.key) : '');
      h += `<div class="snip-row" data-i="${i}"><span class="snip-ic">${esc(it.icon || it.trigger.slice(0, 2))}</span>` +
           `<span class="snip-nm">${esc(it.name)}</span><span class="snip-sc">${sc}</span></div>`;
    });
    dom.list.innerHTML = h;
    dom.box.style.display = 'block';
    place();
    markSel(true);
  }
  function place() {
    const p = cm.cursorCoords(menu.anchor, 'window');
    const b = dom.box, W = innerWidth, H = innerHeight;
    b.style.left = Math.max(8, Math.min(p.left - 6, W - b.offsetWidth - 8)) + 'px';
    const below = p.bottom + 6, h = b.offsetHeight;
    b.style.top = (below + h < H - 8 || p.top - h - 6 < 8 ? below : p.top - h - 6) + 'px';
  }
  function markSel(scroll) {
    dom.list.querySelectorAll('.snip-row').forEach(r => r.classList.toggle('on', +r.dataset.i === menu.sel));
    const on = dom.list.querySelector('.snip-row.on');
    if (on && scroll) on.scrollIntoView({block: 'nearest'});
    showPreview(menu.list[menu.sel], on);
  }
  function previewTex(it) {   // 빈칸은 □로 그린다. 마지막 커서 자리는 빈칸이 아니다
    const {text, stops} = parseBody(it.body, '');
    const at = [...new Set(stops.slice(0, -1).filter(s => s.from === s.to).map(s => s.from))].sort((x, y) => y - x);
    let t = text;
    at.forEach(p => { t = t.slice(0, p) + '\\square ' + t.slice(p); });
    return /^[_^]/.test(t) ? 'x' + t : t;
  }
  function showPreview(it, row) {
    const pv = dom.prev;
    if (!it || !row) { pv.style.display = 'none'; return; }
    const card = pv.querySelector('.snip-card'), code = pv.querySelector('.snip-code');
    const shown = parseBody(it.body, '').text;
    card.className = 'snip-card';
    if (it.math && window.katex) {
      try { katex.render(previewTex(it), card, {throwOnError: false, displayMode: true}); }
      catch (e) { card.textContent = shown; card.className = 'snip-card raw'; }
    } else { card.textContent = shown; card.className = 'snip-card raw'; }
    code.textContent = it.math ? shown : '';
    code.style.display = it.math ? 'block' : 'none';
    pv.querySelector('.snip-desc').innerHTML =
      (it.desc ? esc(it.desc) + '<br>' : '') +
      `약어 <b>${esc(it.trigger)}</b> 뒤 Tab` + (it.key ? ` · 단축키 <b>${keyLabel(it.key)}</b>` : '') +
      (it.math ? ' · 수식 밖에서는 $ $로 감쌈' : '');
    pv.style.display = 'block';
    const b = dom.box.getBoundingClientRect(), r = row.getBoundingClientRect();
    const w = pv.offsetWidth, h = pv.offsetHeight;
    pv.style.left = (b.right + 8 + w < innerWidth ? b.right + 8 : Math.max(8, b.left - w - 8)) + 'px';
    pv.style.top = Math.max(8, Math.min(r.top - 8, innerHeight - h - 8)) + 'px';
  }
  function move(d) {
    if (!menu.list.length) return;
    menu.sel = (menu.sel + d + menu.list.length) % menu.list.length;
    markSel(true);
  }
  function pick(i) {
    const it = menu.list[i === undefined ? menu.sel : i];
    const a = menu.anchor, c = cm.getCursor();
    closeMenu();
    if (it) insertItem(it, a, c);
  }
  const menuKeys = {
    Up: () => move(-1), Down: () => move(1), 'Ctrl-P': () => move(-1), 'Ctrl-N': () => move(1),
    PageUp: () => move(-8), PageDown: () => move(8),
    Enter: () => { if (!menu.list.length) { closeMenu(); return CodeMirror.Pass; } pick(); },
    Tab: () => { if (!menu.list.length) { closeMenu(); return CodeMirror.Pass; } pick(); },
    Esc: () => {
      const a = menu.anchor, c = cm.getCursor(), forced = menu.forced;
      closeMenu();
      if (forced) cm.replaceRange('', a, c, '+snippet');
    },
  };

  // ---------- 붙이기 ----------
  function attach(editor) {
    cm = editor;
    const keys = {
      Tab: () => { if (session) { gotoStop(session.idx + 1); return; } if (expandTrigger()) return; return CodeMirror.Pass; },
      'Shift-Tab': () => { if (session) { gotoStop(session.idx - 1); return; } return CodeMirror.Pass; },
      Esc: () => { if (session) { endSession(); return; } return CodeMirror.Pass; },
      'Cmd-/': () => { closeMenu(); const p = cm.getCursor('head'); cm.replaceRange('/', p, p, '+snippet'); cm.setCursor({line: p.line, ch: p.ch + 1}); openMenu(p, true); },
    };
    cm.addKeyMap(keys);
    cm.on('inputRead', (_, ch) => {
      if (menu || ch.text.length !== 1 || ch.text[0] !== '/') return;
      const p = ch.from, before = p.ch ? cm.getLine(p.line)[p.ch - 1] : '';
      if (before && !/[\s$(~]/.test(before)) return;
      openMenu(p, false);
    });
    cm.on('cursorActivity', onCursor);
    cm.on('blur', () => closeMenu());
    cm.on('scroll', () => { if (menu) place(); });
    fetch('/snippets.json', {cache: 'no-store'}).then(r => r.json()).then(d => {
      groups = d.groups || [];
      items = groups.flatMap(g => g.items.map(it => Object.assign({group: g.name}, it)));
      const km = {};
      items.filter(it => it.key).forEach(it => { km[it.key] = () => insertItem(it); });
      cm.addKeyMap(km);
    }).catch(e => console.error('snippets.json', e));
  }

  window.Snippets = {attach, parseBody, get items() { return items; }, get open() { return !!menu; }};
})();
