"""Agent-Schleife: Modell denkt, ruft Werkzeuge auf, bekommt Ergebnisse — bis die Aufgabe erledigt ist."""

import asyncio
import contextlib
import json
import platform
import re
import time
import uuid
from pathlib import Path
from typing import Awaitable, Callable

from . import agents as A
from . import checkpoints, controller, memory, optimizer, recall, vision
from . import tools as T
from .config import blocked_workspace
from .ollama import OllamaError

Emit = Callable[[dict], Awaitable[None]]
Ask = Callable[[dict], Awaitable[str]]  # -> "allow" | "always" | "deny"

PROJECT_FILES = ("CODER.md", "AGENTS.md", "CLAUDE.md")
TOOL_CALL_RX = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
FENCE_RX = re.compile(r"```[ \t]*(?:json|tool_call|tool|javascript|js)?[ \t]*\r?\n(.*?)```", re.S | re.I)
ANY_FENCE_RX = re.compile(r"```.*?(?:```|\Z)", re.S)
# Qwen3-Coder: <function=glob><parameter=pattern>**/*.kts</parameter></function> – oft ohne öffnendes <tool_call>
XML_CALL_RX = re.compile(r"(?:<tool_call>\s*)?<function=([^>\s]+)>(.*?)</function>(?:\s*</tool_call>)?", re.S)
XML_PARAM_RX = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.S)
JSON_START_RX = re.compile(r"(?m)^[ \t]*([\[{])")
CALL_KEYS = {"name", "tool", "tool_name", "arguments", "parameters", "args", "input", "type", "id"}
MENTION_RX = re.compile(r"^\s*@([A-Za-z0-9][\w-]{0,39})(?![\w-])")
CHARS_PER_TOKEN = 3.3
SUBAGENT_STEPS = 30
OVERVIEW_ENTRIES = 60
# Befehle, die Dateien ändern – für Agents ohne Schreibwerkzeuge gesperrt. Grob, fängt aber die üblichen Fälle ab.
MUTATING_RX = re.compile(
    r"(?:^|[;&|(]\s*|\s)(?:touch|new-item|ni|set-content|add-content|out-file|remove-item|rm|del|erase|rmdir|rd"
    r"|move-item|mv|move|copy-item|cp|copy|rename-item|ren|mkdir|md)(?=\s|$)"
    r"|\bgit\s+(?:commit|push|reset|checkout|apply|stash|clean|rebase|merge|add|rm|mv)\b"
    r"|\bsed\s+-i\b|(?:^|[^2&>])>{1,2}\s*[^&\s>]", re.I)
NUDGE_MAIN = "You stopped without an answer. Briefly tell the user the result of your work so far."
NUDGE_SUB = ("You stopped without a final answer. Write your final report for the main agent now: findings or changes "
             "with file paths and line numbers. Do not call more tools unless strictly necessary.")
NUDGE_REPEAT = "You started repeating the same text over and over. Stop that and continue with the next concrete step."
REPEAT_PROBE = 80
REPEAT_MIN = 8
GPU_BUSY = 5  # Prozent Auslastung, ab denen ein stilles Modell als „rechnet noch“ gilt

# Bewusst ohne Uhrzeit o. ä.: ein stabiler Prompt-Anfang lässt Ollama den
# KV-Cache zwischen den Schritten wiederverwenden — spart Sekunden pro Schritt.
SYSTEM_PROMPT = """You are Coder, an autonomous coding agent running fully locally. You solve software engineering tasks in the user's workspace by calling tools.

# Environment
- Workspace: {workspace}
- Top level of the workspace: {overview}
- OS: {os}. run_command runs {shell} on the user's machine.

# Capabilities
- Terminal: run_command executes real commands. Run commands yourself instead of asking the user to run them.
- Internet: web_search finds pages, web_fetch reads them. web_research searches several queries, reads the best pages and returns excerpts with numbered sources in one step – use it for questions that need more than one source. Never claim you have no internet access.
- Images: images the user attaches are part of their message. view_image looks at image files in the workspace, such as screenshots.
- Long-running processes such as dev servers or watchers: run_command with background=true, then read the log file it reports.

# How to work
- Explore before changing anything: use glob, grep and read_file. Never guess file contents.
- Always read_file before edit_file. old_string must match exactly, including indentation.
- Prefer edit_file for changes to existing files; use write_file for new files.
- For tasks with three or more steps, maintain a todo list with todo_write and update statuses as you progress.
- After making changes, verify them: run tests, a build, or the program with run_command when possible.
- If a tool fails, read the error and change your approach. Never repeat an identical failing call.
- The user may send more messages while you work. Take them into account at your next step.
- Do not ask for permission in text; the app asks the user automatically before risky actions.
- Be concise. No long preambles. When finished, summarize what you changed in one to three sentences.
- Reply in the language the user writes in. In German, address the user informally with "du", never "Sie".
{extra}"""

TEXT_TOOLS_PROMPT = """
# Tools
Call a tool by writing exactly this block, then stop and wait for the result:
<tool_call>{{"name": "read_file", "arguments": {{"path": "main.py"}}}}</tool_call>
You may write several blocks in one reply. Results arrive as <tool_result> messages.
Available tools:
{tools}
"""

DELEGATION_PROMPT = """
# Sub-agents
The agent tool hands a self-contained part of the work to a specialist with its own context: searching a large codebase, reviewing code for bugs, running tests, researching online. Write a complete task description, because the specialist cannot see this conversation. Do small, quick steps yourself.
"""

ROLE_PROMPT = """
# Your role: {name}
{prompt}
"""

MEMORY_PROMPT = """
# Memory
You have a persistent vault of linked Markdown notes (like Obsidian) that survives across chats.
- Notes that match the user's message are attached to it automatically. When a topic may have more history, use memory_search and memory_read.
- Save durable knowledge with memory_write: user preferences, project conventions, decisions and their reasons, hard-won fixes. One topic per note, short and factual. Link related notes with [[Title]] and add #tags. Update an existing note instead of creating a duplicate.
- Finished tasks may be logged automatically in the note "Verlauf" – no need to write that yourself.
- The library holds read-only guides. For UI or design work, read "Design-Prinzipien" and "Kein AI-Slop" first.
- Never store secrets such as passwords, tokens or API keys.
{notes}
"""

