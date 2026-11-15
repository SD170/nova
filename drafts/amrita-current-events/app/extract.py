"""Readable article text for get_news_item (best effort, publisher pages only)."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

from .sources import client

MAX_CHARS = 6000


class _Paragraphs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.skip = 0
        self.buf: list[str] = []
        self.paras: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form"):
            self.skip += 1
        elif tag == "p" and not self.skip:
            self.depth += 1
            self.buf = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header", "aside", "form"):
            self.skip = max(0, self.skip - 1)
        elif tag == "p" and self.depth:
            self.depth -= 1
            text = re.sub(r"\s+", " ", html.unescape("".join(self.buf))).strip()
            if len(text) > 60:  # skip captions, bylines, buttons
                self.paras.append(text)

    def handle_data(self, data):
        if self.depth and not self.skip:
            self.buf.append(data)


async def article_text(url: str) -> tuple[str, str]:
    """Returns (text, note). Text is empty when it can't be read; the link still works."""
    host = urlparse(url).netloc
    if host.endswith("news.google.com"):
        return "", "Google News links open the article in the browser; follow the url to read it."
    try:
        async with client() as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0 (StudentJarvis news reader)"})
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return "", f"The publisher returned {r.status_code}; open the url to read it."
        p = _Paragraphs()
        p.feed(r.text)
        text = "\n\n".join(p.paras)[:MAX_CHARS]
        return (text, "") if text else ("", "This page has no readable text (paywall or app-only); open the url.")
    except Exception:
        return "", "The publisher didn't respond; open the url to read it."
