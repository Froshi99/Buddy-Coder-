# Coder

Ein lokaler Coding-Agent im Stil von Claude Code – für Ollama, mit ruhiger Oberfläche und einem Terminal-Modus samt Axolotl.
Liest, sucht, bearbeitet Dateien, führt Befehle aus, sieht Bilder und recherchiert im Netz. Alles läuft auf deinem Rechner.

## Start

```bash
pip install -r requirements.txt
python coder.py
```

| Befehl | Wirkung |
| --- | --- |
| `python coder.py` | App-Fenster (PyQt6 WebEngine, sonst Browser) |
| `python coder.py --browser` | Oberfläche im Standardbrowser |
| `python coder.py cli` | Agent direkt im Terminal |
| `python coder.py -w C:\Projekte\app` | Workspace festlegen |
| `python coder.py -m qwen2.5-coder:14b` | Modell festlegen |
| `python coder.py --serve --host 0.0.0.0` | Nur Server, im LAN per IP-Adresse erreichbar |
| `start.bat` | Doppelklick-Start unter Windows |

## Was drin ist

**Agent**
- Werkzeuge: `read_file`, `list_dir`, `glob`, `grep`, `view_image`, `edit_file` (exakte Ersetzung mit Diff), `write_file`, `run_command`, `web_search`, `web_fetch`, `web_research`, `memory_search`, `memory_read`, `memory_write`, `todo_write`
- Terminal: PowerShell unter Windows, sonst bash – mit Timeout, echtem Exit-Code und UTF-8. Server und Watcher startet der Agent mit `background=true`; sie loggen nach `%TEMP%\coder-logs` und enden mit Coder
- Natives Ollama-Tool-Calling; für Modelle ohne Tool-Support automatisch ein Text-Protokoll (`<tool_call>`). Schreibt ein Modell seine Aufrufe als JSON in die Antwort – Qwen2.5-Coder tut das über Ollama oft –, erkennt Coder sie trotzdem und blendet sie aus dem Text aus
- Verzeiht typische Fehler kleiner Modelle: Parameternamen wie `file_path` oder `cmd`, aus `read_file` mitkopierte Zeilennummern, Leerzeichen am Zeilenende und eine einheitlich verschobene Einrückung in `edit_file` – nur bei eindeutigen Treffern, sonst meldet es den Fehler
- `glob` versteht `**`, `{ts,tsx}` und `[!x]`, Muster ohne `/` suchen in allen Unterordnern; `grep` liefert auf Wunsch Kontextzeilen oder nur die Dateien. Abhängigkeits- und Build-Ordner werden übersprungen, `.github` nicht
- Kennt beim Start die oberste Ordnerebene des Workspace
- Projektanweisungen aus `CODER.md`, `AGENTS.md` oder `CLAUDE.md` im Workspace (`/init` legt eine an)

**Rückgängig**
- Coder sichert jede Datei, bevor ein Auftrag sie zum ersten Mal ändert – auch Änderungen von Sub-Agents und nach einem Abbruch
- Unter jedem Auftrag steht, welche Dateien sich geändert haben. **Rückgängig** stellt den Stand davor wieder her, im Terminal `/undo`
- Zurückgenommen wird immer der jüngste Auftrag zuerst. Dateien, die danach noch jemand geändert hat, bleiben unangetastet. Befehle im Terminal lassen sich nicht zurücknehmen
- Coder behält die letzten 30 Sicherungen je Chat; beim Löschen eines Chats verschwinden seine Sicherungen

**Während der Arbeit schreiben**
- Drückst du `Enter`, während der Agent arbeitet, wartet die Nachricht über der Eingabe. Der Agent liest sie vor seinem nächsten Schritt – so lassen sich Wünsche nachschieben, ohne zu stoppen
- Mit × ziehst du sie zurück. Stoppst du den Agent, kommen wartende Nachrichten zurück in die Eingabe

