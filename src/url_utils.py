import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

REMOVED_QUERY_PREFIXES = (
    "utm_",
    "ref",
    "fbclid",
    "gclid",
    "yclid",
)


def _normalize_path(path: str) -> str:
    # collapse multiple slashes and remove trailing slash (except root)
    collapsed = re.sub(r"/+", "/", path or "/")
    if collapsed != "/" and collapsed.endswith("/"):
        collapsed = collapsed[:-1]
    return collapsed or "/"


def canonicalize_url(url: str) -> str:
    """Return a canonical form of the URL for deduplication.

    Rules:
    - Lowercase scheme and hostname; force https scheme
    - Remove default ports (:80 for http, :443 for https)
    - Drop fragments
    - Remove tracking params (utm_*, fbclid, gclid, yclid, ref)
    - Sort query parameters
    - Normalize path slashes and trailing slash
    """
    if not url:
        return url

    parts = urlsplit(url)

    scheme = (parts.scheme or "https").lower()
    # Prefer https
    if scheme == "http":
        scheme = "https"

    hostname = (parts.hostname or "").lower()
    port = parts.port
    # Remove default/common ports (both 80 and 443) regardless of scheme normalization
    if port in (80, 443) or port is None:
        netloc = hostname
    else:
        netloc = f"{hostname}:{port}"

    # Clean query
    query_pairs = []
    for k, v in parse_qsl(parts.query, keep_blank_values=True):
        key_l = k.lower()
        if any(key_l.startswith(prefix) for prefix in REMOVED_QUERY_PREFIXES):
            continue
        query_pairs.append((k, v))
    query_pairs.sort(key=lambda kv: (kv[0], kv[1]))
    query = urlencode(query_pairs, doseq=True)

    path = _normalize_path(parts.path)

    return urlunsplit((scheme, netloc, path, query, ""))
