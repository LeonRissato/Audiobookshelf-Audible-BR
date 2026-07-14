# -*- coding: utf-8 -*-
"""
Custom Metadata Provider do Audible BR para o Audiobookshelf.

Implementa o endpoint GET /search conforme a especificação oficial:
https://github.com/advplyr/audiobookshelf/blob/master/custom-metadata-provider-specification.yaml

No ABS: Configurações > Item Metadata Utils > Custom Metadata Providers
  URL:  http://IP_DESTA_MAQUINA:PORTA  (ex.: http://192.168.1.10:5557)
  Authorization: valor de "provider_auth" do config.json (se definido)

Uso: python provider_server.py
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from audible_br import (load_config, search_catalog, product_to_metadata,
                        similarity)

CONFIG = load_config()
PORT = int(CONFIG.get("provider_port", 5557))
AUTH = CONFIG.get("provider_auth") or None
HOST_API = CONFIG.get("audible_region_host")


def to_abs_match(product):
    """Converte metadados para o formato de match do provider customizado."""
    m = product_to_metadata(product)
    match = {
        "title": m["title"],
        "subtitle": m["subtitle"],
        "author": ", ".join(m["authors"]) or None,
        "narrator": ", ".join(m["narrators"]) or None,
        "publisher": m["publisher"],
        "publishedYear": m["publishedYear"],
        "description": m["description"],
        "cover": m["cover"],
        "asin": m["asin"],
        "genres": m["genres"] or None,
        "series": m["series"] or None,
        "language": m["language"],
        "duration": m["durationMin"],  # em minutos, conforme a spec do ABS
    }
    return {k: v for k, v in match.items() if v is not None}


class Handler(BaseHTTPRequestHandler):

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path.rstrip("/") != "/search":
            return self._send(404, {"error": "Not found"})

        if AUTH and self.headers.get("Authorization") != AUTH:
            return self._send(401, {"error": "Unauthorized"})

        qs = parse_qs(url.query)
        query = (qs.get("query") or [""])[0].strip()
        author = (qs.get("author") or [""])[0].strip() or None
        if not query:
            return self._send(400, {"error": "Parâmetro 'query' obrigatório"})

        try:
            products = search_catalog(title=query, author=author,
                                      num_results=10, host=HOST_API)
            if not products:
                # fallback: busca por palavras-chave (título + autor juntos)
                kw = f"{query} {author}" if author else query
                products = search_catalog(keywords=kw, num_results=10,
                                          host=HOST_API)
        except Exception as e:  # noqa: BLE001
            print(f"[erro] busca no Audible falhou: {e}", file=sys.stderr)
            return self._send(500, {"error": str(e)})

        # ordena por similaridade com o título pesquisado
        products.sort(key=lambda p: similarity(p.get("title", ""), query),
                      reverse=True)
        matches = [to_abs_match(p) for p in products]
        print(f"[busca] '{query}' (autor: {author or '-'}) -> "
              f"{len(matches)} resultado(s)")
        self._send(200, {"matches": matches})

    def log_message(self, *args):  # silencia o log padrão
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Provider Audible BR rodando em http://0.0.0.0:{PORT}")
    print("Configure no ABS: Configurações > Item Metadata Utils > "
          "Custom Metadata Providers")
    if AUTH:
        print(f"Authorization exigido: {AUTH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")
