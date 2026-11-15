"""Wöchentlicher Lauf: Quellen abrufen, Claude Termine auswählen lassen, events.json schreiben.

Aufruf:  python scraper/run.py            (braucht ANTHROPIC_API_KEY)
         python scraper/run.py --dry-run  (nur Seiten abrufen, keine KI, nichts schreiben)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import anthropic
import yaml

from fetch import fetch_page

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "scraper" / "sources.yaml"
EVENTS_FILE = ROOT / "docs" / "data" / "events.json"
CACHE_FILE = ROOT / "scraper" / "cache.json"

# Modell: Opus 5.5 = beste Auswahl. Günstiger: "claude-sonnet-5-5" (ca. halber Preis)
# oder "claude-haiku-5-5" (Bruchteil der Kosten, etwas schwächere Auswahl).
MODEL = "claude-opus-5-5"
HORIZON_DAYS = 270  # so weit in die Zukunft werden Termine gezeigt
MIN_RELEVANCE = 3   # 1–5; alles darunter wird nicht angezeigt

CATEGORIES = [
    "Tanz & Ballett",
    "Theater & Oper",
    "Musik & Konzerte",
    "Wandern & Natur",
    "Rad & Bewegung",
    "Ausstellungen & Kunst",
    "Führungen & Vorträge",
    "Kurse zum Mitmachen",
    "Feste & Märkte",
    "Ausflüge & Reisen",
    "Film",
]
REGIONS = [
    "Braunschweig", "Wolfenbüttel", "Wolfsburg", "Hannover", "Hildesheim",
    "Harz", "Magdeburg", "Celle", "Umgebung",
]

# Ticket-Anbieter, die als sichere Buchungsquelle gelten (zusätzlich zur Domain des Veranstalters)
TRUSTED_TICKET_DOMAINS = {
    "eventim.de", "reservix.de", "adticket.de", "ticketmaster.de",
    "eventbrite.de", "ticket-regional.de", "ticketcenter-braunschweig.de",
}

PROFILE = """Ihr wählt Veranstaltungen für ein Ehepaar aus Braunschweig aus (beide 55–65 Jahre).
Sie lieben Tanztheater, Ballett und zeitgenössischen Tanz, gehen gern ins Theater und in Konzerte
und sind sportlich aktiv (Wandern, Radfahren, Bewegung in der Natur). Sie fahren gern auch nach
Hannover, Wolfsburg, Hildesheim, Magdeburg oder in den Harz, wenn es sich lohnt.
Ziel: Sie sollen Dinge entdecken, auf die sie selbst nicht gekommen wären – Qualität vor Menge.

Relevanz (1–5):
5 = Highlight: von der Kritik gelobt, preisgekrönt, renommierte Gastspiel-Compagnie, Festival-Höhepunkt,
    Premiere einer hochgelobten Produktion, seltenes/einmaliges Ereignis, besonderer Ort.
4 = Sehr empfehlenswert: starke Produktion, interessantes Format, schöne geführte Tour, offen für Gäste.
3 = Solide und passend, lohnt sich für Abwechslung.
1–2 = Routine, Massenware oder unpassend → NICHT aufnehmen.

