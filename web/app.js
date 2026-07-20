/* LocalAgent SPA — vanilla frontend that replicates design/redesign.dc.html and consumes /api/. */

// ----------------------------------------------------------------- state
const state = {
  theme: localStorage.getItem('la-theme') || 'dark',
  collapsedSb: localStorage.getItem('la-collapsed') === 'true',
  sessions: {},
  activeId: null,
  models: [],
  modelId: localStorage.getItem('la-model') || null,
  modelMenu: false,
  moreMenu: false,
  menuId: null,
  renamingId: null,
  renameVal: '',
  draft: '',
  sending: false,
  abortCtrl: null,
  advOpen: false,
  cfgOpen: false,
  cfgTab: 'general',
  caps: {
    web: JSON.parse(localStorage.getItem('la-cap-web') ?? 'true'),
    vault: JSON.parse(localStorage.getItem('la-cap-vault') ?? 'true'),
    html: JSON.parse(localStorage.getItem('la-cap-html') ?? 'false'),
    thinking: JSON.parse(localStorage.getItem('la-cap-thinking') ?? 'false'),
    memoria: JSON.parse(localStorage.getItem('la-cap-memoria') ?? 'true'),
  },
  temp: parseFloat(localStorage.getItem('la-temp') ?? '0.4'),
  topP: parseFloat(localStorage.getItem('la-topp') ?? '0.9'),
  maxTok: parseInt(localStorage.getItem('la-maxtok') ?? '8192', 10),
  ctx: localStorage.getItem('la-ctx') ?? '8k',
  sysPrompt: '',
  cfg: { ollamaUrl: '', vaultDir: '', tgToken: '', tgChats: '' },
  mcpServers: [],
  selectedMcps: JSON.parse(localStorage.getItem('la-mcps2') ?? '[]'),
  metaShow: JSON.parse(localStorage.getItem('la-meta') ?? 'true'),
  enterSends: JSON.parse(localStorage.getItem('la-enter') ?? 'true'),
  autoCompact: JSON.parse(localStorage.getItem('la-autocompact') ?? 'false'),
  compacting: false,
  compactNotice: null,
  copiedId: null,
  thinkOpen: {}, // msgIndex -> bool
  callsOpen: null,
  soulDraft: '',
  mcpNew: { name: '', target: '' },
  mcpError: null,
  mcpConfigs: [],      // [{name, type, target, env_keys, raw}]
  mcpEditing: null,    // name of the server being edited
  mcpEditVal: '',
  mcpImportText: '',
};

// ----------------------------------------------------------------- utilities
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => Array.from(ctx.querySelectorAll(sel));
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

function savePrefs() {
  localStorage.setItem('la-theme', state.theme);
  localStorage.setItem('la-collapsed', state.collapsedSb);
  localStorage.setItem('la-model', state.modelId || '');
  localStorage.setItem('la-cap-web', state.caps.web);
  localStorage.setItem('la-cap-vault', state.caps.vault);
  localStorage.setItem('la-cap-html', state.caps.html);
  localStorage.setItem('la-cap-thinking', state.caps.thinking);
  localStorage.setItem('la-cap-memoria', state.caps.memoria);
  localStorage.setItem('la-temp', state.temp);
  localStorage.setItem('la-topp', state.topP);
  localStorage.setItem('la-maxtok', state.maxTok);
  localStorage.setItem('la-ctx', state.ctx);
  localStorage.setItem('la-mcps2', JSON.stringify(state.selectedMcps));
  localStorage.setItem('la-meta', state.metaShow);
  localStorage.setItem('la-enter', state.enterSends);
  localStorage.setItem('la-autocompact', state.autoCompact);
}

function shortArgs(args) {
  if (!args || !Object.keys(args).length) return 'sin argumentos';
  return Object.entries(args)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
    .slice(0, 110);
}

function formatTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  if (sameDay) return d.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleDateString('es-AR', { day: 'numeric', month: 'short' });
}