**Kontrolle** – ein zweites Modell schaut dem Agent über die Schulter
- Nach jeder Aufgabe, bei der Dateien geändert oder Befehle ausgeführt wurden, prüft ein Kontrollmodell selbst nach: Es liest die Dateien, lässt Tests laufen und fällt ein Urteil
- Fehlt etwas, schickt es den Agent mit einer konkreten Anweisung weiter – höchstens so oft wie eingestellt (Standard: 2 Nachbesserungen)
- Bei langen Aufgaben sieht es zwischendurch nach dem Rechten (Standard: alle 10 Minuten) und hilft, wenn Aufrufe mehrmals hintereinander scheitern
- Standardmodell: **Mistral** (`mistral-nemo`, `mistral-small` …), falls installiert – sonst das Hauptmodell. Einstellbar unter *Einstellungen → Kontrolle* oder mit `/controller`
- Die Kontrolle arbeitet nur lesend und sieht auch Nachrichten, die du während der Arbeit nachgeschoben hast; für Befehle fragt sie wie jeder Agent um Freigabe

**Watchdog**
- Kommt länger nichts vom Modell (Standard: 3 Minuten), prüft Coder, ob die GPU noch rechnet und das Modell noch geladen ist. Hängt es wirklich, wird es entladen und neu geladen – bis zu zweimal
- Verfängt sich ein Modell in Endloswiederholungen, bricht Coder die Antwort ab und hakt nach

**Bilderkennung**
- Bilder hängen per Knopf, `Strg+V` oder Hineinziehen an der Nachricht (im Terminal: Bild ins Fenster ziehen oder `/image pfad`)
- Kann das Hauptmodell selbst sehen (z. B. `gemma4`, `gemma3`), bekommt es das Bild direkt. Sonst beschreibt ein Bildmodell das Bild vorher – samt aller sichtbaren Texte und Fehlermeldungen
- `view_image` lässt den Agent Screenshots und Diagramme im Workspace ansehen

**Gedächtnis** – verknüpfte Markdown-Notizen wie in Obsidian
- Tresore: Projekt (`.coder/memory`), global (`~/.coder/memory`) und die schreibgeschützte **Bibliothek** mit Leitfäden, die mit Coder kommt
- Passende Notizen werden automatisch zur Nachricht geholt – nach Bedeutung, wenn ein Embedding-Modell wie `nomic-embed-text` installiert ist, sonst nach Stichworten
- Ist der Grafikspeicher voll, rechnet das Embedding-Modell auf der CPU, statt das Chat-Modell aus dem VRAM zu drängen. Ein großer, neuer Tresor wird im Hintergrund fertig eingelesen
- Erledigte Aufgaben landen in der Notiz „Verlauf“ – so weiß Coder auch im nächsten Chat, was schon passiert ist
- `[[Titel]]` in einer Nachricht holt eine Notiz dazu; Graph-Ansicht, Tags, Backlinks, angeheftete Notizen

**Design-Bibliothek**
- Leitfäden zu Design-Prinzipien, Typografie, Farbe, Layout, Komponenten, Bewegung, Barrierefreiheit, Design-Tokens, einer Review-Checkliste – und „Kein AI-Slop“: woran man generische KI-Oberflächen erkennt und was man stattdessen macht
- `@ui-designer` und `/design` arbeiten danach; eine Kopie ins eigene Gedächtnis lässt sich anpassen

**Recherche**
- `web_research` sucht mit mehreren Suchanfragen parallel, liest die besten Seiten und liefert die passendsten Abschnitte mit nummerierten Quellen
- Websuche über DuckDuckGo ohne API-Schlüssel, mit Bing als Ausweich; gelesene Seiten bleiben 15 Minuten zwischengespeichert

