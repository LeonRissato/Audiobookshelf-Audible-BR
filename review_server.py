# -*- coding: utf-8 -*-
"""
Tela de revisão manual: Audible BR -> Audiobookshelf.

Abre uma página local onde você navega pelos livros da sua biblioteca,
vê os candidatos encontrados no Audible BR e clica no correto para aplicar.

Uso: python review_server.py   (ou revisar.bat)
Depois abra http://localhost:5558 no navegador.
"""
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Timer
from urllib.parse import urlparse, parse_qs

from audible_br import (load_config, search_catalog, get_by_asin,
                        product_to_metadata, similarity)
from sync_library import AbsClient, build_payload

CONFIG = load_config()
PORT = int(CONFIG.get("review_port", 5558))
HOST_API = CONFIG.get("audible_region_host")
ABS = AbsClient(CONFIG["abs_url"], CONFIG["abs_token"])


# ----------------------------------------------------------------------
# API
# ----------------------------------------------------------------------

def api_libraries():
    return [{"id": l["id"], "name": l["name"]} for l in ABS.libraries()]


def api_items(library_id):
    items = []
    for e in ABS.items(library_id):
        md = e.get("media", {}).get("metadata", {})
        items.append({
            "id": e["id"],
            "title": md.get("title") or "(sem título)",
            "author": md.get("authorName") or "",
            "asin": md.get("asin") or "",
            "hasCover": bool(e.get("media", {}).get("coverPath")),
        })
    return items


def api_current(item_id):
    item = ABS.item(item_id)
    md = item.get("media", {}).get("metadata", {})
    return {
        "title": md.get("title"),
        "subtitle": md.get("subtitle"),
        "author": md.get("authorName") or ", ".join(
            a.get("name", "") for a in md.get("authors") or []),
        "narrator": ", ".join(md.get("narrators") or []),
        "publisher": md.get("publisher"),
        "publishedYear": md.get("publishedYear"),
        "asin": md.get("asin"),
        "series": md.get("seriesName") or "",
        "genres": md.get("genres") or [],
        "description": md.get("description"),
        "coverUrl": f"{CONFIG['abs_url'].rstrip('/')}/api/items/{item_id}/cover"
                    f"?token={CONFIG['abs_token']}",
        "hasCover": bool(item.get("media", {}).get("coverPath")),
    }


def api_search(query, author):
    products = search_catalog(title=query, author=author or None,
                              num_results=12, host=HOST_API)
    if not products:
        kw = f"{query} {author}".strip()
        products = search_catalog(keywords=kw, num_results=12, host=HOST_API)
    products.sort(key=lambda p: similarity(p.get("title", ""), query),
                  reverse=True)
    return [product_to_metadata(p) for p in products]


def api_apply(body):
    item_id = body["itemId"]
    asin = body["asin"]
    overwrite = bool(body.get("overwrite", True))
    set_cover = bool(body.get("cover", True))

    product = get_by_asin(asin, host=HOST_API)
    if not product:
        raise ValueError(f"ASIN {asin} não encontrado no Audible BR")
    aud = product_to_metadata(product)

    item = ABS.item(item_id)
    meta = item.get("media", {}).get("metadata", {})
    payload = build_payload(meta, aud, overwrite)
    payload["asin"] = aud["asin"]  # escolha manual: sempre grava o ASIN

    ABS.update_metadata(item_id, payload)
    if set_cover and aud.get("cover"):
        ABS.set_cover_from_url(item_id, aud["cover"])
    return {"ok": True, "campos": sorted(payload.keys()),
            "capa": bool(set_cover and aud.get("cover"))}


# ----------------------------------------------------------------------
# Servidor HTTP
# ----------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):

    def _json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content):
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        try:
            if url.path == "/":
                return self._html(PAGE)
            if url.path == "/api/libraries":
                return self._json(200, api_libraries())
            if url.path == "/api/items":
                return self._json(200, api_items(qs["library"][0]))
            if url.path == "/api/current":
                return self._json(200, api_current(qs["id"][0]))
            if url.path == "/api/search":
                q = (qs.get("q") or [""])[0]
                a = (qs.get("author") or [""])[0]
                return self._json(200, api_search(q, a))
            return self._json(404, {"error": "não encontrado"})
        except Exception as e:  # noqa: BLE001
            print(f"[erro] {url.path}: {e}", file=sys.stderr)
            return self._json(500, {"error": str(e)})

    def do_POST(self):
        url = urlparse(self.path)
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            if url.path == "/api/apply":
                return self._json(200, api_apply(body))
            return self._json(404, {"error": "não encontrado"})
        except Exception as e:  # noqa: BLE001
            print(f"[erro] {url.path}: {e}", file=sys.stderr)
            return self._json(500, {"error": str(e)})

    def log_message(self, *args):
        pass


# ----------------------------------------------------------------------
# Página (HTML + JS embutidos)
# ----------------------------------------------------------------------