// ----------------------------------------------------------------- API
async function apiGet(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

async function saveSession(name, sess) {
  await apiPost(`/api/sessions/${encodeURIComponent(name)}`, { data: sess });
}

async function deleteSession(name) {
  await fetch(`/api/sessions/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

async function renameSession(oldName, newName) {
  await apiPost(`/api/sessions/${encodeURIComponent(oldName)}/rename`, { new: newName });
}

// ----------------------------------------------------------------- lightweight markdown
function inlineMd(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_, label, url) =>
      /^(https?:|mailto:|\/|#)/i.test(url.trim())
        ? `<a href="${url}" target="_blank" rel="noopener">${label}</a>`
        : `${label} (${url})`); // schemes like javascript: are not turned into a link
}

function mdToHtml(src) {
  const rawLines = String(src ?? '').split('\n'); // esc() does not alter line breaks: indices stay aligned
  let text = esc(src);
  const lines = text.split('\n');
  const out = [];
  let i = 0;
  function flushPara(buf) {
    if (!buf.length) return;
    out.push(`<p>${inlineMd(buf.join(' '))}</p>`);
  }
  while (i < lines.length) {
    const line = lines[i];
    // code block
    if (line.startsWith('```')) {
      flushPara([]);
      const lang = line.slice(3).trim();
      const code = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) code.push(rawLines[i++]);
      i++;
      const codeText = code.join('\n');
      const copyId = 'code-' + Math.random().toString(36).slice(2, 8);
      out.push(`<div class="code-block"><div class="code-header"><span class="code-lang">${lang || 'text'} · ${codeText.length} chars</span><button class="code-copy" data-copy="${esc(codeText)}" id="${copyId}"><svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg> Copiar</button></div><pre><code>${esc(codeText)}</code></pre></div>`);
      continue;
    }
    // table
    if (line.includes('|')) {
      flushPara([]);
      const rows = [];
      while (i < lines.length && lines[i].includes('|')) { rows.push(lines[i]); i++; }
      out.push(renderTable(rows));
      continue;
    }
    // heading
    if (/^#{1,3} /.test(line)) {
      flushPara([]);
      const level = line.match(/^(#+)/)[1].length;
      out.push(`<h${level}>${inlineMd(line.replace(/^#{1,3} /, ''))}</h${level}>`);
      i++; continue;
    }
    // list
    if (/^[-*] /.test(line)) {
      flushPara([]);
      const items = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(inlineMd(lines[i].replace(/^[-*] /, '')));
        i++;
      }
      out.push(`<ul>${items.map(x => `<li>${x}</li>`).join('')}</ul>`);
      continue;
    }
    // numbered list
    if (/^\d+\. /.test(line)) {
      flushPara([]);
      const items = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        items.push(inlineMd(lines[i].replace(/^\d+\. /, '')));
        i++;
      }
      out.push(`<ol>${items.map(x => `<li>${x}</li>`).join('')}</ol>`);
      continue;
    }
    // hr
    if (/^---+$/.test(line)) { flushPara([]); out.push('<hr>'); i++; continue; }
    // blank
    if (!line.trim()) { flushPara([]); i++; continue; }
    // paragraph
    let para = [];
    while (i < lines.length && lines[i].trim() && !/^(```|#{1,3} |[-*] |\d+\. |---)/.test(lines[i]) && !lines[i].includes('|')) {
      para.push(lines[i]); i++;
    }
    flushPara(para);
  }
  flushPara([]);
  return out.join('\n');
}

function renderTable(rows) {
  const parsed = rows.map(r => r.split('|').map(c => c.trim()).filter(Boolean));
  if (parsed.length < 2) return `<p>${rows.join('<br>')}</p>`;
  const headers = parsed[0];
  const body = parsed.slice(2);
  const th = headers.map(h => `<th>${h}</th>`).join('');
  const tr = body.map(r => `<tr>${r.map(c => `<td>${inlineMd(c)}</td>`).join('')}</tr>`).join('');
  return `<div style="overflow-x:auto;margin:0 0 16px"><table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

// ----------------------------------------------------------------- main render
function render() {
  const root = $('#root');
  root.className = `lc ${state.theme}`;
  // the theme also goes on <html>: body and scrollbars are outside #root
  document.documentElement.className = state.theme === 'light' ? 'light' : '';
  const act = state.sessions[state.activeId] || { messages: [], tools: {}, mem: {}, tokens: 0, ctx: 0 };
  root.innerHTML = `
    ${renderSidebar()}
    <main style="flex:1;display:flex;flex-direction:column;min-width:0">
      ${renderHeader(act)}
      ${renderChat(act)}
      ${renderComposer()}
    </main>
    ${state.advOpen ? renderAdvanced() : ''}
    ${state.cfgOpen ? renderConfig() : ''}
  `;
  focusComposer();
  scrollToBottom();
}

function renderSidebar() {
  // most-recently-used first (like ChatGPT/Claude): new/active chats bubble to the top,
  // and the list stays stable instead of looking scrambled by number
  const sessions = Object.entries(state.sessions).sort((a, b) => (b[1].updated || 0) - (a[1].updated || 0));
  const activeId = state.activeId;
  const status = modelStatus();

  if (state.collapsedSb) {
    return `
    <aside data-screen-label="Sidebar colapsado" style="width:60px;min-width:60px;background:var(--bg1);border-right:1px solid var(--bd);display:flex;flex-direction:column;align-items:center;padding:14px 0 12px;gap:4px">
      <button data-action="toggleCollapse" aria-label="Expandir sidebar" title="Expandir" style="width:32px;height:32px;border-radius:9px;background:var(--ac);border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;margin-bottom:6px">
        <svg class="svg-icon" width="17" height="17" viewBox="0 0 24 24" fill="#fff"><path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z"></path></svg>
      </button>
      <button data-action="newChat" aria-label="Nuevo chat" title="Nuevo chat" style="width:36px;height:36px;border:1px solid var(--bd);border-radius:10px;background:transparent;color:var(--tx2);cursor:pointer;display:flex;align-items:center;justify-content:center;margin-bottom:6px">
        <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"></path></svg>
      </button>
      ${sessions.map(([name, sess]) => {
        const active = name === activeId;
        return `<button data-action="selectSpace" data-id="${esc(name)}" title="${esc(name)}" aria-label="${esc(name)}" style="width:36px;height:36px;border-radius:10px;border:1px solid ${active ? 'var(--ac)' : 'var(--bd)'};background:${active ? 'var(--bg3)' : 'transparent'};color:${active ? 'var(--tx)' : 'var(--tx2)'};font-family:inherit;font-size:13px;font-weight:600;cursor:pointer">${esc(name.trim().charAt(0).toUpperCase())}</button>`;
      }).join('')}
      <div style="flex:1"></div>
      <button data-action="openCfg" aria-label="Configuración" title="Configuración" style="width:32px;height:32px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;margin-bottom:4px">
        <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z"></path></svg>
      </button>
      <span title="${esc(status.text)}" style="width:8px;height:8px;border-radius:50%;background:${status.dot}"></span>
    </aside>`;
  }

  return `
  <aside data-screen-label="Sidebar" style="width:264px;min-width:264px;background:var(--bg1);border-right:1px solid var(--bd);display:flex;flex-direction:column">
    <div style="display:flex;align-items:center;gap:10px;padding:14px 14px 10px">
      <div style="width:28px;height:28px;border-radius:8px;background:var(--ac);display:flex;align-items:center;justify-content:center;flex:none">
        <svg class="svg-icon" width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z"></path></svg>
      </div>
      <div style="flex:1;min-width:0">
        <div style="font-weight:600;font-size:15px;letter-spacing:-.01em">LocalAgent</div>
        <div style="font-size:11px;color:var(--tx3)">100% local · sin nube</div>
      </div>
      <button data-action="toggleCollapse" aria-label="Colapsar sidebar" title="Colapsar" style="width:28px;height:28px;border:none;background:transparent;color:var(--tx3);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"></path></svg>
      </button>
    </div>
    <div style="padding:6px 12px 10px;display:flex;gap:8px">
      <button data-action="newChat" style="flex:1;display:flex;align-items:center;justify-content:center;gap:7px;height:36px;border:none;border-radius:10px;background:var(--ac);color:#fff;font-family:inherit;font-size:13.5px;font-weight:600;cursor:pointer">
        <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"></path></svg>
        Nuevo chat
      </button>
      <button data-action="clearChat" aria-label="Limpiar conversación actual" title="Limpiar conversación actual" style="width:36px;height:36px;border:1px solid var(--bd);border-radius:10px;background:transparent;color:var(--tx3);cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 10v6M14 10v6"></path></svg>
      </button>
    </div>
    <nav aria-label="Espacios" style="flex:1;overflow-y:auto;padding:2px 0 8px;display:flex;flex-direction:column;gap:1px">
      ${renderSpaceGroups(sessions, activeId)}
    </nav>
    <div style="border-top:1px solid var(--bd);padding:10px 14px;display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--tx3)">
      <span style="width:7px;height:7px;border-radius:50%;background:${status.dot};flex:none"></span>
      <span style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(status.text)}</span>
      <button data-action="openCfg" aria-label="Configuración" title="Configuración" style="width:26px;height:26px;flex:none;border:none;background:transparent;color:var(--tx3);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.9 2.9l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.9-2.9l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.9-2.9l.1.1a1.7 1.7 0 0 0 1.9.3h.1a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.2a1.7 1.7 0 0 0 1 1.5h.1a1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.9 2.9l-.1.1a1.7 1.7 0 0 0-.3 1.9v.1a1.7 1.7 0 0 0 1.5 1h.2a2 2 0 1 1 0 4h-.2a1.7 1.7 0 0 0-1.5 1z"></path></svg>
      </button>
    </div>
  </aside>`;
}

// Sessions grouped by origin channel: Web chats and Telegram chats live in the same
// SQLite store now, tagged with `channel`. Missing/unknown channel defaults to 'web'
// (all legacy sessions predate the tag). Empty groups are not rendered.
const CHANNEL_META = {
  web: { label: 'Web', icon: '💬' },
  telegram: { label: 'Telegram', icon: '✈️' },
};
const CHANNEL_ORDER = ['web', 'telegram'];

function renderSpaceGroups(sessions, activeId) {
  const groups = {};
  for (const [name, sess] of sessions) {
    const ch = sess.channel === 'telegram' ? 'telegram' : 'web';
    (groups[ch] = groups[ch] || []).push([name, sess]);
  }
  const channels = CHANNEL_ORDER.filter(ch => groups[ch]?.length);
  // any unforeseen channel value still shows up, after the known ones
  for (const ch of Object.keys(groups)) if (!channels.includes(ch)) channels.push(ch);

  return channels.map(ch => {
    const meta = CHANNEL_META[ch] || { label: ch, icon: '•' };
    const rows = groups[ch].map(([name, sess]) => renderSpaceRow(name, sess, name === activeId)).join('');
    return `
      <div style="padding:10px 20px 4px;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tx3);display:flex;align-items:center;gap:6px">
        <span aria-hidden="true">${meta.icon}</span><span>${esc(meta.label)}</span>
        <span style="opacity:.55;font-weight:500">${groups[ch].length}</span>
      </div>
      ${rows}`;
  }).join('');
}

function renderSpaceRow(name, sess, active) {
  const renaming = state.renamingId === name;
  const menuOpen = state.menuId === name;
  const sub = lastMsgPreview(sess);
  return `
  <div style="position:relative;margin:0 8px">
    ${renaming ? `
      <input data-input="rename" data-id="${esc(name)}" value="${esc(state.renameVal)}" aria-label="Renombrar espacio" style="width:100%;height:38px;border:1px solid var(--ac);border-radius:10px;background:var(--bg2);color:var(--tx);font-family:inherit;font-size:13.5px;padding:0 10px">
    ` : `
      <div role="button" tabindex="0" data-action="selectSpace" data-id="${esc(name)}" style="display:flex;align-items:center;gap:8px;padding:7px 8px 7px 10px;border-radius:10px;cursor:pointer;background:${active ? 'var(--bg3)' : 'transparent'};transition:background .12s">
        <div style="flex:1;min-width:0">
          <div style="font-size:13.5px;font-weight:500;color:${active ? 'var(--tx)' : 'var(--tx2)'};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(name)}</div>
          <div style="font-size:11.5px;color:var(--tx3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px">${esc(sub)}</div>
        </div>
        <span style="font-size:10.5px;color:var(--tx3);flex:none">${esc(formatTime(sess.updated))}</span>
        <button data-action="openMenu" data-id="${esc(name)}" aria-label="Opciones del espacio" style="width:24px;height:24px;flex:none;border:none;background:transparent;color:var(--tx3);border-radius:6px;cursor:pointer;display:flex;align-items:center;justify-content:center">
          <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6"></circle><circle cx="12" cy="12" r="1.6"></circle><circle cx="19" cy="12" r="1.6"></circle></svg>
        </button>
      </div>
    `}
    ${menuOpen ? `
      <div role="menu" style="position:absolute;right:4px;top:40px;z-index:40;background:var(--bg2);border:1px solid var(--bd);border-radius:10px;box-shadow:var(--shadow);padding:4px;min-width:150px;animation:lcIn .12s ease">
        <button role="menuitem" data-action="startRename" data-id="${esc(name)}" style="display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;color:var(--tx);font-family:inherit;font-size:13px;padding:7px 10px;border-radius:7px;cursor:pointer;text-align:left">
          <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4L8 20l-5 1 1-5zM15 5l4 4"></path></svg>
          Renombrar
        </button>
        <button role="menuitem" data-action="deleteSpace" data-id="${esc(name)}" style="display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;color:var(--err);font-family:inherit;font-size:13px;padding:7px 10px;border-radius:7px;cursor:pointer;text-align:left">
          <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"></path></svg>
          Borrar
        </button>
      </div>
    ` : ''}
  </div>`;
}

function lastMsgPreview(sess) {
  const msgs = sess?.messages || [];
  if (!msgs.length) return 'Sin mensajes';
  const last = msgs[msgs.length - 1];
  return (last.content || '').slice(0, 45).replace(/\n/g, ' ') + ((last.content || '').length > 45 ? '…' : '');
}

function modelStatus() {
  const model = state.models.find(m => m.name === state.modelId);
  if (!model) {
    const fallback = state.models.length ? 'Modelo no disponible' : 'Sin modelos';
    return { dot: 'var(--err)', text: fallback };
  }
  const dot = model.fits ? 'var(--ok)' : 'var(--cn)';
  const toolsOn = ['web', 'vault', 'html'].filter(k => state.caps[k]).length;
  const mcpsOn = state.selectedMcps.length;
  return {
    dot,
    text: `${model.short || model.name} · ${toolsOn} tools${mcpsOn ? ` · ${mcpsOn} MCP` : ''}`,
  };
}

function renderHeader(act) {
  const model = state.models.find(m => m.name === state.modelId);
  const ctxMax = ctxTokens(state.ctx);
  const ctxUsed = Math.min(act.ctx || 0, ctxMax);
  const ctxRatio = ctxUsed / ctxMax;
  const activeName = state.activeId || 'Sin espacio';
  const cur = model || { name: '...', tag: '', fits: true };
  const curDot = cur.fits ? 'var(--ok)' : 'var(--cn)';
  const ctxColor = ctxRatio > 0.85 ? 'var(--err)' : ctxRatio > 0.6 ? 'var(--cn)' : 'var(--ac)';
  const themeIcon = state.theme === 'dark'
    ? 'M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8'
    : 'M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8';
  return `
  <header data-screen-label="Header" style="height:52px;flex:none;display:flex;align-items:center;gap:10px;padding:0 16px;border-bottom:1px solid var(--bd);background:var(--bg0)">
    <h1 style="margin:0;font-size:14.5px;font-weight:600;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:280px">${esc(activeName)}</h1>
    <div style="position:relative">
      <button data-action="toggleModelMenu" aria-haspopup="listbox" aria-expanded="${state.modelMenu}" style="display:flex;align-items:center;gap:7px;height:30px;padding:0 10px;border:1px solid var(--bd);border-radius:8px;background:var(--bg1);color:var(--tx2);font-family:'IBM Plex Mono',monospace;font-size:12px;cursor:pointer">
        <span style="width:7px;height:7px;border-radius:50%;background:${curDot};flex:none"></span>
        ${esc(cur.short || cur.name || '...')}
        <span style="color:var(--tx3);font-size:11px">${esc(cur.tag || '')}</span>
        <svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"></path></svg>
      </button>
      ${state.modelMenu ? renderModelMenu(curDot) : ''}
    </div>
    <div title="Contexto usado / disponible" style="display:flex;align-items:center;gap:8px;height:30px;padding:0 10px;border:1px solid var(--bd);border-radius:8px;background:var(--bg1);color:var(--tx3);font-family:'IBM Plex Mono',monospace;font-size:11.5px">
      <span style="width:44px;height:4px;border-radius:2px;background:var(--bg3);overflow:hidden;display:inline-block"><span style="display:block;height:100%;border-radius:2px;background:${ctxColor};width:${Math.max(3, Math.round(ctxRatio * 100))}%;transition:width .3s"></span></span>
      <span>${ctxUsed >= 1000 ? (ctxUsed / 1000).toFixed(1) + 'k' : ctxUsed} / ${ctxMax >= 1000 ? (ctxMax / 1000).toFixed(0) + 'k' : ctxMax} ctx</span>
    </div>
    <div style="flex:1"></div>
    <button data-action="toggleTheme" aria-label="Cambiar tema" title="Tema claro/oscuro" style="width:32px;height:32px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center">
      <svg class="svg-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${themeIcon}"></path></svg>
    </button>
    <button data-action="openAdv" aria-label="Parámetros avanzados" title="Avanzado" style="width:32px;height:32px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center">
      <svg class="svg-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 8h10M18 8h2M4 16h2M10 16h10"></path><circle cx="16" cy="8" r="2.2"></circle><circle cx="8" cy="16" r="2.2"></circle></svg>
    </button>
    <button data-action="openCfgMcp" aria-label="Configurar MCPs" title="MCPs (${state.selectedMcps.length} activo${state.selectedMcps.length === 1 ? '' : 's'})" style="display:flex;align-items:center;gap:6px;height:30px;padding:0 11px;border:1px solid ${state.selectedMcps.length ? 'var(--ac)' : 'var(--bd)'};border-radius:8px;background:${state.selectedMcps.length ? 'var(--acbg)' : 'transparent'};color:${state.selectedMcps.length ? 'var(--ac)' : 'var(--tx3)'};font-family:inherit;font-size:12.5px;font-weight:500;cursor:pointer">
      <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 7V2M15 7V2M6 7h12v5a6 6 0 0 1-12 0zM12 18v4"></path></svg>
      MCP${state.selectedMcps.length ? ` · ${state.selectedMcps.length}` : ''}
    </button>
    <button title="Todavía sin función (quedó del diseño)" style="display:flex;align-items:center;gap:6px;height:30px;padding:0 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--tx2);font-family:inherit;font-size:12.5px;font-weight:500;cursor:pointer">
      <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17V4M6 10l6-6 6 6M4 20h16"></path></svg>
      Deploy
    </button>
    <div style="position:relative">
      <button data-action="toggleMore" aria-label="Más acciones" style="width:32px;height:32px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.7"></circle><circle cx="12" cy="12" r="1.7"></circle><circle cx="12" cy="19" r="1.7"></circle></svg>
      </button>
      ${state.moreMenu ? `
        <div role="menu" style="position:absolute;right:0;top:36px;z-index:50;background:var(--bg2);border:1px solid var(--bd);border-radius:10px;box-shadow:var(--shadow);padding:4px;min-width:180px;animation:lcIn .12s ease">
          <button role="menuitem" data-action="exportMd" style="display:block;width:100%;border:none;background:transparent;color:var(--tx);font-family:inherit;font-size:13px;padding:7px 10px;border-radius:7px;cursor:pointer;text-align:left">Exportar como .md</button>
          <button role="menuitem" data-action="exportHtml" style="display:block;width:100%;border:none;background:transparent;color:var(--tx);font-family:inherit;font-size:13px;padding:7px 10px;border-radius:7px;cursor:pointer;text-align:left">Exportar como .html</button>
          <button role="menuitem" data-action="copyChat" style="display:block;width:100%;border:none;background:transparent;color:var(--tx);font-family:inherit;font-size:13px;padding:7px 10px;border-radius:7px;cursor:pointer;text-align:left">Copiar conversación</button>
        </div>
      ` : ''}
    </div>
  </header>`;
}

function ctxTokens(label) {
  return { '4k': 4096, '8k': 8192, '32k': 32768 }[label] || 8192;
}

function renderModelMenu(curDot) {
  return `
  <div role="listbox" aria-label="Modelo local" style="position:absolute;left:0;top:36px;z-index:50;width:320px;max-height:min(64vh,460px);overflow-y:auto;background:var(--bg2);border:1px solid var(--bd);border-radius:12px;box-shadow:var(--shadow);padding:5px;animation:lcIn .12s ease">
    <div style="position:sticky;top:0;background:var(--bg2);padding:7px 10px 5px;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--tx3)">Modelos locales</div>
    ${state.models.map(m => {
      const selected = m.name === state.modelId;
      const dot = m.fits ? 'var(--ok)' : 'var(--cn)';
      const tag = m.backend || (`${m.gb} GB` + (m.fits ? '' : ' ⚠️ CPU'));
      const status = m.fits ? 'disponible' : 'CPU (lento)';
      return `
      <button role="option" aria-selected="${selected}" data-action="selectModel" data-id="${esc(m.name)}" style="display:flex;align-items:center;gap:9px;width:100%;border:none;background:${selected ? 'var(--bg3)' : 'transparent'};font-family:inherit;padding:8px 10px;border-radius:8px;cursor:pointer;text-align:left">
        <span style="width:7px;height:7px;border-radius:50%;background:${dot};flex:none"></span>
        <span style="flex:1;min-width:0">
          <span style="display:block;font-size:13px;color:var(--tx);font-family:'IBM Plex Mono',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(m.name)}</span>
          <span style="display:block;font-size:11.5px;color:var(--tx3);margin-top:1px">${esc(tag)} · ${esc(status)}</span>
        </span>
      </button>`;
    }).join('')}
  </div>`;
}

function renderChat(act) {
  const msgs = act.messages || [];
  const empty = msgs.length === 0 && !state.sending;
  const suggestions = [
    'Resume las notas nuevas del vault de esta semana',
    'Genera una landing HTML para el proyecto',
    'Busca en la web novedades de Ollama',
    'Explícame los hooks de pynput con ejemplos',
  ];
  return `
  <div data-screen-label="Conversación" style="flex:1;overflow-y:auto;min-height:0" id="chat-scroll">
    <div style="max-width:var(--cw);margin:0 auto;padding:28px 24px 12px;display:flex;flex-direction:column;gap:24px">
      ${empty ? `
        <div data-screen-label="Empty state" style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:9vh 12px 4vh;animation:lcIn .25s ease">
          <div style="width:44px;height:44px;border-radius:12px;background:var(--acbg);display:flex;align-items:center;justify-content:center;margin-bottom:16px">
            <svg class="svg-icon" width="22" height="22" viewBox="0 0 24 24" fill="var(--ac)"><path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z"></path></svg>
          </div>
          <h2 style="margin:0 0 6px;font-size:22px;font-weight:600;letter-spacing:-.02em">¿En qué trabajamos hoy?</h2>
          <p style="margin:0 0 26px;font-size:13.5px;color:var(--tx3)">Todo corre local: ${esc(state.models.find(m => m.name === state.modelId)?.short || '...')}. Nada sale de tu máquina.</p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;width:100%;max-width:560px">
            ${suggestions.map(t => `
              <button data-action="suggest" data-text="${esc(t)}" style="border:1px solid var(--bd);border-radius:12px;background:var(--bg1);color:var(--tx2);font-family:inherit;font-size:13px;line-height:1.45;padding:12px 14px;text-align:left;cursor:pointer;transition:border-color .12s">${esc(t)}</button>
            `).join('')}
          </div>
        </div>
      ` : ''}
      ${msgs.map((m, idx) => renderMessage(m, idx, act)).join('')}
      ${state.sending && !hasPendingAi(msgs) ? renderTyping() : ''}
    </div>
  </div>`;
}

function hasPendingAi(msgs) {
  const last = msgs[msgs.length - 1];
  return last && last.role === 'assistant' && last.streaming;
}

function renderTyping() {
  return `
  <div style="display:flex;flex-direction:column;gap:10px">
    <div style="display:flex;align-items:center;gap:8px">
      <div style="width:22px;height:22px;border-radius:7px;background:var(--ac);display:flex;align-items:center;justify-content:center;flex:none">
        <svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="#fff"><path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z"></path></svg>
      </div>
      <span style="font-size:12.5px;font-weight:600;color:var(--tx2)">LocalAgent</span>
    </div>
    <div style="display:flex;align-items:center;gap:5px;padding:2px 0" aria-label="Generando respuesta">
      <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite"></span>
      <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite .2s"></span>
      <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite .4s"></span>
    </div>
  </div>`;
}

function renderMessage(m, idx, sess) {
  if (m.role === 'user') {
    return `
    <div style="display:flex;justify-content:flex-end;animation:lcIn .2s ease">
      <div style="max-width:82%;background:var(--usr);border:1px solid var(--bd);border-radius:16px 16px 4px 16px;padding:10px 14px;font-size:14.5px;line-height:1.55;white-space:pre-wrap">${esc(m.content)}</div>
    </div>`;
  }
  // assistant
  const modelName = m.model || (state.models.find(mod => mod.name === state.modelId)?.short || state.modelId || '...');
  const calls = (sess.tools || {})[String(idx)] || [];
  const mems = (sess.mem || {})[String(idx)] || [];
  const meta = m.meta;
  const showThink = m.think && (m.thinkOpen || state.thinkOpen[idx]);
  const body = mdToHtml(m.content);
  const copyId = 'copy-' + idx;
  return `
  <div style="display:flex;flex-direction:column;gap:10px;animation:lcIn .2s ease">
    <div style="display:flex;align-items:center;gap:8px">
      <div style="width:22px;height:22px;border-radius:7px;background:var(--ac);display:flex;align-items:center;justify-content:center;flex:none">
        <svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="#fff"><path d="M12 2l2.4 7.6L22 12l-7.6 2.4L12 22l-2.4-7.6L2 12l7.6-2.4z"></path></svg>
      </div>
      <span style="font-size:12.5px;font-weight:600;color:var(--tx2)">LocalAgent</span>
      <span style="font-size:11px;color:var(--tx3);font-family:'IBM Plex Mono',monospace">${esc(modelName)}</span>
    </div>
    ${m.error ? `
      <div style="border:1px solid var(--err);background:var(--errbg);border-radius:12px;padding:14px 16px;display:flex;gap:12px;align-items:flex-start">
        <svg class="svg-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--err)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex:none;margin-top:1px"><path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"></path></svg>
        <div style="flex:1">
          <div style="font-size:14px;font-weight:600;color:var(--err);margin-bottom:3px">Modelo no disponible</div>
          <div style="font-size:13.5px;line-height:1.55;color:var(--tx2)">${esc(m.content)}</div>
        </div>
      </div>
    ` : ''}
    ${m.think ? `
      <div style="border:1px solid var(--bd);border-radius:10px;background:var(--bg1);padding:9px 12px">
        <button data-action="toggleThink" data-idx="${idx}" style="display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;color:var(--tx3);font-family:inherit;font-size:12.5px;font-weight:500;padding:0;cursor:pointer;text-align:left">
          <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4l1.7 4.3L18 10l-4.3 1.7L12 16l-1.7-4.3L6 10l4.3-1.7zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z"></path></svg>
          ${m.streaming && m.phase === 'think' ? 'Razonando…' : 'Razonamiento'}
          <svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left:auto;transition:transform .15s;transform:${showThink ? 'rotate(180deg)' : 'none'}"><path d="M6 9l6 6 6-6"></path></svg>
        </button>
        ${showThink ? `<div style="margin-top:7px;padding-top:8px;border-top:1px dashed var(--bd);font-size:13px;line-height:1.6;color:var(--tx3)">${esc(m.think)}</div>` : ''}
      </div>
    ` : ''}
    ${m.streaming && !m.content && !m.think ? `
      <div style="display:flex;align-items:center;gap:5px;padding:2px 0" aria-label="Generando respuesta">
        <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite .2s"></span>
        <span style="width:6px;height:6px;border-radius:50%;background:var(--tx3);animation:lcBlink 1.2s infinite .4s"></span>
      </div>
    ` : ''}
    ${m.content ? `
      <div class="msg-text" style="font-size:15px;line-height:1.65;color:var(--tx)">${body}${m.streaming ? '<span style="display:inline-block;width:8px;height:16px;background:var(--ac);border-radius:2px;margin-left:3px;vertical-align:text-bottom;animation:lcCursor .9s steps(1) infinite"></span>' : ''}</div>
    ` : ''}
    ${calls.length ? `
      <div style="border:1px solid var(--bd);border-radius:10px;background:var(--bg1);overflow:hidden">
        <button data-action="toggleCalls" data-idx="${idx}" style="display:flex;align-items:center;gap:8px;width:100%;border:none;background:transparent;color:var(--tx3);font-family:inherit;font-size:12.5px;font-weight:500;padding:9px 12px;cursor:pointer;text-align:left">
          <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.1-3.1a1 1 0 0 0 0-1.4l-1.6-1.6a1 1 0 0 0-1.4 0zM3 13l6 6M21 3l-6 6M3 3l18 18"></path></svg>
          🛠️ ${calls.length} tool${calls.length > 1 ? 's' : ''} ejecutada${calls.length > 1 ? 's' : ''}
          <span style="margin-left:auto;font-size:11px">${state.callsOpen === idx ? 'ocultar detalle' : 'ver detalle'}</span>
        </button>
        <div style="padding:0 12px 9px;display:flex;flex-direction:column;gap:4px">
          ${calls.map(c => {
            const running = m.streaming && !c.result;
            return `<div style="display:flex;align-items:baseline;gap:8px;font-size:12px;min-width:0">
              <span style="flex:none;width:6px;height:6px;border-radius:50%;align-self:center;background:${running ? 'var(--cn)' : 'var(--ok)'};${running ? 'animation:lcBlink 1.2s infinite' : ''}"></span>
              <span style="flex:none;font-family:'IBM Plex Mono',monospace;font-weight:600;color:var(--tx2)">${esc(c.tool)}</span>
              <span style="flex:1;font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--tx3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(shortArgs(c.args))}</span>
            </div>`;
          }).join('')}
        </div>
        ${state.callsOpen === idx ? `
          <div style="padding:9px 12px 11px;border-top:1px dashed var(--bd)">
            ${calls.map(c => `
              <div style="margin-bottom:8px">
                <div style="font-weight:600;font-size:13px;color:var(--tx)">${esc(c.tool)}</div>
                <div style="font-family:'IBM Plex Mono',monospace;font-size:11.5px;color:var(--tx3)">${esc(JSON.stringify(c.args).slice(0, 200))}</div>
                <div style="font-size:12px;color:var(--tx2);margin-top:2px">${esc((c.result || '').slice(0, 280))}</div>
              </div>
            `).join('')}
          </div>
        ` : ''}
      </div>
    ` : ''}
    ${mems.length ? `
      <div style="font-size:12px;color:var(--tx3)">💾 ${mems.length} recuerdo${mems.length > 1 ? 's' : ''} guardado${mems.length > 1 ? 's' : ''}: ${esc(mems.join('; ').slice(0, 120))}</div>
    ` : ''}
    <div style="display:flex;align-items:center;gap:2px;margin-top:-2px">
      ${meta && state.metaShow ? `<span style="font-size:12px;color:var(--tx3);font-family:'IBM Plex Mono',monospace;margin-right:10px">${esc(meta.secs)}s · ${esc(meta.gen)} tokens · ${esc(meta.tps)} tok/s${m.recall ? ` · 🧠 ${esc(m.recall)} recordado${m.recall > 1 ? 's' : ''}` : ''}</span>` : ''}
      <button data-action="copyMsg" data-idx="${idx}" id="${copyId}" aria-label="Copiar mensaje" title="Copiar" style="width:28px;height:28px;border:none;background:transparent;color:var(--tx3);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="11" height="11" rx="2"></rect><path d="M5 15V5a2 2 0 0 1 2-2h10"></path></svg>
      </button>
      <button data-action="editMsg" data-idx="${idx}" aria-label="Editar mensaje" title="Editar" style="width:28px;height:28px;border:none;background:transparent;color:var(--tx3);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center">
        <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4L8 20l-5 1 1-5z"></path></svg>
      </button>
    </div>
  </div>`;
}

function renderComposer() {
  const draftOk = state.draft.trim().length > 0;
  const capDefs = [
    { k: 'web', label: 'Web', tip: 'El modelo puede buscar en la web y leer páginas (web_search / web_fetch)', icon: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M3 12h18M12 3c-2.7 2.6-2.7 15.4 0 18M12 3c2.7 2.6 2.7 15.4 0 18' },
    { k: 'vault', label: 'Vault', tip: 'Puede buscar y leer tus notas de Obsidian (vault_search)', icon: 'M6 3h13v15H8a2 2 0 0 0-2 2V3M6 20a2 2 0 0 1 2-2h11' },
    { k: 'html', label: 'HTML', tip: 'Puede generar documentos/páginas HTML (write_html)', icon: 'M8 8l-4 4 4 4M16 8l4 4-4 4M14 5l-4 14' },
    { k: 'thinking', label: 'Thinking', tip: 'Razonamiento extendido antes de responder — solo en modelos que lo soportan; más lento', icon: 'M12 4l1.7 4.3L18 10l-4.3 1.7L12 16l-1.7-4.3L6 10l4.3-1.7L12 4M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15' },
    { k: 'memoria', label: 'Memoria', tip: 'Recuerda hechos entre chats: guarda datos tuyos y los trae cuando vienen al caso', icon: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3' },
  ];
  return `
  <div data-screen-label="Compositor" style="flex:none;padding:8px 24px 10px;background:var(--bg0)">
    <div style="max-width:var(--cw);margin:0 auto">
      <div id="composer-box" style="background:var(--bg2);border:1px solid ${state.taFocus ? 'var(--ac)' : 'var(--bd)'};border-radius:16px;padding:12px 12px 10px;transition:border-color .15s;box-shadow:0 2px 12px rgba(0,0,0,.12)">
        <textarea data-input="draft" rows="1" placeholder="Pregunta lo que sea — el modelo decide si usa web, vault o tools…" aria-label="Mensaje" style="display:block;width:100%;border:none;background:transparent;color:var(--tx);font-family:inherit;font-size:14.5px;line-height:1.5;resize:none;min-height:24px;max-height:200px;padding:2px 4px 8px">${esc(state.draft)}</textarea>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          ${capDefs.map(c => {
            const on = state.caps[c.k];
            return `<button data-action="toggleCap" data-k="${c.k}" title="${c.tip}" aria-pressed="${on}" style="display:flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:999px;font-family:inherit;font-size:12.5px;font-weight:500;cursor:pointer;border:1px solid ${on ? 'var(--ac)' : 'var(--bd)'};color:${on ? 'var(--ac)' : 'var(--tx3)'};background:${on ? 'var(--acbg)' : 'transparent'};transition:all .12s">
              <svg class="svg-icon" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="${c.icon}"></path></svg>
              ${c.label}
            </button>`;
          }).join('')}
          <div style="flex:1"></div>
          <span id="composer-count" style="font-size:11px;color:var(--tx3);font-family:'IBM Plex Mono',monospace;visibility:${draftOk ? 'visible' : 'hidden'}">${state.draft.length} car.</span>
          ${!state.sending ? `
            <button id="composer-send" data-action="send" ${draftOk && !state.compacting ? '' : 'disabled'} aria-label="Enviar mensaje" title="${state.compacting ? 'Compactando…' : 'Enviar (Enter)'}" style="width:34px;height:34px;border:none;border-radius:10px;background:${draftOk && !state.compacting ? 'var(--ac)' : 'var(--bg3)'};color:${draftOk && !state.compacting ? '#fff' : 'var(--tx3)'};cursor:${draftOk && !state.compacting ? 'pointer' : 'default'};display:flex;align-items:center;justify-content:center;transition:background .15s">
              <svg class="svg-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"></path></svg>
            </button>
          ` : `
            <button data-action="stop" aria-label="Detener generación" title="Detener" style="width:34px;height:34px;border:1px solid var(--bd2);border-radius:10px;background:var(--bg3);color:var(--tx);cursor:pointer;display:flex;align-items:center;justify-content:center">
              <svg class="svg-icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"></rect></svg>
            </button>
          `}
        </div>
      </div>
      ${(() => {
        const msgs = (state.sessions[state.activeId]?.messages || []).length;
        const canCompact = msgs > 4;
        const btn = 'display:inline-flex;align-items:center;gap:4px;height:24px;padding:0 9px;border:1px solid var(--bd);border-radius:7px;background:var(--bg1);color:var(--tx2);font-family:inherit;font-size:11.5px;font-weight:500';
        const st = modelStatus();
        return `
      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:7px 12px;padding:8px 4px 0;font-size:11px;color:var(--tx3)">
        <button data-action="newChat" aria-label="Nuevo chat" title="Empezar un chat nuevo" style="${btn};cursor:pointer">＋ Nuevo</button>
        <button data-action="compact" ${state.compacting ? 'disabled' : ''} aria-label="Compactar conversación" title="${canCompact ? 'Resumir la conversación para liberar contexto' : 'Todavía no hay suficiente conversación para compactar'}" style="${btn};cursor:${state.compacting ? 'default' : 'pointer'};opacity:${state.compacting ? '.6' : (canCompact ? '1' : '.5')}">⤺ ${state.compacting ? 'Compactando…' : 'Compactar'}</button>
        ${state.compactNotice ? `<span style="color:var(--ok);font-weight:500">${esc(state.compactNotice)}</span>` : ''}
        <div style="margin-left:auto;display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px">
          <span><kbd style="font-family:'IBM Plex Mono',monospace;font-size:10px;border:1px solid var(--bd);border-radius:4px;padding:1px 4px;background:var(--bg1)">Enter</kbd> envía · <kbd style="font-family:'IBM Plex Mono',monospace;font-size:10px;border:1px solid var(--bd);border-radius:4px;padding:1px 4px;background:var(--bg1)">⇧Enter</kbd> salto</span>
          <span style="display:flex;align-items:center;gap:6px"><span style="width:6px;height:6px;border-radius:50%;background:${st.dot}"></span>${esc(st.text)}</span>
        </div>
      </div>`;
      })()}
    </div>
  </div>`;
}

function renderAdvanced() {
  return `
  <div>
    <div data-action="closeAdv" style="position:absolute;inset:0;background:rgba(0,0,0,.45);z-index:60"></div>
    <aside data-screen-label="Panel Avanzado" role="dialog" aria-label="Parámetros avanzados" style="position:absolute;top:0;right:0;bottom:0;width:340px;background:var(--bg1);border-left:1px solid var(--bd);z-index:70;display:flex;flex-direction:column;animation:lcSlide .2s ease;box-shadow:var(--shadow)">
      <div style="display:flex;align-items:center;padding:16px 18px 12px;border-bottom:1px solid var(--bd)">
        <div>
          <div style="font-size:15px;font-weight:600">Avanzado</div>
          <div style="font-size:11.5px;color:var(--tx3);margin-top:1px">Parámetros de ${esc(state.models.find(m => m.name === state.modelId)?.short || '...')}</div>
        </div>
        <button data-action="closeAdv" aria-label="Cerrar panel" style="margin-left:auto;width:30px;height:30px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center">
          <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>
        </button>
      </div>
      <div style="flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:20px">
        <label style="display:block" title="Controla la aleatoriedad. Más alto = respuestas más creativas y variadas; más bajo = más predecibles y consistentes. Recomendado: 0.2–0.4 para tools/datos/código, 0.7–1.0 para escritura creativa.">
          <span style="display:flex;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:8px">Temperatura<span style="margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--tx)">${state.temp}</span></span>
          <input data-input="temp" type="range" min="0" max="2" step="0.1" value="${state.temp}" style="width:100%;accent-color:var(--ac)">
        </label>
        <label style="display:block" title="Núcleo de probabilidad: el modelo elige solo entre las palabras más probables que juntas suman este porcentaje. Más bajo = más conservador y repetitivo. Déjalo en 0.9 salvo que sepas por qué cambiarlo.">
          <span style="display:flex;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:8px">Top-p<span style="margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--tx)">${state.topP}</span></span>
          <input data-input="topp" type="range" min="0" max="1" step="0.05" value="${state.topP}" style="width:100%;accent-color:var(--ac)">
        </label>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <label style="display:block" title="Largo máximo de la respuesta, en tokens. Si te corta respuestas largas, súbelo (~4 caracteres ≈ 1 token).">
            <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Máx. tokens</span>
            <input data-input="maxtok" type="number" value="${state.maxTok}" style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:13px;padding:0 10px">
          </label>
          <label style="display:block" title="Ventana de contexto (num_ctx): cuánta conversación y resultados de tools recuerda el modelo en una sola llamada. Más contexto = más memoria pero más VRAM.">
            <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Contexto</span>
            <select data-input="ctx" style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:13px;padding:0 8px">
              ${['4k', '8k', '32k'].map(v => `<option value="${v}" ${state.ctx === v ? 'selected' : ''}>${{ '4k': '4 096', '8k': '8 192', '32k': '32 768' }[v]}</option>`).join('')}
            </select>
          </label>
        </div>
        <label style="display:block">
          <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">System prompt</span>
          <textarea data-input="sysprompt" rows="6" style="width:100%;border:1px solid var(--bd);border-radius:10px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;line-height:1.55;padding:10px;resize:vertical">${esc(state.sysPrompt)}</textarea>
        </label>
      </div>
      <div style="padding:14px 18px;border-top:1px solid var(--bd);display:flex;gap:10px">
        <button data-action="resetAdv" style="height:36px;padding:0 14px;border:1px solid var(--bd);border-radius:9px;background:transparent;color:var(--tx2);font-family:inherit;font-size:13px;font-weight:500;cursor:pointer">Restablecer</button>
        <button data-action="closeAdv" style="flex:1;height:36px;border:none;border-radius:9px;background:var(--ac);color:#fff;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer">Listo</button>
      </div>
    </aside>
  </div>`;
}

function renderConfig() {
  const tabs = [
    { id: 'general', label: 'General' },
    { id: 'mcp', label: 'MCPs' },
    { id: 'agent', label: 'Agente' },
    { id: 'tg', label: 'Telegram' },
  ];
  return `
  <div>
    <div data-action="closeCfg" style="position:absolute;inset:0;background:rgba(0,0,0,.45);z-index:80"></div>
    <div data-screen-label="Configuración" role="dialog" aria-label="Configuración" style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:520px;max-width:92vw;max-height:86vh;overflow-y:auto;background:var(--bg1);border:1px solid var(--bd);border-radius:16px;z-index:90;box-shadow:var(--shadow);animation:lcInModal .15s ease">
      <div style="display:flex;align-items:center;padding:16px 20px 12px;border-bottom:1px solid var(--bd)">
        <div style="font-size:15px;font-weight:600">Configuración</div>
        <button data-action="closeCfg" aria-label="Cerrar" style="margin-left:auto;width:30px;height:30px;border:none;background:transparent;color:var(--tx3);border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center">
          <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"></path></svg>
        </button>
      </div>
      <div style="display:flex;gap:2px;padding:8px 14px 0;border-bottom:1px solid var(--bd)">
        ${tabs.map(t => `
          <button data-action="cfgTab" data-tab="${t.id}" style="height:36px;padding:0 12px;border:none;background:transparent;color:${state.cfgTab === t.id ? 'var(--tx)' : 'var(--tx3)'};font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;border-bottom:2px solid ${state.cfgTab === t.id ? 'var(--ac)' : 'transparent'};margin-bottom:-1px">${t.label}</button>
        `).join('')}
      </div>
      <div style="padding:18px 20px;display:flex;flex-direction:column;gap:22px">
        ${state.cfgTab === 'general' ? renderCfgGeneral() : ''}
        ${state.cfgTab === 'mcp' ? renderCfgMcp() : ''}
        ${state.cfgTab === 'agent' ? renderCfgAgent() : ''}
        ${state.cfgTab === 'tg' ? renderCfgTg() : ''}
      </div>
      <div style="padding:14px 20px;border-top:1px solid var(--bd);display:flex">
        <button data-action="closeCfg" style="flex:1;height:36px;border:none;border-radius:9px;background:var(--ac);color:#fff;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer">Listo</button>
      </div>
    </div>
  </div>`;
}

function renderCfgGeneral() {
  return `
  <div style="display:flex;flex-direction:column;gap:12px">
    <div style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tx3)">Conexión</div>
    <label style="display:block">
      <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Endpoint de Ollama</span>
      <input value="${esc(state.cfg.ollamaUrl)}" readonly style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
    </label>
    <label style="display:block">
      <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Carpeta del vault (Obsidian)</span>
      <input value="${esc(state.cfg.vaultDir)}" readonly style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
    </label>
  </div>
  <div style="display:flex;flex-direction:column;gap:12px">
    <div style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tx3)">Apariencia</div>
    <div style="display:flex;align-items:center;gap:10px">
      <span style="flex:1;font-size:13px;font-weight:500;color:var(--tx2)">Tema</span>
      <div style="display:flex;border:1px solid var(--bd);border-radius:9px;overflow:hidden">
        <button data-action="setTheme" data-theme="dark" style="height:30px;padding:0 14px;border:none;background:${state.theme === 'dark' ? 'var(--acbg)' : 'transparent'};color:${state.theme === 'dark' ? 'var(--ac)' : 'var(--tx3)'};font-family:inherit;font-size:12.5px;font-weight:500;cursor:pointer">Oscuro</button>
        <button data-action="setTheme" data-theme="light" style="height:30px;padding:0 14px;border:none;border-left:1px solid var(--bd);background:${state.theme === 'light' ? 'var(--acbg)' : 'transparent'};color:${state.theme === 'light' ? 'var(--ac)' : 'var(--tx3)'};font-family:inherit;font-size:12.5px;font-weight:500;cursor:pointer">Claro</button>
      </div>
    </div>
  </div>
  <div style="display:flex;flex-direction:column;gap:14px">
    <div style="font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tx3)">Comportamiento</div>
    <div style="display:flex;align-items:center;gap:10px">
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500;color:var(--tx2)">Enter envía el mensaje</div>
        <div style="font-size:11.5px;color:var(--tx3)">Si está apagado, Enter hace salto de línea.</div>
      </div>
      <button data-action="toggleEnter" role="switch" aria-checked="${state.enterSends}" style="width:36px;height:21px;border-radius:999px;border:none;cursor:pointer;background:${state.enterSends ? 'var(--ac)' : 'var(--bg3)'};position:relative;transition:background .15s;flex:none">
        <span style="position:absolute;top:2.5px;left:${state.enterSends ? '17.5px' : '2.5px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s"></span>
      </button>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500;color:var(--tx2)">Mostrar metadata</div>
        <div style="font-size:11.5px;color:var(--tx3)">Tiempo, tokens y tok/s bajo cada respuesta.</div>
      </div>
      <button data-action="toggleMeta" role="switch" aria-checked="${state.metaShow}" style="width:36px;height:21px;border-radius:999px;border:none;cursor:pointer;background:${state.metaShow ? 'var(--ac)' : 'var(--bg3)'};position:relative;transition:background .15s;flex:none">
        <span style="position:absolute;top:2.5px;left:${state.metaShow ? '17.5px' : '2.5px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s"></span>
      </button>
    </div>
    <div style="display:flex;align-items:center;gap:10px">
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500;color:var(--tx2)">Auto-compactar contexto</div>
        <div style="font-size:11.5px;color:var(--tx3)">Al llegar al 85% del contexto, resume automáticamente la conversación.</div>
      </div>
      <button data-action="toggleAutoCompact" role="switch" aria-checked="${state.autoCompact}" style="width:36px;height:21px;border-radius:999px;border:none;cursor:pointer;background:${state.autoCompact ? 'var(--ac)' : 'var(--bg3)'};position:relative;transition:background .15s;flex:none">
        <span style="position:absolute;top:2.5px;left:${state.autoCompact ? '17.5px' : '2.5px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s"></span>
      </button>
    </div>
  </div>`;
}

function renderCfgMcp() {
  return `
  <div style="display:flex;flex-direction:column;gap:10px">
    <div style="font-size:12.5px;color:var(--tx3);line-height:1.5">Servidores MCP declarados en el <code style="font-family:'IBM Plex Mono',monospace;font-size:11.5px;background:var(--bg3);border-radius:5px;padding:1px 6px">mcp.json</code> del proyecto. Se conectan al iniciar cada chat.</div>
    ${state.mcpServers.map(name => {
      const on = state.selectedMcps.includes(name);
      const conf = state.mcpConfigs.find(c => c.name === name) || { type: '?', target: '', env_keys: [] };
      const editing = state.mcpEditing === name;
      return `
      <div style="border:1px solid ${editing ? 'var(--ac)' : 'var(--bd)'};border-radius:10px;background:var(--bg2);overflow:hidden">
        <div style="display:flex;align-items:center;gap:10px;padding:10px 12px">
          <span style="width:7px;height:7px;border-radius:50%;background:${on ? 'var(--ok)' : 'var(--tx3)'};flex:none"></span>
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:500;font-family:'IBM Plex Mono',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(name)}</div>
            <div style="font-size:11px;color:var(--tx3);font-family:'IBM Plex Mono',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(conf.type)} · ${esc(conf.target) || '(sin destino)'}${conf.env_keys.length ? ` · env: ${esc(conf.env_keys.join(', '))}` : ''}</div>
          </div>
          <button data-action="editMcp" data-name="${esc(name)}" aria-label="Editar ${esc(name)}" title="Ver / editar configuración" style="width:28px;height:28px;border:none;background:transparent;color:${editing ? 'var(--ac)' : 'var(--tx3)'};border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none">
            <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3l4 4L8 20l-5 1 1-5z"></path></svg>
          </button>
          <button data-action="toggleMcp" data-name="${esc(name)}" role="switch" aria-checked="${on}" title="${on ? 'Activo: sus tools se ofrecen al modelo' : 'Inactivo'}" style="width:36px;height:21px;border-radius:999px;border:none;cursor:pointer;background:${on ? 'var(--ac)' : 'var(--bg3)'};position:relative;transition:background .15s;flex:none">
            <span style="position:absolute;top:2.5px;left:${on ? '17.5px' : '2.5px'};width:16px;height:16px;border-radius:50%;background:#fff;transition:left .15s"></span>
          </button>
          <button data-action="delMcp" data-name="${esc(name)}" aria-label="Quitar ${esc(name)}" title="Quitar del mcp.json" style="width:28px;height:28px;border:none;background:transparent;color:var(--tx3);border-radius:7px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex:none">
            <svg class="svg-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3"></path></svg>
          </button>
        </div>
        ${editing ? `
          <div style="border-top:1px solid var(--bd);padding:10px 12px;display:flex;flex-direction:column;gap:8px">
            <span style="font-size:11.5px;color:var(--tx3)">Config JSON completa del server (incluye env con sus valores).</span>
            <textarea data-input="mcpEdit" rows="8" spellcheck="false" style="width:100%;border:1px solid var(--bd);border-radius:8px;background:var(--bg1);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:8px 10px;resize:vertical">${esc(state.mcpEditVal)}</textarea>
            ${state.mcpError ? `<div style="font-size:12px;color:var(--err)">${esc(state.mcpError)}</div>` : ''}
            <div style="display:flex;gap:8px">
              <button data-action="saveMcp" data-name="${esc(name)}" style="height:30px;padding:0 14px;border:none;border-radius:8px;background:var(--ac);color:#fff;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer">Guardar</button>
              <button data-action="cancelMcp" style="height:30px;padding:0 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--tx3);font-family:inherit;font-size:12px;cursor:pointer">Cancelar</button>
            </div>
          </div>
        ` : ''}
      </div>`;
    }).join('') || '<div style="font-size:13px;color:var(--tx3)">No hay MCPs configurados.</div>'}
    <div style="border:1px dashed var(--bd2);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px">
      <div style="font-size:12px;font-weight:600;color:var(--tx2)">Agregar servidor</div>
      <input data-input="mcpName" value="${esc(state.mcpNew?.name || '')}" placeholder="nombre (ej: agentic-memory-mcp)" title="Nombre del server: letras, números, - y _" style="width:100%;height:34px;border:1px solid var(--bd);border-radius:8px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
      <input data-input="mcpTarget" value="${esc(state.mcpNew?.target || '')}" placeholder="http://host:puerto/mcp  ó  comando args…" title="URL http(s) para servers remotos, o el comando con argumentos para servers stdio locales" style="width:100%;height:34px;border:1px solid var(--bd);border-radius:8px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
      ${state.mcpError && !state.mcpEditing ? `<div style="font-size:12px;color:var(--err)">${esc(state.mcpError)}</div>` : ''}
      <button data-action="addMcp" style="height:32px;border:none;border-radius:8px;background:var(--ac);color:#fff;font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer">Agregar</button>
    </div>
    <div style="border:1px dashed var(--bd2);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px">
      <div style="font-size:12px;font-weight:600;color:var(--tx2)">Importar</div>
      <div style="font-size:11.5px;color:var(--tx3);line-height:1.5">Pega uno o varios servers (formato <code style="font-family:'IBM Plex Mono',monospace;font-size:11px;background:var(--bg3);border-radius:5px;padding:1px 5px">mcpServers</code> de Claude). Se agregan o reemplazan por nombre.</div>
      <textarea data-input="mcpImport" rows="6" spellcheck="false" placeholder='{"mcpServers": {"mi-server": {"command": "npx", "args": ["-y", "algo"]}}}' style="width:100%;border:1px solid var(--bd);border-radius:8px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:8px 10px;resize:vertical">${esc(state.mcpImportText)}</textarea>
      ${state.mcpError && !state.mcpEditing ? `<div style="font-size:12px;color:var(--err)">${esc(state.mcpError)}</div>` : ''}
      <button data-action="importMcps" style="height:32px;border:none;border-radius:8px;background:var(--ac);color:#fff;font-family:inherit;font-size:12.5px;font-weight:600;cursor:pointer">Importar</button>
    </div>
  </div>`;
}

function renderCfgAgent() {
  return `
  <div style="display:flex;flex-direction:column;gap:10px">
    <div style="font-size:12.5px;color:var(--tx3);line-height:1.5">Archivo que define la personalidad del agente. Se recarga en caliente al guardar.</div>
    <div style="border:1px solid var(--bd);border-radius:10px;background:var(--bg2);overflow:hidden">
      <div style="display:flex;align-items:center;gap:10px;padding:10px 12px">
        <svg class="svg-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="var(--tx3)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="flex:none"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6"></path></svg>
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:500;font-family:'IBM Plex Mono',monospace">soul.md</div>
          <div style="font-size:11.5px;color:var(--tx3)">Personalidad y reglas base</div>
        </div>
        <button data-action="editSoul" style="height:30px;padding:0 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--tx2);font-family:inherit;font-size:12px;font-weight:500;cursor:pointer;flex:none">${state.soulEditing ? 'Cerrar' : 'Editar'}</button>
      </div>
      ${state.soulEditing ? `
        <textarea data-input="soul" rows="8" aria-label="Contenido de soul.md" style="display:block;width:100%;border:none;border-top:1px solid var(--bd);background:var(--bg1);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;line-height:1.6;padding:12px;resize:vertical">${esc(state.soulDraft)}</textarea>
        <div style="display:flex;gap:8px;padding:10px 12px;border-top:1px solid var(--bd)">
          <button data-action="saveSoul" style="height:30px;padding:0 14px;border:none;border-radius:8px;background:var(--ac);color:#fff;font-family:inherit;font-size:12px;font-weight:600;cursor:pointer">Guardar</button>
          <button data-action="cancelSoul" style="height:30px;padding:0 12px;border:1px solid var(--bd);border-radius:8px;background:transparent;color:var(--tx3);font-family:inherit;font-size:12px;cursor:pointer">Cancelar</button>
        </div>
      ` : ''}
    </div>
  </div>`;
}

function renderCfgTg() {
  return `
  <div style="display:flex;flex-direction:column;gap:12px">
    <div style="font-size:12px;color:var(--tx3);line-height:1.55;border:1px solid var(--bd);border-radius:10px;background:var(--bg1);padding:10px 12px">El bot de Telegram se configura con variables de entorno y se arranca con <code style="font-family:'IBM Plex Mono',monospace;font-size:11px;background:var(--bg3);border-radius:5px;padding:1px 5px">run-bot.sh</code>. Desde la web se muestra el estado de solo lectura.</div>
    <label style="display:block">
      <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Bot token</span>
      <input value="${esc(state.cfg.tgToken || '')}" readonly style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
    </label>
    <label style="display:block">
      <span style="display:block;font-size:13px;font-weight:500;color:var(--tx2);margin-bottom:6px">Chat IDs permitidos</span>
      <input value="${esc(state.cfg.tgChats || '')}" readonly style="width:100%;height:36px;border:1px solid var(--bd);border-radius:9px;background:var(--bg2);color:var(--tx);font-family:'IBM Plex Mono',monospace;font-size:12.5px;padding:0 10px">
    </label>
  </div>`;
}

// ----------------------------------------------------------------- events
function attachEvents() {
  const root = $('#root');

  // clicks with data-action
  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const idx = btn.dataset.idx ? parseInt(btn.dataset.idx, 10) : null;
    switch (action) {
      case 'selectSpace': selectSpace(id); break;
      case 'newChat': newChat(); break;
      case 'clearChat': clearChat(); break;
      case 'toggleCollapse': state.collapsedSb = !state.collapsedSb; savePrefs(); render(); break;
      case 'openCfg': state.cfgOpen = true; render(); break;
      case 'openCfgMcp': state.cfgOpen = true; state.cfgTab = 'mcp'; render(); break;
      case 'addMcp': await addMcp(); break;
      case 'delMcp': await delMcp(btn.dataset.name); break;
      case 'editMcp': {
        const n = btn.dataset.name;
        if (state.mcpEditing === n) { state.mcpEditing = null; }
        else {
          state.mcpEditing = n;
          const conf = state.mcpConfigs.find(c => c.name === n);
          state.mcpEditVal = JSON.stringify(conf?.raw ?? {}, null, 2);
          state.mcpError = null;
        }
        render();
        break;
      }
      case 'cancelMcp': state.mcpEditing = null; state.mcpError = null; render(); break;
      case 'saveMcp': await saveMcp(btn.dataset.name); break;
      case 'importMcps': await importMcps(); break;
      case 'closeCfg': state.cfgOpen = false; state.soulEditing = false; render(); break;
      case 'openMenu':
        e.stopPropagation();
        state.menuId = state.menuId === id ? null : id;
        render();
        break;
      case 'startRename':
        e.stopPropagation();
        state.renamingId = id;
        state.renameVal = id;
        state.menuId = null;
        render();
        setTimeout(() => $('[data-input="rename"]')?.focus(), 0);
        break;
      case 'deleteSpace': await deleteSpace(id); break;
      case 'toggleModelMenu':
        e.stopPropagation();
        state.modelMenu = !state.modelMenu;
        state.moreMenu = false;
        render();
        break;
      case 'selectModel': selectModel(btn.dataset.id); break;
      case 'toggleMore':
        e.stopPropagation();
        state.moreMenu = !state.moreMenu;
        state.modelMenu = false;
        render();
        break;
      case 'toggleTheme': state.theme = state.theme === 'dark' ? 'light' : 'dark'; savePrefs(); render(); break;
      case 'openAdv': state.advOpen = true; render(); break;
      case 'closeAdv': state.advOpen = false; render(); break;
      case 'resetAdv':
        state.temp = 0.4; state.topP = 0.9; state.maxTok = 8192; state.ctx = '8k';
        savePrefs(); render();
        break;
      case 'toggleCap':
        state.caps[btn.dataset.k] = !state.caps[btn.dataset.k];
        savePrefs(); render();
        break;
      case 'send': sendMessage(); break;
      case 'stop': stopMessage(); break;
      case 'compact': compactChat(); break;
      case 'toggleAutoCompact': state.autoCompact = !state.autoCompact; savePrefs(); render(); break;
      case 'suggest':
        state.draft = btn.dataset.text;
        render();
        sendMessage();
        break;
      case 'toggleThink':
        state.thinkOpen[idx] = !state.thinkOpen[idx];
        render();
        break;
      case 'toggleCalls':
        state.callsOpen = state.callsOpen === idx ? null : idx;
        render();
        break;
      case 'copyMsg':
        await copyText(idx);
        break;
      case 'copyCode':
        await navigator.clipboard.writeText(btn.dataset.copy || '');
        state.copiedId = btn.id;
        setTimeout(() => { state.copiedId = null; render(); }, 1600);
        render();
        break;
      case 'exportMd': exportChat('md'); break;
      case 'exportHtml': exportChat('html'); break;
      case 'copyChat': copyChat(); break;
      case 'editMsg': editMessage(idx); break;
      case 'cfgTab': state.cfgTab = btn.dataset.tab; render(); break;
      case 'setTheme':
        state.theme = btn.dataset.theme;
        savePrefs();
        render();
        break;
      case 'toggleEnter': state.enterSends = !state.enterSends; savePrefs(); render(); break;
      case 'toggleMeta': state.metaShow = !state.metaShow; savePrefs(); render(); break;
      case 'toggleMcp': toggleMcp(btn.dataset.name); break;
      case 'editSoul':
        state.soulEditing = !state.soulEditing;
        if (state.soulEditing) state.soulDraft = state.sysPrompt;
        render();
        break;
      case 'saveSoul': await saveSoul(); break;
      case 'cancelSoul': state.soulEditing = false; render(); break;
    }
  });

  // inputs
  root.addEventListener('input', (e) => {
    const t = e.target;
    const input = t.dataset.input;
    if (!input) return;
    switch (input) {
      case 'draft':
        state.draft = t.value;
        updateComposer();
        break;
      case 'rename': state.renameVal = t.value; break;
      case 'temp': state.temp = parseFloat(t.value); savePrefs(); render(); break;
      case 'topp': state.topP = parseFloat(t.value); savePrefs(); render(); break;
      case 'maxtok': state.maxTok = parseInt(t.value, 10) || 0; savePrefs(); render(); break;
      case 'ctx': state.ctx = t.value; savePrefs(); render(); break;
      case 'sysprompt': state.sysPrompt = t.value; break;
      case 'soul': state.soulDraft = t.value; break;
      case 'mcpName': state.mcpNew.name = t.value; break;
      case 'mcpTarget': state.mcpNew.target = t.value; break;
      case 'mcpEdit': state.mcpEditVal = t.value; break;
      case 'mcpImport': state.mcpImportText = t.value; break;
      case 'rename': state.renameVal = t.value; break;
    }
  });

  root.addEventListener('keydown', (e) => {
    const t = e.target;
    if (t.dataset.input === 'rename') {
      if (e.key === 'Enter') { e.preventDefault(); commitRename(t.dataset.id); }
      if (e.key === 'Escape') { state.renamingId = null; render(); }
      return;
    }
    if (t.dataset.input === 'draft') {
      if (e.key === 'Enter' && !e.shiftKey && state.enterSends) {
        e.preventDefault();
        if (state.draft.trim() && !state.sending && !state.compacting) sendMessage();
      }
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !state.enterSends) {
        e.preventDefault();
        if (state.draft.trim() && !state.sending && !state.compacting) sendMessage();
      }
    }
  });

  root.addEventListener('focusin', (e) => {
    if (e.target.dataset.input === 'draft') { state.taFocus = true; updateComposer(); }
  });
  root.addEventListener('focusout', (e) => {
    if (e.target.dataset.input === 'draft') { state.taFocus = false; updateComposer(); }
  });

}

// ----------------------------------------------------------------- actions
function selectSpace(name) {
  state.activeId = name;
  state.menuId = null;
  render();
}

let _newChatLock = false;
async function newChat() {
  if (_newChatLock) return;
  _newChatLock = true;
  try {
    const base = 'Chat ';
    let n = 1;
    while (state.sessions[base + n]) n++;
    const name = base + n;
    state.sessions[name] = { messages: [], tools: {}, mem: {}, tokens: 0, ctx: 0, channel: 'web', updated: Date.now() / 1000 };
    state.activeId = name;
    await saveSession(name, state.sessions[name]);
    render();
  } finally {
    setTimeout(() => { _newChatLock = false; }, 300);
  }
}

async function clearChat() {
  const name = state.activeId;
  if (!name) return;
  state.sessions[name] = { messages: [], tools: {}, mem: {}, tokens: 0, ctx: 0, channel: 'web', updated: Date.now() / 1000 };
  await saveSession(name, state.sessions[name]);
  render();
}

function flashNotice(text, ms = 2500) {
  state.compactNotice = text;
  render();
  setTimeout(() => { state.compactNotice = null; render(); }, ms);
}

async function compactChat() {
  const name = state.activeId;
  if (!name || state.compacting) return;
  const sess = state.sessions[name];
  // nothing to compact on a short chat — give feedback instead of silently doing nothing
  if (!sess || (sess.messages || []).length <= 4) {
    flashNotice('Nada para compactar todavía (conversación corta)');
    return;
  }
  if (!state.modelId) { alert('Selecciona un modelo primero.'); return; }

  state.compacting = true;
  render();
  try {
    const data = await apiPost('/api/compact', { session: name, model: state.modelId, keep: 4 });
    if (data.compacted && data.session) {
      state.sessions[name] = data.session;
      flashNotice('✓ Conversación compactada');
    }
  } catch (e) {
    alert(`No se pudo compactar: ${e.message}`);
  } finally {
    state.compacting = false;
    render();
  }
}

async function commitRename(oldName) {
  const newName = state.renameVal.trim();
  if (!newName || newName === oldName) { state.renamingId = null; render(); return; }
  state.renamingId = null;
  try {
    // backend first: if the name already exists (409) we don't touch local state
    await renameSession(oldName, newName);
    const sess = state.sessions[oldName];
    delete state.sessions[oldName];
    state.sessions[newName] = sess;
    state.activeId = newName;
  } catch (e) {
    alert(`No se pudo renombrar: ${e.message}`);
  }
  render();
}

async function deleteSpace(name) {
  if (!confirm(`¿Borrar "${name}"?`)) return;
  delete state.sessions[name];
  await deleteSession(name);
  const remaining = Object.keys(state.sessions);
  state.activeId = remaining[0] || null;
  if (!state.activeId) await newChat();
  render();
}

function selectModel(name) {
  state.modelId = name;
  state.modelMenu = false;
  savePrefs();
  render();
}

async function addMcp() {
  state.mcpError = null;
  try {
    const r = await apiPost('/api/mcps', { name: state.mcpNew.name, target: state.mcpNew.target });
    state.mcpServers = r.servers;
    state.mcpConfigs = r.configs || [];
    if (!state.selectedMcps.includes(state.mcpNew.name.trim())) state.selectedMcps.push(state.mcpNew.name.trim());
    localStorage.setItem('la-mcps2', JSON.stringify(state.selectedMcps));
    state.mcpNew = { name: '', target: '' };
  } catch (e) {
    state.mcpError = e.message.replace(/^\d+: /, '').replace(/^\{"detail":"(.*)"\}$/, '$1');
  }
  render();
}

async function saveMcp(name) {
  state.mcpError = null;
  let config;
  try {
    config = JSON.parse(state.mcpEditVal);
  } catch (e) {
    state.mcpError = 'JSON inválido';
    render();
    return;
  }
  try {
    const r = await fetch(`/api/mcps/${encodeURIComponent(name)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    state.mcpServers = data.servers;
    state.mcpConfigs = data.configs;
    state.mcpEditing = null;
  } catch (e) {
    state.mcpError = e.message.replace(/^\{"detail":"(.*)"\}$/, '$1');
  }
  render();
}

async function importMcps() {
  state.mcpError = null;
  try {
    const r = await fetch('/api/mcps/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: state.mcpImportText }),
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    state.mcpServers = data.servers;
    state.mcpConfigs = data.configs;
    for (const n of data.added || []) {
      if (!state.selectedMcps.includes(n)) state.selectedMcps.push(n);
    }
    localStorage.setItem('la-mcps2', JSON.stringify(state.selectedMcps));
    state.mcpImportText = '';
  } catch (e) {
    state.mcpError = e.message.replace(/^\d+: /, '').replace(/^\{"detail":"(.*)"\}$/, '$1');
  }
  render();
}

async function delMcp(name) {
  if (!confirm(`¿Quitar "${name}" del mcp.json?`)) return;
  state.mcpError = null;
  try {
    const r = await fetch(`/api/mcps/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    state.mcpServers = data.servers;
    state.mcpConfigs = data.configs;
    state.selectedMcps = state.selectedMcps.filter(n => n !== name);
    localStorage.setItem('la-mcps2', JSON.stringify(state.selectedMcps));
  } catch (e) {
    state.mcpError = e.message;
  }
  render();
}

function toggleMcp(name) {
  if (state.selectedMcps.includes(name)) {
    state.selectedMcps = state.selectedMcps.filter(x => x !== name);
  } else {
    state.selectedMcps.push(name);
  }
  savePrefs();
  render();
}

async function saveSoul() {
  await apiPost('/api/soul', { content: state.soulDraft });
  state.sysPrompt = state.soulDraft;
  state.soulEditing = false;
  render();
}

async function copyText(idx) {
  const sess = state.sessions[state.activeId];
  const text = sess?.messages?.[idx]?.content || '';
  await navigator.clipboard.writeText(text);
  state.copiedId = idx;
  setTimeout(() => { state.copiedId = null; render(); }, 1600);
  render();
}

function editMessage(idx) {
  const sess = state.sessions[state.activeId];
  if (!sess?.messages?.[idx] || sess.messages[idx].role !== 'assistant') return;
  // re-edit = go back to that point: the previous user message goes to the draft and history is trimmed
  const prevUser = sess.messages[idx - 1];
  state.draft = prevUser?.role === 'user' ? prevUser.content : sess.messages[idx].content;
  const cut = prevUser?.role === 'user' ? idx - 1 : idx;
  sess.messages = sess.messages.slice(0, cut);
  for (const k of Object.keys(sess.tools || {})) if (+k >= cut) delete sess.tools[k];
  for (const k of Object.keys(sess.mem || {})) if (+k >= cut) delete sess.mem[k];
  saveSession(state.activeId, sess);
  render();
}

function exportChat(format) {
  const sess = state.sessions[state.activeId];
  const lines = (sess?.messages || []).map(m => {
    if (format === 'md') return `**${m.role}:**\n${m.content}\n`;
    return `<p><strong>${m.role}:</strong></p><p>${esc(m.content).replace(/\n/g, '<br>')}</p>`;
  });
  const blob = new Blob([format === 'md' ? lines.join('\n---\n') : `<!doctype html><html><body>${lines.join('')}</body></html>`], { type: 'text/plain' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `chat-${state.activeId}.${format}`;
  a.click();
}

async function copyChat() {
  const sess = state.sessions[state.activeId];
  const text = (sess?.messages || []).map(m => `${m.role}: ${m.content}`).join('\n\n---\n\n');
  await navigator.clipboard.writeText(text);
}

function updateComposer() {
  const ta = $('[data-input="draft"]');
  if (ta) {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 200) + 'px';
  }
  const box = $('#composer-box');
  if (box) box.style.borderColor = state.taFocus ? 'var(--ac)' : 'var(--bd)';
  const count = $('#composer-count');
  if (count) {
    count.textContent = `${state.draft.length} car.`;
    count.style.visibility = state.draft.trim() ? 'visible' : 'hidden';
  }
  const btn = $('#composer-send');
  if (btn) {
    const ok = state.draft.trim().length > 0;
    btn.disabled = !ok;
    btn.style.background = ok ? 'var(--ac)' : 'var(--bg3)';
    btn.style.color = ok ? '#fff' : 'var(--tx3)';
    btn.style.cursor = ok ? 'pointer' : 'default';
  }
}

function focusComposer() {
  const ta = $('[data-input="draft"]');
  if (ta && !state.sending) {
    updateComposer();
  }
}

function scrollToBottom() {
  const el = $('#chat-scroll');
  if (el) el.scrollTop = el.scrollHeight;
}

// ----------------------------------------------------------------- streaming chat
async function sendMessage() {
  const text = state.draft.trim();
  // block while compacting: both would write the same session (race)
  if (!text || state.sending || state.compacting) return;
  if (!state.activeId) await newChat();
  if (!state.modelId) { alert('Selecciona un modelo primero.'); return; }

  state.draft = '';
  state.sending = true;
  state.abortCtrl = new AbortController();

  const name = state.activeId;
  const sess = state.sessions[name];
  sess.messages.push({ role: 'user', content: text });
  sess.updated = Date.now() / 1000;

  // assistant message placeholder
  const aiIdx = sess.messages.length;
  sess.messages.push({ role: 'assistant', content: '', think: '', streaming: true, model: state.modelId });
  render();

  try {
    const body = {
      session: name,
      message: text,
      model: state.modelId,
      temperature: state.temp,
      top_p: state.topP,
      max_tokens: state.maxTok || null,
      num_ctx: ctxTokens(state.ctx),
      system: state.sysPrompt || null,
      use_tools: state.caps.web || state.caps.vault || state.caps.html,
      think: state.caps.thinking,
      use_memory: state.caps.memoria,
      mcp_servers: state.selectedMcps,
    };

    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: state.abortCtrl.signal,
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    if (!res.body) throw new Error('El navegador no soporta streaming.');

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop(); // last incomplete one stays in the buffer
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const ev = JSON.parse(line);
          handleEvent(ev, sess, aiIdx, name);
        } catch (e) {
          console.error('NDJSON parse error:', e, line);
        }
      }
    }
    // final line
    if (buf.trim()) {
      try { handleEvent(JSON.parse(buf), sess, aiIdx, name); } catch (e) {}
    }
  } catch (err) {
    const m = sess.messages[aiIdx];
    if (m) {
      m.streaming = false;
      if (err.name === 'AbortError') {
        m.content = 'Generación detenida.';
      } else {
        m.content = `⚠️ Error: ${err.message}`;
        m.error = true;
      }
      render();
    }
  } finally {
    state.sending = false;
    state.abortCtrl = null;
    const last = sess.messages[sess.messages.length - 1];
    if (last && last.streaming) { last.streaming = false; }
    sess.updated = Date.now() / 1000;
    await saveSession(name, sess);
    render();
    // auto-compact: free up context once we cross 85% usage, if enabled
    if (state.autoCompact && !state.compacting) {
      const ratio = (sess.ctx || 0) / ctxTokens(state.ctx);
      if (ratio > 0.85) await compactChat();
    }
  }
}