**Agents**
- Coder gibt Teilaufgaben an Sub-Agents ab. Sie arbeiten mit eigenem Kontext und liefern einen Bericht; ihre Schritte erscheinen eingerückt im Chat
- Eingebaut: `@explorer`, `@planer`, `@bug-checker`, `@fix-it`, `@test-runner`, `@test-writer`, `@refactorer`, `@security-check`, `@perf-check`, `@ui-designer`, `@doku-writer`, `@commit-writer`, `@recherche`
- `@name` am Anfang einer Nachricht lässt einen Agent den ganzen Auftrag übernehmen
- Eigene Agents im Agents-Fenster oder als Markdown in `~/.coder/agents` bzw. `.coder/agents`; Agents aus Claude Code (`~/.claude/agents`) werden übernommen

**Befehle**
- Fertige Aufgaben: `/init`, `/review`, `/test`, `/write-tests`, `/fix`, `/explain`, `/plan`, `/refactor`, `/security`, `/perf`, `/design`, `/docs`, `/commit`, `/research`, `/remember`
- App: `/new`, `/compact`, `/undo`, `/agents`, `/memory`, `/workspace`, `/models`, `/settings`
- Eigene Befehle als Markdown in `~/.coder/commands` oder `.coder/commands` (auch `~/.claude/commands`); `$ARGUMENTS` wird durch den Text nach dem Befehl ersetzt. Gleichnamige eigene Befehle ersetzen die eingebauten
- In der Befehlspalette (`Strg+K`) außerdem: letzte Änderungen zurücknehmen, Chat als Markdown kopieren. Jede Antwort lässt sich unter ihren Messwerten kopieren

**Terminal**
- Live-Statuszeile, formatierte Antworten, farbige Diffs, Freigaben mit Vorschau; `Strg+C` bricht nur die laufende Aufgabe ab
- Befehle: `/help`, `/new`, `/resume`, `/model`, `/mode`, `/workspace`, `/compact`, `/undo`, `/agents`, `/commands`, `/memory`, `/controller`, `/image`, `/status`, `/buddy`, `/exit` – dazu alle fertigen Befehle wie `/review`
- **Axolotl:** Ein kleines Axolotl wohnt im Terminal. Es zeigt in der Statuszeile, was gerade passiert, und kommentiert Tests, Fehler und das Urteil der Kontrolle. `/buddy` zeigt es, `/buddy streicheln`, `/buddy name Pixel`, `/buddy aus`

**Berechtigungen** (Umschalter oben rechts)
- *Fragen* – Änderungen, Befehle und Seitenabrufe brauchen eine Freigabe, mit Diff-Vorschau
- *Auto-Edit* – Dateien im Workspace frei, Befehle mit Freigabe
- *Planen* – nur lesen, Plan vorlegen
- *Autonom* – alles ohne Rückfrage
- „Immer erlauben“ gilt bei Befehlen nur für Programm und Unterbefehl, etwa `npm test` oder `python -m pytest`, und nur in diesem Chat. Verkettete Befehle und alles, womit sich beliebiger Code ausführen oder Daten löschen lassen (`rm`, `curl`, `python -c`, Shells), fragen jedes Mal

**Workspace**
- Ordner wählen über die Workspace-Karte, den Ordner-Chip in der Eingabe oder `Strg+O`: Systemdialog, zuletzt verwendete Ordner oder direkt durchsuchen
- Jeder Chat bleibt an seinen Ordner gebunden; Systemordner und ganze Laufwerke sind gesperrt
- Links im App-Fenster – auch zu einem Dev-Server auf `localhost` – öffnen im Browser, die Oberfläche bleibt stehen

**PC wach halten** (*Einstellungen → Bilder & System*)
- Standard: kein Standby, **solange Coder offen ist**. Alternativ nur, während der Agent arbeitet, oder nie
- Der Bildschirm darf trotzdem ausgehen. Coder ändert keine Energieeinstellungen – die Anforderung endet spätestens mit Coder

