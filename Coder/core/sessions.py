"""Chatverläufe als JSON unter ~/.coder/sessions/."""

import json
import re
import time
import uuid

from .config import SESSIONS_DIR

_ID = re.compile(r"^[a-f0-9]{12}$")


def new(workspace: str, model: str) -> dict:
    now = time.time()
    return {
        "id": uuid.uuid4().hex[:12],
        "title": "Neuer Chat",
        "created": now,
        "updated": now,
        "workspace": workspace,
        "model": model,
        # Nachrichten im Ollama-Format. Schlüssel mit "_" sind UI-Metadaten
        # und werden vor dem Senden an das Modell entfernt.
        "messages": [],
        "todos": [],
        "allow": [],
        "usage": {"prompt": 0, "completion": 0, "last_prompt": 0},
    }


def _path(session_id: str):
    if not _ID.match(session_id or ""):
        raise ValueError("Ungültige Session-ID")
    return SESSIONS_DIR / f"{session_id}.json"


def save(session: dict) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    session["updated"] = time.time()
    path = _path(session["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load(session_id: str) -> dict | None:
    try:
        return json.loads(_path(session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete(session_id: str) -> None:
    try:
        _path(session_id).unlink()
    except (OSError, ValueError):
        pass


_summaries: dict[str, tuple[float, int, dict]] = {}  # Datei → (Änderungszeit, Größe, Kurzfassung)


def list_all(limit: int = 200) -> list[dict]:
    if not SESSIONS_DIR.exists():
        return []
    items = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            stat = f.stat()
            cached = _summaries.get(str(f))
            if cached and cached[:2] == (stat.st_mtime, stat.st_size):
                items.append(cached[2])  # unverändert: nicht jedes Mal den ganzen Verlauf parsen
                continue
            s = json.loads(f.read_text(encoding="utf-8"))
            summary = {"id": s["id"], "title": s.get("title", ""), "updated": s.get("updated", 0),
                       "workspace": s.get("workspace", ""), "model": s.get("model", "")}
            _summaries[str(f)] = (stat.st_mtime, stat.st_size, summary)
            items.append(summary)
        except (OSError, ValueError, KeyError):
            continue
    items.sort(key=lambda s: s["updated"], reverse=True)
    return items[:limit]
