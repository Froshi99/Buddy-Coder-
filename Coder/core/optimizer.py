"""Hardware-Erkennung und Ladeplanung für Ollama-Modelle.

Berechnet aus freiem VRAM, Dateigröße und Architektur (Layer, KV-Heads,
Head-Dimension) den größten Kontext, der ohne CPU-Offload in die GPU passt.
Nach dem Laden wird die Schätzung mit /api/ps gegen die Realität geprüft.
"""

import ctypes
import os
import platform
import re
import shutil
import subprocess
import time

GB = 1024 ** 3
MB = 1024 ** 2

CTX_STEPS = [4096, 8192, 12288, 16384, 24576, 32768, 49152, 65536, 98304, 131072]
MIN_AGENT_CTX = 8192  # System-Prompt + Tool-Schemas + etwas Verlauf
KV_FACTOR = {"f16": 1.0, "q8_0": 0.5, "q4_0": 0.25}

_hw_cache: tuple[float, dict] | None = None


# --------------------------------------------------------------------------- Hardware

def detect_hardware(max_age: float = 5.0) -> dict:
    global _hw_cache
    if _hw_cache and time.monotonic() - _hw_cache[0] < max_age:
        return _hw_cache[1]
    hw = {
        "os": platform.system(),
        "cpu": _cpu_name(),
        "cores": _physical_cores(),
        "ram_total": _ram_total(),
        "gpus": _nvidia_gpus(),
        "unified_memory": False,
    }
    if not hw["gpus"] and hw["os"] == "Darwin" and platform.machine() == "arm64":
        # Apple Silicon: Metal darf standardmäßig ca. 2/3 bis 3/4 des RAMs nutzen.
        total = hw["ram_total"]
        hw["gpus"] = [{"name": "Apple Silicon GPU", "total": int(total * 0.70), "free": int(total * 0.65)}]
        hw["unified_memory"] = True
    hw["vram_total"] = sum(g["total"] for g in hw["gpus"])
    hw["vram_free"] = sum(g["free"] for g in hw["gpus"])
    _hw_cache = (time.monotonic(), hw)
    return hw


def _nvidia_gpus() -> list[dict]:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[1].isdigit():
            gpus.append({"name": parts[0], "total": int(parts[1]) * MB, "free": int(parts[2]) * MB})
    return gpus


