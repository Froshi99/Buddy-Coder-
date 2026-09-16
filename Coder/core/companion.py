"""Companion fürs Terminal: ein Axolotl, das mitfiebert.

Es wohnt in ~/.coder/companion.json, heißt so, wie du es nennst, und kommentiert Tests, Fehler und das Urteil der
Kontrolle. Seine Sprüche kommen ohne Modellaufruf aus – es kostet keine Sekunde Rechenzeit.
"""

import json
import random
import time

from .config import HOME

PATH = HOME / "companion.json"
SPECIES = "Axolotl"
NAME = "Axo"
COLOR = "95"  # hellrosa, wie ein Axolotl
WIDTH = 15
FACE_ROW = 2

# Von vorn: flacher, breiter Kopf, links und rechts je drei Kiemenbüschel. {L}/{R} sind die Augen, {M} der Mund.
# Nur ASCII – Zeichen mit unklarer Breite verschieben in manchen Konsolen die ganze Figur.
ART = [
    r"    .-----.",
    r" \\/       \//",
    r" =|  {L}   {R}  |=",
    r" //\   {M}   /\\",
    r"    '-----'",
]
MINI = ">({L}{M}{R})<"
MOODS = {
    "idle": ("o", "o", "w"),
    "happy": ("^", "^", "w"),
    "think": ("o", "O", "~"),
    "work": (">", "<", "o"),
    "alert": ("O", "O", "o"),
    "sad": ("x", "x", "n"),
    "sleep": ("-", "-", "z"),
    "love": ("♥", "♥", "w"),
}

LINES = {
    "hello": ["Na, was bauen wir heute?", "Bereit, wenn du es bist.", "*wedelt mit den Kiemen*",
              "Leg los – ich schau zu.", "Schön, dass du da bist!"],
    "done": ["Fertig – {steps}, {time}.", "Erledigt in {time}.", "Geschafft! {steps}.", "Das war's. {time}."],
    "answer": ["Gern geschehen.", "Hoffe, das hilft!", "Noch was?"],
    "edit": ["Sauber editiert.", "Code angefasst – sieht gut aus.", "Datei geändert."],
    "tests_ok": ["Tests grün! *freudiges Blubbern*", "Alles grün. Herrlich.", "Tests bestanden."],
    "run_fail": ["Autsch, Exit {code}.", "Das knallte – wird schon.", "Rot. Nicht schlimm, das wächst nach."],
    "controller": ["{model} schaut drüber …", "Kontrolle läuft – Daumen drücken."],
    "verdict_done": ["Abgesegnet!", "Kontrolle sagt: passt.", "Geprüft und für gut befunden."],
    "verdict_continue": ["Da fehlt noch was – weiter geht's.", "Nachsitzen!", "Die Kontrolle ist streng. Gut so."],
    "ask": ["Brauch dein Okay.", "Darf ich?", "Kurz nachgefragt …"],
    "denied": ["Okay, lass ich.", "Verstanden, Kiemen weg."],
    "cancel": ["Abgebrochen. Kein Ding.", "Gestoppt."],
    "error": ["Uff, das ging schief.", "Hoppla."],
    "watchdog": ["Das Modell hing – ich hab's neu gestartet."],
    "recall": ["Mir fällt da was ein …", "Das hatten wir schon mal!"],
    "image": ["Schönes Bild!", "Ich schau's mir an."],
    "pet": ["♥", "*blubb*", "Hehe, das kitzelt an den Kiemen!", "Mehr davon!", "*lächelt Axolotl-breit*"],
    "bye": ["Bis bald!", "Tschüss – ich bewach den Code.", "Gute Nacht, Code."],
}


class Companion:
    def __init__(self, data: dict):
        self.data = data

    @property
    def name(self) -> str:
        return self.data.get("name") or NAME

    @property
    def species(self) -> str:
        return SPECIES

    @property
    def enabled(self) -> bool:
        return bool(self.data.get("enabled", True))

    @property
    def color(self) -> str:
        return COLOR

    @property
    def face_row(self) -> int:
        return FACE_ROW

    @classmethod
    def load(cls) -> "Companion":
        try:
            data = json.loads(PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and data.get("name"):
            # Frühere Versionen ließen Katzen, Eulen & Co. schlüpfen – Name und Streicheleinheiten ziehen mit um.
            buddy = cls({"name": str(data["name"])[:20], "species": SPECIES, "born": data.get("born") or time.time(),
                         "pets": int(data.get("pets") or 0), "enabled": data.get("enabled", True)})
            if data.get("species") != SPECIES or set(data) - set(buddy.data):
                buddy.save()
            return buddy
        buddy = cls.hatch()
        buddy.save()
        return buddy

    @classmethod
    def hatch(cls, name: str | None = None) -> "Companion":
        return cls({"name": name or NAME, "species": SPECIES, "born": time.time(), "pets": 0, "enabled": True})

    def save(self) -> None:
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def eyes(self, mood: str, tick: int = 0) -> tuple[str, str, str]:
        left, right, mouth = MOODS.get(mood, MOODS["idle"])
        if mood == "work" and tick % 10 >= 5:
            left, right = "o", "o"  # schaut kurz auf
        elif mood == "think" and (tick // 8) % 3 == 2:
            left, right = "O", "o"  # schaut zur anderen Seite
        if tick and tick % 30 in (0, 1) and mood not in ("sleep", "love", "sad"):
            left = right = "-"  # blinzeln
        return left, right, mouth

    def _fill(self, template: str, mood: str, tick: int) -> str:
        left, right, mouth = self.eyes(mood, tick)
        return template.replace("{L}", left).replace("{R}", right).replace("{M}", mouth)

    def art(self, mood: str = "idle", tick: int = 0) -> list[str]:
        return [self._fill(line, mood, tick).ljust(WIDTH) for line in ART]

    def face(self, mood: str = "idle", tick: int = 0) -> str:
        return self._fill(MINI, mood, tick)

    def line(self, event: str, **values) -> str:
        text = random.choice(LINES.get(event) or [""])
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text

    def pet(self) -> None:
        self.data["pets"] = int(self.data.get("pets", 0)) + 1
        self.save()
