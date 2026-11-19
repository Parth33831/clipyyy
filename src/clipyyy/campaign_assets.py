"""Campaign-specific stock-footage discovery using the existing Pexels integration.

Discovered assets are optional supporting footage. Creator-supplied campaign sources remain
first in the source list and keep their existing indexes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx

from clipyyy.media import probe

logger = logging.getLogger(__name__)


def campaign_search_queries(plan: dict[str, Any], brief: str = "") -> list[str]:
    """Build a few concise stock-search phrases from explicit campaign requirements."""
    subject = _phrase(plan.get("subject_or_theme"))
    content_type = _phrase(plan.get("content_type"))
    moods = _phrase(plan.get("mood"))
    styles = _phrase(plan.get("visual_style_and_pacing"))
    mandatory = _phrase(plan.get("mandatory_content"))

    candidates = [
        subject,
        " ".join(part for part in (subject, moods) if part),
        " ".join(part for part in (content_type, subject) if part),
        " ".join(part for part in (subject, mandatory) if part),
        styles,
    ]
    if not any(candidates):
        words = re.findall(r"[a-zA-Z]{3,}", brief.lower())
        stop = {"the", "and", "for", "with", "from", "this", "that", "video", "campaign", "make"}
        fallback = " ".join(word for word in words if word not in stop)[:80]
        candidates.append(fallback)

    queries: list[str] = []
    for candidate in candidates:
        query = " ".join(candidate.split())[:80].strip()
        if query and query.casefold() not in {item.casefold() for item in queries}:
            queries.append(query)
        if len(queries) == 3:
            break
    return queries


def _phrase(value: Any) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value[:3])
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE).strip()


def discover_campaign_assets(
    plan: dict[str, Any],
    work_dir: Path,
    api_key: str,
    orientation: str = "portrait",
    max_assets: int = 3,
    brief: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Search and download a small set of Pexels clips; failures never block the campaign."""
    if not api_key:
        return [], {"status": "skipped_missing_pexels_key", "queries": [], "assets_found": 0}

    queries = campaign_search_queries(plan, brief)
    if not queries:
        return [], {"status": "skipped_no_search_terms", "queries": [], "assets_found": 0}

    folder = work_dir / "campaign-stock"
    folder.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    failures = 0

    try:
        with httpx.Client(timeout=45, headers={"Authorization": api_key}) as client:
            for query in queries:
                if len(assets) >= max_assets:
                    break
                try:
                    response = client.get(
                        "https://api.pexels.com/videos/search",
                        params={"query": query, "orientation": orientation, "per_page": 12},
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    failures += 1
                    logger.warning("Campaign Pexels search failed for %r: %s", query, exc)
                    continue

                try:
                    videos = response.json().get("videos", [])
                except (AttributeError, ValueError):
                    failures += 1
                    logger.warning("Pexels returned an invalid video-search response for %r", query)
                    continue
                if not isinstance(videos, list):
                    failures += 1
                    continue
                for item in videos:
                    if not isinstance(item, dict):
                        continue
                    try:
                        video_id = int(item["id"])
                        duration = float(item.get("duration") or 0)
                    except (KeyError, TypeError, ValueError):
                        continue
                    if video_id in used_ids or duration < 3.0 or duration > 180.0:
                        continue
                    video_file = _best_video_file(item.get("video_files", []), orientation)
                    if not video_file:
                        continue

                    target = folder / f"pexels-{video_id}.mp4"
                    try:
                        _download_video(video_file["link"], target)
                        width, height, actual_duration = probe(target)
                    except Exception as exc:
                        failures += 1
                        target.unlink(missing_ok=True)
                        logger.warning("Could not stage Pexels video %s: %s", video_id, exc)
                        continue
                    if not width or actual_duration < 3.0:
                        target.unlink(missing_ok=True)
                        continue

                    author = str((item.get("user") or {}).get("name") or "Pexels creator")
                    page = str(item.get("url") or "")
                    if not page:
                        target.unlink(missing_ok=True)
                        continue
                    assets.append(
                        {
                            "source": page,
                            "title": f"Pexels stock footage — {query}",
                            "uploader": author,
                            "duration_seconds": float(actual_duration),
                            "width": int(width),
                            "height": int(height),
                            "video_path": str(target),
                            "source_kind": "pexels",
                            "pexels_id": video_id,
                            "search_query": query,
                            "credit": f"Video by {author} on Pexels",
                            "credit_url": page,
                        }
                    )
                    used_ids.add(video_id)
                    if len(assets) >= max_assets:
                        break
    except httpx.HTTPError as exc:
        failures += 1
        logger.warning("Campaign Pexels client failed: %s", exc)

    status = "added" if assets else ("search_failed" if failures else "no_matches")
    return assets, {
        "status": status,
        "queries": queries,
        "assets_found": len(assets),
        "search_failures": failures,
    }


def _best_video_file(files: list[dict[str, Any]], orientation: str) -> dict[str, Any] | None:
    candidates = []
    target_ratio = {"portrait": 9 / 16, "square": 1.0, "landscape": 16 / 9}.get(orientation, 9 / 16)
    for item in files:
        try:
            width, height = int(item.get("width") or 0), int(item.get("height") or 0)
        except (TypeError, ValueError):
            continue
        if item.get("link") and 480 <= width <= 1920 and height >= 270:
            candidates.append((abs(width / height - target_ratio), abs(width - 1080), item))
    return min(candidates, default=(0, 0, None), key=lambda value: (value[0], value[1]))[2]


def _download_video(url: str, path: Path) -> None:
    max_bytes = 80 * 1024 * 1024
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > max_bytes:
            raise ValueError("Pexels video exceeds the 80 MB per-asset limit.")
        downloaded = 0
        with path.open("wb") as handle:
            for chunk in response.iter_bytes():
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise ValueError("Pexels video exceeds the 80 MB per-asset limit.")
                handle.write(chunk)