SUBAGENT_PROMPT = """
# Working as a sub-agent
- The main agent gave you exactly one task. The user does not see your messages; only your final reply is passed back.
- Work autonomously and never ask questions. If something is unclear, make a sensible assumption and mention it.
- Finish with a concise report: findings or changes with file paths and line numbers, plus anything left open.
"""


class StopTurn(Exception):
    pass


class AgentError(RuntimeError):
    """Ein Problem, das der Nutzer selbst beheben kann – wird ohne Traceback angezeigt."""


class ModelStalled(Exception):
    """Das Modell liefert nichts mehr und rechnet auch nicht – der Watchdog lädt es neu."""


class ModelRepeating(Exception):
    """Das Modell wiederholt denselben Text in Schleife."""


def wire_messages(messages: list[dict], native: bool, images: bool = False) -> list[dict]:
    """Entfernt UI-Metadaten und übersetzt bei Bedarf ins Text-Tool-Protokoll.

    images: das Modell sieht selbst – angehängte Bilder gehen dann direkt mit.
    """
    out = []
    for m in messages:
        if m.get("_hidden") or m.get("_ui"):
            continue
        msg = {k: v for k, v in m.items() if not k.startswith("_")}
        if not native and msg["role"] == "tool":
            msg = {"role": "user",
                   "content": f'<tool_result name="{m.get("_name", "")}">\n{msg["content"]}\n</tool_result>'}
        if images and m.get("_images") and not m.get("_vision"):
            encoded = []
            for image_id in m["_images"]:
                path = vision.path_of(image_id)
                with contextlib.suppress(OSError, ValueError):
                    if path:
                        encoded.append(vision.encode(path))
            if encoded:
                msg["images"] = encoded
        out.append(msg)
    return out


