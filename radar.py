#!/usr/bin/env python3
"""
ZeroPrice — radar de precios rotos y tiradas de stock.
Lee stores.yaml, rastrea cada ficha, genera docs/index.html
y avisa por Telegram SOLO cuando hay un precio a 0 €.

No necesita servidor: lo ejecuta GitHub Actions cada 15 min.
Secrets (nunca en el código): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
HISTORY_FILE = ROOT / "data" / "history.json"
OUTPUT_HTML = ROOT / "docs" / "index.html"
OUTPUT_JSON = ROOT / "data" / "latest.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (ZeroPrice radar; +https://github.com/) "
                  "AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Accept-Language": "es-ES,es;q=0.9",
}

# ---------------------------------------------------------------- precios
def parse_price(text):
    """'1.299,99 €' -> 1299.99 | '0,00 €' -> 0.0 | None si no hay cifra."""
    if text is None:
        return None
    text = str(text).strip()
    # Quita símbolos y espacios, deja dígitos, punto y coma
    m = re.search(r"(\d[\d.,\s]*)", text)
    if not m:
        return None
    num = m.group(1).replace(" ", "").replace("\u00a0", "")
    if "," in num and "." in num:
        # Formato europeo: 1.299,99
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


def from_json_ld(soup):
    """La mayoría de tiendas publican el precio en schema.org/Product."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") not in ("Product", "Offer"):
                # A veces viene dentro de @graph
                graph = item.get("@graph", [])
                for g in graph if isinstance(graph, list) else []:
                    if isinstance(g, dict) and g.get("@type") == "Product":
                        item = g
                        break
                else:
                    continue
            offers = item.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            price = parse_price(offers.get("price"))
            availability = str(offers.get("availability", ""))
            stock = None
            if "OutOfStock" in availability:
                stock = "Agotado"
            elif "InStock" in availability:
                stock = "En stock"
            if price is not None:
                return price, stock
    return None, None


