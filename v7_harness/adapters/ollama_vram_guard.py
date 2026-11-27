"""U390: Disjoint 6GB VRAM & provider-error guard for local Ollama calls.

Keeps local generation within safe VRAM context buckets, normalizes Go-style
``keep_alive`` durations (converting ISO-8601 ``PT*`` strings that Ollama rejects
with HTTP 400), rejects oversized prompts before hitting the local server, and
bounds transient retries while holding the serialized GPU lease.
"""

from __future__ import annotations

from contextlib import nullcontext
import os
import re
import time
import urllib.error
from typing import Any, Callable, Sequence

from v7_harness.adapters.gpu_priority import pilot_holds

DEFAULT_NUM_CTX = 16384
DEFAULT_NUM_PREDICT = 4096
SAFE_PROMPT_CTX_RATIO = 0.78
TRANSIENT_RETRIES = 1
VRAM_CTX_BUCKETS = (4096, 8192, 16384)
MIN_RETRY_BUDGET_S = 30.0
EFFECTIVE_6GB_USABLE_VRAM_GB = 4.95
RECOMMENDED_DAEMON_ENV: dict[str, str] = {
    "OLLAMA_FLASH_ATTENTION": "1",
    "OLLAMA_KV_CACHE_TYPE": "q8_0",
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
}
SAFE_OLLAMA_FAMILIES: tuple[str, ...] = (
    "qwen",
    "deepseek",
    "gemma",
    "llama",
    "phi",
    "mistral",
    "devstral",
    "codestral",
    "starcoder",
    "nomic-embed",
    "mxbai-embed",
    "bge-",
)
RECOMMENDED_6GB_SYNC_CANDIDATES: tuple[str, ...] = ("qwen3:4b", "deepseek-r1:7b", "gemma3:4b")

OLLAMA_CELLULAR_PROFILES: dict[str, dict[str, Any]] = {
    "qwen2.5-coder:7b": {
        "weights_gb": 4.7,
        "quant": "Q4_K_M",
        "optimal_num_ctx": 4096,
        "max_100pct_gpu_ctx": 4096,
        "spill_ctx_warning": 16384,
        "force_think_false": False,
        "temperature": 0.0,
        "best_for": "code_slice_20L",
        "cli_cmd": "ollama run qwen2.5-coder:7b",
    },
    "qwen2.5-coder:3b": {
        "weights_gb": 1.9,
        "quant": "Q4_K_M",
        "optimal_num_ctx": 8192,
        "max_100pct_gpu_ctx": 16384,
        "force_think_false": False,
        "temperature": 0.0,
        "best_for": "fast_json_and_draft",
        "cli_cmd": "ollama run qwen2.5-coder:3b",
    },
    "qwen3.5:4b": {
        "weights_gb": 3.4,
        "quant": "Q4_K_M",
        "optimal_num_ctx": 8192,
        "max_100pct_gpu_ctx": 8192,
        "force_think_false": True,
        "temperature": 0.0,
        "presence_penalty": 0.0,
        "best_for": "schema_concretize_and_triage",
        "cli_cmd": "ollama run qwen3.5:4b",
    },
    "qwen3.5-32k:latest": {
        "weights_gb": 3.4,
        "quant": "Q4_K_M",
        "optimal_num_ctx": 8192,
        "max_100pct_gpu_ctx": 8192,
        "spill_ctx_warning": 32768,
        "force_think_false": True,
        "temperature": 0.0,
        "presence_penalty": 0.0,
        "best_for": "bounded_doc_digest",
        "cli_cmd": "ollama run qwen3.5-32k:latest",
    },
    "qwen3-embedding:0.6b": {
        "weights_gb": 0.64,
        "quant": "Q8_0",
        "optimal_num_ctx": 8192,
        "max_100pct_gpu_ctx": 32768,
        "force_think_false": False,
        "temperature": 0.0,
        "best_for": "semantic_embedding",
        "cli_cmd": "ollama run qwen3-embedding:0.6b",
    },
}

_GO_DURATION_RE = re.compile(r"^[0-9]+(?:ms|s|m|h)$")
_ISO_DURATION_RE = re.compile(r"^PT([0-9]+)([HMS])$", re.IGNORECASE)


class PromptBudgetExceeded(ValueError):
    """Raised before network dispatch when prompt tokens exceed safe VRAM context."""


