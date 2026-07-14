# -*- coding: utf-8 -*-
"""
Sincronização em lote: Audible BR -> Audiobookshelf.

Varre a biblioteca do ABS, localiza cada livro no catálogo do Audible BR
(por ASIN quando existir, senão por título/autor) e atualiza os metadados.

Por padrão roda em MODO SIMULAÇÃO (não altera nada). Use --aplicar para
gravar as alterações.

Exemplos:
  python sync_library.py                          # simulação, todas as bibliotecas
  python sync_library.py --aplicar                # aplica (só preenche campos vazios)
  python sync_library.py --aplicar --sobrescrever # substitui pelos dados do Audible
  python sync_library.py --aplicar --capas        # também baixa capas
  python sync_library.py --biblioteca "Audiobooks" --limite 20
"""
import argparse
import sys

import requests

from audible_br import (load_config, get_by_asin, search_catalog, best_match,
                        product_to_metadata)

# Campos do ABS que serão preenchidos a partir do Audible
FIELDS = ["subtitle", "publisher", "publishedYear", "description",
          "asin", "language"]


class AbsClient:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {token}"

    def _get(self, path, **params):
        r = self.s.get(f"{self.base}{path}", params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def libraries(self):
        libs = self._get("/api/libraries").get("libraries", [])
        return [l for l in libs if l.get("mediaType") == "book"]

    def items(self, library_id):
        page = 0
        while True:
            data = self._get(f"/api/libraries/{library_id}/items",
                             limit=100, page=page)
            results = data.get("results", [])
            if not results:
                break
            yield from results
            page += 1
            if (page * 100) >= data.get("total", 0):
                break

    def item(self, item_id):
        return self._get(f"/api/items/{item_id}")

    def update_metadata(self, item_id, metadata):
        r = self.s.patch(f"{self.base}/api/items/{item_id}/media",
                         json={"metadata": metadata}, timeout=30)
        r.raise_for_status()

    def set_cover_from_url(self, item_id, url):
        r = self.s.post(f"{self.base}/api/items/{item_id}/cover",
                        json={"url": url}, timeout=60)
        r.raise_for_status()


def build_payload(current, aud, overwrite):
    """Monta o payload PATCH só com o que precisa mudar."""
    payload = {}

    def want(field, value):
        if value in (None, "", []):
            return
        if overwrite or not current.get(field):
            if current.get(field) != value:
                payload[field] = value

    for f in FIELDS:
        want(f, aud.get(f))

    if aud["authors"] and (overwrite or not current.get("authors")):
        payload["authors"] = [{"name": n} for n in aud["authors"]]
    if aud["narrators"] and (overwrite or not current.get("narrators")):
        payload["narrators"] = aud["narrators"]
    if aud["genres"] and (overwrite or not current.get("genres")):
        payload["genres"] = aud["genres"]
    if aud["series"] and (overwrite or not current.get("series")):
        payload["series"] = [{"name": s["series"], "sequence": s["sequence"]}
                             for s in aud["series"]]
    return payload


def find_on_audible(meta, host):
    """Localiza o livro no Audible BR. Retorna (product, como_achou)."""
    asin = (meta.get("asin") or "").strip()
    if asin:
        p = get_by_asin(asin, host=host)
        if p:
            return p, f"ASIN {asin}"

    title = meta.get("title") or ""
    author = None
    if meta.get("authors"):
        author = meta["authors"][0].get("name")
    elif meta.get("authorName"):
        author = meta["authorName"].split(",")[0].strip()

    if not title:
        return None, "sem título"

    products = search_catalog(title=title, author=author, host=host)
    if not products:
        kw = f"{title} {author}" if author else title
        products = search_catalog(keywords=kw, host=host)

    p, score = best_match(products, title, author)
    if p:
        return p, f"busca ({score:.0%} de similaridade)"
    return None, f"nenhum resultado bom (melhor: {score:.0%})"


def main():
    ap = argparse.ArgumentParser(
        description="Sincroniza metadados do Audible BR para o Audiobookshelf")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava as alterações (sem isso, apenas simula)")
    ap.add_argument("--sobrescrever", action="store_true",
                    help="substitui campos já preenchidos no ABS")
    ap.add_argument("--capas", action="store_true",
                    help="baixa capas do Audible (itens sem capa, ou todos "
                         "com --sobrescrever)")
    ap.add_argument("--biblioteca", help="nome da biblioteca (padrão: todas)")
    ap.add_argument("--limite", type=int, default=0,
                    help="processa no máximo N itens")
    ap.add_argument("--config", help="caminho do config.json")
    args = ap.parse_args()

    cfg = load_config(args.config)
    abs_client = AbsClient(cfg["abs_url"], cfg["abs_token"])
    host = cfg.get("audible_region_host")

    libs = abs_client.libraries()
    if args.biblioteca:
        libs = [l for l in libs
                if l["name"].lower() == args.biblioteca.lower()]
        if not libs:
            sys.exit(f"Biblioteca '{args.biblioteca}' não encontrada.")

    modo = "APLICANDO" if args.aplicar else "SIMULAÇÃO (use --aplicar para gravar)"
    print(f"Modo: {modo}\n")

    stats = {"atualizados": 0, "sem_mudanca": 0, "nao_encontrados": 0,
             "erros": 0}
    processados = 0

    for lib in libs:
        print(f"=== Biblioteca: {lib['name']} ===")
        for entry in abs_client.items(lib["id"]):
            if args.limite and processados >= args.limite:
                break
            processados += 1
            item_id = entry["id"]
            try:
                item = abs_client.item(item_id)
                meta = item.get("media", {}).get("metadata", {})
                title = meta.get("title") or "(sem título)"

                product, how = find_on_audible(meta, host)
                if not product:
                    print(f"  [não encontrado] {title} — {how}")
                    stats["nao_encontrados"] += 1
                    continue

                aud = product_to_metadata(product)
                payload = build_payload(meta, aud, args.sobrescrever)

                need_cover = args.capas and aud.get("cover") and (
                    args.sobrescrever or not item.get("media", {}).get("coverPath"))

                if not payload and not need_cover:
                    print(f"  [ok] {title} — nada a mudar ({how})")
                    stats["sem_mudanca"] += 1
                    continue

                campos = ", ".join(payload.keys()) or "-"
                extra = " + capa" if need_cover else ""
                print(f"  [{'atualizado' if args.aplicar else 'mudaria'}] "
                      f"{title} — via {how} — campos: {campos}{extra}")

                if args.aplicar:
                    if payload:
                        abs_client.update_metadata(item_id, payload)
                    if need_cover:
                        abs_client.set_cover_from_url(item_id, aud["cover"])
                stats["atualizados"] += 1

            except Exception as e:  # noqa: BLE001
                print(f"  [erro] item {item_id}: {e}")
                stats["erros"] += 1
        else:
            continue
        break  # atingiu o --limite

    print(f"\nResumo: {stats['atualizados']} atualizados/atualizáveis, "
          f"{stats['sem_mudanca']} sem mudança, "
          f"{stats['nao_encontrados']} não encontrados, "
          f"{stats['erros']} erros.")
    if not args.aplicar:
        print("Nada foi alterado. Rode novamente com --aplicar para gravar.")


if __name__ == "__main__":
    main()