PAGE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Revisão Audible BR → Audiobookshelf</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; font-family: system-ui, Segoe UI, sans-serif;
         background:#16181d; color:#e6e6e6; }
  header { display:flex; gap:12px; align-items:center; padding:12px 16px;
           background:#22252c; position:sticky; top:0; z-index:5;
           flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0 12px 0 0; color:#f0a742; }
  select,input,button { background:#2c303a; color:#e6e6e6; border:1px solid #444;
           border-radius:6px; padding:7px 10px; font-size:14px; }
  button { cursor:pointer; }
  button:hover { background:#3a3f4d; }
  button.primary { background:#f0a742; color:#1a1a1a; border:none; font-weight:600; }
  button.primary:hover { background:#ffbc5c; }
  .wrap { display:grid; grid-template-columns: 330px 1fr; gap:16px;
          padding:16px; align-items:start; }
  .panel { background:#22252c; border-radius:10px; padding:14px; }
  .panel h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em;
              color:#9aa0ae; margin:0 0 10px; }
  #atual img { width:140px; border-radius:6px; display:block; margin-bottom:10px; }
  #atual .t { font-size:17px; font-weight:600; }
  #atual .l { color:#9aa0ae; font-size:13px; margin-top:6px; }
  #atual .l b { color:#cfd3dc; font-weight:500; }
  .nav { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; }
  .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr));
           gap:12px; }
  .card { background:#22252c; border-radius:10px; padding:12px;
          border:1px solid transparent; display:flex; flex-direction:column; }
  .card:hover { border-color:#f0a742; }
  .card img { width:100%; border-radius:6px; aspect-ratio:1; object-fit:cover;
              background:#2c303a; }
  .card .t { font-weight:600; margin:8px 0 2px; font-size:14px; }
  .card .l { color:#9aa0ae; font-size:12.5px; line-height:1.5; }
  .card button { margin-top:auto; }
  .card .desc { font-size:12px; color:#8b90a0; max-height:52px; overflow:hidden;
                margin:6px 0; }
  .opts { display:flex; gap:14px; align-items:center; font-size:13px;
          color:#cfd3dc; }
  .status { font-size:13px; color:#9aa0ae; margin-left:auto; }
  .done { color:#7dc97d; }
  .skipped { color:#888; }
  .msg { padding:30px; text-align:center; color:#9aa0ae; grid-column:1/-1; }
  .search { display:flex; gap:8px; margin-bottom:12px; flex-wrap:wrap; }
  .search input { flex:1; min-width:140px; }
  .badge { display:inline-block; background:#2c303a; border-radius:4px;
           padding:1px 7px; font-size:11.5px; margin:2px 3px 0 0; color:#b8bdc9; }
  .tag-done { position:absolute; }
</style>
</head>
<body>
<header>
  <h1>Audible BR → ABS</h1>
  <select id="lib"></select>
  <select id="filtro">
    <option value="todos">Todos os itens</option>
    <option value="semasin" selected>Só itens sem ASIN</option>
    <option value="semcapa">Só itens sem capa</option>
  </select>
  <label class="opts"><input type="checkbox" id="sobrescrever" checked>
    Sobrescrever campos</label>
  <label class="opts"><input type="checkbox" id="capa" checked>
    Aplicar capa</label>
  <span class="status" id="progresso"></span>
</header>

<div class="wrap">
  <div class="panel" id="atual"><div class="msg">Carregando…</div></div>
  <div>
    <div class="search panel">
      <input id="q" placeholder="Título para buscar">
      <input id="qa" placeholder="Autor (opcional)">
      <button onclick="buscar()">Buscar de novo</button>
    </div>
    <div class="cards" id="cards"><div class="msg">…</div></div>
  </div>
</div>

<script>
let itens = [], idx = 0, estado = {};   // estado[id] = 'aplicado' | 'pulado'

const $ = s => document.querySelector(s);
const esc = s => (s||'').replace(/[&<>"]/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

async function api(path) {
  const r = await fetch(path);
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.status);
  return j;
}

async function init() {
  const libs = await api('/api/libraries');
  $('#lib').innerHTML = libs.map(l =>
    `<option value="${l.id}">${esc(l.name)}</option>`).join('');
  $('#lib').onchange = carregar;
  $('#filtro').onchange = carregar;
  await carregar();
}

async function carregar() {
  $('#atual').innerHTML = '<div class="msg">Carregando itens…</div>';
  $('#cards').innerHTML = '';
  let todos = await api('/api/items?library=' + $('#lib').value);
  const f = $('#filtro').value;
  itens = todos.filter(i =>
    f === 'semasin' ? !i.asin :
    f === 'semcapa' ? !i.hasCover : true);
  idx = 0;
  if (!itens.length) {
    $('#atual').innerHTML = '<div class="msg">Nenhum item nesse filtro 🎉</div>';
    progresso(); return;
  }
  mostrar();
}

function progresso() {
  const feitos = itens.filter(i => estado[i.id]).length;
  $('#progresso').textContent =
    itens.length ? `Item ${idx+1} de ${itens.length} — ${feitos} resolvidos` : '';
}

async function mostrar() {
  progresso();
  const item = itens[idx];
  $('#atual').innerHTML = '<div class="msg">Carregando…</div>';
  $('#cards').innerHTML = '<div class="msg">Buscando no Audible BR…</div>';
  const cur = await api('/api/current?id=' + item.id);
  const st = estado[item.id];
  $('#atual').innerHTML = `
    <h2>No Audiobookshelf agora</h2>
    ${cur.hasCover ? `<img src="${cur.coverUrl}" onerror="this.remove()">` : ''}
    <div class="t">${esc(cur.title)||'—'}</div>
    <div class="l"><b>Autor:</b> ${esc(cur.author)||'—'}</div>
    <div class="l"><b>Narrador:</b> ${esc(cur.narrator)||'—'}</div>
    <div class="l"><b>Série:</b> ${esc(cur.series)||'—'}</div>
    <div class="l"><b>Editora:</b> ${esc(cur.publisher)||'—'}
        &nbsp; <b>Ano:</b> ${esc(cur.publishedYear)||'—'}</div>
    <div class="l"><b>ASIN:</b> ${esc(cur.asin)||'—'}</div>
    ${st ? `<div class="l ${st==='aplicado'?'done':'skipped'}">✔ ${st}</div>` : ''}
    <div class="nav">
      <button onclick="anterior()">◀ Anterior</button>
      <button onclick="pular()">Pular ▶</button>
    </div>`;
  $('#q').value = cur.title || item.title;
  $('#qa').value = (cur.author || '').split(',')[0].trim();
  await buscar();
}

async function buscar() {
  $('#cards').innerHTML = '<div class="msg">Buscando no Audible BR…</div>';
  try {
    const cands = await api('/api/search?q=' + encodeURIComponent($('#q').value)
      + '&author=' + encodeURIComponent($('#qa').value));
    if (!cands.length) {
      $('#cards').innerHTML = '<div class="msg">Nada encontrado. ' +
        'Tente simplificar o título acima e buscar de novo.</div>';
      return;
    }
    $('#cards').innerHTML = cands.map((c, i) => `
      <div class="card">
        ${c.cover ? `<img src="${c.cover}" loading="lazy">` : '<img>'}
        <div class="t">${esc(c.title)}</div>
        <div class="l">${esc((c.authors||[]).join(', '))}</div>
        <div class="l">🎙 ${esc((c.narrators||[]).join(', '))||'—'}</div>
        <div class="l">${c.series&&c.series.length ?
          '📚 '+esc(c.series[0].series)+' #'+esc(c.series[0].sequence) : ''}</div>
        <div class="l">${esc(c.publisher)||''} ${c.publishedYear?'· '+c.publishedYear:''}
          ${c.durationMin ? '· '+Math.floor(c.durationMin/60)+'h'+(c.durationMin%60)+'m':''}</div>
        <div>${(c.genres||[]).slice(0,3).map(g=>`<span class="badge">${esc(g)}</span>`).join('')}</div>
        <div class="desc">${esc(c.description||'')}</div>
        <button class="primary" onclick='aplicar(${JSON.stringify(c.asin)}, this)'>
          Usar este</button>
      </div>`).join('');
  } catch (e) {
    $('#cards').innerHTML = `<div class="msg">Erro: ${esc(e.message)}</div>`;
  }
}

async function aplicar(asin, btn) {
  btn.disabled = true; btn.textContent = 'Aplicando…';
  try {
    const r = await fetch('/api/apply', { method:'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ itemId: itens[idx].id, asin,
        overwrite: $('#sobrescrever').checked, cover: $('#capa').checked })});
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.status);
    estado[itens[idx].id] = 'aplicado';
    proximo();
  } catch (e) {
    btn.disabled = false; btn.textContent = 'Usar este';
    alert('Erro ao aplicar: ' + e.message);
  }
}

function pular()   { estado[itens[idx].id] ||= 'pulado'; proximo(); }
function proximo() { if (idx < itens.length-1) { idx++; mostrar(); }
                     else fim(); }
function anterior(){ if (idx > 0) { idx--; mostrar(); } }
function fim() {
  progresso();
  const feitos = itens.filter(i => estado[i.id]==='aplicado').length;
  $('#atual').innerHTML =
    `<div class="msg">Fim da lista! ${feitos} item(ns) atualizados. 🎉<br><br>
     <button onclick="carregar()">Recarregar lista</button></div>`;
  $('#cards').innerHTML = '';
}

init().catch(e => $('#atual').innerHTML =
  `<div class="msg">Erro: ${esc(e.message)}.<br>
   Confira abs_url e abs_token no config.json.</div>`);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Tela de revisão em {url}  (Ctrl+C para encerrar)")
    Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