Nicht aufnehmen: Kinder-/Schul-/Familienvorstellungen, Comedy-Massenware, Tribute- und Coverbands,
Partys/Clubnächte, Kurse für Kinder, Vereinsinterna (nur für Mitglieder), regelmäßige Routine-Termine
ohne Besonderheit, ausverkaufte oder abgesagte Termine, Termine in der Vergangenheit.
Ein Stück mit mehreren Vorstellungen = EIN Eintrag (nächster Termin als Datum, weitere in other_dates)."""

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "date_start": {"type": "string", "description": "YYYY-MM-DD"},
                    "date_end": {"type": "string", "description": "YYYY-MM-DD bei mehrtägigen Events, sonst leer"},
                    "time": {"type": "string", "description": "z.B. 19:30, sonst leer"},
                    "other_dates": {"type": "array", "items": {"type": "string"}, "description": "weitere Termine YYYY-MM-DD"},
                    "venue": {"type": "string"},
                    "city": {"type": "string"},
                    "region": {"type": "string", "enum": REGIONS},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "summary": {"type": "string", "description": "1–2 Sätze: Was ist das?"},
                    "why": {"type": "string", "description": "1 Satz: Warum lohnt es sich für die beiden?"},
                    "relevance": {"type": "integer"},
                    "url": {"type": "string", "description": "Link zur Detailseite, exakt aus dem Text kopiert"},
                    "booking_url": {"type": "string", "description": "Ticket-/Anmelde-Link exakt aus dem Text, sonst leer"},
                    "price": {"type": "string", "description": "Preisangabe, sonst leer"},
                },
                "required": [
                    "title", "date_start", "date_end", "time", "other_dates", "venue", "city",
                    "region", "category", "summary", "why", "relevance", "url", "booking_url", "price",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""{PROFILE}

Du bekommst den Text einer Veranstaltungs-Webseite (Links stehen als [Text](URL) im Text).
Extrahiere nur passende Veranstaltungen mit Relevanz ≥ {MIN_RELEVANCE} und schreibe alles auf Deutsch.
- Links: Verwende ausschließlich URLs, die wörtlich im Text vorkommen. Erfinde niemals Links.
  url = Detailseite der Veranstaltung (falls keine vorhanden: die Seiten-URL).
  booking_url = nur ein offizieller Ticket-/Anmeldelink aus dem Text, sonst leer lassen.
- Daten: nur Termine ab dem heutigen Datum. Wenn das Jahr fehlt, leite es sinnvoll ab.
- summary: sachlich, kurz, ohne Werbesprache. why: persönlich und konkret für die beiden.
- Wenn nichts Passendes dabei ist, gib eine leere Liste zurück."""

DISCOVERY_PROMPT = """{profile}

Heute ist {today}. Suche im Web nach besonderen Veranstaltungen in den nächsten 4 Monaten, die man
von Braunschweig aus gut erreicht (Braunschweig, Wolfenbüttel, Wolfsburg, Hannover, Hildesheim, Harz,
Magdeburg, Celle, Heide, Elm, Lappwald) und die NICHT ohnehin im Spielplan der großen Häuser stehen
(Staatstheater Braunschweig, Staatsoper Hannover u. ä. werden schon separat abgedeckt).

Suche besonders nach:
- geführten Wanderungen und Naturexkursionen, die für Gäste offen sind (Harzklub, Alpenverein, NABU, Nationalpark Harz, Wandervereine)
- geführten Radtouren (ADFC u. a.)
- Tanz-Gastspielen, Tanzfestivals, besonderen Konzertreihen, Kloster- und Schlosskonzerten
- Kursen und Workshops für Erwachsene zum Mitmachen (z. B. Tango-/Salsa-Schnupperkurse für Paare, Tanzworkshops)
- besonderen Ausstellungen, Führungen hinter die Kulissen, Tagesausflügen und Festivals

Liste am Ende jede gefundene Veranstaltung mit Titel, Datum, Ort, kurzer Beschreibung und der
offiziellen Veranstalter-URL aus deinen Suchergebnissen auf. Nimm nur Veranstaltungen mit konkretem Datum."""


# ---------------------------------------------------------------- Hilfsfunktionen

def domain(url: str) -> str:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def same_site(url: str, site: str) -> bool:
    d, s = domain(url), domain(site)
    root = ".".join(s.split(".")[-2:])
    return d == s or d.endswith("." + root) or d == root


def safe_booking(url: str, source_url: str, allowed_links: set[str]) -> str:
    if not url or not url.startswith("https://") or url not in allowed_links:
        return ""
    if same_site(url, source_url):
        return url
    d = domain(url)
    if any(d == t or d.endswith("." + t) for t in TRUSTED_TICKET_DOMAINS):
        return url
    return ""


def parse_date(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s.strip()[:10])
    except (ValueError, AttributeError):
        return None


