"""Lädt eine Webseite und macht daraus gut lesbaren Text inkl. Links."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; KulturTippsBot/1.0; "
    "+https://github.com/paulinawn/activities-braunschweig)"
)
MAX_CHARS = 60_000  # ca. 15.000 Tokens pro Seite


@dataclass
class Page:
    url: str
    text: str = ""
    links: set[str] = field(default_factory=set)
    error: str = ""


def fetch_page(url: str, timeout: int = 30) -> Page:
    page = Page(url=url)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "de-DE,de;q=0.9"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        page.error = str(e)[:200]
        return page

    resp.encoding = resp.encoding or resp.apparent_encoding
    base = resp.url
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "svg", "iframe", "form", "header", "footer"]):
        tag.decompose()
    for tag in soup.select("nav, [role=navigation], .cookie, #cookie, .cookie-banner"):
        tag.decompose()

    # Links als "[Text](URL)" in den Text einbetten, damit die KI echte Links verwenden kann
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urldefrag(urljoin(base, href))[0]
        if urlparse(absolute).scheme not in ("http", "https"):
            continue
        page.links.add(absolute)
        label = a.get_text(" ", strip=True)
        a.replace_with(f" [{label}]({absolute}) " if label else f" ({absolute}) ")

    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    page.text = text[:MAX_CHARS]
    page.links.add(base)
    page.links.add(url)
    return page