def gpu_utilization() -> int | None:
    """Auslastung der GPU in Prozent (höchster Wert aller Karten) – None ohne nvidia-smi."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        values = [int(v) for v in re.findall(r"\d+", out)]
        return max(values) if values else None
    except (OSError, subprocess.SubprocessError):
        return None


def _ram_total() -> int:
    system = platform.system()
    try:
        if system == "Windows":
            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMSTAT()
            stat.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys)
        if system == "Darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout)
        with open("/proc/meminfo") as f:
            return int(re.search(r"MemTotal:\s+(\d+)", f.read()).group(1)) * 1024
    except Exception:
        return 0


def _physical_cores() -> int:
    try:
        import psutil  # optional
        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except ImportError:
        return max(1, (os.cpu_count() or 2) // 2)


def _cpu_name() -> str:
    name = platform.processor()
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
            name = winreg.QueryValueEx(key, "ProcessorNameString")[0]
        except OSError:
            pass
    return re.sub(r"\s+", " ", name or platform.machine()).strip()


def server_env() -> dict:
    """Ollama-Umgebungsvariablen (Prozess + unter Windows die Benutzer-Variablen)."""
    keys = ["OLLAMA_FLASH_ATTENTION", "OLLAMA_KV_CACHE_TYPE", "OLLAMA_NUM_PARALLEL", "OLLAMA_MAX_LOADED_MODELS"]
    env = {k: os.environ.get(k) for k in keys}
    if platform.system() == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            for k in keys:
                if not env[k]:
                    try:
                        env[k] = winreg.QueryValueEx(key, k)[0]
                    except OSError:
                        pass
        except OSError:
            pass
    return env


# --------------------------------------------------------------------------- Modellprofil

def model_profile(show: dict, size: int) -> dict:
    info = show.get("model_info") or {}
    arch = info.get("general.architecture", "")

    def g(key, default=None):
        return info.get(f"{arch}.{key}", default)

    def scalar(v, default=0):
        if isinstance(v, list):
            vals = [x for x in v if isinstance(x, (int, float))]
            return max(vals) if vals else default
        return v if isinstance(v, (int, float)) else default

    layers = scalar(g("block_count"), 0)
    n_embd = scalar(g("embedding_length"), 0)
    n_head = scalar(g("attention.head_count"), 0)
    n_head_kv = scalar(g("attention.head_count_kv"), n_head) or n_head
    key_len = scalar(g("attention.key_length"), 0) or (n_embd // n_head if n_head else 128)
    val_len = scalar(g("attention.value_length"), 0) or key_len
    ctx_max = scalar(g("context_length"), 0) or _ctx_from_details(show) or 8192

    kv_layers = max(1, layers - scalar(g("attention.shared_kv_layers"), 0))
    per_token = 2 * kv_layers * n_head_kv * (key_len + val_len)  # f16: 2 Bytes je Element
    sliding = scalar(g("attention.sliding_window"), 0)

    return {
        "arch": arch,
        "params": show.get("details", {}).get("parameter_size", ""),
        "quant": show.get("details", {}).get("quantization_level", ""),
        "size": size,
        "layers": layers,
        "ctx_max": int(ctx_max),
        "kv_per_token_f16": int(per_token),
        "sliding_window": int(sliding),
        "capabilities": show.get("capabilities") or [],
        "moe": bool(scalar(g("expert_count"), 0)),
    }


def _ctx_from_details(show: dict) -> int:
    m = re.search(r"num_ctx\s+(\d+)", show.get("parameters") or "")
    return int(m.group(1)) if m else 0


def kv_bytes(profile: dict, ctx: int, kv_type: str) -> int:
    per_tok = profile["kv_per_token_f16"] * KV_FACTOR.get(kv_type, 1.0)
    sw = profile["sliding_window"]
    if sw and ctx > sw:
        # Sliding-Window-Modelle (z. B. Gemma): nur ca. jede 6. Schicht hält den vollen Kontext.
        return int(per_tok * (ctx / 6 + sw * 5 / 6))
    return int(per_tok * ctx)


def graph_overhead(profile: dict, ctx: int) -> int:
    # Compute-Buffer wächst mit Kontext und Modellbreite; empirisch 0.4–1.2 GB.
    return int(400 * MB + ctx * 12_000 + profile["size"] * 0.02)


# --------------------------------------------------------------------------- Ladeplan

def plan(profile: dict, hw: dict, cfg: dict, loaded_vram: int = 0) -> dict:
    """Wählt num_ctx so, dass Gewichte + KV-Cache vollständig in den VRAM passen."""
    env = server_env()
    kv_type = cfg.get("kv_cache_type") or "auto"
    if kv_type == "auto":
        kv_type = (env.get("OLLAMA_KV_CACHE_TYPE") or "f16").lower()
        if env.get("OLLAMA_FLASH_ATTENTION") not in ("1", "true", "True"):
            kv_type = "f16"  # Quantisierter KV-Cache wirkt nur mit Flash Attention

    # Speicher, den dieses Modell bereits belegt, gilt als verfügbar.
    budget = hw["vram_free"] + loaded_vram - 350 * MB
    weights = profile["size"]
    ctx_cap = min(profile["ctx_max"], int(cfg.get("max_auto_ctx") or 32768))
    notes: list[str] = []

    if cfg.get("num_ctx"):
        ctx = min(int(cfg["num_ctx"]), profile["ctx_max"])
        source = "manuell"
    else:
        fitting = [c for c in CTX_STEPS if MIN_AGENT_CTX <= c <= ctx_cap
                   and weights + kv_bytes(profile, c, kv_type) + graph_overhead(profile, c) <= budget]
        if fitting:
            ctx = fitting[-1]
        else:
            # MoE-Modelle laufen mit Teil-Offload ohnehin flott — 16K geben dem Agenten Luft,
            # solange GPU + RAM Gewichte und Cache sicher tragen. Dichte Modelle bleiben knapp,
            # damit möglichst viele Schichten auf der GPU landen.
            ctx = min(MIN_AGENT_CTX, profile["ctx_max"])
            roomy = min(16384, ctx_cap)
            total_mem = hw["vram_total"] + hw["ram_total"] * 0.75
            if profile["moe"] and roomy > ctx and weights + kv_bytes(profile, roomy, kv_type) + graph_overhead(profile, roomy) < total_mem:
                ctx = roomy
        source = "auto"

    need = weights + kv_bytes(profile, ctx, kv_type) + graph_overhead(profile, ctx)
    gpu_share = 1.0 if hw["vram_total"] == 0 and hw["unified_memory"] else (
        min(1.0, max(0.0, budget / need)) if need and hw["vram_total"] else 0.0)

    if not hw["gpus"]:
        notes.append("Keine GPU erkannt – das Modell läuft auf der CPU. Kleine Modelle (≤ 8B) sind hier deutlich schneller.")
    elif gpu_share < 1.0:
        pct = round(gpu_share * 100)
        if profile["moe"]:
            notes.append(f"Mixture-of-Experts: ca. {pct}% auf der GPU. Dank weniger aktiver Parameter trotzdem gut nutzbar.")
        else:
            notes.append(f"Nur ca. {pct}% passen in den VRAM – der Rest läuft auf der CPU und bremst stark.")
    if env.get("OLLAMA_FLASH_ATTENTION") not in ("1", "true", "True"):
        notes.append("OLLAMA_FLASH_ATTENTION=1 senkt den Speicherbedarf bei langem Kontext.")
    if kv_type == "f16" and hw["gpus"]:
        notes.append("OLLAMA_KV_CACHE_TYPE=q8_0 halbiert den KV-Cache – fast doppelter Kontext bei gleichem VRAM.")
    if env.get("OLLAMA_NUM_PARALLEL") not in ("1",):
        notes.append("OLLAMA_NUM_PARALLEL=1 verhindert, dass der Kontextspeicher mehrfach reserviert wird.")
    if "tools" not in profile["capabilities"]:
        notes.append("Kein natives Tool-Calling – Coder nutzt ein Text-Protokoll, das weniger zuverlässig ist.")

    options = {"num_ctx": int(ctx)}
    if gpu_share < 1.0 and hw["cores"]:
        options["num_thread"] = int(hw["cores"])

    return {
        "options": options,
        "num_ctx": int(ctx),
        "ctx_source": source,
        "kv_type": kv_type,
        "estimate_bytes": int(need),
        "gpu_share": round(gpu_share, 3),
        "fits": gpu_share >= 1.0,
        "notes": notes,
    }


# --------------------------------------------------------------------------- Empfehlung

def score(profile: dict, pl: dict, name: str) -> float:
    caps = profile["capabilities"]
    if "completion" not in caps and caps:
        return -1  # Embedding-Modelle
    s = 0.0
    s += 40 if "tools" in caps else 0
    s += 25 if re.search(r"coder|code|devstral|codestral", name, re.I) else 0
    s += 30 * pl["gpu_share"] if not profile["moe"] else 30 * min(1.0, pl["gpu_share"] * 1.6)
    s += min(20.0, profile["size"] / GB * 1.6)  # größer = meist klüger
    s += 5 if pl["num_ctx"] >= 16384 else 0
    s -= 15 if profile["size"] < 1.5 * GB else 0  # Winzlinge scheitern an Agent-Aufgaben
    return round(s, 1)
