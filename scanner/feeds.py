"""YouTube feed fetcher + Claude narrative generator (feeds feature).

build_feeds_json()   — fetch all channels, generate narrative, return payload dict
_resolve_channel_id  — resolve YouTube @handle → channel ID via page scrape
_fetch_videos        — parse YouTube RSS feed for a channel
_generate_narrative  — call Claude Haiku to summarise recent video titles/descriptions
"""

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

from scanner import config as _cfg

log = logging.getLogger(__name__)

_YT_RSS  = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
_YT_PAGE = "https://www.youtube.com/@{handle}"
_THUMB   = "https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

# XML namespace used in YouTube Atom feeds
_NS = {
    "atom":   "http://www.w3.org/2005/Atom",
    "yt":     "http://www.youtube.com/xml/schemas/2015",
    "media":  "http://search.yahoo.com/mrss/",
}


def _resolve_channel_id(handle: str) -> str | None:
    """Fetch the YouTube @handle page and extract the channel ID."""
    url = _YT_PAGE.format(handle=handle)
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        # YouTube embeds the channel ID as "externalId":"UCxxxxxxxx..." in the page JS.
        m = re.search(r'"externalId"\s*:\s*"(UC[A-Za-z0-9_\-]{20,})"', r.text)
        if m:
            return m.group(1)
        # Fallback: browse_id pattern
        m2 = re.search(r'"browseId"\s*:\s*"(UC[A-Za-z0-9_\-]{20,})"', r.text)
        if m2:
            return m2.group(1)
    except Exception as e:
        log.warning("feeds: could not resolve channel ID for @%s: %s", handle, e)
    return None


def _fetch_videos(channel_id: str, max_items: int) -> list[dict]:
    """Return a list of video dicts from the YouTube Atom RSS feed."""
    url = _YT_RSS.format(channel_id=channel_id)
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log.warning("feeds: RSS fetch failed for channel %s: %s", channel_id, e)
        return []

    videos = []
    for entry in root.findall("atom:entry", _NS)[:max_items]:
        video_id = (entry.findtext("yt:videoId", namespaces=_NS) or "").strip()
        title    = (entry.findtext("atom:title", namespaces=_NS) or "").strip()
        link_el  = entry.find("atom:link[@rel='alternate']", _NS)
        link     = link_el.get("href", "") if link_el is not None else (
            f"https://www.youtube.com/watch?v={video_id}" if video_id else "")
        published = (entry.findtext("atom:published", namespaces=_NS) or "").strip()

        # Short description from media:group/media:description
        desc = ""
        mg = entry.find("media:group", _NS)
        if mg is not None:
            raw = (mg.findtext("media:description", namespaces=_NS) or "").strip()
            # Trim to first 200 chars so the payload stays small
            desc = raw[:200] + ("…" if len(raw) > 200 else "")

        if not video_id or not title:
            continue

        videos.append({
            "video_id":  video_id,
            "title":     title,
            "url":       link or f"https://www.youtube.com/watch?v={video_id}",
            "published": published,
            "thumbnail": _THUMB.format(video_id=video_id),
            "description": desc,
        })

    return videos


def _generate_narrative(channels: list[dict]) -> dict | None:
    """Call Claude Haiku with recent video titles to generate a market narrative.

    Returns None if ANTHROPIC_API_KEY is not set or the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        log.info("feeds: ANTHROPIC_API_KEY not set — skipping narrative generation")
        return None

    # Build context from all channels' recent videos
    lines = []
    for ch in channels:
        if ch["videos"]:
            lines.append(f"\n## {ch['name']} (@{ch['handle']})")
            for v in ch["videos"]:
                pub = v["published"][:10] if v["published"] else ""
                lines.append(f"- [{pub}] {v['title']}")
                if v["description"]:
                    lines.append(f"  > {v['description'][:120]}")

    if not lines:
        return None

    context_block = "\n".join(lines)
    prompt = (
        "You are a concise market analyst. Based on the recent YouTube video titles and "
        "descriptions below from trading/finance content creators, write a short market "
        "narrative summary (3-5 sentences). Focus on: what themes are dominating (crypto, "
        "tech stocks, macro, etc.), the overall tone (bullish/bearish/cautious), and any "
        "specific assets getting attention. Write in plain English — no bullet points, no "
        "headers. End with one sentence on what to watch this week.\n\n"
        f"Recent videos:\n{context_block}"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=_cfg.FEEDS_NARRATIVE_MODEL,
            max_tokens=_cfg.FEEDS_NARRATIVE_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip() if msg.content else ""
        if not text:
            return None
        return {
            "summary":      text,
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model":        _cfg.FEEDS_NARRATIVE_MODEL,
        }
    except Exception as e:
        log.warning("feeds: narrative generation failed: %s", e)
        return None


def build_feeds_json() -> dict:
    """Fetch all YouTube channels and generate the narrative. Returns the full payload."""
    max_v = int(getattr(_cfg, "FEEDS_MAX_VIDEOS", 8))
    channels_out = []

    for ch_cfg in _cfg.YOUTUBE_CHANNELS:
        name      = ch_cfg["name"]
        handle    = ch_cfg["handle"]
        ch_id     = ch_cfg.get("channel_id", "").strip()

        if not ch_id:
            log.info("feeds: resolving channel ID for @%s …", handle)
            ch_id = _resolve_channel_id(handle) or ""
            if ch_id:
                log.info("feeds: resolved @%s → %s", handle, ch_id)
            else:
                log.warning("feeds: could not resolve channel ID for @%s — skipping", handle)

        videos = _fetch_videos(ch_id, max_v) if ch_id else []
        log.info("feeds: %s — %d videos fetched", name, len(videos))

        channels_out.append({
            "name":       name,
            "handle":     handle,
            "channel_id": ch_id,
            "url":        f"https://www.youtube.com/@{handle}",
            "videos":     videos,
        })

    narrative = _generate_narrative(channels_out)

    return {
        "updated":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "narrative": narrative,
        "channels":  channels_out,
        "x_accounts": _cfg.X_ACCOUNTS,
    }
