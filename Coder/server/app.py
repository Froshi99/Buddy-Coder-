"""HTTP- und WebSocket-Server für die Oberfläche."""

import asyncio
import ipaddress
import logging
import socket
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Body, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core import __version__, agents, checkpoints, commands, folders, memory, optimizer, power, sessions, tools, vision
from core import config as config_mod
from core.agent import Agent, AgentError
from core.ollama import OllamaError
from core.runtime import Runtime

WEB = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("coder")
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_QUEUE = 8


def is_local(request: Request) -> bool:
    """Systemdialoge öffnen sich auf dem Rechner mit dem Server – bei Zugriff aus dem LAN wären sie unsichtbar."""
    return bool(request.client) and request.client.host in ("127.0.0.1", "::1", "localhost")


def hostname(value: str) -> str:
    """Hostname aus einem Host-Header: ohne Port, IPv6 ohne Klammern."""
    try:
        return (urlsplit(f"//{value}").hostname or "").lower()
    except ValueError:
        return ""


def same_origin(origin: str, host: str) -> bool:
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host) and parts.netloc.lower() == host.lower()


class LocalGuard:
    """Nimmt nur Anfragen an diesen Rechner an – und von Browsern nur solche, die von der Oberfläche selbst kommen.

    WebSockets kennen keine Same-Origin-Regel: Ohne diese Prüfung könnte jede geöffnete Webseite eine Verbindung zu
    Coder aufbauen, Aufträge schicken und Freigaben erteilen, also Befehle auf diesem Rechner ausführen. Der Blick auf
    den Host-Header wehrt zusätzlich DNS-Rebinding ab, bei dem eine fremde Domain plötzlich auf 127.0.0.1 zeigt.
    """

    def __init__(self, app, public: bool = False):
        self.app = app
        self.public = public  # mit --host 0.0.0.0 gestartet: auch Adressen im LAN
        name = socket.gethostname().lower()
        self.machine = {name, f"{name}.local"}

    def host_allowed(self, host: str) -> bool:
        name = hostname(host)
        if name in LOOPBACK:
            return True
        if not self.public or not name:
            return False
        try:
            ipaddress.ip_address(name)
            return True
        except ValueError:
            return name in self.machine

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers") or []}
        host, origin = headers.get("host", ""), headers.get("origin")
        if self.host_allowed(host) and (origin is None or same_origin(origin, host)):
            await self.app(scope, receive, send)
            return
        log.warning("Anfrage abgewiesen: Host %r, Origin %r", host, origin)
        if scope["type"] == "websocket":
            await receive()  # websocket.connect – ein close davor lehnt den Handshake ab
            await send({"type": "websocket.close", "code": 1008})
            return
        body = "Coder nimmt nur Anfragen seiner eigenen Oberfläche an.".encode("utf-8")
        await send({"type": "http.response.start", "status": 403,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})