def from_meta(soup):
    for prop in ("product:price:amount", "og:price:amount"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            price = parse_price(tag["content"])
            if price is not None:
                return price
    return None


def check_store(store):
    """Devuelve un dict con precio, stock y estado. Nunca inventa un precio."""
    url = store["url"]
    result = {
        "name": store.get("name", url),
        "store": store.get("store", ""),
        "url": url,
        "price": None,
        "stock": None,
        "status": "ERROR",
        "detail": "",
    }
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        result["detail"] = f"No se pudo cargar la ficha: {type(e).__name__}"
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    price, stock = from_json_ld(soup)
    if price is None:
        price = from_meta(soup)
    if price is None and store.get("price_selector"):
        el = soup.select_one(store["price_selector"])
        if el:
            price = parse_price(el.get_text(" ", strip=True))
    if stock is None and store.get("stock_selector"):
        el = soup.select_one(store["stock_selector"])
        if el:
            stock = el.get_text(" ", strip=True)[:60]

    result["price"] = price
    result["stock"] = stock
    if price is None:
        result["status"] = "SIN_PRECIO"
        result["detail"] = "No se detectó precio (la tienda puede bloquear bots o haber cambiado su HTML). Revisa el selector en stores.yaml."
    elif price == 0:
        result["status"] = "ZERO"
        result["detail"] = "Precio a 0 € — posible error de precio."
    elif stock == "Agotado":
        result["status"] = "AGOTADO"
    else:
        result["status"] = "OK"
    return result


# ---------------------------------------------------------------- Telegram
def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Telegram no configurado (faltan secrets), se omite el aviso.")
        return False
    payload = json.dumps({"chat_id": chat_id, "text": message, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print("Telegram:", r.status)
            return True
    except Exception as e:
        print(f"Error enviando a Telegram: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- HTML
BADGE = {
    "ZERO": ("🚨 PRECIO 0 €", "#e11d48"),
    "ROTO": ("⚠️ PRECIO ROTO", "#f59e0b"),
    "AGOTADO": ("AGOTADO", "#64748b"),
    "OK": ("EN SEGUIMIENTO", "#0d9488"),
    "SIN_PRECIO": ("SIN PRECIO DETECTADO", "#64748b"),
    "ERROR": ("ERROR AL CARGAR", "#64748b"),
}


def render_html(results, checked_at):
    cards = []
    for r in results:
        label, color = BADGE[r["status"]]
        price = "—" if r["price"] is None else f"{r['price']:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
        stock = f"<p class='stock'>{r['stock']}</p>" if r["stock"] else ""
        detail = f"<p class='detail'>{r['detail']}</p>" if r["detail"] else ""
        cards.append(f"""
        <article class="card {'zero' if r['status'] == 'ZERO' else ''}">
          <span class="badge" style="background:{color}">{label}</span>
          <h2>{r['name']}</h2>
          <p class="store">{r['store']}</p>
          <p class="price">{price}</p>
          {stock}{detail}
          <a href="{r['url']}" target="_blank" rel="noopener">Ver ficha →</a>
        </article>""")
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ZeroPrice — Radar de precios</title>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700;800&display=swap" rel="stylesheet">
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: Montserrat, system-ui, sans-serif; background: #ecfeff; color: #134e4a; }}
  header {{ background: linear-gradient(135deg, #0f766e, #00b8b0 60%, #22d3ee); color: #fff; padding: 2.5rem 1.5rem; }}
  header h1 {{ margin: 0; font-size: 2.4rem; font-weight: 800; text-transform: uppercase; letter-spacing: .02em; }}
  header p {{ margin: .5rem 0 0; opacity: .9; }}
  main {{ max-width: 1080px; margin: -1rem auto 3rem; padding: 0 1rem; display: grid; gap: 1rem; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); }}
  .card {{ background: #fff; border: 2px solid #99f6e4; border-radius: 16px; padding: 1.25rem; }}
  .card.zero {{ border-color: #e11d48; box-shadow: 0 0 0 4px #ffe4e6; }}
  .badge {{ display: inline-block; color: #fff; font-size: .75rem; font-weight: 800; padding: .3rem .6rem; border-radius: 999px; text-transform: uppercase; }}
  h2 {{ font-size: 1.05rem; margin: .8rem 0 .2rem; text-transform: uppercase; }}
  .store {{ color: #0f766e; margin: 0; font-size: .9rem; }}
  .price {{ font-size: 2rem; font-weight: 800; color: #0d9488; margin: .6rem 0; }}
  .card.zero .price {{ color: #e11d48; }}
  .stock, .detail {{ font-size: .85rem; color: #475569; }}
  a {{ color: #0891b2; font-weight: 700; text-decoration: none; }}
  footer {{ text-align: center; color: #64748b; font-size: .85rem; padding-bottom: 2rem; }}
</style></head>
<body><header><h1>ZeroPrice</h1><p>Radar de precios rotos y stock · Última revisión: {checked_at}</p></header>
<main>{''.join(cards) if cards else '<p>Sin tiendas configuradas en stores.yaml.</p>'}</main>
<footer>Se revisa automáticamente cada 15 minutos con GitHub Actions. El aviso a Telegram se envía solo con precios a 0 €.</footer>
</body></html>"""


def main():
    with open(ROOT / "stores.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    stores = config.get("stores", [])
    history = {}
    if HISTORY_FILE.exists():
        history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))

    results = []
    for store in stores:
        r = check_store(store)
        prev = history.get(store["url"])
        # Precio roto: caída ≥ 50 % respecto a la última revisión (no dispara Telegram, solo se marca)
        if r["price"] is not None and prev and prev.get("price"):
            if r["price"] > 0 and r["price"] <= prev["price"] * 0.5 and r["status"] == "OK":
                r["status"] = "ROTO"
                r["detail"] = f"Caída fuerte: antes {prev['price']:.2f} €, ahora {r['price']:.2f} €."
        history[store["url"]] = {"price": r["price"], "checked_at": datetime.now(timezone.utc).isoformat()}
        r["checked_at"] = history[store["url"]]["checked_at"]
        results.append(r)
        print(f"{r['status']:10} {r['price']}  {r['url']}")

    checked_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_HTML.write_text(render_html(results, checked_at), encoding="utf-8")
    OUTPUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    zeros = [r for r in results if r["status"] == "ZERO"]
    if zeros:
        lines = ["🚨 ZeroPrice: ¡PRECIO A 0 €!"] + [
            f"• {r['name']} ({r['store']}) — 0,00 €\n  {r['url']}" for r in zeros
        ]
        send_telegram("\n".join(lines))
    print(f"Hecho: {len(results)} fichas, {len(zeros)} a 0 €.")


if __name__ == "__main__":
    main()
