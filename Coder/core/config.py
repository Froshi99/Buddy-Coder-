"""Persistente Einstellungen unter ~/.coder/config.json."""

import json
import os
import re
from pathlib import Path

from .power import mode as awake_mode

HOME = Path(os.environ.get("CODER_HOME", Path.home() / ".coder"))
CONFIG_PATH = HOME / "config.json"
SESSIONS_DIR = HOME / "sessions"
APP_DIR = Path(__file__).resolve().parent.parent

PERMISSION_MODES = ("ask", "auto-edit", "plan", "yolo")


def normalize_path(raw: str | Path) -> Path:
    """Nimmt Pfade so, wie man sie einfügt: in Anführungszeichen („Als Pfad kopieren“), mit ~ oder %VARIABLEN%.

    Relative Angaben gelten ab dem Benutzerordner – das Arbeitsverzeichnis von Coder ist dafür kein sinnvoller Anker.
    """
    text = os.path.expandvars(os.path.expanduser(str(raw).strip().strip("\"'").strip()))
    if re.fullmatch(r"[A-Za-z]:", text):
        text += "\\"  # „D:“ meint das Laufwerk, nicht dessen letztes Arbeitsverzeichnis
    path = Path(text)
    if not path.is_absolute():
        path = Path.home() / path
    return path.resolve()


def blocked_workspace(path: str | Path) -> str | None:
    """Warum ein Ordner kein Workspace sein darf – oder None.

    Systemordner könnte der Agent beschädigen, und auf einer ganzen Laufwerkswurzel dauert jede Suche ewig.
    """
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        return "ungültiger Pfad"
    system_root = Path(os.environ.get("SystemRoot", "C:/Windows")).resolve()
    if p == system_root or system_root in p.parents:
        return "Systemordner von Windows"
    if p == Path(p.anchor):
        return "ganze Laufwerkswurzel"
    return None


def _default_workspace() -> str:
    # Per Doppelklick gestartet ist das Arbeitsverzeichnis oft Coder selbst oder system32 – dann der Benutzerordner.
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return str(Path.home())
    return str(Path.home() if cwd == APP_DIR or blocked_workspace(cwd) else cwd)


DEFAULTS = {
    "ollama_url": "http://localhost:11434",
    "model": "",
    "workspace": _default_workspace(),
    "permission_mode": "ask",
    # Wie lange das Modell nach der letzten Anfrage im VRAM bleibt.
    "keep_alive": "30m",
    # 0 = automatisch aus VRAM und Modellarchitektur berechnen.
    "num_ctx": 0,
    # Obergrenze für die Auto-Berechnung: größerer Kontext = langsameres Prompt-Processing.
    "max_auto_ctx": 32768,
    # KV-Cache-Typ, mit dem der Ollama-Server läuft (OLLAMA_KV_CACHE_TYPE). Nur für die Schätzung.
    "kv_cache_type": "auto",
    "temperature": None,
    "think": False,
    "max_steps": 50,
    "max_tool_output": 16000,
    "command_timeout": 120,
    "unload_others": True,
    # Coder darf Teilaufgaben an Sub-Agents abgeben.
    "subagents": True,
    # Agents und Slash-Befehle aus Claude Code (~/.claude) mit anbieten.
    "claude_extensions": True,
    # Gedächtnis: verknüpfte Notizen, die der Agent über Chats hinweg liest und schreibt.
    "memory": True,
    # Passende Notizen automatisch zur Nachricht holen und erledigte Aufgaben in der Notiz „Verlauf“ festhalten.
    "auto_recall": True,
    "journal": True,
    # Kontrolle: ein zweites Modell prüft und testet das Ergebnis und schickt den Agent weiter, bis es passt.
    "controller": True,
    "controller_model": "",  # leer: automatisch – Mistral, falls installiert, sonst das Hauptmodell
    "controller_rounds": 2,
    "controller_interval": 10,  # Minuten zwischen Prüfungen bei langen Aufgaben; 0 = nur am Ende
    # Watchdog: kommt so viele Sekunden nichts vom Modell und die GPU ruht, wird es neu geladen. 0 = aus.
    "watchdog": 180,
    # Bilderkennung für Modelle ohne eigene Vision. Leer: automatisch.
    "vision_model": "",
    # Kein Standby: "open" solange Coder offen ist, "work" während der Agent arbeitet, "off" nie.
    "keep_awake": "open",
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    if cfg.get("permission_mode") not in PERMISSION_MODES:
        cfg["permission_mode"] = "ask"
    cfg["keep_awake"] = awake_mode(cfg.get("keep_awake"))  # früher an/aus – „an“ heißt jetzt: solange Coder offen ist
    workspace = str(cfg.get("workspace") or "")
    if not workspace or blocked_workspace(workspace) or not Path(workspace).is_dir():
        cfg["workspace"] = str(Path.home())
    return cfg


def save(cfg: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    clean = {k: cfg[k] for k in DEFAULTS if k in cfg}
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(CONFIG_PATH)


def update(changes: dict) -> dict:
    cfg = load()
    for key, value in changes.items():
        if key in DEFAULTS:
            cfg[key] = value
    save(cfg)
    return cfg
