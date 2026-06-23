"""
auto_caption.py — Generate a clean caption from a video filename.

When caption_cleaner strips everything leaving an empty caption,
this generates a readable title from the filename.

  Input:  The.Chestnut.Man.2026.S02.480p.HEVC.HDRip.Hindi.English.x265.ESubs.mkv
  Output: The Chestnut Man (2026) S02 | 480p | Hindi - English
"""
import re

# Tokens that mark the end of the title portion
_TITLE_STOPWORDS = {
    r'\d{4}',                              # year like 2026
    r'S\d{1,2}(E\d{1,2})?',               # S01, S02E03
    r'E\d{1,2}',                           # E01
    r'(480|720|1080|2160|4K)p?',           # quality
    r'(BluRay|BDRip|HDRip|WEB-?DL|WEBRip|CAMRip|HDTV|DVDRip)',
    r'(HEVC|AVC|x264|x265|H\.?264|H\.?265|AV1)',
    r'(Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali|Marathi)',
    r'(AAC|DDP?5?\.?1|DTS|AC3|FLAC)',
    r'(ESub|ESubs|Subs?|Sub)',
    r'(PROPER|REPACK|EXTENDED|UNRATED|THEATRICAL|DIRECTORS)',
}

_QUALITY_RE   = re.compile(r'(480|720|1080|2160)p?', re.I)
_YEAR_RE      = re.compile(r'\b(19|20)\d{2}\b')
_SEASON_RE    = re.compile(r'S(\d{1,2})(?:E(\d{1,2}))?', re.I)
_LANG_RE      = re.compile(r'\b(Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali|Marathi)\b', re.I)
_CODEC_RE     = re.compile(r'\b(HEVC|x265|x264|AVC|H\.?265|H\.?264)\b', re.I)
_SOURCE_RE    = re.compile(r'\b(BluRay|BDRip|HDRip|WEB-?DL|WEBRip|HDTV|DVDRip|CAMRip)\b', re.I)
_STOP_RE      = re.compile(
    r'^(' + '|'.join(_TITLE_STOPWORDS) + r')$', re.I
)


def from_filename(filename: str | None) -> str | None:
    """
    Parse a media filename and return a clean readable caption.
    Returns None if filename is empty or unparseable.
    """
    if not filename:
        return None

    # Strip extension
    name = re.sub(r'\.[a-zA-Z0-9]{2,4}$', '', filename)

    # Normalize separators
    name = re.sub(r'[._]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()

    tokens = name.split()

    # Find where the title ends (first stop-word token)
    title_tokens = []
    for tok in tokens:
        if _STOP_RE.match(tok):
            break
        title_tokens.append(tok)

    if not title_tokens:
        return None

    title = ' '.join(title_tokens).title()

    # Year
    year_m = _YEAR_RE.search(name)
    year   = year_m.group() if year_m else None

    # Season / Episode
    season_m = _SEASON_RE.search(name)
    season   = None
    if season_m:
        s = f"S{int(season_m.group(1)):02d}"
        e = f"E{int(season_m.group(2)):02d}" if season_m.group(2) else ""
        season = s + e

    # Quality
    quality_m = _QUALITY_RE.search(name)
    quality   = f"{quality_m.group(1)}p" if quality_m else None

    # Languages
    langs = list(dict.fromkeys(  # preserve order, deduplicate
        m.group(0).capitalize() for m in _LANG_RE.finditer(name)
    ))
    lang_str = " - ".join(langs) if langs else None

    # Assemble caption
    parts = [title]
    if year:
        parts[0] = f"{title} ({year})"
    if season:
        parts.append(season)
    if quality:
        parts.append(quality)
    if lang_str:
        parts.append(lang_str)

    return " | ".join(parts)