def event_id(ev: dict) -> str:
    norm = re.sub(r"[^a-z0-9äöüß]", "", ev["title"].lower())[:60]
    return hashlib.sha1(f"{norm}|{ev['date_start']}|{ev.get('city','').lower()}".encode()).hexdigest()[:12]


def text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


# ---------------------------------------------------------------- KI-Schritte

def extract_events(client, source_name: str, page_url: str, page_text: str, today: dt.date, usage: dict) -> list[dict]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        output_config={"format": {"type": "json_schema", "schema": EVENT_SCHEMA}},
        messages=[{
            "role": "user",
            "content": f"Heute ist {today.isoformat()}.\nQuelle: {source_name}\nSeiten-URL: {page_url}\n\n---\n{page_text}",
        }],
    )
    track(usage, response)
    if response.stop_reason == "refusal":
        print(f"   ! abgelehnt: {source_name}")
        return []
    if response.stop_reason == "max_tokens":
        print(f"   ! Antwort abgeschnitten: {source_name}")
        return []
    return json.loads(text_of(response))["events"]


def discover(client, today: dt.date, usage: dict) -> tuple[str, set[str]]:
    """Freie Websuche nach Veranstaltungen, die die festen Quellen nicht abdecken."""
    messages = [{"role": "user", "content": DISCOVERY_PROMPT.format(profile=PROFILE, today=today.isoformat())}]
    tools = [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 12,
        "user_location": {"type": "approximate", "city": "Braunschweig", "country": "DE", "timezone": "Europe/Berlin"},
    }]
    found_urls: set[str] = set()
    text = ""
    for _ in range(5):  # pause_turn: Suche ggf. fortsetzen
        with client.messages.stream(model=MODEL, max_tokens=32000, tools=tools, messages=messages) as stream:
            response = stream.get_final_message()
        track(usage, response)
        for block in response.content:
            if block.type == "web_search_tool_result" and isinstance(block.content, list):
                found_urls.update(r.url for r in block.content if getattr(r, "url", None))
        text += text_of(response)
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": response.content}]
    # Links, die Claude im Text nennt und die in den Suchergebnissen vorkamen, sind erlaubt
    return text, found_urls


def track(usage: dict, response) -> None:
    u = response.usage
    usage["input"] += (u.input_tokens or 0) + (u.cache_creation_input_tokens or 0)
    usage["cached"] += u.cache_read_input_tokens or 0
    usage["output"] += u.output_tokens or 0
    st = getattr(u, "server_tool_use", None)
    usage["searches"] += getattr(st, "web_search_requests", 0) or 0 if st else 0


# ---------------------------------------------------------------- Hauptablauf

