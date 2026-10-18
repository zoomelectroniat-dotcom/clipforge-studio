"""Groq AI client: Whisper transcription + LLM highlight detection / virality scoring.

Uses the user's real free Groq stack. The key is read from the GROQ_API_KEY
environment variable, falling back to the user's existing key file
(~/workspace/clipforge-server/.groq_key). It is never logged or exposed.

Set GROQ_STUB=1 to use deterministic canned outputs (offline dev / tests).
"""
import json
import os
import pathlib
import time

import httpx

BASE = "https://api.groq.com/openai/v1"
WHISPER_MODEL = "whisper-large-v3-turbo"
LLM_MODEL = "openai/gpt-oss-120b"
KEY_FILE = pathlib.Path.home() / "workspace" / "clipforge-server" / ".groq_key"


def _api_key() -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if key:
        return key.strip()
    try:
        if KEY_FILE.exists():
            return KEY_FILE.read_text().strip()
    except OSError:
        pass
    return None


def stub_mode() -> bool:
    return os.environ.get("GROQ_STUB") == "1" or not _api_key()


class GroqClient:
    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        # NOTE: the sandbox sets proxy env vars with IPv6 no_proxy entries that
        # httpx 0.28 cannot parse ("Invalid port"). Bypass env parsing and hand
        # httpx the egress proxy explicitly.
        proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        self._proxy = proxy_url or None

    def _client_kwargs(self) -> dict:
        kw = {"timeout": self.timeout, "trust_env": False}
        if self._proxy:
            kw["proxy"] = self._proxy
        return kw

    # ------------------------------------------------------------------ ping
    def ping(self) -> dict:
        """Lightweight connectivity check. Returns {'ok': True} or {'ok': False, 'error': ...}."""
        if stub_mode():
            return {"ok": True, "stub": True}
        try:
            r = httpx.get(f"{BASE}/models", headers=self._headers(), **self._client_kwargs())
            return {"ok": r.status_code == 200, "status": r.status_code}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:200]}

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {_api_key()}"}

    # ----------------------------------------------------------- transcription
    def transcribe(self, audio_path: str) -> dict:
        """Return {'words': [{'w': str, 'start_ms': int, 'end_ms': int}], 'text': str}."""
        if stub_mode():
            return _stub_transcript()
        last_err = ""
        for attempt in range(3):
            try:
                with open(audio_path, "rb") as f:
                    files = {"file": (pathlib.Path(audio_path).name, f, "audio/wav")}
                    data = {
                        "model": WHISPER_MODEL,
                        "response_format": "verbose_json",
                        "timestamp_granularities[]": "word",
                        "language": "en",
                    }
                    r = httpx.post(
                        f"{BASE}/audio/transcriptions",
                        headers=self._headers(),
                        files=files,
                        data=data,
                        **self._client_kwargs(),
                    )
                if r.status_code == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                r.raise_for_status()
                payload = r.json()
                words = []
                for w in payload.get("words", []):
                    words.append({
                        "w": w.get("word", "").strip(),
                        "start_ms": int(float(w.get("start", 0)) * 1000),
                        "end_ms": int(float(w.get("end", 0)) * 1000),
                    })
                words = [w for w in words if w["w"]]
                return {"words": words, "text": payload.get("text", "")}
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:200]
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"Groq transcription failed after retries: {last_err}")

    # ------------------------------------------------------ highlight detect
    def detect_highlights(self, transcript_text: str, prefs: dict) -> list[dict]:
        """Return a list of clip dicts: title, start_ms, end_ms, hook, flow,
        value, virality, keywords[]."""
        if stub_mode():
            return _stub_highlights(prefs)
        prompt = _detect_prompt(transcript_text, prefs)
        last_err = ""
        for attempt in range(3):
            try:
                r = httpx.post(
                    f"{BASE}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": "You are a short-form video editor. Reply with JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.4,
                        "max_tokens": 4000,
                    },
                    **self._client_kwargs(),
                )
                if r.status_code == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                return _parse_clips(content)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:200]
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"Groq highlight detection failed after retries: {last_err}")


    # ------------------------------------------------- AI opening hooks
    def rewrite_hooks(self, clips: list[dict]) -> list[str]:
        """Rewrite clip titles into punchier opening hooks.

        clips: [{'title': str, 'text': str}] (text = first ~40 words of the clip).
        Returns a same-length list of rewritten titles. One LLM call for the batch.
        """
        if stub_mode():
            return [_stub_hook(c["title"]) for c in clips]
        payload = [{"title": c["title"], "text": c["text"][:400]} for c in clips]
        prompt = (
            "You write opening hooks for vertical short-form clips (TikTok/Reels/Shorts). "
            "For each clip, rewrite its title into a punchier hook a scroller cannot ignore: "
            "under 60 characters, no clickbait lies, keep the clip's real topic, Title Case not required. "
            "Reply with a JSON array of strings only, same order, no commentary.\n\n"
            f"Clips:\n{json.dumps(payload)}"
        )
        last_err = ""
        for attempt in range(3):
            try:
                r = httpx.post(
                    f"{BASE}/chat/completions",
                    headers=self._headers(),
                    json={
                        "model": LLM_MODEL,
                        "messages": [
                            {"role": "system", "content": "You write viral video hooks. Reply with JSON only."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.6,
                        "max_tokens": 1500,
                    },
                    **self._client_kwargs(),
                )
                if r.status_code == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1] if "\n" in content else content[3:]
                    if content.rstrip().endswith("```"):
                        content = content.rstrip()[:-3]
                data = json.loads(content)
                if isinstance(data, list) and len(data) == len(clips):
                    return [str(t)[:120] for t in data]
                raise RuntimeError("hook rewrite returned wrong shape")
            except Exception as e:  # noqa: BLE001
                last_err = str(e)[:200]
                time.sleep(2 ** attempt * 2)
        raise RuntimeError(f"Groq hook rewrite failed after retries: {last_err}")


def _stub_hook(title: str) -> str:
    return f"{title} — watch this"


def _detect_prompt(transcript_text: str, prefs: dict) -> str:
    min_len = prefs.get("clip_length_min", 15)
    max_len = prefs.get("clip_length_max", 60)
    genre = prefs.get("genre", "talking-head")
    keywords = ", ".join(prefs.get("keywords", []) or [])
    user_prompt = prefs.get("prompt", "")
    language = prefs.get("language", "en")
    return f"""You are editing viral short-form clips from a {genre} video transcript.

Each line is [seconds] text. Find the most engaging standalone moments that work
as vertical short clips. Prefer moments with a strong hook in the first 3 seconds,
a clear payoff, and concrete value (a tip, a story, a surprising claim).

Constraints:
- Clip length between {min_len} and {max_len} seconds each.
- Return at most 8 clips, ordered by virality (best first).
- Language: {language}.
- {"Bias toward these keywords/topics: " + keywords + "." if keywords else ""}
- {"User instruction: " + user_prompt if user_prompt else ""}

Score every clip 0-100 on:
- hook: does the first 3 seconds stop a scroller?
- flow: does the moment have a complete arc (setup -> payoff)?
- value: concrete takeaway for the viewer?
- virality: overall 0-100 (roughly the average, weighted to the hook).

Reply with a JSON array only, no markdown fences, no commentary:
[{{"title": "short punchy title", "start_sec": 12.5, "end_sec": 47.0,
   "hook": 82, "flow": 74, "value": 68, "virality": 76,
   "keywords": ["word1", "word2"]}}]

Transcript:
{transcript_text[:12000]}"""


def _parse_clips(content: str) -> list[dict]:
    text = content.strip()
    # strip markdown fences if the model added them
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    data = json.loads(text)
    clips = []
    for c in data if isinstance(data, list) else []:
        try:
            clips.append({
                "title": str(c.get("title", "Untitled clip"))[:120],
                "start_ms": int(float(c.get("start_sec", 0)) * 1000),
                "end_ms": int(float(c.get("end_sec", 30)) * 1000),
                "hook": int(c.get("hook", 50)),
                "flow": int(c.get("flow", 50)),
                "value": int(c.get("value", 50)),
                "virality": max(0, min(100, int(c.get("virality", 50)))),
                "keywords": [str(k)[:40] for k in (c.get("keywords") or [])][:8],
            })
        except (TypeError, ValueError):
            continue
    return clips


# ------------------------------------------------------------------ stubs
def _stub_transcript() -> dict:
    """Deterministic canned transcript for offline dev/tests."""
    sentences = [
        "Welcome back to the show, today we are talking about focus.",
        "The biggest mistake people make is checking their phone first thing.",
        "Here is a simple trick: put your phone in another room overnight.",
        "I tried this for thirty days and my mornings completely changed.",
        "Let me explain why this works better than any productivity app.",
        "Your brain craves novelty, and the phone is a novelty slot machine.",
        "Replace the habit, do not just remove it, keep a book by the bed.",
        "Thanks for watching, subscribe for one practical tip every week.",
    ]
    words, t = [], 0
    for s in sentences:
        for w in s.split():
            dur = 320
            words.append({"w": w, "start_ms": t, "end_ms": t + dur})
            t += dur + 80
        t += 600
    return {"words": words, "text": " ".join(s for s in sentences)}


def _stub_highlights(prefs: dict) -> list[dict]:
    return [
        {"title": "Put your phone in another room", "start_ms": 8000, "end_ms": 28000,
         "hook": 85, "flow": 78, "value": 82, "virality": 82, "keywords": ["phone", "trick"]},
        {"title": "Your brain craves novelty", "start_ms": 30000, "end_ms": 52000,
         "hook": 76, "flow": 72, "value": 74, "virality": 74, "keywords": ["brain", "novelty"]},
        {"title": "Replace the habit, don't remove it", "start_ms": 54000, "end_ms": 68000,
         "hook": 70, "flow": 66, "value": 71, "virality": 69, "keywords": ["habit", "book"]},
    ]
