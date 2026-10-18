"""Google Drive downloads. Clean-room.

Two paths:
  1. PUBLIC files shared as "Anyone with the link" — direct download, NO OAuth
     credentials needed.
  2. PRIVATE files — via the Drive API (files.get alt=media) with the user's
     own OAuth access token.
"""
import re
from urllib.parse import parse_qs, urlparse

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def extract_drive_file_id(url: str) -> str | None:
    """Pull the file id out of the common Drive share-URL shapes.

    Handles: /file/d/<id>/..., open?id=<id>, uc?id=<id>&export=download.
    Folders (/drive/folders/<id>) are NOT downloadable files -> None.
    """
    if not url:
        return None
    m = re.search(r"/file/d/([A-Za-z0-9_-]{10,})", url)
    if m:
        return m.group(1)
    try:
        q = parse_qs(urlparse(url).query)
        for cand in q.get("id", []):
            if re.fullmatch(r"[A-Za-z0-9_-]{10,}", cand):
                return cand
    except Exception:
        pass
    return None


def download_public(file_id: str, dest_path: str) -> str:
    """Download a Drive file shared as 'Anyone with the link'.

    Raises RuntimeError with a user-friendly message when the file is not
    publicly shared or Drive refuses the download.
    """
    base = "https://drive.google.com/uc?export=download"
    with httpx.Client(timeout=180, follow_redirects=True,
                      trust_env=False, headers=_UA) as c:
        r = c.get(base, params={"id": file_id})
        if "text/html" in r.headers.get("content-type", ""):
            # Large files show a virus-scan interstitial with a confirm token.
            m = (re.search(r"confirm=([0-9A-Za-z_-]+)", r.text)
                 or re.search(r'name="confirm"\s+value="([0-9A-Za-z_-]+)"', r.text))
            if not m:
                raise RuntimeError(
                    "This Drive file isn't shared publicly (\"Anyone with the link\"). "
                    "Change its sharing to public, or connect your Google account "
                    "to import private files.")
            r = c.get(base, params={"id": file_id, "confirm": m.group(1)})
            if "text/html" in r.headers.get("content-type", ""):
                raise RuntimeError(
                    "Drive refused the download — the file may be private, "
                    "deleted, or too large.")
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_bytes(1024 * 256):
                f.write(chunk)
    return dest_path


def download_private(file_id: str, dest_path: str, access_token: str) -> str:
    """Download via the Drive API (files.get?alt=media) with an OAuth token."""
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    try:
        with httpx.stream("GET", url,
                          headers={"Authorization": f"Bearer {access_token}", **_UA},
                          timeout=300, follow_redirects=True,
                          trust_env=False) as r:
            if r.status_code in (401, 403):
                raise RuntimeError("DRIVE_TOKEN_BAD")
            if r.status_code == 404:
                raise RuntimeError(
                    "Drive file not found — check the link and that the file "
                    "is shared with your Google account.")
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_bytes(1024 * 256):
                    f.write(chunk)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001 — map to a friendly message
        raise RuntimeError(f"Drive download failed: {str(e)[:160]}")
    return dest_path
