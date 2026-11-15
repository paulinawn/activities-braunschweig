# Kulturtipps rund um Braunschweig

Eine kleine Webseite mit handverlesenen Veranstaltungstipps (Tanz, Ballett, Theater, Musik, Wandern,
Radtouren, Ausstellungen, Kurse, Ausflüge) für Braunschweig und Umgebung, also auch Hannover, Wolfsburg,
Hildesheim, Magdeburg und den Harz.

**Webseite:** https://paulinawn.github.io/activities-braunschweig/

## So funktioniert's

> **Aktueller Stand:** Die erste Auswahl wurde einmalig von Hand erstellt (ohne API-Kosten).
> Der wöchentliche Lauf ist **ausgeschaltet**. Zum Einschalten im Repo unter *Settings → Secrets → Actions*
> das Secret `ANTHROPIC_API_KEY` anlegen und in `.github/workflows/weekly.yml` die `schedule`-Zeilen wieder einkommentieren.

1. Jeden **Freitag früh** startet automatisch eine GitHub Action (`.github/workflows/weekly.yml`), sobald sie eingeschaltet ist.
2. Sie ruft die Programmseiten aus [`scraper/sources.yaml`](scraper/sources.yaml) ab und macht zusätzlich
   eine Websuche nach besonderen Terminen (geführte Wanderungen, Festivals, Gastspiele, Kurse …).
3. Claude wählt daraus nur die lohnenden Termine aus, bewertet sie mit 1–5 Sternen und schreibt eine
   kurze Zusammenfassung plus „Warum für euch“.
4. Ticket-Links werden nur übernommen, wenn sie direkt zum Veranstalter oder zu einem bekannten
   Ticketanbieter führen (Eventim, Reservix …) und tatsächlich auf der Veranstalterseite stehen.
5. Das Ergebnis landet in `docs/data/events.json`, und GitHub Pages zeigt es auf der Webseite an.

## Anpassen

- **Neue Quelle:** einen Block in `scraper/sources.yaml` ergänzen.
- **Geschmack/Kriterien:** Text `PROFILE` in `scraper/run.py`.
- **Kosten senken:** in `scraper/run.py` `MODEL = "claude-sonnet-5-5"` (ca. halber Preis) oder
  `"claude-haiku-5-5"` (nur ein Bruchteil der Kosten) einstellen.
- **Sofort aktualisieren:** Reiter *Actions* → *Wöchentliche Kulturtipps* → *Run workflow*.

Seiten, die sich seit der letzten Woche nicht verändert haben, werden nicht neu von der KI ausgewertet.
Das spart Kosten.