function handleEvent(ev, sess, aiIdx, name) {
  const m = sess.messages[aiIdx];
  if (!m) return;
  if (ev.type === 'token') {
    m.content += ev.token || '';
  } else if (ev.type === 'tool') {
    // we store the tool calls to show at the end
    sess.tools = sess.tools || {};
    sess.tools[aiIdx] = sess.tools[aiIdx] || [];
    sess.tools[aiIdx].push({ tool: ev.name, args: ev.args, result: '' });
  } else if (ev.type === 'recall') {
    if (ev.count > 0) m.recall = ev.count;
  } else if (ev.type === 'done') {
    m.content = ev.reply;
    m.think = ''; // ollama does not separate thinking in this channel
    m.streaming = false;
    m.meta = ev.meta;
    if (ev.usage) {
      sess.ctx = ev.usage.ctx ?? sess.ctx;
      sess.tokens = (sess.tokens || 0) + (ev.usage.total || 0);
    }
    if (ev.calls?.length) sess.tools[aiIdx] = ev.calls;
    if (ev.saved_facts?.length) { sess.mem = sess.mem || {}; sess.mem[aiIdx] = ev.saved_facts; }
  } else if (ev.type === 'error') {
    m.error = true;
  } else if (ev.type === 'warning') {
    console.warn(ev.text);
  }
  // partial render with throttling
  if (!state._raf) {
    state._raf = requestAnimationFrame(() => {
      state._raf = null;
      render();
    });
  }
}

