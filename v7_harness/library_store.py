"""U250: Canonical Reference & Benchmark Library Store for UAOS-RSI.

Enforces the global rule that all GitHub sample and benchmarking reference
repositories used by UAOS-RSI (Codex, Claude Code, Antigravity) are uniformly
stored under:
  D:\\D_Workspace_NB\\-agentic-ai-workspace\\260916_agentic-ai-env-diet\\.work\\library\\<repo>
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def is_symlink_or_junction(path: Path) -> bool:
    """True if path is a POSIX symlink, Windows junction, or reparse point."""
    import os
    try:
        if path.is_symlink():
            return True
        if hasattr(path, "is_junction") and path.is_junction():
            return True
        if hasattr(os.path, "isjunction") and os.path.isjunction(path):
            return True
        st = path.lstat()
        attrs = getattr(st, "st_file_attributes", 0)
        if attrs and (attrs & 0x0400):
            return True
    except OSError:
        return True
    return False


CANONICAL_LIBRARY_PATH_STR = (
    r"D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library"
)
CANONICAL_LIBRARY_ROOT = Path(CANONICAL_LIBRARY_PATH_STR)

_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_GIT_REF_RE = re.compile(r"^refs/[A-Za-z0-9._/-]+$")
_HEX_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
_GITHUB_URL_RE = re.compile(
    r"^(?:https?://github\.com/|git@github\.com:)?(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


def extract_repo_name(repo_slug_or_url: str) -> str:
    """Extract a safe repository folder name from a GitHub URL, owner/repo slug, or repo name."""
    raw = (repo_slug_or_url or "").strip()
    if not raw or ".." in raw:
        raise ValueError(f"INVALID_LIBRARY_REPO: {repo_slug_or_url!r}")
    match = _GITHUB_URL_RE.match(raw)
    if match:
        repo = match.group("repo")
    else:
        repo = raw.strip("/\\")
    if not _REPO_NAME_RE.match(repo) or repo in {".", "..", "_analysis", "_tmp"}:
        raise ValueError(f"INVALID_LIBRARY_REPO_NAME: {repo!r}")
    return repo


def resolve_library_repo_path(
    repo_slug_or_url: str,
    library_root: Path | None = None,
) -> Path:
    """Resolve the canonical `.work/library/<repo>` destination path."""
    root = Path(library_root) if library_root is not None else CANONICAL_LIBRARY_ROOT
    repo_name = extract_repo_name(repo_slug_or_url)
    resolved_root = root.resolve()
    target = (resolved_root / repo_name).resolve()
    if target.parent != resolved_root:
        raise ValueError(f"LIBRARY_PATH_ESCAPE: {target}")
    return target


def _is_safe_git_ref(git_dir: Path, ref_rel: str) -> Path | None:
    """Validate that a symbolic git ref stays strictly under `git_dir/refs/` with no traversal or symlinks."""
    if not ref_rel or ".." in ref_rel or "\\" in ref_rel or ":" in ref_rel or ref_rel.startswith("/"):
        return None
    if not _GIT_REF_RE.match(ref_rel):
        return None
    git_root = git_dir.resolve()
    candidate = git_dir / ref_rel
    try:
        cur = git_dir
        for part in Path(ref_rel).parts:
            cur = cur / part
            if cur.is_symlink():
                return None
        resolved = candidate.resolve()
        if not resolved.is_relative_to(git_root / "refs"):
            return None
        return resolved
    except OSError:
        return None


def _read_git_head_and_origin(git_dir: Path) -> tuple[str, str, bool]:
    """Read HEAD commit SHA (9 chars), remote.origin.url, and ref safety flag from `.git/` without subprocess."""
    commit_sha = "UNKNOWN"
    ref_safe = True
    try:
        head_file = git_dir / "HEAD"
        if head_file.is_symlink():
            return "UNKNOWN", "", False
        head_raw = head_file.read_text(encoding="utf-8", errors="replace").strip()
        if head_raw.startswith("ref:"):
            ref_rel = head_raw.split(":", 1)[1].strip()
            safe_ref_file = _is_safe_git_ref(git_dir, ref_rel)
            if safe_ref_file is None:
                ref_safe = False
                commit_sha = "INVALID_REF"
            elif safe_ref_file.is_file():
                raw_sha = safe_ref_file.read_text(encoding="utf-8", errors="replace").strip()
                if _HEX_SHA_RE.match(raw_sha):
                    commit_sha = raw_sha[:9]
                else:
                    ref_safe = False
                    commit_sha = "INVALID_SHA"
            else:
                packed = git_dir / "packed-refs"
                if packed.is_file() and not packed.is_symlink():
                    for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                        if not line.startswith("#") and line.endswith(f" {ref_rel}"):
                            cand_sha = line.split()[0].strip()
                            if _HEX_SHA_RE.match(cand_sha):
                                commit_sha = cand_sha[:9]
                            break
        elif _HEX_SHA_RE.match(head_raw):
            commit_sha = head_raw[:9]
        else:
            ref_safe = False
    except OSError:
        commit_sha = "UNKNOWN"
        ref_safe = False

    origin_url = ""
    try:
        cfg_file = git_dir / "config"
        if cfg_file.is_file() and not cfg_file.is_symlink():
            in_origin = False
            for raw_line in cfg_file.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw_line.strip()
                if line.startswith("[") and line.endswith("]"):
                    in_origin = line.lower() == '[remote "origin"]'
                elif in_origin and line.lower().startswith("url"):
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        origin_url = parts[1].strip()
                        break
    except OSError:
        origin_url = ""
    if origin_url.endswith(".git"):
        origin_url = origin_url[:-4]
    return commit_sha, origin_url, ref_safe


def inspect_library_repo(repo_dir: Path) -> dict[str, Any]:
    """Inspect a cloned reference repository inside `.work/library/<repo>` without executing any code or subprocess."""
    repo_path = Path(repo_dir).resolve()
    if not repo_path.is_dir():
        return {
            "ok": False,
            "error": "REPO_DIR_MISSING",
            "path": str(repo_path),
        }
    git_dir = repo_path / ".git"
    if not git_dir.exists() or is_symlink_or_junction(git_dir) or git_dir.resolve() != (repo_path.resolve() / ".git"):
        return {
            "ok": False,
            "error": "NOT_A_GIT_REPO",
            "path": str(repo_path),
        }

    commit_sha, origin_url, ref_safe = _read_git_head_and_origin(git_dir)
    if not ref_safe:
        return {
            "ok": False,
            "error": "UNSAFE_GIT_HEAD_REF",
            "name": repo_path.name,
            "path": str(repo_path),
            "origin_url": origin_url,
            "commit_sha": "UNKNOWN",
            "file_count": 0,
            "total_bytes": 0,
            "read_only_isolated": False,
        }

    file_count = 0
    total_bytes = 0
    symlink_escaped = False
    for item in repo_path.rglob("*"):
        if ".git" in item.parts:
            continue
        if is_symlink_or_junction(item):
            symlink_escaped = True
            continue
        try:
            if not item.resolve().is_relative_to(repo_path.resolve()):
                symlink_escaped = True
                continue
        except OSError:
            symlink_escaped = True
            continue
        if item.is_symlink():
            try:
                if not item.resolve().is_relative_to(repo_path):
                    symlink_escaped = True
            except OSError:
                symlink_escaped = True
            continue
        if item.is_file():
            file_count += 1
            try:
                total_bytes += item.stat().st_size
            except OSError:
                pass

    return {
        "ok": not symlink_escaped,
        "name": repo_path.name,
        "path": str(repo_path),
        "origin_url": origin_url,
        "commit_sha": commit_sha,
        "file_count": file_count,
        "total_bytes": total_bytes,
        "read_only_isolated": not symlink_escaped,
    }


def register_library_entry(
    library_root: Path,
    folder_name: str,
    source_url: str,
    license_id: str,
    commit_sha: str,
    file_count: int,
    description: str = "",
) -> Path:
    """Idempotently register or update a benchmark/sample project row in `.work/library/README.md`."""
    root = Path(library_root)
    root.mkdir(parents=True, exist_ok=True)
    readme_path = root / "README.md"

    clean_folder = extract_repo_name(folder_name)
    source_cell = f"{source_url} ({description})" if description else source_url
    new_row = (
        f"| `{clean_folder}/` | {source_cell} | {license_id} | "
        f"{commit_sha} | {file_count} |"
    )

    header_block = (
        "# UAOS-RSI 참조·벤치마킹 자료실 (`.work/library`)\n\n"
        "> **전역 규칙(U250)**: 외부 공개 저장소 및 벤치마킹 샘플은 모두 본 폴더(`.work/library/<저장소명>`)에\n"
        "> 읽기 전용(Read-Only)으로 격리 보관하며, 내부에서 설치·빌드·스크립트 실행을 절대 금지합니다.\n\n"
        "| 폴더 | 원본 URL | 라이선스 | 커밋 SHA | 파일 수 |\n"
        "|---|---|---|---|---|\n"
    )

    if not readme_path.is_file():
        readme_path.write_text(header_block + new_row + "\n", encoding="utf-8")
        return readme_path

    lines = readme_path.read_text(encoding="utf-8").splitlines()
    marker = f"| `{clean_folder}/` |"
    updated = False
    out_lines: list[str] = []
    for line in lines:
        if line.strip().startswith(marker):
            out_lines.append(new_row)
            updated = True
        else:
            out_lines.append(line)

    if not updated:
        out_lines.append(new_row)

    readme_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return readme_path

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone


class LibraryStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def library_root(project_root: Path | str | None = None) -> Path:
    if project_root is None:
        return CANONICAL_LIBRARY_ROOT
    return (Path(project_root).resolve() / ".work" / "library").resolve()


def ensure_library_scaffold(project_root: Path | str | None = None) -> Path:
    """Ensure clean, non-duplicated scaffold under .work/library.
    Only three meta folders exist:
      - _analysis/ (active selected projects only)
      - _sessions/ (active selected projects only)
      - _excluded/ (unified single folder for all excluded repos & sessions)
    """
    lib_dir = library_root(project_root)
    for sub in ("_analysis", "_sessions", "_excluded"):
        (lib_dir / sub).mkdir(parents=True, exist_ok=True)
    (lib_dir / "_excluded" / "repos").mkdir(parents=True, exist_ok=True)
    (lib_dir / "_excluded" / "sessions").mkdir(parents=True, exist_ok=True)
    # Remove legacy duplicate folders if present
    for legacy in ("_excluded_sessions", "_tmp"):
        legacy_path = lib_dir / legacy
        if legacy_path.exists():
            shutil.rmtree(legacy_path, ignore_errors=True)
    return lib_dir


def _iter_repo_files(repo_dir: Path):
    for item in repo_dir.rglob("*"):
        if ".git" in item.parts:
            continue
        if is_symlink_or_junction(item):
            continue
        if item.is_file():
            yield item


# --- U314: Curated UAOS-RSI Library Selection & Unified Excluded Folder + Freshness Sync ---

KNOWN_LIBRARY_PROJECT_PROFILES: dict[str, dict[str, str]] = {
    "graphify": {
        "canonical_dir": "graphify",
        "upstream_repo": "Graphify-Labs/graphify",
        "category": "AST_KNOWLEDGE_GRAPH_TOKEN_SAVER",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "Tree-sitter AST 코드 지식그래프 압축기 (71.5배 토큰 절감)",
        "uaos_adoption_target": "v7_harness.coord.nonstop_orchestrator.build_zero_token_code_graph (신규 세션 16만 토큰 재탐색 차단, 갓노드 우선 라우팅, [EXTRACTED]/[INFERRED] 태깅)",
        "target_card": "U315",
        "source_video": "docs/동영상/261105-#Claude Code 토큰 새는 거, Graphify로막는 법/Graphify.mp4",
    },
    "ai-memory": {
        "canonical_dir": "ai-memory",
        "upstream_repo": "akitaonrails/ai-memory",
        "category": "CROSS_TOOL_HANDOFF_AND_MEMORY_DECAY",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "이종 코딩 AI 간 자동 HANDOFF 주입·망각(Memory Decay) 공유 메모리",
        "uaos_adoption_target": "v7_harness.coord.nonstop_orchestrator.generate_cross_tool_handoff (Codex↔Claude↔Antigravity 5시간 한도 전환 시 진행률·실패테스트·남은과제 자동 주입 및 180KB 망각 압축)",
        "target_card": "U316",
        "source_video": "docs/동영상/261105-#Claude Code 토큰 새는 거, Graphify로막는 법/AI 메모리.mp4",
    },
    "agent-desktop": {
        "canonical_dir": "agent-desktop",
        "upstream_repo": "vercel-labs/agent-desktop",
        "category": "OS_AX_TREE_AND_INPUT_LEASE_LOCK",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "OS 접근성 트리(@e1..@eN) 결정론적 검증 및 멀티에이전트 순차 Input Lease 락",
        "uaos_adoption_target": "v7_harness.coord.nonstop_orchestrator.acquire_sequential_input_lease (다중 병렬 세션 동시 가동 시 단일 쓰기/UI 액션 임대권 순서 제어 및 read->act->re-read 검증)",
        "target_card": "U317",
        "source_video": "docs/동영상/261102/dbf0bf0144e53241374cb369feeb1955.mp4",
    },
    "orca": {
        "canonical_dir": "orca",
        "upstream_repo": "stablyai/orca",
        "category": "MULTI_AGENT_WORKTREE_ORCHESTRATOR",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "멀티 코딩 에이전트(Claude·Codex·Gemini) 병렬 워크트리 터미널 오케스트레이터",
        "uaos_adoption_target": "uaos coord lanes / window (카드별 독립 git worktree + 5레인 병렬 세션 생명주기 관리)",
        "target_card": "U318",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "ruflo": {
        "canonical_dir": "ruflo",
        "upstream_repo": "ruvnet/ruflo",
        "category": "SWARM_ROUTER_AND_FAILOVER_ENGINE",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "멀티에이전트 스웜 작업 복잡도 라우터 및 장애 조치(Failover) 엔진",
        "uaos_adoption_target": "v7_harness.coord.helper_thinking_router (도우미·추론 모델 Thinking Level 자동 배정 및 쿼터 소진 시 즉각 Failover)",
        "target_card": "U318",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "ponytail": {
        "canonical_dir": "ponytail",
        "upstream_repo": "DietrichGebert/ponytail",
        "category": "SURGICAL_DIFF_CODE_DIET_BENCHMARK",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "AI 코드 비대화(-53%) 방지 1줄 외과수술식 패치(Surgical Fix) 규율 엔진",
        "uaos_adoption_target": "v7_harness.coord.nonstop_orchestrator.verify_surgical_diff_and_security (U198 20줄 슬라이스 규율 및 최소 변경 줄수 게이트)",
        "target_card": "U317",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "security-audit-skill": {
        "canonical_dir": "security-audit-skill",
        "upstream_repo": "cloudflare/security-audit-skill",
        "category": "SECURITY_AUDIT_GATE_SKILL",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "Cloudflare 보안·비밀키·인젝션 정적 감사 스킬",
        "uaos_adoption_target": "v7_harness.coord.nonstop_orchestrator.verify_surgical_diff_and_security (시크릿/권한 우회 탐지 룰셋)",
        "target_card": "U317",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "rea": {
        "canonical_dir": "rea",
        "upstream_repo": "morluto/rea",
        "category": "REASONING_EXECUTION_AGENT_ARCHITECTURE",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "추론·실행 분리형 에이전트 아키텍처 레퍼런스",
        "uaos_adoption_target": "UAOS 3대 도구 추론(Planning)↔실행(Ollama/Worker) 분리 계약 매뉴얼 고도화",
        "target_card": "U315",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "cockpit-tools": {
        "canonical_dir": "cockpit-tools",
        "upstream_repo": "cockpit-tools/cockpit-tools",
        "category": "QUOTA_HUD_AND_ACCOUNT_TELEMETRY",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "멀티 계정 쿼터 모니터링 및 콕핏 HUD 텔레메트리 레퍼런스",
        "uaos_adoption_target": "v7_harness.cockpit (3대 도구 5시간/주간 쿼터 실측 대시보드)",
        "target_card": "U316",
        "source_video": "existing_library",
    },
    "agentcodegui": {
        "canonical_dir": "AgentCodeGUI",
        "upstream_repo": "AgentCodeGUI/AgentCodeGUI",
        "category": "MULTI_AGENT_GUI_SESSION_MANAGER",
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "core_title_ko": "멀티 에이전트 GUI 세션 매니저 레퍼런스",
        "uaos_adoption_target": "uaos coord window (카드별 병렬 세션 GUI 상태 표시)",
        "target_card": "U318",
        "source_video": "existing_library",
    },
}

EXCLUDED_LIBRARY_PROJECT_PROFILES: dict[str, dict[str, str]] = {
    "impeccable": {
        "upstream_repo": "pbakaus/impeccable",
        "category": "FRONTEND_MARKETING_DESIGN_PACK",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "웹 마케팅 프론트엔드 타이포·컬러 디자인 스킬팩 (4,469파일)",
        "exclusion_reason_ko": "일반 웹 프론트엔드 디자인 가이드 번들로 UAOS-RSI 3대 도구 병렬 오케스트레이션·토큰 절감 OS 코어와 무관하며 4,469개 파일로 라이브러리 비대화 유발",
        "storage_mode": "QUARANTINED_IN_EXCLUDED_DIR",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "taste-skill": {
        "upstream_repo": "Leonxlnx/taste-skill",
        "category": "FRONTEND_AESTHETIC_PROMPT",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "일반 프론트엔드 웹 심미성 프롬프트 스킬",
        "exclusion_reason_ko": "UI 심미성 단일 프롬프트 팩으로 UAOS-RSI OS 오케스트레이션 로직과 무관하며 고정 컨텍스트(Fixed Context) 토큰만 증가시킴",
        "storage_mode": "QUARANTINED_IN_EXCLUDED_DIR",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "agent-reach": {
        "upstream_repo": "Panniantong/Agent-Reach",
        "category": "SOCIAL_MEDIA_SCRAPER_CLI",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "외부 소셜미디어(샤오홍슈·빌리빌리·웨이보·X) 스크래핑 CLI",
        "exclusion_reason_ko": "외부 SNS 플랫폼 크롤러로 UAOS-RSI 로컬 3대 도구 협업 OS의 목적과 무관하며 외부 계정/쿠키 의존 위험 존재",
        "storage_mode": "QUARANTINED_IN_EXCLUDED_DIR",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "openrig": {
        "upstream_repo": "openrig/openrig",
        "category": "EXTERNAL_HARDWARE_RIG_SAMPLE",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "외부 도메인 샘플 저장소 (openrig)",
        "exclusion_reason_ko": "UAOS-RSI 3대 도구 오케스트레이션·토큰 절감 아키텍처와 직접 관련 없는 외부 도메인 프로젝트로 논외 격리",
        "storage_mode": "QUARANTINED_IN_EXCLUDED_DIR",
        "source_video": "existing_library",
    },
    "voicestudio": {
        "upstream_repo": "debpalash/VoiceStudio",
        "category": "AUDIO_TTS_PRODUCTION_STUDIO",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "로컬 다국어 음성 합성·더빙 오디오 스튜디오",
        "exclusion_reason_ko": "오디오·음성 합성 미디어 제작 툴로 UAOS-RSI 에이전트 오케스트레이션 OS에 불필요하여 클론 제외 및 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "hyperframes": {
        "upstream_repo": "heygen-com/hyperframes",
        "category": "HTML_VIDEO_RENDERING_ENGINE",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "HTML 애니메이션 MP4 동영상 렌더링 엔진",
        "exclusion_reason_ko": "영상 렌더링 제작 도구로 UAOS-RSI 코어 오케스트레이션과 무관하여 클론 제외 및 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "comfyui": {
        "upstream_repo": "Comfy-Org/ComfyUI",
        "category": "DIFFUSION_IMAGE_VIDEO_GUI",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "노드 기반 이미지·비디오 생성형 AI 워크플로 GUI",
        "exclusion_reason_ko": "이미지·영상 디퓨전 생성 툴로 UAOS-RSI 코딩 에이전트 협업 OS와 무관하여 클론 제외 및 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "ghidra": {
        "upstream_repo": "NationalSecurityAgency/ghidra",
        "category": "BINARY_REVERSE_ENGINEERING_SUITE",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "NSA 바이너리 리버스 엔지니어링 디컴파일러",
        "exclusion_reason_ko": "대용량 바이너리 역공학 도구로 UAOS-RSI OS와 무관하여 클론 제외 및 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "freellmapi": {
        "upstream_repo": "tashfeenahmed/freellmapi",
        "category": "UNOFFICIAL_FREE_API_WRAPPER",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "비공식 무료 LLM API 티어 통합 래퍼",
        "exclusion_reason_ko": "UAOS-RSI Safety 규칙(공식 구독 로그인 및 승인된 API 캡 외 우회 금지)과 충돌하여 도입 배제 및 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "deepinfer": {
        "upstream_repo": "deepseek-ai/DeepInfer",
        "category": "HEAVY_GPU_LLM_SERVING_ENGINE",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "단일 GPU 초거대 모델 8비트 오프로딩 추론 엔진",
        "exclusion_reason_ko": "초거대 모델 서빙 엔진으로 UAOS 로컬 전자계산기(Ollama qwen2.5-coder:7b/14b) 운영 범위를 벗어나 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "ecc": {
        "upstream_repo": "affaan-m/ECC",
        "category": "BULK_UNCURATED_CLAUDE_PLUGINS",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "Claude Code 314개 범용 스킬·에이전트 대량 번들",
        "exclusion_reason_ko": "검증되지 않은 314개 스킬 일괄 로드는 고정 컨텍스트 토큰 누수(Token Bleed)의 주원인이므로 UAOS 토큰절약 원칙에 따라 배제",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/d1d15b00ac20660c3afaba63adb8d2a7.mp4",
    },
    "opencode": {
        "upstream_repo": "anomalyco/opencode",
        "category": "STANDALONE_TERMINAL_CODING_AGENT",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "독립형 오픈소스 터미널 코딩 에이전트",
        "exclusion_reason_ko": "이미 구축된 UAOS 3대 도구(Codex·Claude Code·Antigravity + Ollama) 체제와 역할이 중복되어 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "claude-plugins-official": {
        "upstream_repo": "anthropics/claude-plugins-official",
        "category": "EXTERNAL_SAAS_PLUGIN_DIRECTORY",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "Anthropic 공식 외부 SaaS 플러그인 디렉터리",
        "exclusion_reason_ko": "외부 상용 SaaS 연동 카탈로그로 로컬 결정론적 UAOS-RSI 코어 엔진 도입 대상이 아니므로 논외 세션 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
    "rea-prompts": {
        "upstream_repo": "JoaoASantos/REA-Prompts",
        "category": "STATIC_PROMPT_TEMPLATE_COLLECTION",
        "selection_status": "EXCLUDED_OUT_OF_SCOPE",
        "core_title_ko": "정적 프롬프트 템플릿 모음집",
        "exclusion_reason_ko": "단순 프롬프트 모음집으로 이미 도입 선별된 morluto/rea 및 UAOS 계약 매뉴얼(pilot manual new)로 대체 완료되어 논외 기록",
        "storage_mode": "NOT_DOWNLOADED_OUT_OF_SCOPE",
        "source_video": "docs/동영상/261102/cbc28180da605d54938f254372ef774d.mp4",
    },
}


def create_library_project_session(
    project_root: Path | str,
    repo_name: str,
    *,
    upstream_url: str = "",
    head_commit: str = "",
    freshness_digest: str = "",
) -> dict[str, Any]:
    """Create or update an isolated per-project library analysis session for a SELECTED UAOS-RSI repository."""
    root = Path(project_root).resolve()
    lib_dir = ensure_library_scaffold(root)
    slug_key = repo_name.lower()
    profile = KNOWN_LIBRARY_PROJECT_PROFILES.get(slug_key, {})
    canonical_dir = profile.get("canonical_dir", repo_name)
    repo_dir = (lib_dir / canonical_dir).resolve()
    session_id = f"libsess_{slug_key}_{hashlib.sha1(str(repo_dir).encode('utf-8')).hexdigest()[:10]}"

    sessions_dir = lib_dir / "_sessions" / canonical_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)
    coord_sessions_dir = root / ".coord" / "library_sessions"
    coord_sessions_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "schema": "uaos.library_project_session.v3",
        "session_id": session_id,
        "repo_name": canonical_dir,
        "repo_slug": slug_key,
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "upstream_repo": profile.get("upstream_repo", canonical_dir),
        "upstream_url": upstream_url or f"https://github.com/{profile.get('upstream_repo', canonical_dir)}",
        "head_commit": head_commit,
        "freshness_digest": freshness_digest,
        "category": profile.get("category", "SELECTED_REFERENCE_REPO"),
        "core_title_ko": profile.get("core_title_ko", f"{canonical_dir} 도입 선별 레퍼런스"),
        "uaos_adoption_target": profile.get("uaos_adoption_target", "UAOS-RSI 아키텍처 벤치마킹"),
        "target_card": profile.get("target_card", "U315"),
        "source_video": profile.get("source_video", "library"),
        "isolated_repo_path": str(repo_dir.relative_to(root)).replace("\\", "/") if repo_dir.exists() else "",
        "read_only_quarantine": True,
        "updated_at": _utc_now(),
    }
    _atomic_write_json(sessions_dir / "session.json", payload)
    _atomic_write_json(coord_sessions_dir / f"{slug_key}.json", payload)
    if canonical_dir != slug_key:
        # Also keep canonical filename alias if needed by tests, or remove duplicate if same on Windows case-insensitive FS
        pass
    return payload


def create_excluded_library_session(
    project_root: Path | str,
) -> dict[str, Any]:
    """Consolidate all excluded/out-of-scope projects into the single `.work/library/_excluded` folder and session."""
    root = Path(project_root).resolve()
    lib_dir = ensure_library_scaffold(root)
    excluded_dir = lib_dir / "_excluded"
    excluded_repos_dir = excluded_dir / "repos"
    excluded_sessions_dir = excluded_dir / "sessions"
    coord_excluded_dir = root / ".coord" / "library_excluded_sessions"
    coord_excluded_dir.mkdir(parents=True, exist_ok=True)

    # Migrate any top-level folders inside _excluded/<repo> into _excluded/repos/<lowercase_slug>
    for child in list(excluded_dir.iterdir()):
        if child.name in ("repos", "sessions", "session.json", "README.md"):
            continue
        if child.is_dir():
            dst = excluded_repos_dir / child.name.lower()
            if not dst.exists():
                shutil.move(str(child), str(dst))
            else:
                shutil.rmtree(child, ignore_errors=True)

    excluded_session_id = "libsess_excluded_out_of_scope_v1"
    excluded_entries: list[dict[str, Any]] = []

    for slug, prof in sorted(EXCLUDED_LIBRARY_PROJECT_PROFILES.items()):
        quarantined_path = ""
        cand_repo = excluded_repos_dir / slug.lower()
        if cand_repo.is_dir():
            quarantined_path = str(cand_repo.relative_to(root)).replace("\\", "/")
        item_session_id = f"libsess_excl_{slug}_{hashlib.sha1(slug.encode('utf-8')).hexdigest()[:8]}"
        entry = {
            "schema": "uaos.library_excluded_project.v2",
            "excluded_session_id": excluded_session_id,
            "item_session_id": item_session_id,
            "repo_slug": slug,
            "upstream_repo": prof["upstream_repo"],
            "category": prof["category"],
            "selection_status": "EXCLUDED_OUT_OF_SCOPE",
            "core_title_ko": prof["core_title_ko"],
            "exclusion_reason_ko": prof["exclusion_reason_ko"],
            "storage_mode": "QUARANTINED_IN_EXCLUDED_DIR" if quarantined_path else prof["storage_mode"],
            "quarantined_path": quarantined_path,
            "source_video": prof["source_video"],
            "excluded_from_active_library": True,
            "updated_at": _utc_now(),
        }
        excluded_entries.append(entry)
        _atomic_write_json(coord_excluded_dir / f"excluded_{slug}.json", entry)
        _atomic_write_json(excluded_sessions_dir / f"{slug}.json", entry)

    master_payload = {
        "schema": "uaos.library_excluded_session.v2",
        "excluded_session_id": excluded_session_id,
        "status": "EXCLUDED_OUT_OF_SCOPE",
        "unified_excluded_folder": ".work/library/_excluded",
        "purpose_ko": "UAOS-RSI OS 코어(3대 도구 병렬 오케스트레이션·토큰 절감·최상 품질 게이트)와 무관하거나 충돌하는 외부 깃허브 자료를 단일 폴더(.work/library/_excluded) 및 별도 논외 세션으로 통합 격리",
        "total_excluded_projects": len(excluded_entries),
        "quarantined_local_count": sum(1 for e in excluded_entries if e["quarantined_path"]),
        "not_downloaded_filtered_count": sum(1 for e in excluded_entries if not e["quarantined_path"]),
        "updated_at": _utc_now(),
        "excluded_projects": excluded_entries,
    }
    _atomic_write_json(excluded_dir / "session.json", master_payload)
    _atomic_write_json(coord_excluded_dir / "_excluded_out_of_scope_session.json", master_payload)
    return master_payload


def identify_library_project(project_root: Path | str, repo_name: str) -> dict[str, Any]:
    """Identify what independent project lives at .work/library/<repo_name> with freshness digest."""
    root = Path(project_root).resolve()
    lib_dir = ensure_library_scaffold(root)
    slug_key = repo_name.lower()

    if slug_key in EXCLUDED_LIBRARY_PROJECT_PROFILES:
        excl_prof = EXCLUDED_LIBRARY_PROJECT_PROFILES[slug_key]
        excl_path = lib_dir / "_excluded" / "repos" / slug_key
        return {
            "schema": "uaos.library_project_identity.v3",
            "repo_name": slug_key,
            "selection_status": "EXCLUDED_OUT_OF_SCOPE",
            "upstream_repo": excl_prof["upstream_repo"],
            "category": excl_prof["category"],
            "core_title_ko": excl_prof["core_title_ko"],
            "exclusion_reason_ko": excl_prof["exclusion_reason_ko"],
            "storage_mode": excl_prof["storage_mode"],
            "quarantined_path": str(excl_path.relative_to(root)).replace("\\", "/") if excl_path.exists() else "",
            "read_only": True,
            "inspected_at": _utc_now(),
        }

    profile = KNOWN_LIBRARY_PROJECT_PROFILES.get(slug_key, {})
    canonical_dir = profile.get("canonical_dir", repo_name)
    repo_dir = (lib_dir / canonical_dir).resolve()
    if not repo_dir.exists() or not repo_dir.is_dir():
        repo_dir = (lib_dir / repo_name).resolve()
    if not repo_dir.exists() or not repo_dir.is_dir():
        raise LibraryStoreError("LIBRARY_REPO_MISSING", f"repository folder not found: {repo_dir}")

    stacks: list[str] = []
    markers = {
        "pyproject.toml": "python",
        "setup.py": "python",
        "Cargo.toml": "rust",
        "package.json": "node/typescript",
        "go.mod": "go",
        "SKILL.md": "agent-skill",
        ".claude-plugin": "claude-plugin",
    }
    for marker, label in markers.items():
        if (repo_dir / marker).exists() and label not in stacks:
            stacks.append(label)

    ext_counts: dict[str, int] = {}
    total_files = 0
    total_bytes = 0
    latest_mtime_ns = 0
    for fpath in _iter_repo_files(repo_dir):
        total_files += 1
        try:
            st = fpath.stat()
            total_bytes += st.st_size
            if st.st_mtime_ns > latest_mtime_ns:
                latest_mtime_ns = st.st_mtime_ns
        except OSError:
            pass
        ext = fpath.suffix.lower() or "<no_ext>"
        ext_counts[ext] = ext_counts.get(ext, 0) + 1

    latest_mtime_utc = (
        datetime.fromtimestamp(latest_mtime_ns / 1e9, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if latest_mtime_ns > 0
        else _utc_now()
    )

    top_extensions = sorted(ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    if not stacks and top_extensions:
        stacks.append(f"ext:{top_extensions[0][0]}")

    readme_title = ""
    readme_summary = ""
    for rname in ("README.md", "README.ko.md", "SKILL.md"):
        rpath = repo_dir / rname
        if rpath.exists() and rpath.is_file():
            try:
                lines = [ln.strip() for ln in rpath.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
                for ln in lines:
                    if ln.startswith("#") and not readme_title:
                        readme_title = ln.lstrip("#").strip()[:120]
                    elif not ln.startswith("#") and not ln.startswith("![") and not ln.startswith("<") and not readme_summary:
                        readme_summary = ln[:240]
                    if readme_title and readme_summary:
                        break
            except OSError:
                pass
            if readme_title or readme_summary:
                break

    head_commit = ""
    upstream_url = ""
    git_dir = repo_dir / ".git"
    if git_dir.exists():
        sha, url, _ = _read_git_head_and_origin(git_dir)
        head_commit = sha if sha not in ("UNKNOWN", "INVALID_REF", "INVALID_SHA") else ""
        upstream_url = url

    freshness_raw = f"{canonical_dir}|{head_commit}|{total_files}|{total_bytes}|{latest_mtime_utc}"
    freshness_digest = hashlib.sha256(freshness_raw.encode("utf-8")).hexdigest()[:16]

    session_info = create_library_project_session(
        root,
        canonical_dir,
        upstream_url=upstream_url,
        head_commit=head_commit,
        freshness_digest=freshness_digest,
    )

    return {
        "schema": "uaos.library_project_identity.v3",
        "repo_name": canonical_dir,
        "repo_slug": slug_key,
        "session_id": session_info["session_id"],
        "selection_status": "SELECTED_FOR_UAOS_RSI",
        "upstream_repo": profile.get("upstream_repo", canonical_dir),
        "upstream_url": session_info["upstream_url"],
        "head_commit": head_commit,
        "freshness_digest": freshness_digest,
        "latest_mtime_utc": latest_mtime_utc,
        "category": profile.get("category", "SELECTED_REFERENCE_REPO"),
        "core_title_ko": profile.get("core_title_ko", readme_title or f"{canonical_dir} 오픈소스 프로젝트"),
        "uaos_adoption_target": profile.get("uaos_adoption_target", "UAOS-RSI 기능 벤치마킹"),
        "target_card": profile.get("target_card", "U315"),
        "source_video": profile.get("source_video", "library"),
        "detected_stacks": stacks,
        "total_files": total_files,
        "total_bytes": total_bytes,
        "top_extensions": [{"ext": k, "count": v} for k, v in top_extensions],
        "readme_title": readme_title,
        "readme_summary": readme_summary,
        "path": str(repo_dir.relative_to(root)).replace("\\", "/"),
        "session_file": f".coord/library_sessions/{slug_key}.json",
        "read_only": True,
        "inspected_at": _utc_now(),
    }


def build_library_catalog_index(project_root: Path | str) -> dict[str, Any]:
    """Deduplicate, clean stale artifacts, and synchronize .work/library catalog index based on latest freshness."""
    root = Path(project_root).resolve()
    lib_dir = ensure_library_scaffold(root)

    # 1. Relocate any excluded repo that might still be at top-level of .work/library into .work/library/_excluded/repos/
    for child in list(lib_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        if child.name.lower() in EXCLUDED_LIBRARY_PROJECT_PROFILES:
            dst = lib_dir / "_excluded" / "repos" / child.name.lower()
            if not dst.exists():
                shutil.move(str(child), str(dst))
            else:
                shutil.rmtree(child, ignore_errors=True)

    # 2. Scan active selected projects and compute freshness-based identity
    projects: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for child in sorted(lib_dir.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        slug = child.name.lower()
        if slug in seen_slugs or slug in EXCLUDED_LIBRARY_PROJECT_PROFILES:
            continue
        seen_slugs.add(slug)
        identity = identify_library_project(root, child.name)
        analysis_dir = lib_dir / "_analysis" / identity["repo_name"]
        analysis_dir.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(analysis_dir / "identity.json", identity)
        projects.append(identity)

    # 3. Purge any stale/excluded folders from _analysis and _sessions so zero duplicates remain
    valid_dir_names = {p["repo_name"].lower() for p in projects}
    for meta_sub in ("_analysis", "_sessions"):
        sub_path = lib_dir / meta_sub
        for item in list(sub_path.iterdir()):
            if item.is_dir() and item.name.lower() not in valid_dir_names:
                shutil.rmtree(item, ignore_errors=True)
            elif item.is_file():
                item.unlink(missing_ok=True)

    # 4. Build unified excluded session in .work/library/_excluded
    excluded_session = create_excluded_library_session(root)
    excluded_projects = excluded_session["excluded_projects"]

    catalog_digest = hashlib.sha256(
        json.dumps([p["freshness_digest"] for p in projects] + [e["repo_slug"] for e in excluded_projects]).encode("utf-8")
    ).hexdigest()[:16]

    catalog = {
        "schema": "uaos.library_catalog_index.v3",
        "updated_at": _utc_now(),
        "catalog_freshness_digest": catalog_digest,
        "library_root": ".work/library",
        "unified_excluded_root": ".work/library/_excluded",
        "deduplicated": True,
        "total_independent_projects": len(projects),
        "total_selected_projects": len(projects),
        "total_excluded_projects": len(excluded_projects),
        "excluded_session_id": excluded_session["excluded_session_id"],
        "excluded_session_file": ".work/library/_excluded/session.json",
        "coord_excluded_session_file": ".coord/library_excluded_sessions/_excluded_out_of_scope_session.json",
        "projects": projects,
        "selected_projects": projects,
        "excluded_projects": excluded_projects,
    }
    _atomic_write_json(lib_dir / "INDEX.json", catalog)
    coord_index = root / ".coord" / "library_index.json"
    coord_index.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(coord_index, catalog)

    lines = [
        "# Reference Library Index (`.work/library` — UAOS-RSI 선별 10종 및 단일 `_excluded` 통합 카탈로그)",
        "",
        f"- **동기화 시각(UTC)**: `{catalog['updated_at']}` | **카탈로그 최신성 해시(`catalog_freshness_digest`)**: `{catalog_digest}`",
        "- **폴더 구조 최적화 완료**:",
        "  - 활성 도입 프로젝트(`10종`): `.work/library/<repo>` (세션: `.work/library/_sessions/<repo>`, 분석: `.work/library/_analysis/<repo>`)",
        "  - 논외 제외 프로젝트(`14종`): 단일 폴더 `.work/library/_excluded/` (`repos/`, `sessions/`, `session.json`)로 완전 통합 및 중복 제거 완료",
        "",
        f"## 1. UAOS-RSI OS 도입 선별 독립 프로젝트 (`SELECTED_FOR_UAOS_RSI`: 총 {len(projects)}개)",
        "",
        "| Name | Target Card | Commit | Freshness Digest | Updated (UTC) | Files | 핵심 기능 및 UAOS-RSI OS 도입 로직 |",
        "|---|---|---|---|---|---:|---|",
    ]
    for p in projects:
        lines.append(
            f"| `{p['repo_name']}` | `{p['target_card']}` | `{p['head_commit'] or '-'}` | `{p['freshness_digest']}` | `{p['latest_mtime_utc']}` | {p['total_files']} | **{p['core_title_ko']}** → {p['uaos_adoption_target']} |"
        )

    lines.extend([
        "",
        f"## 2. UAOS-RSI OS 논외 제외 프로젝트 — 단일 `.work/library/_excluded` 통합 세션 (`EXCLUDED_OUT_OF_SCOPE`: 총 {len(excluded_projects)}개)",
        "",
        "| Slug | Item Session ID | Upstream | Storage Mode | Unified Path | 핵심 내용 및 UAOS-RSI OS 논외(제외) 사유 |",
        "|---|---|---|---|---|---|",
    ])
    for e in excluded_projects:
        upath = e["quarantined_path"] or ".work/library/_excluded/sessions/" + e["repo_slug"] + ".json"
        lines.append(
            f"| `{e['repo_slug']}` | `{e['item_session_id']}` | `{e['upstream_repo']}` | `{e['storage_mode']}` | `{upath}` | **{e['core_title_ko']}** — {e['exclusion_reason_ko']} |"
        )
    lines.append("")
    (lib_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    return catalog
