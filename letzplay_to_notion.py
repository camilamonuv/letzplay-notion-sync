import os
from datetime import datetime, date
import requests
from bs4 import BeautifulSoup

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_ID = os.getenv("NOTION_DB_ID")

HEADERS_NOTION = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Páginas /tourneys que você quer monitorar
CIRCUIT_URLS = [
    "https://letzplay.me/circuitobeachtennis/tourneys",
    # adicione outras URLs aqui quando quiser
]

def parse_date_br(s: str):
    s = s.strip().lower()
    meses = {
        "jan": "01", "fev": "02", "mar": "03", "abr": "04",
        "mai": "05", "jun": "06", "jul": "07", "ago": "08",
        "set": "09", "out": "10", "nov": "11", "dez": "12",
    }

    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        pass

    try:
        partes = s.split("/")
        if len(partes) == 3 and partes[1] in meses:
            dia = partes[0]
            mes = meses[partes[1]]
            ano = partes[2]
            return datetime.strptime(f"{dia}/{mes}/{ano}", "%d/%m/%Y").date()
    except Exception:
        pass

    return None

def fetch_tournaments_from_circuit(url_tourneys: str):
    resp = requests.get(url_tourneys, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/tourneys/" in href:
            if href.startswith("/"):
                href = "https://letzplay.me" + href
            links.append(href)

    return sorted(list(set(links)))

def parse_tournament(url_tourney: str):
    resp = requests.get(url_tourney, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Nome do torneio
    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else "Torneio sem nome"

    full_text = soup.get_text("\n", strip=True)

    # ----- Local (Arena) e Bairro -----
    arena = ""
    bairro = ""

    for line in full_text.split("\n"):
        if "são paulo" in line.lower() and "sp" in line.lower():
            arena = line.strip()
            # tentativa simples de extrair bairro
            parts = arena.split("-")
            if len(parts) > 1:
                possible_bairro = parts[-1].strip()
                if "são paulo" not in possible_bairro.lower() and "sp" not in possible_bairro.lower():
                    bairro = possible_bairro
            break

    # só queremos São Paulo/SP
    if "são paulo" not in arena.lower():
        return None

    # ----- Datas -----
    start_date = None
    end_date = None

    for line in full_text.split("\n"):
        low = line.lower()

        if "início em" in low:
            try:
                token = low.split("início em", 1)[1].strip().split()[0]
                d = parse_date_br(token)
                if d:
                    start_date = d
            except:
                pass

        if "jogos de" in low and "até" in low:
            try:
                after = low.split("jogos de", 1)[1]
                antes, depois = after.split("até", 1)
                d1 = parse_date_br(antes.strip().split()[0])
                d2 = parse_date_br(depois.strip().split()[0])
                if d1:
                    start_date = d1
                if d2:
                    end_date = d2
            except:
                pass

    if end_date is None:
        end_date = start_date

    # ----- Valor de inscrição -----
    valor = ""
    for line in full_text.split("\n"):
        if "r$" in line.lower():
            valor = line.strip()
            break

    return {
        "name": name,
        "arena": arena,
        "bairro": bairro,
        "valor": valor,
        "start_date": start_date,
        "end_date": end_date,
        "url": url_tourney,
    }

def notion_upsert(t):
    # usa o Link Letzplay como chave única
    query_url = f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query"
    payload = {
        "filter": {
            "property": "Link Letzplay",
            "url": {"equals": t["url"]}
        },
        "page_size": 1
    }
    r = requests.post(query_url, headers=HEADERS_NOTION, json=payload)
    r.raise_for_status()
    results = r.json().get("results", [])

    props = {
        "Torneio": {"title": [{"text": {"content": t["name"]}}]},
        "Local (Arena)": {"rich_text": [{"text": {"content": t["arena"]}}]},
        "Bairro": {"rich_text": [{"text": {"content": t["bairro"]}}]},
        "Valor de inscrição": {"rich_text": [{"text": {"content": t["valor"]}}]},
        "Link Letzplay": {"url": t["url"]},
    }

    if t["start_date"]:
        props["Data"] = {
            "date": {
                "start": t["start_date"].isoformat(),
                "end": t["end_date"].isoformat() if t["end_date"] else None,
            }
        }

    if results:
        page_id = results[0]["id"]
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        requests.patch(update_url, headers=HEADERS_NOTION, json={"properties": props})
        print(f"[UPDATE] {t['name']}")
    else:
        create_url = "https://api.notion.com/v1/pages"
        body = {"parent": {"database_id": NOTION_DB_ID}, "properties": props}
        requests.post(create_url, headers=HEADERS_NOTION, json=body)
        print(f"[CREATE] {t['name']}")

def main():
    if not NOTION_TOKEN or not NOTION_DB_ID:
        raise RuntimeError("NOTION_TOKEN ou NOTION_DB_ID não configurados")

    all_items = []

    for url in CIRCUIT_URLS:
        print("Buscando:", url)
        urls = fetch_tournaments_from_circuit(url)

        for u in urls:
            t = parse_tournament(u)
            if t:
                all_items.append(t)

    print(f"Encontrados {len(all_items)} torneios.")
    for t in all_items:
        notion_upsert(t)

if __name__ == "__main__":
    main()