def estimate_prompt_tokens(prompt: str) -> int:
    """Return a conservative character/UTF-8 byte token estimate for ``prompt``."""
    if not prompt:
        return 0
    return max(len(prompt) // 3, len(prompt.encode("utf-8")) // 3)


def choose_vram_safe_ctx(
    est_prompt_tokens: int,
    *,
    max_ctx: int = DEFAULT_NUM_CTX,
    num_predict: int = DEFAULT_NUM_PREDICT,
) -> int:
    """Pick the smallest power-of-two bucket fitting prompt+predict+headroom up to ``max_ctx``."""
    cap = max(1024, int(max_ctx))
    needed = max(0, int(est_prompt_tokens)) + max(0, int(num_predict)) + 512
    for bucket in VRAM_CTX_BUCKETS:
        if bucket <= cap and bucket >= needed:
            return bucket
    return max(4096, cap) if cap >= 4096 else cap


def normalize_keep_alive(raw: object) -> str:
    """Normalize ``keep_alive`` to a valid Ollama Go duration, ``'0'``, or ``'-1'``."""
    raw_str = str(raw or "5m").strip()
    if not raw_str:
        return "5m"
    if raw_str in ("-1", "0") or _GO_DURATION_RE.match(raw_str):
        return raw_str
    match = _ISO_DURATION_RE.match(raw_str)
    if match:
        num, unit = match.groups()
        return f"{num}{unit.lower()}"
    return "5m"


def preflight_prompt_budget(
    prompt: str,
    *,
    max_ctx: int = DEFAULT_NUM_CTX,
    num_predict: int = DEFAULT_NUM_PREDICT,
    safe_ratio: float = SAFE_PROMPT_CTX_RATIO,
) -> dict[str, Any]:
    """Check whether ``prompt`` fits safely inside ``max_ctx`` before hitting Ollama."""
    cap = max(512, int(max_ctx))
    estimated = estimate_prompt_tokens(prompt)
    safe_limit = max(256, int(cap * float(safe_ratio)))
    recommended_ctx = choose_vram_safe_ctx(estimated, max_ctx=cap, num_predict=num_predict)
    if estimated > safe_limit:
        return {
            "ok": False,
            "estimated_tokens": estimated,
            "safe_limit": safe_limit,
            "recommended_ctx": recommended_ctx,
            "error_code": "PROMPT_TOO_LARGE",
            "detail": (
                f"PROMPT_TOO_LARGE: estimated {estimated} tokens exceeds safe ctx budget "
                f"{safe_limit} (slice prompt before calling Ollama)"
            ),
        }
    return {
        "ok": True,
        "estimated_tokens": estimated,
        "safe_limit": safe_limit,
        "recommended_ctx": recommended_ctx,
        "error_code": None,
        "detail": "OK",
    }


def call_with_vram_guard(
    fn: Callable[..., Any],
    *,
    prompt: str,
    max_ctx: int = DEFAULT_NUM_CTX,
    num_predict: int = DEFAULT_NUM_PREDICT,
    keep_alive: object = "10m",
    timeout_s: int = 120,
    retries: int = TRANSIENT_RETRIES,
    backoff_s: float = 0.5,
    use_gpu_lease: bool = True,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Any:
    """Invoke local Ollama callable ``fn`` with preflight cap, GPU lease, and bounded retry."""
    budget = preflight_prompt_budget(prompt, max_ctx=max_ctx, num_predict=num_predict)
    if not budget["ok"]:
        raise PromptBudgetExceeded(budget["detail"])

    ka = normalize_keep_alive(keep_alive)
    ctx = int(budget["recommended_ctx"])
    max_attempts = max(0, int(retries)) + 1
    deadline = time.monotonic() + max(1, int(timeout_s))

    for attempt in range(max_attempts):
        remaining = max(1, int(deadline - time.monotonic()))
        lease_ctx = pilot_holds(remaining) if use_gpu_lease else nullcontext()
        try:
            with lease_ctx:
                return fn(prompt=prompt, num_ctx=ctx, keep_alive=ka, timeout_s=remaining)
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt + 1 >= max_attempts or (deadline - time.monotonic()) < MIN_RETRY_BUDGET_S:
                raise
            if backoff_s > 0:
                sleep_fn(backoff_s)


def is_safe_ollama_model_tag(tag: str) -> bool:
    """Allow vetted local model families and reject foreign IP/URL/unvetted tags."""
    raw = str(tag or "").strip()
    if not raw or any(ch.isspace() for ch in raw) or ".." in raw or "\\" in raw or "://" in raw:
        return False
    if "/" in raw:
        prefix = raw.split("/", 1)[0]
        if "." in prefix or ":" in prefix:
            return False
    lowered = raw.lower()
    return any(lowered.startswith(fam) for fam in SAFE_OLLAMA_FAMILIES)


def _lookup_cellular_profile(model: str) -> dict[str, Any]:
    norm = str(model or "").strip().lower()
    if norm in OLLAMA_CELLULAR_PROFILES:
        return OLLAMA_CELLULAR_PROFILES[norm]
    if f"{norm}:latest" in OLLAMA_CELLULAR_PROFILES:
        return OLLAMA_CELLULAR_PROFILES[f"{norm}:latest"]
    if norm.endswith(":latest") and norm[:-7] in OLLAMA_CELLULAR_PROFILES:
        return OLLAMA_CELLULAR_PROFILES[norm[:-7]]
    return {
        "weights_gb": 4.0,
        "quant": "Q4_K_M",
        "optimal_num_ctx": 4096,
        "max_100pct_gpu_ctx": 8192,
        "force_think_false": False,
        "temperature": 0.0,
        "best_for": "general",
    }


def build_cellular_ollama_options(
    model: str,
    *,
    prompt_tokens: int = 1500,
    allow_thinking: bool = False,
    vram_gb: float = 6.0,
) -> dict[str, Any]:
    """Return GPU-pinned per-model options curing Modelfile thinking/ctx traps."""
    norm = str(model or "").strip()
    if not is_safe_ollama_model_tag(norm):
        raise ValueError(f"UNSAFE_OLLAMA_MODEL_TAG:{model}")

    prof = _lookup_cellular_profile(norm)
    vram = float(vram_gb)
    ptok = max(0, int(prompt_tokens))
    max_gpu_ctx = int(prof.get("max_100pct_gpu_ctx", 4096))
    opt_ctx = int(prof.get("optimal_num_ctx", 4096))

    if vram <= 6.5:
        if ptok <= 2800:
            num_ctx = min(opt_ctx, max_gpu_ctx)
        elif ptok <= 6200:
            num_ctx = 8192
        else:
            num_ctx = choose_vram_safe_ctx(ptok, max_ctx=16384)
    else:
        num_ctx = choose_vram_safe_ctx(ptok, max_ctx=16384)

    estimated_100pct_gpu = (vram > 6.5) or (num_ctx <= max_gpu_ctx)
    opts: dict[str, Any] = {
        "num_ctx": num_ctx,
        "temperature": float(prof.get("temperature", 0.0)),
    }
    if "presence_penalty" in prof or prof.get("force_think_false"):
        opts["presence_penalty"] = float(prof.get("presence_penalty", 0.0))

    think_val: bool | None = bool(allow_thinking) if prof.get("force_think_false") else None
    return {
        "model": norm,
        "think": think_val,
        "keep_alive": "10m",
        "options": opts,
        "estimated_100pct_gpu": estimated_100pct_gpu,
        "weights_gb": prof.get("weights_gb"),
        "best_for": prof.get("best_for"),
    }


def audit_ollama_cellular_harness(
    installed_tags: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    vram_gb: float = 6.0,
) -> dict[str, Any]:
    """Audit installed local tags, daemon env, and 6GB sync gaps without paid calls."""
    safe_models: list[str] = []
    quarantined_foreign_tags: list[str] = []
    for raw_tag in installed_tags:
        tag = str(raw_tag or "").strip()
        if not tag:
            continue
        if is_safe_ollama_model_tag(tag):
            if tag not in safe_models:
                safe_models.append(tag)
        else:
            if tag not in quarantined_foreign_tags:
                quarantined_foreign_tags.append(tag)

    active_env = os.environ if env is None else env
    missing_or_suboptimal_env: dict[str, dict[str, Any]] = {}
    for key, desired in RECOMMENDED_DAEMON_ENV.items():
        actual = active_env.get(key)
        if str(actual or "").strip().lower() != desired.lower():
            missing_or_suboptimal_env[key] = {"expected": desired, "actual": actual}

    installed_set = {m.lower() for m in safe_models}
    recommended_sync_candidates = [
        cand
        for cand in RECOMMENDED_6GB_SYNC_CANDIDATES
        if cand.lower() not in installed_set and f"{cand}:latest".lower() not in installed_set
    ]
    cellular_options = {
        m: build_cellular_ollama_options(m, vram_gb=vram_gb) for m in safe_models
    }

    return {
        "schema": "uaos-ollama-cellular-audit-v1",
        "vram_gb": float(vram_gb),
        "usable_vram_gb": EFFECTIVE_6GB_USABLE_VRAM_GB if float(vram_gb) <= 6.5 else round(float(vram_gb) * 0.85, 2),
        "safe_models": safe_models,
        "quarantined_foreign_tags": quarantined_foreign_tags,
        "missing_or_suboptimal_env": missing_or_suboptimal_env,
        "recommended_sync_candidates": recommended_sync_candidates,
        "cellular_options": cellular_options,
        "live_paid_benchmarking_used": False,
    }