def _call_shape(data, names: set[str] | None) -> list[dict] | None:
    """Sieht das JSON wie ein oder mehrere Werkzeugaufrufe aus? Dann im Ollama-Format – sonst None."""
    items = data if isinstance(data, list) else [data]
    calls = []
    for item in items:
        if not isinstance(item, dict):
            return None
        fn = item["function"] if isinstance(item.get("function"), dict) else item
        if set(fn) - CALL_KEYS or (fn is not item and set(item) - CALL_KEYS - {"function"}):
            return None  # weitere Schlüssel: eher Daten als ein Aufruf
        name = fn.get("name") or fn.get("tool") or fn.get("tool_name")
        args = next((fn[key] for key in ("arguments", "parameters", "args", "input") if key in fn), {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                return None
        if not isinstance(name, str) or not isinstance(args, dict) or (names is not None and name not in names):
            return None
        calls.append({"function": {"name": name, "arguments": args}})
    return calls or None


def _xml_value(raw: str) -> str:
    """Parameterwert im Qwen-Format: je ein Zeilenumbruch vorn und hinten gehört zum Format, nicht zum Wert."""
    value = raw[1:] if raw.startswith("\n") else raw
    value = value[:-1] if value.endswith("\n") else value
    return value if "\n" in value else value.strip()


def _decode_sequence(body: str, names: set[str]) -> list[dict] | None:
    """Ein Codeblock zählt nur, wenn er ausschließlich aus Aufrufen besteht."""
    decoder, pos, calls = json.JSONDecoder(), 0, []
    while True:
        while pos < len(body) and body[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(body):
            return calls or None
        try:
            data, pos = decoder.raw_decode(body, pos)
        except ValueError:
            return None
        shape = _call_shape(data, names)
        if not shape:
            return None
        calls += shape


def parse_text_calls(content: str, names: set[str] | None = None) -> tuple[list[dict], str]:
    """Werkzeugaufrufe, die ein Modell als Text schreibt – und der Text ohne sie.

    Erkennt <tool_call>{…}</tool_call> (das Text-Protokoll von Coder) und, nur für bekannte Werkzeugnamen, reines JSON
    wie {"name": "read_file", "arguments": {…}}, auch in ```json-Blöcken. Qwen2.5-Coder antwortet über Ollama oft so,
    obwohl es natives Tool-Calling beherrscht.
    """
    text = content or ""
    calls, spans = [], []
    for match in TOOL_CALL_RX.finditer(text):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("name"):
            calls.append({"function": {"name": data["name"], "arguments": data.get("arguments") or {}}})
            spans.append(match.span())
    if not calls:
        for match in XML_CALL_RX.finditer(text):
            args = {p.group(1): _xml_value(p.group(2)) for p in XML_PARAM_RX.finditer(match.group(2))}
            calls.append({"function": {"name": match.group(1).strip(), "arguments": args}})
            spans.append(match.span())
        if calls:  # übrig gebliebene Tags eines halben Aufrufs nicht im Text stehen lassen
            text = re.sub(r"</?tool_call>", lambda m: " " * len(m.group(0)), text)
    if not calls and names:
        for match in FENCE_RX.finditer(text):
            found = _decode_sequence(match.group(1), names)
            if found:
                calls += found
                spans.append(match.span())
        if not calls:
            # JSON in anderen Codeblöcken ist Beispiel oder Daten – nie ein Aufruf.
            fenced = [m.span() for m in ANY_FENCE_RX.finditer(text)]
            decoder, pos = json.JSONDecoder(), 0
            for match in JSON_START_RX.finditer(text):
                start = match.start(1)
                if start < pos or any(a <= start < b for a, b in fenced):
                    continue
                try:
                    data, end = decoder.raw_decode(text, start)
                except ValueError:
                    continue
                shape = _call_shape(data, names)
                if shape:
                    calls += shape
                    spans.append((start, end))
                    pos = end
    if not spans:
        return calls, text
    kept, last = [], 0
    for start, end in sorted(spans):
        kept.append(text[last:start])
        last = end
    kept.append(text[last:])
    return calls, re.sub(r"\n{3,}", "\n\n", "".join(kept)).strip()


def _ui_args(args: dict) -> dict:
    return {k: (v[:2000] + " …" if isinstance(v, str) and len(v) > 2000 else v) for k, v in args.items()}


def repeating(text: str) -> bool:
    """Kleine Modelle verfangen sich gern in immer demselben Absatz."""
    if len(text) < REPEAT_PROBE * REPEAT_MIN:
        return False
    probe = text[-REPEAT_PROBE:]
    return len(set(probe)) > 8 and text[-REPEAT_PROBE * 40:].count(probe) >= REPEAT_MIN


def trim_repeat(text: str) -> str:
    probe = text[-REPEAT_PROBE:]
    first = text.find(probe)
    second = text.find(probe, first + 1)
    return (text[:second] if second > 0 else text).rstrip() + " …"


class Agent:
    def __init__(self, runtime, session: dict, emit: Emit, ask: Ask, *,
                 profile: "A.AgentDef | None" = None, parent: "Agent | None" = None,
                 model: str | None = None, steps: int | None = None, inbox: list | None = None):
        self.rt = runtime
        self.s = session
        self.emit = emit
        self.ask = ask
        self.profile = profile  # Rolle: als Sub-Agent gestartet oder per @name angesprochen
        self.parent = parent
        self.model_override = model  # die Kontrolle läuft auf ihrem eigenen Modell
        self.steps_override = steps
        self.inbox = inbox if inbox is not None else []  # Nachrichten, die während der Arbeit eintreffen
        self.stopped = False  # der Nutzer hat eine Aktion abgelehnt
        self.hit_limit = False
        self._agents: dict[str, A.AgentDef] | None = None
        if parent is None and not any(m.get("role") == "user" for m in session.get("messages", [])):
            session["workspace"] = runtime.cfg["workspace"]  # ein leerer Chat folgt dem gerade gewählten Ordner
        self.ctx = T.ToolContext(
            workspace=Path(session["workspace"]),
            max_output=int(runtime.cfg["max_tool_output"]),
            command_timeout=int(runtime.cfg["command_timeout"]),
            todos=session.setdefault("todos", []),
            runtime=runtime,
        )
        self._recent: list[str] = []
        self._system: dict[bool, str] = {}
        # Kontrolle
        self.turn_start = 0
        self.reviews = 0
        self.continuations = 0
        self.fail_streak = 0
        self.review_at = time.monotonic()
        self.side_model_used = False

    @property
    def cfg(self) -> dict:
        return self.rt.cfg

    # ------------------------------------------------------------------ Agents & Werkzeuge

    def available_agents(self) -> dict[str, "A.AgentDef"]:
        if self._agents is None:
            self._agents = A.load(self.ctx.workspace, include_claude=bool(self.cfg.get("claude_extensions", True)))
        return self._agents

    @property
    def can_delegate(self) -> bool:
        return self.parent is None and self.profile is None and bool(self.cfg.get("subagents", True))

    @property
    def read_only(self) -> bool:
        """Rollen ohne Schreibwerkzeuge dürfen auch über das Terminal nichts ändern."""
        return bool(self.profile) and not (self.profile.allows("edit_file") or self.profile.allows("write_file"))

    def tool_defs(self) -> list[dict]:
        memory_on = bool(self.cfg.get("memory", True))
        defs = [t for t in T.TOOLS if (self.profile is None or self.profile.allows(t["name"]))
                and (memory_on or t["kind"] != "memory")]
        if self.can_delegate and self.available_agents():
            defs.append(A.tool_schema(self.available_agents()))
        return defs

    def schemas(self) -> list[dict]:
        return [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
                for t in self.tool_defs()]

    @staticmethod
    def kind(name: str) -> str:
        return "agent" if name == "agent" else T.kind(name)

    @staticmethod
    def summarize(name: str, args: dict) -> str:
        if name == "agent":
            task = " ".join(str(args.get("task") or "").split())
            return f"{args.get('agent') or '?'} · {task[:160]}"
        return T.summarize(name, args)

    def mentioned_agent(self, text: str) -> "A.AgentDef | None":
        match = MENTION_RX.match(text or "")
        return self.available_agents().get(match.group(1).lower()) if match else None

    def last_answer(self) -> str:
        return next((m["content"].strip() for m in reversed(self.s["messages"])
                     if m["role"] == "assistant" and (m.get("content") or "").strip()), "")

    # ------------------------------------------------------------------ Prompt

    def overview(self) -> str:
        """Die oberste Ebene des Workspace – spart dem Modell den ersten list_dir-Aufruf und ändert sich selten."""
        entries = []
        try:
            for entry in self.ctx.workspace.iterdir():
                try:
                    entries.append((not entry.is_dir(), entry.name))
                except OSError:
                    continue
        except OSError:
            return "(not readable)"
        names = [name + ("" if is_file else "/") for is_file, name in sorted(entries, key=lambda e: (e[0], e[1].lower()))
                 if is_file or not (name in T.IGNORE_DIRS or (name.startswith(".") and name not in T.HIDDEN_KEEP))]
        text = ", ".join(names[:OVERVIEW_ENTRIES]) or "(empty)"
        if len(names) > OVERVIEW_ENTRIES:
            text += f", … {len(names) - OVERVIEW_ENTRIES} more"
        if (self.ctx.workspace / ".git").exists():
            text += " (git repository)"
        return text

    def system_prompt(self, native: bool) -> str:
        if native not in self._system:
            extra = ""
            for name in PROJECT_FILES:
                p = self.ctx.workspace / name
                if p.is_file():
                    text = p.read_text("utf-8", errors="replace")[:6000]
                    extra += f"\n# Project instructions ({name})\n{text}\n"
                    break
            if self.profile:
                extra += ROLE_PROMPT.format(name=self.profile.name, prompt=self.profile.prompt[:8000])
            if self.parent:
                extra += SUBAGENT_PROMPT
            elif self.can_delegate and self.available_agents():
                extra += DELEGATION_PROMPT
            if self.parent is None and self.cfg.get("memory", True):
                extra += MEMORY_PROMPT.format(notes=memory.context(self.ctx.workspace))
            if not native:
                lines = []
                for t in self.tool_defs():
                    props = t["parameters"]["properties"]
                    req = t["parameters"]["required"]
                    params = ", ".join(f"{k}{'' if k in req else '?'}: {v.get('type', 'any')}" for k, v in props.items())
                    lines.append(f"- {t['name']}({params}): {t['description']}")
                extra += TEXT_TOOLS_PROMPT.format(tools="\n".join(lines))
            shell = "PowerShell" if T.IS_WINDOWS else "bash"
            self._system[native] = SYSTEM_PROMPT.format(
                workspace=self.ctx.workspace, overview=self.overview(), os=f"{platform.system()} {platform.release()}",
                shell=shell, extra=extra)
        return self._system[native]

    # ------------------------------------------------------------------ Modell

    async def model_name(self) -> str:
        model = self.model_override or self.cfg.get("model")
        if not model:
            model = await self.rt.recommended_model()
            if not model:
                raise OllamaError("Kein Chat-Modell installiert. Beispiel: ollama pull qwen3-coder:30b")
            await self.rt.update_config({"model": model})
        return model

    async def _in_memory(self, model: str) -> bool:
        loaded = getattr(self.rt, "loaded", None)
        return True if loaded is None else any(m["name"] == model for m in await loaded())

    async def resolve_model(self) -> str:
        model = await self.model_name()
        side = bool(self.model_override)
        if model not in self.rt.plans or not await self._in_memory(model):
            await self.emit({"type": "status", "text": f"{model} wird {'geladen' if side else 'optimiert geladen'} …"})
        plan = await self.rt.ensure_loaded(model, side=side)
        self.s["model"] = model
        await self.emit({"type": "model", "model": model, "plan": plan})
        return model

    async def side_chat(self, model: str, messages: list[dict]) -> str:
        """Kurze Anfrage ohne Werkzeuge, etwa an ein Bildmodell."""
        think = False if "thinking" in await self.rt.model_caps(model) else None
        text = ""
        async for chunk in self.rt.client.chat_stream(model, messages, options=self.rt.chat_options(model),
                                                      keep_alive=self.cfg["keep_alive"], think=think):
            text += (chunk.get("message") or {}).get("content") or ""
        return text.strip()

    def check_workspace(self) -> None:
        ws = self.ctx.workspace
        if not ws.is_dir():
            raise AgentError(f"Der Ordner dieses Chats existiert nicht mehr: {ws}. Wähle einen Workspace, "
                             "dann geht es in einem neuen Chat weiter.")
        reason = blocked_workspace(ws)
        if reason:
            raise AgentError(f"{ws} geht nicht als Workspace ({reason}). Wähle einen Projektordner.")

    # ------------------------------------------------------------------ Bilder

    async def describe_images(self, images: list[str], request: str) -> dict | None:
        """Für Hauptmodelle ohne Vision: ein Bildmodell beschreibt die Bilder, bevor das Hauptmodell geladen wird."""
        model = await self.rt.vision_model(await self.model_name())
        if not model:
            await self.emit({"type": "notice", "text": "Kein installiertes Modell erkennt Bilder – das Bild bleibt "
                                                       "unbeachtet. Zum Beispiel: ollama pull gemma3:12b"})
            return None
        count = "das Bild" if len(images) == 1 else f"{len(images)} Bilder"
        await self.emit({"type": "status", "text": f"{model} sieht sich {count} an …"})
        await self.rt.ensure_loaded(model, side=True)
        self.side_model_used = True
        parts = []
        for n, image_id in enumerate(images, 1):
            try:
                data = await asyncio.to_thread(vision.encode, vision.path_of(image_id))
            except (OSError, ValueError, AttributeError) as e:
                parts.append(f"[Image {n} could not be read: {e}]")
                continue
            prompt = vision.DESCRIBE_PROMPT.format(request=request[:1500] or "–")
            text = await self.side_chat(model, [{"role": "user", "content": prompt, "images": [data]}])
            parts.append(f"[Image {n} attached by the user – described by {model}]\n{text or '(no description)'}")
        return {"model": model, "text": "\n\n".join(parts)}

    async def view_image(self, args: dict) -> dict:
        path = T.resolve(self.ctx, str(args.get("path") or ""))
        question = str(args.get("question") or "").strip()
        if not path.is_file():
            return {"ok": False, "display": {}, "content": f"Fehler: Datei nicht gefunden: {path}"}
        if not vision.is_image(path):
            return {"ok": False, "display": {}, "content": f"Fehler: {path.name} ist kein Bild (PNG, JPEG, GIF, WebP, BMP)."}
        main = await self.model_name()
        model = await self.rt.vision_model(main)
        if not model:
            return {"ok": False, "display": {}, "content": "No installed model can see images. Tell the user to "
                                                           "install one, for example: ollama pull gemma3:12b"}
        try:
            data = await asyncio.to_thread(vision.encode, path)
        except (OSError, ValueError) as e:
            return {"ok": False, "display": {}, "content": f"Fehler: {e}"}
        if model != main:
            await self.emit({"type": "status", "text": f"{model} sieht sich {path.name} an …"})
            await self.rt.ensure_loaded(model, side=True)
            self.side_model_used = True
        prompt = (f"Question about this image: {question}\n\n" if question else "") + \
            vision.DESCRIBE_PROMPT.format(request=question or "–")
        text = await self.side_chat(model, [{"role": "user", "content": prompt, "images": [data]}])
        if model != main:
            await self.resolve_model()  # Hauptmodell zurück in den VRAM
        return {"ok": bool(text), "content": f"[{path.name} – seen by {model}]\n{text or '(no description)'}",
                "display": {"image": T.rel(self.ctx, path), "model": model, "chars": len(text)}}

    # ------------------------------------------------------------------ Hauptschleife

    async def run(self, text: str, display: str | None = None, images: list[str] | None = None) -> None:
        """display: was der Chat zeigt, wenn es vom Text fürs Modell abweicht (/befehl statt ausgeschriebenem Prompt)."""
        self.check_workspace()
        shown = text if display is None else display
        if self.parent is None and self.profile is None:
            self.profile = self.mentioned_agent(shown) or self.mentioned_agent(text)  # /review → @bug-checker
        images = [i for i in images or [] if vision.path_of(i)][:6]

        described = None
        if images and "vision" not in await self.rt.model_caps(await self.model_name()):
            described = await self.describe_images(images, shown)  # vor dem Hauptmodell: nur ein Modellwechsel
            if described:
                await self.emit({"type": "vision", **described})
        model = await self.resolve_model()
        caps = self.rt.capabilities(model)
        native = "tools" in caps
        think = bool(self.cfg.get("think")) if "thinking" in caps else None

        message = {"role": "user", "content": text, "_text": shown, "_ts": time.time()}
        if images:
            message["_images"] = images
        if described:
            message["content"] += "\n\n" + described["text"]
            message["_vision"] = described
        if self.parent is None and self.cfg.get("memory", True):
            await self.attach_memory(message, shown)
        if self.cfg["permission_mode"] == "plan":
            message["content"] += ("\n\n[Plan mode: explore read-only, then present a concrete step-by-step plan. "
                                   "Do not modify files or run commands.]")
        if self.profile and self.parent is None:
            message["_agent"] = self.profile.name
            await self.emit({"type": "profile", "agent": self.profile.name})
        # Sub-Agents schreiben in die Sicherung der Aufgabe, die sie beauftragt hat.
        self.ctx.checkpoint = self.new_checkpoint(message) if self.parent is None else self.parent.ctx.checkpoint
        self.turn_start = len(self.s["messages"])
        self.s["messages"].append(message)
        if self.s.get("title") in (None, "", "Neuer Chat") and shown.strip():
            self.s["title"] = shown.strip().splitlines()[0][:60]
        self.reviews = self.continuations = self.fail_streak = 0
        self.review_at = time.monotonic()

        try:
            outcome = await self.work(model, native, think)
            # Kontrolle: prüft das Ergebnis und schickt den Agent weiter, solange etwas fehlt.
            checked, forced = -1, False  # Aufrufe bei der letzten Prüfung · nach einer Nachbesserung wird immer geprüft
            while outcome == "answer":
                if self.parent is None and self.inbox:  # der Nutzer hat während der letzten Antwort geschrieben
                    model = await self.resolve_model()
                    outcome = await self.work(model, native, think)
                    continue
                calls = controller.call_count(self)
                if not controller.due_at_end(self) or (calls == checked and not forced):
                    break
                verdict = await controller.review(self, "end")
                checked, forced = calls, False
                if verdict["verdict"] != "continue":
                    continue  # abgesegnet – es sei denn, inzwischen kam eine neue Nachricht
                if self.continuations >= int(self.cfg.get("controller_rounds", 2)):
                    await self.emit({"type": "notice", "text": f"Die Kontrolle sieht noch offene Punkte: {verdict['note']} "
                                                               "Schreib „weiter“, dann geht es daran weiter."})
                    break
                controller.inject(self, verdict)
                forced = True
                model = await self.resolve_model()
                outcome = await self.work(model, native, think)
            if self.parent is None:
                await self.finish_turn(model, outcome)
        finally:
            if self.parent is None:
                await self.record_changes()  # auch nach Abbruch oder Fehler – gerade dann will man zurücknehmen können

    def new_checkpoint(self, message: dict):
        turn = uuid.uuid4().hex[:12]
        message["_turn"] = turn
        try:
            return checkpoints.Checkpoint(str(self.s.get("id") or ""), turn)
        except ValueError:
            return None  # Chat ohne gültige Kennung: ohne Rückgängig weiterarbeiten

    async def record_changes(self) -> None:
        """Hält fest, welche Dateien diese Aufgabe geändert hat, und bietet sie zum Zurücknehmen an."""
        cp = self.ctx.checkpoint
        if cp is None or not cp.files:
            return
        try:
            changes = await asyncio.to_thread(cp.seal, self.ctx.workspace)
        except (OSError, ValueError):
            return
        if changes:
            self.s["messages"].append({"role": "event", "_ui": True, "_changes": changes})
            await self.emit({"type": "changes", **changes})

    async def attach_memory(self, message: dict, shown: str) -> None:
        referenced: set[str] = set()
        if "[[" in shown:
            notes = memory.references(shown, self.ctx.workspace)
            if notes:
                message["content"] += f"\n\n[Notes the user referenced]\n{notes}"
                referenced = {m.group(1).strip() for m in memory.LINK_RX.finditer(shown)}
        if not self.cfg.get("auto_recall", True):
            return
        try:
            found = await recall.recall(shown, self.ctx.workspace, self.rt, exclude=referenced)
        except Exception:  # noqa: BLE001 — Erinnern ist ein Bonus, nie ein Grund zum Abbruch
            found = None
        if found:
            message["content"] += f"\n\n[Notes from memory that may be relevant – use them if they help]\n{found['text']}"
            message["_recall"] = found["titles"]
            await self.emit({"type": "recall", "notes": found["titles"]})

    async def take_inbox(self) -> None:
        """Nachrichten, die während der Arbeit eingetroffen sind – das Modell liest sie vor seinem nächsten Schritt."""
        items, self.inbox[:] = list(self.inbox), []
        for item in items:
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            shown = str(item.get("display") or text)
            message = {"role": "user", "content": text, "_text": shown, "_ts": time.time(), "_queued": True}
            if self.cfg.get("memory", True) and "[[" in shown:
                notes = memory.references(shown, self.ctx.workspace)
                if notes:
                    message["content"] += f"\n\n[Notes the user referenced]\n{notes}"
            self.s["messages"].append(message)
            await self.emit({"type": "queued_taken", "id": item.get("id"), "text": shown})

    async def finish_turn(self, model: str, outcome: str) -> None:
        if self.side_model_used and hasattr(self.rt, "preload"):
            self.rt.preload(model)  # Hauptmodell schon wieder bereitlegen
        files = controller.changed_files(self)
        delegated = any(c["name"] == "agent" for m in self.s["messages"][self.turn_start:] for c in m.get("_calls") or [])
        if (outcome == "answer" and (files or delegated) and self.cfg.get("memory", True)
                and self.cfg.get("journal", True)):
            first = self.s["messages"][self.turn_start]
            try:
                await asyncio.to_thread(recall.journal, self.ctx.workspace, first.get("_text") or first["content"],
                                        self.last_answer(), files)
                await self.emit({"type": "memory_changed"})
            except (OSError, ValueError):
                pass

    async def work(self, model: str, native: bool, think: bool | None) -> str:
        """Arbeitet bis zur nächsten Antwort. Ergebnis: answer · stopped · empty · limit."""
        limit = int(self.cfg["max_steps"])
        if self.parent is not None:
            limit = min(limit, self.steps_override or SUBAGENT_STEPS)
        nudged, stalls = False, 0
        for _ in range(limit):
            if self.parent is None and self.inbox:
                await self.take_inbox()
            await self.compact_if_needed(model, native)
            try:
                calls = await self.model_turn(model, native, think)
            except ModelStalled as e:
                stalls += 1
                if stalls > 2:
                    raise AgentError(f"{model} reagiert wiederholt nicht mehr. Starte Ollama neu oder wähle in den "
                                     "Einstellungen weniger Kontext.") from e
                await self.recover(model, str(e), stalls)
                continue
            except ModelRepeating:
                if self.parent is None:
                    await self.emit({"type": "notice", "text": "Das Modell hat sich wiederholt – abgebrochen und nachgehakt."})
                self.s["messages"].append({"role": "user", "content": NUDGE_REPEAT, "_nudge": True})
                continue
            stalls = 0
            if calls:
                try:
                    for call in calls:
                        await self.handle_call(call)
                except StopTurn:
                    self.stopped = True
                    return "stopped"
                reason = controller.due_while_working(self)
                if reason:
                    verdict = await controller.review(self, reason)
                    if verdict["verdict"] == "continue":
                        controller.inject(self, verdict, hint=True)
                    if verdict["model"] != model:
                        model = await self.resolve_model()
                continue
            if (self.s["messages"][-1].get("content") or "").strip():
                return "answer"
            if nudged:  # auch nach der Nachfrage nichts: aufhören statt endlos zu drehen
                if self.parent is None:
                    await self.emit({"type": "notice", "text": "Das Modell hat keine Antwort geliefert."})
                return "empty"
            # Kleine Modelle hören nach Werkzeugergebnissen gern wortlos auf – einmal nachhaken.
            nudged = True
            self.s["messages"].pop()
            self.s["messages"].append({"role": "user", "content": NUDGE_SUB if self.parent else NUDGE_MAIN, "_nudge": True})
        self.hit_limit = True
        if self.parent is None:
            await self.emit({"type": "notice", "text": "Schrittlimit erreicht. Schreib „weiter“, um fortzufahren."})
        return "limit"

    async def model_turn(self, model: str, native: bool, think: bool | None) -> list[dict]:
        sees = "vision" in self.rt.capabilities(model)
        messages = [{"role": "system", "content": self.system_prompt(native)}] + \
            wire_messages(self.s["messages"], native, images=sees)
        msg = {"role": "assistant", "content": "", "_id": uuid.uuid4().hex[:10]}
        if self.profile and self.parent is None:
            msg["_agent"] = self.profile.name
        self.s["messages"].append(msg)  # früh anhängen, damit ein Abbruch den Teiltext behält
        await self.emit({"type": "assistant_start", "id": msg["_id"]})

        raw_calls: list[dict] = []
        final: dict = {}
        t0 = time.perf_counter()
        first_token = None
        checked = 0
        stream = self.rt.client.chat_stream(
            model, messages,
            tools=self.schemas() if native else None,
            options=self.rt.chat_options(model),
            keep_alive=self.cfg["keep_alive"],
            think=think,
        )
        try:
            while True:
                try:
                    chunk = await self.next_chunk(stream, model, waiting=first_token is None)
                except StopAsyncIteration:
                    break
                m = chunk.get("message") or {}
                if m.get("thinking"):
                    first_token = first_token or time.perf_counter()
                    msg["_thinking"] = msg.get("_thinking", "") + m["thinking"]
                    await self.emit({"type": "thinking", "id": msg["_id"], "text": m["thinking"]})
                if m.get("content"):
                    first_token = first_token or time.perf_counter()
                    msg["content"] += m["content"]
                    await self.emit({"type": "text", "id": msg["_id"], "text": m["content"]})
                if m.get("tool_calls"):
                    raw_calls.extend(m["tool_calls"])
                if chunk.get("done"):
                    final = chunk
                size = len(msg["content"]) + len(msg.get("_thinking", ""))
                if size - checked >= 400:
                    checked = size
                    for key in ("content", "_thinking"):
                        if repeating(msg.get(key, "")):
                            msg[key] = trim_repeat(msg[key])
                            raise ModelRepeating
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

        if not raw_calls:
            raw_calls, cleaned = parse_text_calls(msg["content"], {t["name"] for t in self.tool_defs()})
            if raw_calls and cleaned != msg["content"]:
                if native:
                    msg["content"] = cleaned  # im nativen Protokoll gehören Aufrufe in tool_calls, nicht in den Text
                else:
                    msg["_shown"] = cleaned  # Text-Protokoll: das Modell soll seine Aufrufe im Verlauf wiedersehen
                await self.emit({"type": "assistant_text", "id": msg["_id"], "text": cleaned})

        calls = []
        for rc in raw_calls:
            fn = rc.get("function") or {}
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            calls.append({"id": uuid.uuid4().hex[:10], "name": str(fn.get("name", "")), "args": args if isinstance(args, dict) else {}})
        if calls:
            if native:
                msg["tool_calls"] = [{"function": {"name": c["name"], "arguments": c["args"]}} for c in calls]
            msg["_calls"] = calls

        stats = self._stats(final, t0, first_token)
        msg["_stats"] = stats
        usage = self.s.setdefault("usage", {"prompt": 0, "completion": 0, "last_prompt": 0})
        usage["prompt"] += stats["prompt_tokens"]
        usage["completion"] += stats["tokens"]
        await self.emit({"type": "stats", "id": msg["_id"], "stats": stats})
        await self.emit_context(model, native)

        return calls

    async def next_chunk(self, stream, model: str, waiting: bool) -> dict:
        """Nächstes Stück vom Modell – mit Watchdog.

        Stille allein heißt nichts: Prompt-Verarbeitung und lange Werkzeugaufrufe streamen nicht. Erst wenn auch die
        GPU ruht oder das Modell aus dem Speicher verschwunden ist, gilt es als hängend.
        """
        limit = float(self.cfg.get("watchdog") or 0)
        if not limit:
            return await stream.__anext__()
        pending = asyncio.ensure_future(stream.__anext__())
        window, silent = (limit * 2 if waiting else limit), 0.0
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=window)
                if done:
                    return pending.result()
                silent += window
                if not await self.model_alive(model, silent, limit, waiting):
                    raise ModelStalled(f"seit {int(silent)} s keine Antwort")
                window = min(limit, 60.0)
        except BaseException:
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(BaseException):
                    await pending
            raise

    async def model_alive(self, model: str, silent: float, limit: float, waiting: bool) -> bool:
        if silent >= limit * 6:
            return False  # harte Obergrenze
        if not waiting and not await self._in_memory(model):
            return False  # Runner abgestürzt oder entladen
        for attempt in range(2):
            busy = await asyncio.to_thread(optimizer.gpu_utilization)
            if busy is None:
                return silent < limit * 3  # ohne Messung: großzügig warten
            if busy >= GPU_BUSY:
                return True
            if attempt == 0:
                await asyncio.sleep(3)
        return False

    async def recover(self, model: str, reason: str, attempt: int) -> None:
        last = self.s["messages"][-1] if self.s["messages"] else {}
        if last.get("role") == "assistant" and not last.get("_calls"):
            self.s["messages"].pop()
            await self.emit({"type": "assistant_discard", "id": last.get("_id")})
        await self.emit({"type": "watchdog",
                         "text": f"{model} hängt ({reason}) – wird neu geladen, Versuch {attempt} von 2 …"})
        with contextlib.suppress(OllamaError):
            await self.rt.client.unload(model)
        self.rt.plans.pop(model, None)
        await self.resolve_model()

    @staticmethod
    def _stats(final: dict, t0: float, first_token: float | None) -> dict:
        eval_s = (final.get("eval_duration") or 0) / 1e9
        prompt_s = (final.get("prompt_eval_duration") or 0) / 1e9
        return {
            "tokens": final.get("eval_count") or 0,
            "prompt_tokens": final.get("prompt_eval_count") or 0,
            "tokens_per_s": round((final.get("eval_count") or 0) / eval_s, 1) if eval_s else 0,
            "prompt_per_s": round((final.get("prompt_eval_count") or 0) / prompt_s, 1) if prompt_s else 0,
            "load_s": round((final.get("load_duration") or 0) / 1e9, 2),
            "ttft_s": round(first_token - t0, 2) if first_token else None,
            "total_s": round(time.perf_counter() - t0, 2),
            "done_reason": final.get("done_reason"),
        }

    # ------------------------------------------------------------------ Werkzeuge

    def permission(self, name: str, args: dict) -> str:
        kind = self.kind(name)
        mode = self.cfg["permission_mode"]
        allow = self.s.get("allow", [])
        if kind in ("read", "meta", "agent", "memory"):  # Sub-Agents fragen selbst; Notizen sind keine Projektdateien
            return "allow"
        if kind == "web":  # liest nur, schickt aber Daten nach draußen – im Modus „Fragen“ also nachfragen
            return "ask" if mode == "ask" and name not in allow else "allow"
        if mode == "plan":
            return "plan"
        if mode == "yolo" or name in allow:
            return "allow"
        if name == "run_command" and T.command_allowed(str(args.get("command", "")), allow):
            return "allow"
        if kind == "write" and mode == "auto-edit":
            if T.inside_workspace(self.ctx, T.resolve(self.ctx, args.get("path"))):
                return "allow"
        return "ask"

    @staticmethod
    def always_label(name: str, args: dict) -> str | None:
        """Wofür „Immer erlauben“ gilt: bei Befehlen nur für Programm und Unterbefehl – None heißt, jedes Mal fragen."""
        if name == "run_command":
            return T.command_prefix(str(args.get("command", "")))
        return name

    def remember_allow(self, name: str, always: str) -> None:
        entry = f"run_command:{always}" if name == "run_command" else name
        allow = self.s.setdefault("allow", [])
        if entry not in allow:
            allow.append(entry)

    async def execute(self, name: str, args: dict) -> dict:
        if name == "view_image":
            return await self.view_image(args)
        return await T.execute(name, args, self.ctx)

    async def handle_call(self, call: dict) -> None:
        cid, name = call["id"], call["name"]
        # Erst die Namen der Argumente angleichen, dann prüfen: file_path muss als path in die Freigabe.
        args = call["args"] = T.normalize_args(name, call["args"])
        summary = self.summarize(name, args)
        await self.emit({"type": "tool_call", "id": cid, "name": name, "args": _ui_args(args),
                         "summary": summary, "kind": self.kind(name)})

        signature = json.dumps([name, args], sort_keys=True, default=str)
        self._recent = (self._recent + [signature])[-8:]
        stop = False
        available = {t["name"] for t in self.tool_defs()}

        if self._recent.count(signature) >= 3 and T.kind(name) != "meta":
            result = {"ok": False, "display": {},
                      "content": "You already made this exact call several times. Change your approach."}
        elif name == "agent":
            result = await self.delegate(cid, args)
            stop = result.pop("stop", False)
        elif name not in available:
            content = (f"The tool {name} is not available to you. Use only the tools you were given."
                       if name in T.TOOL_MAP else
                       f"Unknown tool '{name}'. Available tools: {', '.join(sorted(available))}.")
            result = {"ok": False, "display": {}, "content": content}
        elif name == "run_command" and self.read_only and MUTATING_RX.search(str(args.get("command", ""))):
            result = {"ok": False, "display": {"denied": True},
                      "content": "You are a read-only agent and this command looks like it changes files. "
                                 "Use only commands that read or test, and report what should be changed instead."}
        else:
            decision = self.permission(name, args)
            if decision == "plan":
                result = {"ok": False, "display": {"denied": True},
                          "content": "Plan mode is active: no file changes or commands. Present your plan instead."}
            elif decision == "ask":
                always = self.always_label(name, args)
                answer = await self.ask({"id": cid, "name": name, "summary": summary, "kind": T.kind(name),
                                         "args": _ui_args(args), "preview": T.preview(name, args, self.ctx),
                                         "always": always})
                if answer == "deny":
                    result = {"ok": False, "display": {"denied": True},
                              "content": "The user declined this action. Stop and wait for their instructions."}
                    stop = True
                else:
                    if answer == "always" and always:
                        self.remember_allow(name, always)
                    await self.emit({"type": "tool_running", "id": cid})
                    result = await self.execute(name, args)
            else:
                result = await self.execute(name, args)

        if not result["display"].get("denied"):
            self.fail_streak = 0 if result["ok"] else self.fail_streak + 1
        self.s["messages"].append({
            "role": "tool", "content": result["content"], "tool_name": name,
            "_id": cid, "_name": name, "_summary": summary, "_ok": result["ok"], "_display": result["display"],
        })
        await self.emit({"type": "tool_result", "id": cid, "name": name, "ok": result["ok"],
                         "output": result["content"][:8000], "display": result["display"]})
        if name == "todo_write":
            await self.emit({"type": "todos", "todos": self.ctx.todos})
        if stop:
            raise StopTurn

    async def delegate(self, cid: str, args: dict) -> dict:
        """Lässt einen Sub-Agent die Aufgabe mit eigenem Kontext erledigen und gibt seinen Bericht zurück."""
        if not self.can_delegate:
            return {"ok": False, "display": {}, "content": "Sub-agents are not available here. Do the work yourself."}
        agents = self.available_agents()
        name = str(args.get("agent") or args.get("name") or "").strip().lstrip("@").lower()
        task = str(args.get("task") or args.get("prompt") or args.get("description") or "").strip()
        profile = agents.get(name)
        if profile is None:
            return {"ok": False, "display": {}, "content": f"Unknown agent '{name}'. Available: {', '.join(agents)}."}
        if not task:
            return {"ok": False, "display": {}, "content": "The task for the agent is missing."}

        steps: dict[str, dict] = {}

        async def emit(ev: dict) -> None:
            if ev.get("type") == "tool_call":
                steps[ev["id"]] = {"id": ev["id"], "name": ev["name"], "summary": ev["summary"], "args": ev["args"]}
            elif ev.get("type") == "tool_result" and ev["id"] in steps:
                steps[ev["id"]].update(ok=ev["ok"], output=ev["output"][:1500], display=ev["display"])
            await self.emit({**ev, "parent": cid, "agent": profile.name})

        async def ask(request: dict) -> str:
            return await self.ask({**request, "agent": profile.name})

        session = {"id": cid, "title": profile.name, "workspace": self.s["workspace"], "messages": [], "todos": [],
                   "allow": self.s.setdefault("allow", [])}
        sub = Agent(self.rt, session, emit, ask, profile=profile, parent=self)
        started = time.perf_counter()
        await sub.run(task)
        report = sub.last_answer()
        display = {"agent": profile.name, "task": task, "steps": list(steps.values()), "report": report,
                   "seconds": round(time.perf_counter() - started, 1)}
        if sub.stopped:
            content = f"The user declined an action of the {profile.name} agent. Stop and wait for their instructions."
        elif report:
            content = f"Report from {profile.name}:\n{report}"
        else:
            log = "\n".join(f"- {s['name']} {s['summary'][:120]} → {'ok' if s.get('ok') else 'failed'}"
                            for s in steps.values())
            content = (f"The {profile.name} agent finished WITHOUT a report, so there are no findings from it. "
                       "Do not invent or assume results: check the code yourself or tell the user the agent "
                       f"returned nothing.\nIts steps:\n{log or '- none'}")
        if sub.hit_limit:
            content += "\n[The agent hit its step limit; the result may be incomplete.]"
        return {"ok": bool(report) and not sub.stopped, "content": content, "display": display, "stop": sub.stopped}

    # ------------------------------------------------------------------ Kontext

    def context_tokens(self, native: bool) -> int:
        chars = len(self.system_prompt(native))
        for m in wire_messages(self.s["messages"], native):
            chars += len(m.get("content") or "")
            if m.get("tool_calls"):
                chars += len(json.dumps(m["tool_calls"], ensure_ascii=False))
        if native:
            chars += len(json.dumps(self.schemas(), ensure_ascii=False))
        return int(chars / CHARS_PER_TOKEN)

    async def emit_context(self, model: str, native: bool) -> None:
        await self.emit({"type": "context", "used": self.context_tokens(native), "max": self.rt.num_ctx(model)})

    async def compact_if_needed(self, model: str, native: bool, force: bool = False) -> None:
        limit = self.rt.num_ctx(model)
        if force or self.context_tokens(native) > 0.6 * limit:
            self._shrink_tool_outputs(keep_last=6)
        if force or self.context_tokens(native) > 0.8 * limit:
            await self._summarize(model)
            if self.context_tokens(native) > 0.9 * limit:
                self._shrink_tool_outputs(keep_last=2, head=400, tail=200)
            await self.emit_context(model, native)

    def _shrink_tool_outputs(self, keep_last: int, head: int = 700, tail: int = 300) -> None:
        msgs = self.s["messages"]
        for m in msgs[:max(0, len(msgs) - keep_last)]:
            c = m.get("content") or ""
            if m["role"] == "tool" and len(c) > head + tail + 200:
                m["content"] = f"{c[:head]}\n… [ältere Ausgabe gekürzt, {len(c)} Zeichen] …\n{c[-tail:]}"

    async def _summarize(self, model: str) -> None:
        msgs = self.s["messages"]
        user_turns = [i for i, m in enumerate(msgs) if m["role"] == "user" and "_text" in m and not m.get("_hidden")]
        if not user_turns:
            return
        cut = user_turns[-1]
        older = [i for i in range(cut) if not msgs[i].get("_hidden") and not msgs[i].get("_ui")]
        if len(older) < 2:
            return

        parts = []
        for i in older:
            m = msgs[i]
            label = {"user": "USER", "assistant": "ASSISTANT", "tool": f"TOOL {m.get('_name', '')}"}.get(m["role"], m["role"])
            body = (m.get("content") or "")[:1500]
            if m.get("_calls"):
                body += "\n" + "; ".join(f"call {c['name']}({self.summarize(c['name'], c['args'])})" for c in m["_calls"])
            parts.append(f"{label}: {body}")
        budget = int(self.rt.num_ctx(model) * 0.5 * CHARS_PER_TOKEN)
        transcript = "\n\n".join(parts)[-budget:]

        await self.emit({"type": "status", "text": "Verlauf wird verdichtet …"})
        prompt = [
            {"role": "system", "content": "You compress coding-agent conversations into dense, factual summaries."},
            {"role": "user", "content": (
                "Summarize this conversation so work can continue without it. Keep: the user's goals, decisions, "
                "files created or changed (with key details), important findings, errors and how they were solved, "
                "current state and open tasks. Max 350 words, bullet points.\n\n" + transcript)},
        ]
        think = False if "thinking" in self.rt.capabilities(model) else None
        summary = ""
        async for chunk in self.rt.client.chat_stream(model, prompt, options=self.rt.chat_options(model),
                                                      keep_alive=self.cfg["keep_alive"], think=think):
            summary += (chunk.get("message") or {}).get("content") or ""
        summary = summary.strip()
        if not summary:
            return

        for i in older:
            msgs[i]["_hidden"] = True
        msgs[cut:cut] = [
            {"role": "user", "content": f"[Summary of the earlier conversation]\n{summary}", "_summary": True},
            {"role": "assistant", "content": "Understood. Continuing from this summary.", "_summary": True, "_quiet": True},
        ]
        await self.emit({"type": "compacted", "summary": summary})

    async def compact(self) -> None:
        model = await self.resolve_model()
        native = "tools" in self.rt.capabilities(model)
        await self.compact_if_needed(model, native, force=True)