def create_app(host: str = "127.0.0.1") -> FastAPI:
    runtime = Runtime()

    @asynccontextmanager
    async def lifespan(_app):
        # „Solange Coder offen ist“: Die Anforderung gehört der Event-Loop und wird dort auch wieder freigegeben.
        power.keep_awake.hold(runtime.cfg.get("keep_awake") == "open")
        yield
        power.keep_awake.hold(False)
        tools.stop_background()
        await runtime.close()

    app = FastAPI(title="Coder", version=__version__, lifespan=lifespan)
    app.add_middleware(LocalGuard, public=host.strip("[]").lower() not in LOOPBACK)
    app.mount("/static", StaticFiles(directory=WEB), name="static")
    no_cache = {"Cache-Control": "no-store"}

    @app.get("/")
    async def index():
        return FileResponse(WEB / "index.html", headers=no_cache)

    @app.get("/api/state")
    async def state(request: Request):
        return {
            "version": __version__,
            "native_picker": is_local(request),
            "config": runtime.cfg,
            "ollama": await runtime.status(),
            "hardware": await asyncio.to_thread(optimizer.detect_hardware),
            "loaded": await runtime.loaded(),
            "sessions": sessions.list_all(),
        }

    @app.get("/api/models")
    async def models():
        try:
            return await runtime.models()
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/models/load")
    async def load_model(model: str = Body(..., embed=True)):
        try:
            await runtime.update_config({"model": model})
            plan = await runtime.ensure_loaded(model, force=True)
            return {"model": model, "plan": plan, "loaded": await runtime.loaded()}
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.post("/api/models/unload")
    async def unload_model(model: str = Body(..., embed=True)):
        try:
            await runtime.client.unload(model)
            runtime.plans.pop(model, None)
            return {"loaded": await runtime.loaded()}
        except OllamaError as e:
            raise HTTPException(503, str(e))

    @app.get("/api/loaded")
    async def loaded():
        return {"loaded": await runtime.loaded(), "hardware": await asyncio.to_thread(optimizer.detect_hardware)}

    @app.post("/api/images")
    async def upload_image(data: str = Body(..., embed=True)):
        try:
            image_id = await asyncio.to_thread(vision.store_base64, data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": image_id, "url": f"/api/images/{image_id}"}

    @app.get("/api/images/{image_id}")
    async def get_image(image_id: str):
        path = vision.path_of(image_id)
        if not path:
            raise HTTPException(404, "Bild nicht gefunden")
        return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.post("/api/config")
    async def set_config(changes: dict = Body(...)):
        if "workspace" in changes:
            raw = str(changes["workspace"] or "").strip()
            if not raw:
                raise HTTPException(400, "Bitte einen Ordner angeben.")
            ws = config_mod.normalize_path(raw)
            if not ws.is_dir():
                raise HTTPException(400, f"Ordner nicht gefunden: {ws}")
            reason = config_mod.blocked_workspace(ws)
            if reason:
                raise HTTPException(400, f"{ws} geht nicht als Workspace ({reason}). Wähle einen Projektordner.")
            changes["workspace"] = str(ws)
        cfg = await runtime.update_config(changes)
        power.keep_awake.hold(cfg.get("keep_awake") == "open")
        return cfg

    @app.get("/api/folders")
    async def browse_folders(path: str = ""):
        return await asyncio.to_thread(folders.listing, path)

    @app.get("/api/folders/places")
    async def folder_places():
        places, recent = await asyncio.gather(asyncio.to_thread(folders.places), asyncio.to_thread(folders.recent))
        return {"places": places, "recent": recent}

    @app.post("/api/folders/pick")
    async def pick_folder(request: Request, start: str = Body("", embed=True)):
        if not is_local(request):
            raise HTTPException(403, "Der Ordnerdialog öffnet sich nur auf dem Rechner, auf dem Coder läuft.")
        try:
            return {"path": await asyncio.to_thread(folders.pick, start)}
        except RuntimeError as e:
            raise HTTPException(501, str(e))

    def workspace_of(raw: str) -> Path:
        """Agents und Befehle hängen vom Ordner des offenen Chats ab; Ungültiges fällt auf den Workspace zurück."""
        ws = config_mod.normalize_path(raw) if raw.strip() else Path(runtime.cfg["workspace"])
        return ws if ws.is_dir() and not config_mod.blocked_workspace(ws) else Path(runtime.cfg["workspace"])

    @app.get("/api/agents")
    async def list_agents(workspace: str = ""):
        include_claude = bool(runtime.cfg.get("claude_extensions", True))
        found = await asyncio.to_thread(agents.load, workspace_of(workspace), include_claude)
        return {"agents": [a.public() for a in found.values()], "tools": [t["name"] for t in tools.TOOLS]}

    @app.post("/api/agents")
    async def save_agent(data: dict = Body(...)):
        try:
            return agents.save(data, workspace_of(str(data.get("workspace") or ""))).public()
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/agents/{scope}/{name}")
    async def delete_agent(scope: str, name: str, workspace: str = ""):
        try:
            agents.delete(scope, name, workspace_of(workspace))
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/memory")
    async def memory_overview(workspace: str = ""):
        return await asyncio.to_thread(memory.overview, workspace_of(workspace))

    @app.get("/api/memory/note")
    async def memory_note(title: str, workspace: str = "", vault: str = ""):
        try:
            return await asyncio.to_thread(memory.read, title, workspace_of(workspace), vault or None)
        except KeyError:
            raise HTTPException(404, f"Keine Notiz „{title}“")

    @app.post("/api/memory/note")
    async def memory_save(data: dict = Body(...)):
        try:
            return await asyncio.to_thread(memory.save, data, workspace_of(str(data.get("workspace") or "")))
        except KeyError as e:
            raise HTTPException(404, f"Keine Notiz „{e.args[0]}“")
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/memory/note")
    async def memory_delete(title: str, vault: str, workspace: str = ""):
        try:
            await asyncio.to_thread(memory.delete, title, workspace_of(workspace), vault)
        except (ValueError, OSError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    @app.get("/api/commands")
    async def list_commands(workspace: str = ""):
        include_claude = bool(runtime.cfg.get("claude_extensions", True))
        return {"commands": await asyncio.to_thread(commands.load, workspace_of(workspace), include_claude)}

    @app.get("/api/sessions")
    async def list_sessions():
        return sessions.list_all()

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        s = sessions.load(session_id)
        if not s:
            raise HTTPException(404, "Chat nicht gefunden")
        return s

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        sessions.delete(session_id)
        await asyncio.to_thread(checkpoints.delete_session, session_id)
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        conn = Connection(ws, runtime)
        try:
            await conn.loop()
        except WebSocketDisconnect:
            pass
        finally:
            conn.shutdown()

    return app


class Connection:
    """Ein Browserfenster: eine aktive Session, höchstens ein laufender Agent – und was während der Arbeit eintrifft."""

    def __init__(self, ws: WebSocket, runtime: Runtime):
        self.ws = ws
        self.rt = runtime
        self.session: dict | None = None
        self.task: asyncio.Task | None = None
        self.pending: dict[str, asyncio.Future] = {}
        self.inbox: list[dict] = []  # Nachrichten, die der Agent vor seinem nächsten Schritt liest
        self._send_lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return bool(self.task and not self.task.done())

    async def send(self, event: dict) -> None:
        async with self._send_lock:
            try:
                await self.ws.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                pass

    async def loop(self) -> None:
        while True:
            msg = await self.ws.receive_json()
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "open":
                s = sessions.load(str(msg.get("session_id") or "")) if msg.get("session_id") else None
                await self.set_session(s)
            elif kind == "new":
                await self.set_session(None)
            elif kind == "send":
                text = str(msg.get("text", ""))
                images = [str(i) for i in msg.get("images") or [] if isinstance(i, str)][:6]
                if self.busy:
                    await self.enqueue(text, msg.get("display"), msg.get("queue_id"), images)
                else:
                    await self.start(self.run_agent(text, msg.get("display"), images))
            elif kind == "unqueue":
                await self.unqueue(str(msg.get("id") or ""))
            elif kind == "undo":
                await self.undo()
            elif kind == "compact":
                await self.start(self.run_compact())
            elif kind == "cancel":
                if self.busy:
                    self.task.cancel()
            elif kind == "permission":
                fut = self.pending.get(msg.get("id"))
                if fut and not fut.done():
                    fut.set_result(msg.get("decision", "deny"))

    async def set_session(self, s: dict | None) -> None:
        if self.busy:
            await self.send({"type": "error", "message": "Der Agent arbeitet noch. Erst stoppen."})
            return
        self.inbox.clear()
        self.session = s or sessions.new(self.rt.cfg["workspace"], self.rt.cfg.get("model", ""))
        await self.send({"type": "session", "session": self.session})

    async def start(self, coro) -> None:
        if self.busy:
            coro.close()
            await self.send({"type": "error", "message": "Der Agent arbeitet bereits."})
            return
        if self.session is None:
            await self.set_session(None)
        self.task = asyncio.create_task(coro)

    async def enqueue(self, text: str, display, queue_id, images: list[str]) -> None:
        """Während der Agent arbeitet, wartet eine neue Nachricht – er liest sie vor seinem nächsten Schritt."""
        item_id = str(queue_id or uuid.uuid4().hex[:10])[:40]
        problem = ("Bilder lassen sich erst anhängen, wenn der Agent fertig ist." if images
                   else "Es warten schon genug Nachrichten." if len(self.inbox) >= MAX_QUEUE
                   else "Die Nachricht ist leer." if not text.strip() else "")
        if problem:
            await self.send({"type": "queue_rejected", "id": item_id, "message": problem})
            return
        item = {"id": item_id, "text": text, "display": text if display is None else str(display)}
        self.inbox.append(item)
        await self.send({"type": "queued", "id": item_id, "text": item["display"]})

    async def unqueue(self, item_id: str) -> None:
        before = len(self.inbox)
        self.inbox[:] = [item for item in self.inbox if item["id"] != item_id]
        await self.send({"type": "unqueued", "id": item_id, "ok": len(self.inbox) < before})

    async def undo(self) -> None:
        if self.busy:
            await self.send({"type": "undo_failed", "message": "Erst den laufenden Auftrag stoppen, dann zurücknehmen."})
            return
        if self.session is None:
            await self.send({"type": "undo_failed", "message": "Es gibt keine Änderungen, die sich zurücknehmen lassen."})
            return
        try:
            result = await asyncio.to_thread(checkpoints.undo, self.session)
        except ValueError as e:
            await self.send({"type": "undo_failed", "message": str(e)})
            return
        sessions.save(self.session)
        await self.send({"type": "undone", **result})

    async def ask(self, request: dict) -> str:
        fut = asyncio.get_running_loop().create_future()
        self.pending[request["id"]] = fut
        await self.send({"type": "permission", **request})
        try:
            return await fut
        finally:
            self.pending.pop(request["id"], None)

    async def run_agent(self, text: str, display: str | None = None, images: list[str] | None = None) -> None:
        await self._guarded(lambda agent: agent.run(text, None if display is None else str(display), images))

    async def run_compact(self) -> None:
        await self._guarded(lambda agent: agent.compact())

    async def _guarded(self, action) -> None:
        awake = self.rt.cfg.get("keep_awake") != "off"
        if awake:
            power.keep_awake.acquire()  # kein Standby mitten in einer langen Aufgabe
        await self.send({"type": "busy", "busy": True})
        try:
            while True:
                await action(Agent(self.rt, self.session, self.send, self.ask, inbox=self.inbox))
                if not self.inbox:
                    break
                # Kam erst nach dem letzten Schritt an: wird der nächste Auftrag. Weitere liest der Agent unterwegs.
                item = self.inbox.pop(0)
                await self.send({"type": "queued_taken", "id": item["id"], "text": item["display"]})
                action = (lambda text, shown: lambda agent: agent.run(text, shown))(item["text"], item["display"])
        except asyncio.CancelledError:
            await self.send({"type": "notice", "text": "Gestoppt."})
        except (OllamaError, AgentError) as e:
            await self.send({"type": "error", "message": str(e)})
        except Exception as e:  # noqa: BLE001
            log.error(traceback.format_exc())
            await self.send({"type": "error", "message": f"{e.__class__.__name__}: {e}"})
        finally:
            if awake:
                power.keep_awake.release()
            dropped, self.inbox[:] = list(self.inbox), []
            if dropped:  # gestoppt oder gescheitert: die wartenden Texte gehen zurück in die Eingabe, nicht verloren
                await self.send({"type": "queue_dropped", "items": dropped})
            if self.session.get("messages"):
                sessions.save(self.session)
            await self.send({"type": "done", "session": {"id": self.session["id"], "title": self.session["title"],
                                                         "model": self.session.get("model")}})

    def shutdown(self) -> None:
        if self.task and not self.task.done():
            self.task.cancel()
        self.inbox.clear()
        for fut in self.pending.values():
            if not fut.done():
                fut.set_result("deny")
