"""Scrape the full Verso Books catalog via Shopify's products.json API and emit a single markdown file.

Run: python3 scrape_verso.py
Output: books.md in the same directory.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

CATALOG_URL = "https://www.versobooks.com/collections/catalog/products.json"
PRODUCT_URL = "https://www.versobooks.com/products/{handle}"
PAGE_SIZE = 100
DELAY_SECONDS = 1.5
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
OUT_PATH = "books.md"


class _HTMLToText(HTMLParser):
    """Strip HTML tags while preserving paragraph and list breaks."""

    BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self._chunks.append("\n")
        if tag == "li":
            self._chunks.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def get_text(self) -> str:
        raw = "".join(self._chunks)
        raw = html.unescape(raw)
        # Collapse runs of spaces/tabs but keep newlines.
        raw = re.sub(r"[ \t]+", " ", raw)
        # Collapse 3+ newlines to 2.
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        # Strip trailing/leading whitespace per line.
        lines = [ln.strip() for ln in raw.split("\n")]
        return "\n".join(lines).strip()


def html_to_text(body_html: str | None) -> str:
    if not body_html:
        return ""
    parser = _HTMLToText()
    parser.feed(body_html)
    return parser.get_text()


def fetch_page(page: int) -> list[dict]:
    url = f"{CATALOG_URL}?limit={PAGE_SIZE}&page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                return payload.get("products", [])
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_err = exc
            backoff = 2 ** attempt
            print(f"  ! page {page} attempt {attempt + 1} failed ({exc}); sleeping {backoff}s", file=sys.stderr)
            time.sleep(backoff)
    raise RuntimeError(f"failed to fetch page {page} after 3 attempts: {last_err}")


def fetch_all() -> list[dict]:
    seen: set[int] = set()
    books: list[dict] = []
    page = 1
    while True:
        print(f"fetching page {page} ...", flush=True)
        products = fetch_page(page)
        if not products:
            break
        new_in_page = 0
        for p in products:
            pid = p.get("id")
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            books.append(p)
            new_in_page += 1
        print(f"  got {len(products)} products ({new_in_page} new); total so far: {len(books)}", flush=True)
        if len(products) < PAGE_SIZE:
            break
        page += 1
        time.sleep(DELAY_SECONDS)
    return books


def format_price(variant: dict) -> str:
    price = variant.get("price")
    if price in (None, "", "0.00"):
        return ""
    title = (variant.get("title") or "").strip()
    if title and title.lower() != "default title":
        return f"{title} ${price}"
    return f"${price}"


def book_to_markdown(book: dict) -> str:
    title = (book.get("title") or "Untitled").strip()
    handle = book.get("handle") or ""
    link = PRODUCT_URL.format(handle=handle) if handle else ""
    vendor = (book.get("vendor") or "").strip()
    product_type = (book.get("product_type") or "").strip()
    published_at = book.get("published_at") or ""
    published_date = published_at[:10] if published_at else ""
    tags = book.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    variants = book.get("variants") or []
    formats = [format_price(v) for v in variants]
    formats = [f for f in formats if f]
    formats_line = " / ".join(formats)

    description = html_to_text(book.get("body_html"))

    lines: list[str] = []
    lines.append(f"## {title}")
    lines.append("")
    if link:
        lines.append(f"- **Link**: {link}")
    if vendor:
        lines.append(f"- **Vendor/Author**: {vendor}")
    if product_type:
        lines.append(f"- **Type**: {product_type}")
    if published_date:
        lines.append(f"- **Published**: {published_date}")
    if formats_line:
        lines.append(f"- **Formats & Prices**: {formats_line}")
    if tags:
        lines.append(f"- **Tags**: {', '.join(tags)}")
    if description:
        lines.append("")
        lines.append(description)
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def write_markdown(books: list[dict], path: str) -> None:
    today = dt.date.today().isoformat()
    header = [
        "# Verso Books Catalog",
        "",
        f"Scraped from https://www.versobooks.com/collections/catalog on {today}.",
        f"Total: {len(books)} books.",
        "",
        "---",
        "",
    ]
    sorted_books = sorted(
        books,
        key=lambda b: (b.get("published_at") or ""),
        reverse=True,
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(header))
        for book in sorted_books:
            f.write(book_to_markdown(book))


def main() -> int:
    books = fetch_all()
    if not books:
        print("no books fetched; aborting", file=sys.stderr)
        return 1
    write_markdown(books, OUT_PATH)
    print(f"\nwrote {len(books)} books to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