def clean(raw: list[dict], source: dict, allowed_links: set[str], today: dt.date) -> list[dict]:
    out = []
    horizon = today + dt.timedelta(days=HORIZON_DAYS)
    for ev in raw:
        start = parse_date(ev.get("date_start", ""))
        end = parse_date(ev.get("date_end", "")) or start
        if not start or end < today or start > horizon:
            continue
        rel = max(1, min(5, int(ev.get("relevance", 0) or 0)))
        if rel < MIN_RELEVANCE:
            continue
        url = ev.get("url", "").strip()
        if url not in allowed_links or not url.startswith("http"):
            url = source["url"]
        ev = {**ev, "url": url, "relevance": rel}
        ev["booking_url"] = safe_booking(ev.get("booking_url", "").strip(), url, allowed_links)
        if ev["category"] not in CATEGORIES:
            ev["category"] = "Ausflüge & Reisen"
        if ev["region"] not in REGIONS:
            ev["region"] = source.get("region", "Umgebung")
        ev["other_dates"] = sorted(d for d in ev.get("other_dates", []) if (p := parse_date(d)) and p >= today)[:20]
        ev["source"] = source["name"]
        ev["id"] = event_id(ev)
        out.append(ev)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-discovery", action="store_true")
    args = ap.parse_args()

    today = dt.date.today()
    sources = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    old = json.loads(EVENTS_FILE.read_text(encoding="utf-8")) if EVENTS_FILE.exists() else {"events": []}
    old_events = old.get("events", [])
    cache = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}

    client = None if args.dry_run else anthropic.Anthropic()
    usage = {"input": 0, "cached": 0, "output": 0, "searches": 0}
    new_events: list[dict] = []
    ok_sources: set[str] = set()
    report = []

    for src in sources:
        page = fetch_page(src["url"])
        if page.error or len(page.text) < 200:
            report.append(f"✗ {src['name']}: {page.error or 'kaum Inhalt'}")
            continue
        text = (f"Hinweis zur Quelle: {src['hint']}\n\n" if src.get("hint") else "") + page.text
        digest = hashlib.sha256(text.encode()).hexdigest()
        if args.dry_run:
            report.append(f"✓ {src['name']}: {len(page.text)} Zeichen")
            continue
        cached = cache.get(src["url"])
        if cached and cached["hash"] == digest and cached.get("date", "") >= (today - dt.timedelta(days=28)).isoformat():
            raw = cached["events"]  # Seite unverändert → keine KI-Kosten
            note = "unverändert"
        else:
            try:
                raw = extract_events(client, src["name"], src["url"], text, today, usage)
            except anthropic.APIError as e:
                report.append(f"✗ {src['name']}: API-Fehler {e}")
                continue
            cache[src["url"]] = {"hash": digest, "date": today.isoformat(), "events": raw}
            note = "neu ausgewertet"
        events = clean(raw, src, page.links, today)
        new_events += events
        ok_sources.add(src["name"])
        report.append(f"✓ {src['name']}: {len(events)} Tipps ({note})")

    if not args.dry_run and not args.no_discovery:
        try:
            text, urls = discover(client, today, usage)
            if text.strip():
                src = {"name": "Websuche", "url": "https://www.google.de/search?q=" + "Veranstaltungen+Braunschweig", "region": "Umgebung"}
                raw = extract_events(client, "Websuche (verschiedene Veranstalter)", "", text, today, usage)
                events = [e for e in clean(raw, src, urls, today) if e["url"] in urls]  # nur echte Treffer-Links
                new_events += events
                ok_sources.add("Websuche")
                report.append(f"✓ Websuche: {len(events)} Tipps")
        except anthropic.APIError as e:
            report.append(f"✗ Websuche: API-Fehler {e}")

    if args.dry_run:
        print("\n".join(report))
        return 0

    # Zusammenführen: Quellen, die diesmal nicht erreichbar waren, behalten ihre alten Termine;
    # Funde aus der Websuche sammeln sich über die Wochen an.
    first_seen = {e["id"]: e.get("first_seen", today.isoformat()) for e in old_events}
    kept = [e for e in old_events if e.get("source") not in ok_sources or e.get("source") == "Websuche"]
    merged: dict[str, dict] = {}
    for ev in kept + new_events:
        end = parse_date(ev.get("date_end") or "") or parse_date(ev["date_start"])
        if not end or end < today:
            continue
        ev["first_seen"] = first_seen.get(ev["id"], today.isoformat())
        if ev["id"] not in merged or ev["relevance"] > merged[ev["id"]]["relevance"]:
            merged[ev["id"]] = ev

    events = sorted(merged.values(), key=lambda e: (e["date_start"], -e["relevance"]))
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    EVENTS_FILE.write_text(json.dumps({
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "count": len(events),
        "events": events,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    # Kosten grob schätzen (Opus 5.5: 4 $/20 $ pro Mio. Tokens, Cache-Lesen 0,20 $, Suche 10 $/1000)
    cost = usage["input"] * 4e-6 + usage["cached"] * 0.2e-6 + usage["output"] * 20e-6 + usage["searches"] * 0.01
    print("\n".join(report))
    print(f"\n{len(events)} Termine gespeichert. Tokens: {usage}. Geschätzte Kosten: ~{cost:.2f} $ (bei {MODEL})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
