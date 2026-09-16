"""Eigene Slash-Befehle: Markdown-Dateien, deren Text als Aufgabe gesendet wird – wie bei Claude Code.

    ---
    description: Prüft die angegebenen Dateien auf Fehler
    argument-hint: [Dateien]
    ---
    Prüfe $ARGUMENTS gründlich auf Fehler …

Gesucht wird in ~/.claude/commands, ~/.coder/commands und im Workspace unter .claude/commands und
.coder/commands. Unterordner ergeben Namensräume: frontend/test.md wird zu /frontend:test.
"""

import re
from pathlib import Path

from .agents import CLAUDE_HOME, clip, parse_frontmatter, squash
from .config import HOME

NAME_RX = re.compile(r"^[\w-]+(:[\w-]+)*$")
RESERVED = {"new", "clear", "compact", "models", "model", "settings", "agents", "workspace", "memory"}

# Fertige Befehle für häufige Aufgaben. Viele übergeben direkt an einen passenden Agent (@name am Anfang).
BUILTIN = [
    ("init", "CODER.md für dieses Projekt anlegen: Aufbau, Befehle, Konventionen", "",
     "Analysiere dieses Projekt und lege im Workspace eine CODER.md an: Zweck in zwei Sätzen, wichtigste Ordner und "
     "Dateien, Befehle für Installation, Start, Tests und Build, Code-Konventionen und Stolperfallen. Lies zuerst README, "
     "Paket-Manifeste und Einstiegspunkte. Höchstens 80 Zeilen. Gibt es schon eine CODER.md, AGENTS.md oder CLAUDE.md, "
     "aktualisiere sie, statt eine neue anzulegen. $ARGUMENTS"),
    ("review", "Aktuelle Änderungen auf Fehler prüfen lassen", "[Dateien]",
     "@bug-checker Prüfe die aktuellen Änderungen mit git status, git diff und git diff --staged. Ohne Git prüfe die "
     "zuletzt geänderten Dateien. Nenne echte Fehler, Randfälle und Sicherheitsprobleme mit Datei:Zeile. $ARGUMENTS"),
    ("test", "Tests finden, ausführen und Fehlschläge erklären", "[Bereich]",
     "@test-runner Finde heraus, wie dieses Projekt getestet wird, führe die Tests aus und erkläre jeden Fehlschlag. $ARGUMENTS"),
    ("write-tests", "Tests schreiben und zum Laufen bringen", "<Datei oder Bereich>",
     "@test-writer Schreibe sinnvolle Tests für: $ARGUMENTS"),
    ("fix", "Einen Fehler beheben und die Korrektur prüfen", "<Fehlermeldung>",
     "@fix-it Behebe diesen Fehler und prüfe die Korrektur:\n$ARGUMENTS"),
    ("explain", "Code oder Zusammenhänge verständlich erklären", "<Datei oder Thema>",
     "@explorer Erkläre verständlich und mit Datei:Zeile, wie das funktioniert: $ARGUMENTS"),
    ("plan", "Umsetzungsplan erstellen, ohne etwas zu ändern", "<Aufgabe>",
     "@planer Erstelle einen konkreten Umsetzungsplan für: $ARGUMENTS"),
    ("refactor", "Code aufräumen, ohne das Verhalten zu ändern", "<Datei oder Bereich>",
     "@refactorer Räume diesen Code auf, ohne das Verhalten zu ändern, und prüfe danach mit den Tests: $ARGUMENTS"),
    ("security", "Projekt auf Sicherheitslücken prüfen", "[Bereich]",
     "@security-check Prüfe dieses Projekt auf Sicherheitsprobleme. $ARGUMENTS"),
    ("perf", "Performance-Engpässe finden", "[Bereich]",
     "@perf-check Finde die wichtigsten Performance-Engpässe. $ARGUMENTS"),
    ("design", "Oberfläche verbessern: Layout, Typografie, Zustände", "<Ansicht oder Datei>",
     "@ui-designer Verbessere das Design von: $ARGUMENTS"),
    ("docs", "README und Doku an den Code anpassen", "[Datei]",
     "@doku-writer Bringe die Dokumentation auf den Stand des Codes. $ARGUMENTS"),
    ("commit", "Commit-Nachricht zu den aktuellen Änderungen vorschlagen", "",
     "@commit-writer Schlage eine Commit-Nachricht für die aktuellen Änderungen vor. $ARGUMENTS"),
    ("research", "Im Internet recherchieren, mit Quellen", "<Frage>",
     "@recherche $ARGUMENTS"),
    ("remember", "Etwas dauerhaft im Gedächtnis ablegen", "<was Coder sich merken soll>",
     "Lege das dauerhaft im Gedächtnis ab (memory_write): passender Titel, verwandte Notizen mit [[Titel]] verknüpfen, "
     "danach kurz bestätigen, was gespeichert wurde:\n$ARGUMENTS"),
]


def load(workspace: str | Path | None = None, include_claude: bool = True) -> list[dict]:
    ws = Path(workspace) if workspace else None
    sources = [("claude", CLAUDE_HOME / "commands", include_claude), ("global", HOME / "commands", True)]
    if ws:
        sources += [("claude-project", ws / ".claude" / "commands", include_claude),
                    ("project", ws / ".coder" / "commands", True)]
    # Eigene Befehle gleichen Namens ersetzen die eingebauten
    found: dict[str, dict] = {name: {"name": name, "description": description, "hint": hint, "template": template,
                                     "source": "builtin"} for name, description, hint, template in BUILTIN}
    seen: set[Path] = set()
    for source, folder, enabled in sources:
        try:
            if not enabled or not folder.is_dir() or folder.resolve() in seen:
                continue
            seen.add(folder.resolve())
            files = sorted(folder.rglob("*.md"))[:300]
        except OSError:
            continue
        for path in files:
            name = ":".join(path.relative_to(folder).with_suffix("").parts).lower()
            if not NAME_RX.match(name) or name in RESERVED:
                continue
            try:
                meta, body = parse_frontmatter(path.read_text("utf-8", errors="replace"))
            except OSError:
                continue
            body = body.strip()
            if not body:
                continue
            found[name] = {
                "name": name,
                "description": squash(str(meta.get("description") or "")) or clip(squash(body.splitlines()[0]), 90),
                "hint": squash(str(meta.get("argument-hint") or "")),
                "template": body[:20000],
                "source": source,
            }
    return sorted(found.values(), key=lambda c: c["name"])


def expand(template: str, args: str) -> str:
    """$ARGUMENTS wird zum ganzen Rest, $1, $2 … zu einzelnen Wörtern; ohne Platzhalter kommt der Rest ans Ende."""
    words = args.split()
    text = template.replace("$ARGUMENTS", args)
    text = re.sub(r"\$(\d)", lambda m: words[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(words) else "", text)
    if args and not re.search(r"\$ARGUMENTS|\$\d", template):
        text += f"\n\n{args}"
    return text.strip()
