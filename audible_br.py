# -*- coding: utf-8 -*-
"""
Acesso ao catálogo do Audible Brasil (api.audible.com.br).

Usa a mesma API pública de catálogo que os projetos mkb79/Audible e
mkb79/audible-cli utilizam. As buscas de catálogo NÃO exigem login.
"""
import html
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

DEFAULT_HOST = "api.audible.com.br"

RESPONSE_GROUPS = ",".join([
    "contributors",
    "media",
    "product_attrs",
    "product_desc",
    "product_extended_attrs",
    "series",
    "category_ladders",
    "rating",
])

HEADERS = {
    "User-Agent": "AudibleBR-ABS/1.0 (metadata sync)",
    "Accept": "application/json",
}


def load_config(path=None):
    """Carrega config.json (na mesma pasta deste arquivo, por padrão)."""
    if path is None:
        path = Path(__file__).parent / "config.json"
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {path}\n"
            "Copie config.json.example para config.json e preencha os valores."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _base_url(host=None):
    return f"https://{host or DEFAULT_HOST}/1.0/catalog/products"


def _get(url, params, timeout=30):
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def search_catalog(title=None, author=None, keywords=None,
                   num_results=10, host=None):
    """Busca produtos no catálogo. Retorna lista de products (dicts)."""
    params = {
        "num_results": min(int(num_results), 50),
        "products_sort_by": "Relevance",
        "response_groups": RESPONSE_GROUPS,
        "image_sizes": "500,1024",
    }
    if title:
        params["title"] = title
    if author:
        params["author"] = author
    if keywords:
        params["keywords"] = keywords
    data = _get(_base_url(host), params)
    return data.get("products", []) or []


def get_by_asin(asin, host=None):
    """Busca um produto específico pelo ASIN. Retorna dict ou None."""
    params = {
        "response_groups": RESPONSE_GROUPS,
        "image_sizes": "500,1024",
    }
    try:
        data = _get(f"{_base_url(host)}/{asin}", params)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    return data.get("product")


# ----------------------------------------------------------------------
# Conversão de produto Audible -> metadados
# ----------------------------------------------------------------------

def _strip_html(text):
    if not text:
        return None
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip() or None


def _names(items):
    return [i.get("name", "").strip() for i in (items or []) if i.get("name")]


def _genres(product):
    genres = []
    for ladder in product.get("category_ladders") or []:
        for cat in ladder.get("ladder") or []:
            name = (cat.get("name") or "").strip()
            if name and name not in genres:
                genres.append(name)
    return genres


def _cover(product):
    images = product.get("product_images") or {}
    for size in ("1024", "500"):
        if images.get(size):
            # remove o sufixo de redimensionamento para obter a resolução máxima
            # ex.: .../61abc._SL500_.jpg -> .../61abc.jpg
            return re.sub(r"\._SL\d+_(?=\.)", "", images[size])
    return None


def _series(product):
    out = []
    for s in product.get("series") or []:
        name = (s.get("title") or "").strip()
        if name:
            out.append({"series": name, "sequence": str(s.get("sequence") or "")})
    return out


LANG_MAP = {
    "portuguese": "Português",
    "english": "Inglês",
    "spanish": "Espanhol",
    "french": "Francês",
    "german": "Alemão",
    "italian": "Italiano",
    "japanese": "Japonês",
}


def product_to_metadata(product):
    """Converte um product da API do Audible em um dict de metadados neutro."""
    release = product.get("release_date") or product.get("issue_date") or ""
    lang = (product.get("language") or "").lower()
    return {
        "title": product.get("title"),
        "subtitle": product.get("subtitle"),
        "authors": _names(product.get("authors")),
        "narrators": _names(product.get("narrators")),
        "publisher": product.get("publisher_name"),
        "publishedYear": release[:4] if release else None,
        "description": _strip_html(product.get("publisher_summary")
                                   or product.get("merchandising_summary")),
        "cover": _cover(product),
        "asin": product.get("asin"),
        "genres": _genres(product),
        "series": _series(product),
        "language": LANG_MAP.get(lang, lang.capitalize() or None),
        "durationMin": product.get("runtime_length_min"),
        "explicit": bool(product.get("is_adult_product")),
    }


# ----------------------------------------------------------------------
# Similaridade para escolher o melhor resultado
# ----------------------------------------------------------------------

def _norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).strip()


def similarity(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def best_match(products, title, author=None, min_score=0.55):
    """Escolhe o produto mais parecido com título (e autor, se houver)."""
    best, best_score = None, 0.0
    for p in products:
        score = similarity(p.get("title", ""), title)
        if author and p.get("authors"):
            a_score = max(similarity(a.get("name", ""), author)
                          for a in p["authors"])
            score = 0.7 * score + 0.3 * a_score
        if score > best_score:
            best, best_score = p, score
    if best_score >= min_score:
        return best, best_score
    return None, best_score