function stopMessage() {
  if (state.abortCtrl) state.abortCtrl.abort();
}

// ----------------------------------------------------------------- init
async function init() {
  attachEvents(); // only once: #root persists and the listeners were accumulating on each render
  document.addEventListener('click', () => {
    if (state.modelMenu || state.moreMenu || state.menuId) {
      state.modelMenu = false; state.moreMenu = false; state.menuId = null; render();
    }
  });
  try {
    // critical to paint: sessions + models. It renders as soon as these two arrive.
    const [sessions, models] = await Promise.all([
      apiGet('/api/sessions'),
      apiGet('/api/models'),
    ]);
    state.sessions = sessions;
    const names = Object.keys(sessions);
    state.activeId = names[0] || null;

    state.models = models.models.map(m => ({
      ...m,
      short: m.name,
      tag: m.backend || (`${m.gb} GB` + (m.fits ? '' : ' ⚠️ CPU')),
    }));
    const pick = state.models.find(m => m.name === state.modelId)
              || state.models.find(m => m.name === models.default)
              || state.models[0];
    state.modelId = pick?.name;
    if (!state.activeId) await newChat(); else render(); // UI already visible, without waiting for the rest

    // non-critical: env + mcps + soul arrive later and re-render without blocking startup
    const [env, mcps, soul] = await Promise.all([
      apiGet('/api/env').catch(() => ({})),
      apiGet('/api/mcps').catch(() => ({ servers: [] })),
      apiGet('/api/soul').catch(() => ({ content: '' })),
    ]);
    state.cfg = {
      ...state.cfg,
      ollamaUrl: env.ollama_url || '',
      vaultDir: env.vault_dir || '',
      tgToken: env.tg_token || '',
      tgChats: env.tg_chats || '',
    };
    state.mcpServers = mcps.servers || [];
    state.mcpConfigs = mcps.configs || [];
    // no saved preference: the MCPs declared in mcp.json start enabled
    if (localStorage.getItem('la-mcps2') === null) state.selectedMcps = [...state.mcpServers];
    // clean saved selections of servers that no longer exist in mcp.json
    state.selectedMcps = state.selectedMcps.filter(n => state.mcpServers.includes(n));
    localStorage.setItem('la-mcps2', JSON.stringify(state.selectedMcps));
    state.sysPrompt = soul.content;
    state.soulDraft = soul.content;
    render();
  } catch (e) {
    $('#root').innerHTML = `<div style="padding:40px;color:var(--err)">No se pudo conectar con el backend: ${esc(e.message)}</div>`;
    console.error(e);
  }
}

init();