**Optimiertes Laden für Ollama**
- Erkennt GPU, VRAM, RAM und CPU-Kerne, liest die Modellarchitektur und wählt `num_ctx` so, dass Gewichte und KV-Cache in den VRAM passen
- Entlädt andere Modelle vor dem Laden und misst danach die echte GPU-Verteilung; Kontroll- und Bildmodelle laden mit kleinerem Kontext, danach wird das Hauptmodell im Hintergrund wieder bereitgelegt
- Stabiler System-Prompt für den Prompt-Cache; alte Werkzeugausgaben ab 60 % kürzen, ab 80 % den Verlauf verdichten
- Mehr Kontext bei gleichem VRAM – einmalig für den Ollama-Server setzen und Ollama neu starten:

```bash
setx OLLAMA_FLASH_ATTENTION 1
setx OLLAMA_KV_CACHE_TYPE q8_0
```

## Tastenkürzel

| Taste | Aktion |
| --- | --- |
| `Enter` / `Shift+Enter` | Senden – während der Arbeit: Nachricht für den nächsten Schritt einreihen / neue Zeile |
| `Strg+K` | Befehlspalette: Aktionen, Befehle, Agents, Notizen, Chats |
| `Esc` | Freigabe ablehnen, Agent stoppen, Dialog schließen |
| `Strg+N` | Neuer Chat |
| `Strg+O` | Workspace wählen |
| `Strg+B` | Seitenleiste ein- und ausblenden |
| `Strg+M` | Modelle |
| `Strg+,` | Einstellungen |
| `Strg+Enter` | Freigabe erteilen |
| `Strg+V` | Bild aus der Zwischenablage anhängen |

In der Eingabe: `@` für Agents, `/` für Befehle, `[[` für Notizen – mit `↑`/`↓` wählen, `Enter` oder `Tab` übernimmt.

## Aufbau

```
coder.py            Start: App-Fenster, Browser, Server oder CLI
core/
  agent.py          Agent-Schleife, Berechtigungen, Watchdog, Kontextverdichtung, Nachrichten während der Arbeit
  checkpoints.py    Rückgängig: Sicherungen je Auftrag
  controller.py     Kontrolle durch ein zweites Modell
  tools.py          Werkzeuge
  web.py            Websuche, Seitenabruf, Recherche
  vision.py         Bilder speichern und für Vision-Modelle vorbereiten
  memory.py         Gedächtnis: Notizen, Links, Tresore
  recall.py         Erinnern nach Bedeutung, Verlauf
  agents.py         Sub-Agents: eingebaute, eigene und aus Claude Code
  commands.py       fertige und eigene Slash-Befehle
  folders.py        Ordnerauswahl: Durchsuchen, Orte, Systemdialog
  ollama.py         async Ollama-Client (Streaming, Embeddings)
  optimizer.py      Hardware-Erkennung, Ladeplan, Modell-Ranking
  runtime.py        Laden, Messen, Rollen (Kontrolle, Bilder, Embeddings)
  power.py          PC wach halten
  sessions.py       Chats unter ~/.coder/sessions
  config.py         Einstellungen unter ~/.coder/config.json
  cli.py            Terminal-Modus
  companion.py      das Axolotl fürs Terminal
library/            Design-Bibliothek (schreibgeschützter Tresor)
server/app.py       FastAPI + WebSocket
web/                Oberfläche (HTML, CSS, JS – ohne Build, ohne CDN)
```

## Sicherheit

- Der Server nimmt nur Anfragen an `127.0.0.1` an – und von Browsern nur solche, die von der Coder-Oberfläche selbst kommen. Eine andere Webseite, die im Browser offen ist, kann weder Aufträge schicken noch Freigaben erteilen; auch DNS-Rebinding wird abgewiesen
- Mit `--serve --host 0.0.0.0` ist Coder im LAN per IP-Adresse erreichbar – ohne Anmeldung. Das nur in Netzen tun, denen du vertraust
- Im Modus *Autonom* führt das Modell Befehle ohne Rückfrage aus. Nutze ihn nur in Projekten, bei denen das unkritisch ist
