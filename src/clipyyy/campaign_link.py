"""Import publicly accessible campaign pages into a structured editing brief.

This fetcher deliberately reads only the supplied public page. It does not log in,
bypass access controls, execute page scripts, or download copyrighted reference media.
"""
from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

MAX_PAGE_BYTES = 2_000_000
MAX_TEXT_CHARS = 18_000
USER_AGENT = "ClipyyyCampaignImporter/1.0 (+local user-requested page analysis)"


class _PageParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.video_urls: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag == "title":
            self._in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "meta":
            key = values.get("property") or values.get("name") or ""
            content = values.get("content", "").strip()
            if key and content:
                self.meta[key.lower()] = content[:2000]
        if tag == "a" and values.get("href"):
            href = urljoin(self.base_url, values["href"])
            self.links.append({"url": href, "text": ""})
        if tag in {"video", "source"}:
            src = values.get("src") or values.get("data-src")
            if src:
                self.video_urls.append(urljoin(self.base_url, src))
            if values.get("poster"):
                self.video_urls.append(urljoin(self.base_url, values["poster"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        if not self._skip_depth:
            self.text_parts.append(text)
            if self.links and len(self.links[-1]["text"]) < 500:
                self.links[-1]["text"] = (self.links[-1]["text"] + " " + text).strip()


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Campaign link must be a public http:// or https:// webpage.")
    if parsed.username or parsed.password:
        raise ValueError("Campaign links containing embedded credentials are not supported.")
    host = parsed.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local and private-network campaign links are blocked for security.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))}
    except OSError as exc:
        raise ValueError("Could not resolve the campaign website. Check the link and internet connection.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("Campaign links pointing to private or local network addresses are blocked.")


def import_campaign_page(url: str) -> dict:
    """Fetch a public campaign page and return readable text plus reference links."""
    current = url.strip()
    if len(current) > 2048:
        raise ValueError("Campaign URL is too long.")
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    with httpx.Client(timeout=httpx.Timeout(20.0), follow_redirects=False, trust_env=False) as client:
        response = None
        for _ in range(5):
            _validate_public_url(current)
            response = client.get(current, headers=headers)
            if response.status_code not in {301, 302, 303, 307, 308}:
                break
            location = response.headers.get("location")
            if not location:
                raise ValueError("Campaign website returned an invalid redirect.")
            current = urljoin(current, location)
        else:
            raise ValueError("Campaign link redirected too many times.")
    assert response is not None
    if response.status_code >= 400:
        if response.status_code in {401, 403, 404}:
            raise ValueError(
                "The campaign page is private, blocked, or unavailable to Clipyyy. "
                "This site may require its app or a login."
            )
        raise ValueError(f"Campaign website returned HTTP {response.status_code}.")
    content_type = response.headers.get("content-type", "").lower()
    if "html" not in content_type and "text/" not in content_type:
        raise ValueError("That link did not return a readable campaign webpage.")
    if len(response.content) > MAX_PAGE_BYTES:
        raise ValueError("Campaign webpage is too large to analyse safely (2 MB limit).")
    encoding = response.encoding or "utf-8"
    parser = _PageParser(current)
    parser.feed(response.content.decode(encoding, errors="replace"))
    title = " ".join(parser.title_parts).strip() or parser.meta.get("og:title", "")
    description = parser.meta.get("og:description") or parser.meta.get("description", "")
    page_text = "\n".join(parser.text_parts)
    if description:
        page_text = f"Page description: {description}\n\n{page_text}"
    page_text = page_text[:MAX_TEXT_CHARS]
    if len(page_text.strip()) < 80:
        raise ValueError(
            "Clipyyy reached the page, but it contains too little readable text. "
            "The site may render campaign details inside an app or require login."
        )
    links = []
    seen = {current}
    for item in parser.links:
        target = item["url"]
        if target.startswith(("http://", "https://")) and target not in seen:
            seen.add(target)
            links.append(item)
    video_urls = list(dict.fromkeys(parser.video_urls))
    for key in ("og:video", "og:video:url", "twitter:player:stream"):
        value = parser.meta.get(key)
        if value:
            video_urls.append(urljoin(current, value))
    return {
        "url": current,
        "title": title[:300],
        "description": description[:2000],
        "text": page_text,
        "links": links[:100],
        "video_urls": list(dict.fromkeys(video_urls))[:20],
        "access": "public_html",
    }
