"""Terminal-Modus: derselbe Agent wie in der App – mit Companion, Befehlen und Live-Anzeige."""

import asyncio
import os
import random
import re
import shutil
import signal
import sys
import textwrap
import time
import unicodedata
from pathlib import Path

from . import __version__
from . import agents as agents_mod
from . import commands as commands_mod
from . import memory as memory_mod
from . import checkpoints, optimizer, power, recall, sessions, vision
from .agent import Agent, AgentError
from .companion import WIDTH, Companion
from .config import PERMISSION_MODES, blocked_workspace, normalize_path
from .ollama import OllamaError
from .runtime import Runtime

TTY = sys.stdout.isatty()
ANSI_RX = re.compile(r"\033\[[0-9;]*m")
IMAGE_RX = re.compile(r'"([^"\n]+\.(?:png|jpe?g|gif|webp|bmp))"|\'([^\'\n]+\.(?:png|jpe?g|gif|webp|bmp))\''
                      r'|((?:[A-Za-z]:)?[^\s"\']+\.(?:png|jpe?g|gif|webp|bmp))(?=\s|$)', re.I)


def style(code: str):
    if not TTY or not code:
        return lambda s: str(s)
    return lambda s: f"\033[{code}m{s}\033[0m"


DIM, BOLD, BLUE, GREEN, RED, YELLOW, CYAN, MAGENTA = (style(c) for c in ("2", "1", "34", "32", "31", "33", "36", "35"))

VERB = {"read_file": "Lesen", "list_dir": "Ordner", "glob": "Dateien suchen", "grep": "Durchsuchen",
        "view_image": "Bild ansehen", "web_search": "Websuche", "web_fetch": "Webseite", "web_research": "Recherche",
        "memory_search": "Erinnern", "memory_read": "Notiz lesen", "memory_write": "Notieren",
        "edit_file": "Bearbeiten", "write_file": "Schreiben", "run_command": "Ausführen", "agent": "Delegieren"}
APPROVAL = {"edit_file": "Datei bearbeiten?", "write_file": "Datei schreiben?", "run_command": "Befehl ausführen?",
            "web_fetch": "Webseite öffnen?", "web_research": "Im Internet recherchieren?"}
MODE_LABEL = {"ask": "Fragen", "auto-edit": "Auto-Edit", "plan": "Plan", "yolo": "Yolo"}
REASON_LABEL = {"end": "prüft das Ergebnis", "interval": "schaut nach dem Rechten", "stuck": "hilft aus der Sackgasse"}
VAULT_LABEL = {"project": "Projekt", "global": "Global", "library": "Bibliothek"}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
HELP = [
    ("/new", "neuer Chat"), ("/resume [nr]", "frühere Chats fortsetzen"),
    ("/model [name|nr]", "Modelle anzeigen oder wechseln"), ("/mode [modus]", "ask · auto-edit · plan · yolo"),
    ("/workspace [pfad]", "Ordner anzeigen oder wechseln"), ("/compact", "Verlauf verdichten"),
    ("/undo", "Dateiänderungen des letzten Auftrags zurücknehmen"),
    ("/agents", "Spezialisten – mit @name ansprechen"), ("/commands", "fertige Befehle: /review, /test, /fix …"),
    ("/memory [suche]", "Gedächtnis und Bibliothek"), ("/controller [an|aus|modell]", "Kontrolle durch ein zweites Modell"),
    ("/image pfad", "Bild an die nächste Nachricht hängen"), ("/status", "Modell, GPU, Kontext, Token"),
    ("/buddy [streicheln|name X|aus|an]", "dein Axolotl"), ("/exit", "beenden"),
]


def width(text: str) -> int:
    plain = ANSI_RX.sub("", text)
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in plain)


def clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds} s" if seconds < 60 else f"{seconds // 60} min {seconds % 60:02d} s"


def ago(ts: float) -> str:
    minutes = int((time.time() - (ts or 0)) / 60)
    if minutes < 1:
        return "gerade eben"
    if minutes < 60:
        return f"vor {minutes} min"
    if minutes < 48 * 60:
        return f"vor {minutes // 60} h"
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def inline(text: str) -> str:
    text = re.sub(r"`([^`]+)`", lambda m: CYAN(m.group(1)), text)
    return re.sub(r"\*\*([^*]+)\*\*", lambda m: BOLD(m.group(1)), text)


def result_info(ev: dict) -> tuple[str, list[str]]:
    """Kurzfassung eines Werkzeugergebnisses plus ein paar Zeilen Vorschau."""
    name, d, output = ev["name"], ev["display"] or {}, ev.get("output") or ""
    if d.get("denied"):
        return RED("abgelehnt"), []
    if d.get("diff"):
        lines = [line for line in d["diff"].splitlines()[2:] if not line.startswith("@@")]
        preview = [GREEN(line) if line.startswith("+") else RED(line) if line.startswith("-") else DIM(line)
                   for line in lines[:10]]
        if len(lines) > 10:
            preview.append(DIM(f"… {len(lines) - 10} weitere Zeilen"))
        return f"{GREEN('+' + str(d.get('added', 0)))} {RED('−' + str(d.get('removed', 0)))}", preview
    if name == "run_command":
        lines = [line for line in output.strip().splitlines() if not line.startswith(("[Exit-Code", "[Timeout"))]
        if d.get("background"):
            return f"läuft im Hintergrund · PID {d.get('pid')}", [DIM(clip(line, 150)) for line in lines[-3:]]
        if d.get("timed_out"):
            return RED("Zeitüberschreitung"), [DIM(clip(line, 150)) for line in lines[-6:]]
        if d.get("exit_code") == 0:
            return GREEN("Exit 0") + (DIM(" · " + clip(lines[-1], 90)) if lines else ""), []
        return RED(f"Exit {d.get('exit_code')}"), [DIM(clip(line, 150)) for line in lines[-8:]]
    if name == "web_research":
        return f"{d.get('count', 0)} Quellen", [DIM(f"[{s['n']}] {clip(s['title'], 60)} · {clip(s['url'], 60)}")
                                                for s in d.get("sources", [])[:6]]
    if name == "view_image":
        return f"gesehen mit {d.get('model', '?')}", [DIM(clip(line, 150)) for line in output.splitlines()[1:4] if line.strip()]
    if "lines" in d:
        return f"{d['lines']} Zeilen", []
    if name == "list_dir" and "count" in d:
        return f"{d['count']} Einträge", []
    if "count" in d:
        return f"{d['count']} Treffer", []
    if "chars" in d:
        return f"{d['chars']:,} Zeichen".replace(",", "."), []
    first = (output.strip().splitlines() or [""])[0]
    return DIM(clip(first, 110)), []


class Terminal:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.buddy = Companion.load()
        self.session = sessions.new(rt.cfg["workspace"], rt.cfg.get("model", ""))
        self.images: list[str] = []
        self.turn: asyncio.Future | None = None
        self.sigint_at = 0.0
        self.commands: dict[str, str] = {}
        self.context: dict = {}
        self.shown_plan: int | None = None
        # Anzeige
        self.status: tuple[str, str, float] | None = None
        self.status_shown = False
        self.tick = 0
        self.line = ""
        self.in_code = False
        self.text_started = False
        self.thinking_started = False
        self.steps = 0

    # ------------------------------------------------------------------ Ausgabe

    def out(self, text: str = "") -> None:
        self.clear_status()
        self.flush_line()
        sys.stdout.write(text + "\n")
        sys.stdout.flush()

    def clear_status(self) -> None:
        if self.status_shown:
            sys.stdout.write("\r\033[2K")
            self.status_shown = False

    def set_status(self, text: str, mood: str = "think") -> None:
        self.status = (text, mood, time.monotonic())

    def stop_status(self) -> None:
        self.status = None
        self.clear_status()
        sys.stdout.flush()

    async def animate(self) -> None:
        """Statuszeile mit Companion-Gesicht und Uhr – überschreibt nie gestreamten Text."""
        while True:
            await asyncio.sleep(0.1)
            if not TTY or not self.status or self.line:
                continue
            self.tick += 1
            text, mood, since = self.status
            face = self.buddy.face(mood, self.tick) if self.buddy.enabled else SPINNER[self.tick % len(SPINNER)]
            color = style(self.buddy.color) if self.buddy.enabled and self.buddy.color else CYAN
            seconds = int(time.monotonic() - since)
            room = max(10, shutil.get_terminal_size().columns - width(face) - 14)
            label = text if len(text) <= room else text[:room - 1] + "…"
            sys.stdout.write(f"\r\033[2K  {color(face)} {label}{DIM(f'  {seconds} s') if seconds else ''}")
            sys.stdout.flush()
            self.status_shown = True

    def stream(self, text: str, dim: bool = False) -> None:
        self.stop_status()
        for piece in re.split(r"(\n)", text):
            if piece == "\n":
                if dim:
                    sys.stdout.write("\n")
                    self.line = ""
                else:
                    self.finish_line()
            elif piece:
                self.line += piece
                sys.stdout.write(DIM(piece) if dim else piece)
        sys.stdout.flush()

    def finish_line(self) -> None:
        raw, self.line = self.line, ""
        styled = self.render(raw)
        if TTY and styled != raw and width(raw) < shutil.get_terminal_size().columns:
            sys.stdout.write("\r\033[2K" + styled + "\n")  # fertige Zeile hübsch neu setzen
        else:
            sys.stdout.write("\n")

    def flush_line(self) -> None:
        if self.line:
            self.finish_line()

    def render(self, line: str) -> str:
        if not TTY:
            return line
        fence = re.match(r"^\s*```\s*([\w+#.-]*)", line)
        if fence:
            self.in_code = not self.in_code
            return DIM("  ╭─" + (f" {fence.group(1)}" if fence.group(1) else "")) if self.in_code else DIM("  ╰─")
        if self.in_code:
            return DIM("  │ ") + CYAN(line)
        heading = re.match(r"^#{1,6}\s+(.*)", line)
        if heading:
            return BOLD(inline(heading.group(1)))
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if bullet:
            return f"{bullet.group(1)}  {DIM('•')} {inline(bullet.group(2))}"
        quote = re.match(r"^\s*>\s?(.*)", line)
        if quote:
            return DIM("  ▎ ") + inline(quote.group(1))
        return inline(line)

    def scene(self, text: str, mood: str) -> list[str]:
        """Companion mit Sprechblase."""
        art = self.buddy.art(mood)
        wrap = max(16, min(52, shutil.get_terminal_size().columns - WIDTH - 10))
        lines = [part for para in text.splitlines() or [""] for part in (textwrap.wrap(para, wrap) or [""])]
        inner = max(width(line) for line in lines)
        box = ["╭" + "─" * (inner + 2) + "╮", *[f"│ {line}{' ' * (inner - width(line))} │" for line in lines],
               "╰" + "─" * (inner + 2) + "╯"]
        top = max(0, self.buddy.face_row - 1)
        color = style(self.buddy.color)
        rows = []
        for i in range(max(len(art), top + len(box))):
            figure = art[i] if i < len(art) else " " * WIDTH
            bubble = box[i - top] if 0 <= i - top < len(box) else ""
            joint = " "
            if i == self.buddy.face_row and bubble.startswith("│"):
                joint, bubble = "─", "┤" + bubble[1:]
            rows.append(f"{color(figure)}{DIM(joint)}{DIM(bubble[:1])}{bubble[1:-1]}{DIM(bubble[-1:])}"
                        if bubble.startswith("│") or bubble.startswith("┤")
                        else f"{color(figure)}{joint}{DIM(bubble)}")
        return rows

    def say(self, event: str, mood: str = "happy", **values) -> None:
        if not self.buddy.enabled:
            return
        text = self.buddy.line(event, **values)
        if text:
            color = style(self.buddy.color) if self.buddy.color else CYAN
            self.out(f"  {color(self.buddy.face(mood))} {DIM(self.buddy.name + ':')} {text}")

    # ------------------------------------------------------------------ Ereignisse des Agenten

    async def emit(self, ev: dict) -> None:
        t = ev["type"]
        if ev.get("parent"):
            self.sub_event(ev)
            return
        if t == "profile":
            self.out(DIM(f"  @{ev['agent']} übernimmt"))
        elif t == "status":
            self.set_status(ev["text"], "work")
        elif t == "model":
            plan = ev["plan"]
            if plan.get("load_seconds") and id(plan) != self.shown_plan:
                self.shown_plan = id(plan)
                share = (plan.get("actual") or {}).get("gpu_share", plan.get("gpu_share", 0))
                self.out(DIM(f"  {ev['model']} geladen · {plan['num_ctx'] // 1024}K Kontext · "
                             f"{round(share * 100)} % GPU · {plan['load_seconds']} s"))
        elif t == "assistant_start":
            self.text_started = self.thinking_started = False
            self.set_status("denkt nach …", "think")
        elif t == "thinking":
            if self.rt.cfg.get("think"):
                if not self.thinking_started:
                    self.thinking_started = True
                    self.out("")
                self.stream(ev["text"], dim=True)
        elif t == "text":
            if not self.text_started:
                self.text_started = True
                self.stop_status()
                self.line = ""
                sys.stdout.write("\n")
            self.stream(ev["text"])
        elif t == "stats":
            self.flush_line()
            self.in_code = False
            s = ev["stats"]
            if self.text_started and s.get("tokens"):
                self.out(DIM(f"  {s['tokens_per_s']} tok/s · {s['tokens']} Token · {s['total_s']} s"))
        elif t == "tool_call":
            if ev["name"] == "todo_write":
                return
            self.steps += 1
            self.commands[ev["id"]] = str(ev["args"].get("command") or "")
            label = f"@{ev['args'].get('agent', '?')}" if ev["name"] == "agent" else VERB.get(ev["name"], ev["name"])
            summary = clip(ev["args"].get("task", "") if ev["name"] == "agent" else ev["summary"], 100)
            self.out(f"{BLUE('●')} {BOLD(label)} {DIM(summary)}")
            self.set_status(f"{label} …", "work")
        elif t == "tool_result":
            if ev["name"] == "todo_write":
                return
            self.stop_status()
            info, extra = result_info(ev)
            self.out(f"  {(GREEN if ev['ok'] else RED)('⎿')} {info}")
            for line in extra:
                self.out(f"     {line}")
            self.react(ev)
            self.set_status("denkt weiter …", "think")
        elif t == "todos":
            marks = {"pending": DIM("○"), "in_progress": YELLOW("◐"), "completed": GREEN("●")}
            for todo in ev["todos"]:
                label = DIM(todo["content"]) if todo["status"] == "completed" else todo["content"]
                self.out(f"    {marks[todo['status']]} {label}")
        elif t == "controller":
            self.controller_event(ev)
        elif t == "recall":
            self.out(DIM(f"  ✦ Aus dem Gedächtnis: {', '.join(ev['notes'])}"))
        elif t == "watchdog":
            self.out(YELLOW(f"  ⟳ {ev['text']}"))
            self.say("watchdog", "alert")
        elif t == "assistant_discard":
            self.flush_line()
        elif t == "compacted":
            self.out(DIM("  Verlauf verdichtet."))
        elif t == "changes":
            files = ev["files"]
            names = ", ".join(f["path"] for f in files[:4]) + (f" und {len(files) - 4} weitere" if len(files) > 4 else "")
            added = sum(f.get("added") or 0 for f in files)
            removed = sum(f.get("removed") or 0 for f in files)
            self.out(DIM(f"  {len(files)} {'Datei' if len(files) == 1 else 'Dateien'} geändert: {names} ")
                     + GREEN(f"+{added}") + " " + RED(f"−{removed}") + DIM(" · /undo nimmt das zurück"))
        elif t == "context":
            self.context = ev
        elif t in ("notice", "error"):
            self.out(YELLOW(f"  {ev.get('text') or ev.get('message')}"))

    def sub_event(self, ev: dict) -> None:
        t, who = ev["type"], ev.get("agent", "")
        label = "Kontrolle" if who == "kontrolle" else f"@{who}"
        if t == "tool_call" and ev["name"] != "todo_write":
            verb = VERB.get(ev["name"], ev["name"])
            self.out(DIM(f"    ↳ {label} · {verb} {clip(ev['summary'], 90)}"))
            self.set_status(f"{label} · {verb} …", "work")
        elif t == "tool_result" and not ev["ok"] and not (ev["display"] or {}).get("denied"):
            info, _ = result_info(ev)
            self.out(f"      {RED('⎿')} {DIM(ANSI_RX.sub('', info))}")
        elif t == "status":
            self.set_status(f"{label} · {ev['text']}", "work")
        elif t == "assistant_start":
            self.set_status(f"{label} denkt nach …", "think")

    def controller_event(self, ev: dict) -> None:
        if ev["state"] == "start":
            self.out(f"{MAGENTA('◆')} {BOLD('Kontrolle')} {DIM(ev['model'] + ' · ' + REASON_LABEL.get(ev['reason'], ''))}")
            self.set_status(f"Kontrolle · {ev['model']} prüft …", "work")
            return
        self.stop_status()
        verdict, note = ev["verdict"], ev.get("note") or ""
        if verdict == "done":
            self.out(f"  {GREEN('✓')} {note or 'Passt.'}")
            self.say("verdict_done", "happy")
        elif verdict == "continue":
            self.out(f"  {YELLOW('↻')} {note}")
            self.say("verdict_continue", "alert")
        else:
            self.out(DIM(f"  – {note or 'Kein klares Urteil.'}"))

    def react(self, ev: dict) -> None:
        d = ev["display"] or {}
        if d.get("denied"):
            self.say("denied", "sad")
        elif ev["name"] == "run_command" and not d.get("background"):
            command = self.commands.get(ev["id"], "")
            if ev["ok"] and re.search(r"\b(test|tests|pytest|jest|vitest|unittest)\b", command):
                self.say("tests_ok", "happy")
            elif not ev["ok"] and random.random() < 0.4:
                self.say("run_fail", "sad", code=d.get("exit_code"))

    async def ask(self, req: dict) -> str:
        self.stop_status()
        self.flush_line()
        who = "Kontrolle · " if req.get("agent") == "kontrolle" else (f"@{req['agent']} · " if req.get("agent") else "")
        self.out("")
        face = f"{style(self.buddy.color)(self.buddy.face('alert'))} " if self.buddy.enabled else ""
        self.out(f"{YELLOW('?')} {face}{BOLD(who + APPROVAL.get(req['name'], req['name'] + ' ausführen?'))}")
        self.out(f"  {CYAN(clip(req['summary'], 400))}")
        lines = (req.get("preview") or {}).get("diff", "").splitlines()[2:]
        for line in lines[:30]:
            self.out("  " + (GREEN(line) if line.startswith("+") else RED(line) if line.startswith("-") else DIM(line)))
        if len(lines) > 30:
            self.out(DIM(f"  … {len(lines) - 30} weitere Zeilen"))
        always = req.get("always")
        if always and req["name"] == "run_command":
            self.out(DIM(f"  „immer“ gilt in diesem Chat für Befehle, die mit „{always}“ beginnen"))
        choices = "[J]a · [i]mmer · [n]ein" if always else "[J]a · [n]ein"
        try:
            answer = (await asyncio.to_thread(input, f"  {BOLD('Erlauben?')} {DIM(choices)} › "))
        except EOFError:
            return "deny"
        answer = answer.strip().lower()
        if answer.startswith("i") and always:
            return "always"
        return "deny" if answer.startswith("n") else "allow"

    # ------------------------------------------------------------------ Ablauf

    async def main(self) -> int:
        status = await self.rt.status()
        if not status["ok"]:
            print(RED(status["error"]))
            return 1
        await self.banner(status)
        animator = asyncio.create_task(self.animate())
        loop = asyncio.get_running_loop()

        def on_sigint(_signum, _frame):
            self.sigint_at = time.monotonic()
            if self.turn and not self.turn.done():
                loop.call_soon_threadsafe(self.turn.cancel)  # Strg+C bricht nur die laufende Aufgabe ab

        previous = signal.signal(signal.SIGINT, on_sigint)
        power.keep_awake.hold(self.rt.cfg.get("keep_awake") == "open")  # „solange Coder offen ist“
        try:
            await self.repl()
        finally:
            power.keep_awake.hold(False)
            signal.signal(signal.SIGINT, previous if callable(previous) else signal.default_int_handler)
            animator.cancel()
            self.stop_status()
            self.say("bye", "happy")
            await self.rt.close()
        return 0

    async def banner(self, status: dict) -> None:
        cfg = self.rt.cfg
        hw = optimizer.detect_hardware()
        gpu = f"{hw['gpus'][0]['name']} · {hw['vram_total'] / 1024 ** 3:.0f} GB" if hw["gpus"] else "CPU"
        print()
        if self.buddy.enabled:
            for line in self.scene(self.buddy.line("hello"), "happy"):
                print(line)
            print(DIM(f"  {self.buddy.name} · {self.buddy.species}"))
            print()
        print(f"  {BOLD('Coder')} {DIM(__version__)}  {self.session['workspace']}")
        details = [cfg.get("model") or "Modell automatisch", gpu, f"Ollama {status['version']}",
                   f"Modus {MODE_LABEL[cfg['permission_mode']]}"]
        if cfg.get("controller", True):
            details.append(f"Kontrolle {await self.rt.controller_model(cfg.get('model') or '') or 'Hauptmodell'}")
        print(DIM("  " + " · ".join(details)))
        print(DIM("  /help Befehle · @agent Spezialist · [[Notiz]] Gedächtnis · Bild ins Fenster ziehen"))

    def prompt(self) -> str:
        parts = []
        mode = self.rt.cfg["permission_mode"]
        if mode != "ask":
            parts.append(MAGENTA(MODE_LABEL[mode]))
        if self.images:
            parts.append(CYAN(f"{len(self.images)} {'Bild' if len(self.images) == 1 else 'Bilder'}"))
        return "\n" + "".join(f"{p} " for p in parts) + BOLD("› ")

    async def repl(self) -> None:
        last_interrupt = 0.0
        while True:
            try:
                text = await asyncio.to_thread(input, self.prompt())
            except EOFError:
                if time.monotonic() - self.sigint_at < 1.5:  # Strg+C am Prompt (Windows meldet es als EOF)
                    if time.monotonic() - last_interrupt < 2.5:
                        return
                    last_interrupt = time.monotonic()
                    self.out(DIM("  Noch einmal Strg+C zum Beenden – oder /exit."))
                    continue
                return
            text = text.strip()
            if not text:
                continue
            if text.startswith("/") and not IMAGE_RX.fullmatch(text):
                if await self.command(text) is False:
                    return
                continue
            await self.send(text)

    def extract_images(self, text: str) -> tuple[str, list[str]]:
        """Ins Terminal gezogene Bilder kommen als Pfad an – die werden angehängt."""
        found: list[str] = []

        def take(match: re.Match) -> str:
            raw = next(g for g in match.groups() if g)
            path = Path(raw.strip())
            if not path.is_absolute():
                path = Path(self.session["workspace"]) / path
            try:
                if path.is_file() and vision.is_image(path):
                    found.append(vision.store(path.read_bytes()))
                    return f"[Bild: {path.name}]"
            except (OSError, ValueError) as e:
                self.out(YELLOW(f"  {path.name}: {e}"))
            return match.group(0)

        return IMAGE_RX.sub(take, text), found

    async def send(self, text: str, display: str | None = None) -> None:
        text, found = self.extract_images(text)
        images, self.images = self.images + found, []
        if images and not re.sub(r"\[Bild: [^\]]+\]", "", text).strip():
            text += "\nWas ist auf dem Bild zu sehen?"
        if images:
            self.say("image", "happy")
        agent = Agent(self.rt, self.session, self.emit, self.ask)  # je Auftrag neu: @agent gilt nur für diesen
        await self.run_turn(agent.run(text, display, images))

    async def run_turn(self, coro) -> None:
        awake = self.rt.cfg.get("keep_awake") != "off"
        if awake:
            power.keep_awake.acquire()
        self.steps = 0
        started = time.monotonic()
        outcome = "done"
        self.turn = asyncio.ensure_future(coro)
        try:
            await self.turn
        except asyncio.CancelledError:
            outcome = "cancel"
        except (OllamaError, AgentError) as e:
            outcome = "error"
            self.out(RED(f"  {e}"))
        except Exception as e:  # noqa: BLE001 — das Terminal soll weiterlaufen
            outcome = "error"
            self.out(RED(f"  {e.__class__.__name__}: {e}"))
        finally:
            self.turn = None
            if awake:
                power.keep_awake.release()
            self.stop_status()
            self.flush_line()
            self.in_code = False
            if self.session["messages"]:
                sessions.save(self.session)
        if outcome == "cancel":
            self.out(YELLOW("  Abgebrochen."))
        elif outcome == "error":
            self.say("error", "sad")
        elif self.steps:
            steps = f"{self.steps} {'Schritt' if self.steps == 1 else 'Schritte'}"
            self.say("done", "happy", steps=steps, time=duration(time.monotonic() - started))

    # ------------------------------------------------------------------ Befehle

    async def command(self, text: str) -> bool | None:
        head, _, rest = text.partition(" ")
        name, rest = head[1:].lower(), rest.strip()
        if name in ("exit", "quit", "q"):
            return False
        handler = {
            "help": self.cmd_help, "?": self.cmd_help, "new": self.cmd_new, "clear": self.cmd_new,
            "resume": self.cmd_resume, "compact": self.cmd_compact, "mode": self.cmd_mode, "model": self.cmd_model,
            "models": self.cmd_model, "workspace": self.cmd_workspace, "agents": self.cmd_agents,
            "commands": self.cmd_commands, "memory": self.cmd_memory, "controller": self.cmd_controller,
            "kontrolle": self.cmd_controller, "image": self.cmd_image, "bild": self.cmd_image,
            "status": self.cmd_status, "buddy": self.cmd_buddy, "undo": self.cmd_undo, "rückgängig": self.cmd_undo,
        }.get(name)
        if handler:
            await handler(rest)
            return None
        found = await asyncio.to_thread(commands_mod.load, self.session["workspace"],
                                        bool(self.rt.cfg.get("claude_extensions", True)))
        cmd = next((c for c in found if c["name"] == name), None)
        if cmd:
            await self.send(commands_mod.expand(cmd["template"], rest), display=text)
        else:
            self.out(YELLOW(f"  Unbekannter Befehl /{name} – /help zeigt alle, /commands die fertigen Aufgaben."))
        return None

    async def cmd_help(self, _rest: str) -> None:
        pad = max(len(c) for c, _ in HELP) + 2
        self.out("")
        for cmd, text in HELP:
            self.out(f"  {BOLD(cmd.ljust(pad))}{DIM(text)}")
        self.out("")
        self.out(DIM("  @agent am Anfang spricht einen Spezialisten an · [[Notiz]] holt eine Notiz dazu"))
        self.out(DIM("  Bild ins Terminal ziehen hängt es an · Strg+C bricht die laufende Aufgabe ab"))

    async def cmd_new(self, _rest: str) -> None:
        self.session = sessions.new(self.rt.cfg["workspace"], self.rt.cfg.get("model", ""))
        self.context = {}
        self.out(DIM("  Neuer Chat."))

    async def cmd_resume(self, rest: str) -> None:
        items = sessions.list_all(30)
        if not items:
            self.out(DIM("  Noch keine Chats."))
            return
        if not rest:
            for i, s in enumerate(items[:15], 1):
                where = Path(s["workspace"]).name or s["workspace"]
                self.out(f"  {DIM(str(i).rjust(2))}  {clip(s['title'] or 'Ohne Titel', 52)}  {DIM(ago(s['updated']) + ' · ' + where)}")
            self.out(DIM("  /resume nr setzt den Chat fort."))
            return
        pick = items[int(rest) - 1] if rest.isdigit() and 0 < int(rest) <= len(items) else \
            next((s for s in items if s["id"].startswith(rest)), None)
        loaded = sessions.load(pick["id"]) if pick else None
        if not loaded:
            self.out(YELLOW("  Chat nicht gefunden."))
            return
        self.session = loaded
        self.out(f"  {BOLD(loaded['title'])} {DIM('· ' + loaded['workspace'])}")
        for m in [m for m in loaded["messages"] if m["role"] == "user" and "_text" in m][-3:]:
            self.out(DIM(f"  › {clip(m['_text'], 110)}"))
        answer = next((m["content"] for m in reversed(loaded["messages"])
                       if m["role"] == "assistant" and (m.get("content") or "").strip()), "")
        if answer:
            self.out(f"  {clip(answer, 300)}")

    async def cmd_compact(self, _rest: str) -> None:
        await self.run_turn(Agent(self.rt, self.session, self.emit, self.ask).compact())

    async def cmd_undo(self, _rest: str) -> None:
        try:
            result = await asyncio.to_thread(checkpoints.undo, self.session)
        except ValueError as e:
            self.out(YELLOW(f"  {e}"))
            return
        sessions.save(self.session)
        for path in result["restored"]:
            self.out(f"  {GREEN('↺')} {path}")
        for item in result["skipped"]:
            self.out(f"  {YELLOW('–')} {item['path']} {DIM('· ' + item['reason'])}")
        if not result["restored"] and not result["skipped"]:
            self.out(DIM("  Die Dateien waren schon im alten Zustand."))
        elif result["restored"]:
            self.out(DIM("  Befehle im Terminal lassen sich nicht zurücknehmen – nur Dateiänderungen."))

    async def cmd_mode(self, rest: str) -> None:
        mode = rest.lower()
        if mode in PERMISSION_MODES:
            await self.rt.update_config({"permission_mode": mode})
            self.out(DIM(f"  Modus: {MODE_LABEL[mode]}"))
        else:
            current = self.rt.cfg["permission_mode"]
            self.out("  " + "  ".join(BOLD(m) if m == current else DIM(m) for m in PERMISSION_MODES))

    async def cmd_model(self, rest: str) -> None:
        try:
            data = await self.rt.models()
        except OllamaError as e:
            self.out(RED(f"  {e}"))
            return
        items = data["models"]
        if not rest:
            current = self.rt.cfg.get("model") or data["recommended"]
            for i, m in enumerate(items, 1):
                caps, plan = m["profile"]["capabilities"], m["plan"]
                tags = [t for t, ok in (("Tools", "tools" in caps), ("Bilder", "vision" in caps),
                                        ("empfohlen", m["name"] == data["recommended"])) if ok]
                fit = f"{plan['num_ctx'] // 1024}K · {round(plan['gpu_share'] * 100)} % GPU"
                mark = GREEN("●") if m["name"] == current else " "
                self.out(f"  {mark} {DIM(str(i).rjust(2))} {m['name'][:36].ljust(36)} {DIM(fit.ljust(16))} {CYAN(' · '.join(tags))}")
            roles = data.get("roles") or {}
            self.out(DIM(f"  Kontrolle: {roles.get('controller') or '–'} · Bilder: {roles.get('vision') or '–'} · "
                         f"Gedächtnis: {roles.get('embed') or 'nur Stichworte'}"))
            self.out(DIM("  /model nr oder /model name wechselt."))
            return
        name = items[int(rest) - 1]["name"] if rest.isdigit() and 0 < int(rest) <= len(items) else rest
        if name not in {m["name"] for m in items}:
            self.out(YELLOW(f"  {name} ist nicht installiert."))
            return
        await self.rt.update_config({"model": name})
        self.out(DIM(f"  Modell: {name} – wird beim nächsten Auftrag geladen."))

    async def cmd_workspace(self, rest: str) -> None:
        if not rest:
            self.out(f"  {self.session['workspace']}")
            return
        path = normalize_path(rest)
        if not path.is_dir():
            self.out(YELLOW(f"  Ordner nicht gefunden: {path}"))
            return
        reason = blocked_workspace(path)
        if reason:
            self.out(YELLOW(f"  {path} geht nicht als Workspace ({reason})."))
            return
        await self.rt.update_config({"workspace": str(path)})
        self.session = sessions.new(str(path), self.rt.cfg.get("model", ""))
        self.out(DIM(f"  Workspace: {path} · neuer Chat"))

    async def cmd_agents(self, _rest: str) -> None:
        found = await asyncio.to_thread(agents_mod.load, self.session["workspace"],
                                        bool(self.rt.cfg.get("claude_extensions", True)))
        pad = max((len(a.name) for a in found.values()), default=8) + 3
        for a in found.values():
            self.out(f"  {BOLD(('@' + a.name).ljust(pad))}{DIM(clip(a.description, 90))}")

    async def cmd_commands(self, _rest: str) -> None:
        found = await asyncio.to_thread(commands_mod.load, self.session["workspace"],
                                        bool(self.rt.cfg.get("claude_extensions", True)))
        for c in found:
            head = f"/{c['name']}" + (f" {c['hint']}" if c["hint"] else "")
            origin = "" if c["source"] == "builtin" else DIM(f"  ({c['source']})")
            self.out(f"  {BOLD(head[:34].ljust(34))} {DIM(clip(c['description'], 70))}{origin}")

    async def cmd_memory(self, rest: str) -> None:
        workspace = self.session["workspace"]
        if rest:
            hits = await recall.search(rest, workspace, self.rt, limit=10)
            if not hits:
                self.out(DIM("  Nichts gefunden."))
            for h in hits:
                self.out(f"  {BOLD(h['title'])} {DIM(VAULT_LABEL.get(h['vault'], h['vault']))}")
                self.out(DIM(f"    {clip(h['snippet'], 140)}"))
            return
        notes = await asyncio.to_thread(memory_mod.load, workspace)
        if not notes:
            self.out(DIM("  Noch keine Notizen."))
            return
        for vault in ("project", "global", "library"):
            titles = [n for n in notes if n.vault == vault]
            if titles:
                self.out(f"  {BOLD(VAULT_LABEL[vault])} {DIM(str(len(titles)))}")
                self.out("    " + DIM(", ").join(("★ " if n.pinned else "") + n.title for n in titles[:40]))
        self.out(DIM("  /memory suche durchsucht nach Bedeutung · [[Titel]] in einer Nachricht holt die Notiz dazu"))

    async def cmd_controller(self, rest: str) -> None:
        arg = rest.lower()
        if arg in ("an", "on", "ein"):
            await self.rt.update_config({"controller": True})
        elif arg in ("aus", "off"):
            await self.rt.update_config({"controller": False})
        elif arg in ("auto", "automatisch"):
            await self.rt.update_config({"controller_model": ""})
        elif rest:
            if rest not in await self.rt.installed(max_age=0):
                self.out(YELLOW(f"  {rest} ist nicht installiert."))
                return
            await self.rt.update_config({"controller_model": rest, "controller": True})
        cfg = self.rt.cfg
        model = await self.rt.controller_model(cfg.get("model") or "") or "das Hauptmodell"
        source = "" if cfg.get("controller_model") else " (automatisch)"
        interval = cfg.get("controller_interval") or 0
        self.out(f"  Kontrolle {BOLD('an' if cfg.get('controller') else 'aus')} · {model}{DIM(source)}")
        self.out(DIM(f"  prüft am Ende jeder Aufgabe mit Änderungen · höchstens {cfg.get('controller_rounds', 2)} "
                     f"Nachbesserungen · {'alle ' + str(interval) + ' min zwischendurch' if interval else 'nicht zwischendurch'}"))

    async def cmd_image(self, rest: str) -> None:
        if not rest:
            self.out(DIM(f"  {len(self.images)} Bild(er) hängen an der nächsten Nachricht." if self.images
                         else "  Kein Bild angehängt. /image pfad – oder das Bild einfach ins Terminal ziehen."))
            return
        if rest.lower() in ("weg", "löschen", "clear"):
            self.images = []
            self.out(DIM("  Anhänge entfernt."))
            return
        path = Path(rest.strip("\"'"))
        if not path.is_absolute():
            path = Path(self.session["workspace"]) / path
        if not path.is_file() or not vision.is_image(path):
            self.out(YELLOW(f"  Kein Bild gefunden: {path}"))
            return
        try:
            self.images.append(vision.store(path.read_bytes()))
        except (OSError, ValueError) as e:
            self.out(YELLOW(f"  {e}"))
            return
        self.out(DIM(f"  {path.name} hängt an der nächsten Nachricht."))

    async def cmd_status(self, _rest: str) -> None:
        cfg = self.rt.cfg
        hw = optimizer.detect_hardware(max_age=0)
        loaded = await self.rt.loaded()
        model = cfg.get("model") or "automatisch"
        plan = self.rt.plans.get(cfg.get("model") or "")
        rows = [("Modell", model + (f" · {plan['num_ctx'] // 1024}K Kontext" if plan else ""))]
        if hw["gpus"]:
            free = hw["vram_free"] / 1024 ** 3
            rows.append(("Grafik", f"{hw['gpus'][0]['name']} · {hw['vram_total'] / 1024 ** 3:.0f} GB, {free:.1f} GB frei"))
        rows.append(("Geladen", ", ".join(f"{m['name']} ({round(m['gpu_share'] * 100)} % GPU)" for m in loaded) or "nichts"))
        if self.context.get("max"):
            share = round(self.context["used"] / self.context["max"] * 100)
            rows.append(("Kontext", f"{self.context['used']:,} von {self.context['max']:,} Token ({share} %)".replace(",", ".")))
        usage = self.session.get("usage") or {}
        if usage:
            rows.append(("Token", f"Prompt {usage.get('prompt', 0):,} · Antworten {usage.get('completion', 0):,}".replace(",", ".")))
        awake = {"open": "solange Coder offen ist", "work": "während der Arbeit", "off": "aus"}.get(cfg.get("keep_awake"), "aus")
        rows.append(("Modus", f"{MODE_LABEL[cfg['permission_mode']]} · Kontrolle {'an' if cfg.get('controller') else 'aus'} · "
                              f"PC wach {awake}"))
        rows.append(("Workspace", self.session["workspace"]))
        for label, value in rows:
            self.out(f"  {DIM(label.ljust(10))} {value}")

    async def cmd_buddy(self, rest: str) -> None:
        buddy, arg = self.buddy, rest.lower()
        if arg in ("aus", "off"):
            buddy.data["enabled"] = False
            buddy.save()
            self.out(DIM(f"  {buddy.name} macht Pause. /buddy an holt es zurück."))
            return
        if arg in ("an", "on"):
            buddy.data["enabled"] = True
            buddy.save()
        elif arg.startswith("name "):
            new = rest[5:].strip()[:20]
            if new:
                buddy.data["name"] = new
                buddy.save()
                for line in self.scene(f"Ab jetzt heiße ich {new}!", "happy"):
                    self.out(line)
                return
        elif arg in ("streicheln", "pet", "kraulen"):
            buddy.pet()
            for line in self.scene(buddy.line("pet"), "love"):
                self.out(line)
            return
        for line in self.scene(f"Hi, ich bin {buddy.name}!", "happy"):
            self.out(line)
        born = time.strftime("%d.%m.%Y", time.localtime(buddy.data.get("born", time.time())))
        self.out(f"  {style(buddy.color)(buddy.name)} {DIM('· Axolotl · geschlüpft am ' + born + ' · ' + str(buddy.data.get('pets', 0)) + '× gestreichelt')}")
        self.out(DIM("  /buddy streicheln · /buddy name Pixel · /buddy aus"))


async def run() -> int:
    if os.name == "nt":
        os.system("")  # ANSI-Farben in der Windows-Konsole aktivieren
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    return await Terminal(Runtime()).main()
