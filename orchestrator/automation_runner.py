#!/usr/bin/env python3
"""
automation_runner.py - the Orchestrator Runner of the Hybrid Operating Framework.

The Master Agent (a strong model) writes orchestrator/execution_plan.md. This script
reads it, and for each task:

  1. snapshots the task's target files,
  2. calls the `claude` CLI headless (`claude -p`, prompt on stdin) against a LOCAL
     model served by Ollama (the sub-agent), with a hard timeout,
  3. checks that only the task's target files changed (anything else is reverted),
  4. runs the task's test commands locally,
  5. on any failure restores the snapshot and retries with the failure fed back,
  6. records every step in checkpoint.json, so an interrupted run resumes where it stopped.

It never commits and never pushes. The Master reviews orchestrator/runs/report.md and
`git diff`, and decides.

Usage (from the repo root, Windows 11 PowerShell or any shell with Python 3.10+):

    python orchestrator/automation_runner.py --check          # preflight, no model call
    python orchestrator/automation_runner.py --dry-run        # parse and order the plan
    python orchestrator/automation_runner.py                  # run every pending task
    python orchestrator/automation_runner.py --only A1,A2     # run selected tasks
    python orchestrator/automation_runner.py --reset          # forget the checkpoint

Standard library only.
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parent

DEFAULT_TIMEOUT_S = 180           # per model call (one attempt)
DEFAULT_RETRIES = 2               # retries after the first failure -> up to 3 attempts
TEST_TIMEOUT_S = 900              # per test command
DEFAULT_MAX_TURNS = 40
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:31b-cloud")

# The sub-agent may read and edit, never run shell commands: the runner runs the tests.
# Adjust to your `claude --help` if your CLI version names these flags differently.
ALLOWED_TOOLS = "Read,Edit,Write,Grep,Glob"
DISALLOWED_TOOLS = "Bash,WebFetch,WebSearch,Agent,Task,NotebookEdit"

STATUS_DONE, STATUS_FAILED, STATUS_BLOCKED, STATUS_PENDING = "done", "failed", "blocked", "pending"


# --------------------------------------------------------------------------- plan model


@dataclass
class Task:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)
    test_commands: list[str] = field(default_factory=list)
    timeout_sec: int = DEFAULT_TIMEOUT_S
    max_retries: int = DEFAULT_RETRIES
    read_only: bool = False
    verify_only: bool = False
    context: str = ""
    prompt: str = ""
    body_hash: str = ""


class PlanError(Exception):
    pass


TASK_RE = re.compile(r"<!--\s*TASK_START:\s*([A-Za-z0-9_.-]+)\s*-->(.*?)<!--\s*TASK_END\s*-->", re.S)
FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def _split_sections(body: str) -> dict[str, list[str]]:
    """Split a task body on `## Heading` lines, ignoring headings inside code fences."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    fence: str | None = None
    for line in body.splitlines():
        if fence is None:
            m = FENCE_OPEN_RE.match(line)
            if m:
                fence = m.group(1)
            elif line.startswith("## "):
                current = line[3:].strip().lower()
                sections.setdefault(current, [])
                continue
        else:
            stripped = line.strip()
            if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
                fence = None
        if current is not None:
            sections[current].append(line)
    return sections


def _first_fenced_block(lines: list[str]) -> str | None:
    fence: str | None = None
    out: list[str] = []
    for line in lines:
        if fence is None:
            m = FENCE_OPEN_RE.match(line)
            if m:
                fence = m.group(1)
            continue
        stripped = line.strip()
        if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            return "\n".join(out)
        out.append(line)
    return None


def _parse_meta(lines: list[str]) -> dict[str, Any]:
    """A tiny YAML subset: `key: value`, `key: [a, b]`, and `key:` followed by `- item` lines."""
    meta: dict[str, Any] = {}
    key: str | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        # An INDENTED `- item` belongs to the list opened by the last `key:` line.
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key is not None and isinstance(meta.get(key), list):
            meta[key].append(item.group(1).strip().strip("`"))
            continue
        # A key line, written either `key: value` or as a top-level bullet `- key: value`.
        kv = re.match(r"^(?:-\s+)?([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
        if not kv:
            continue
        key, value = kv.group(1), kv.group(2).strip()
        if value == "":
            meta[key] = []
        elif value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip().strip("`'\"") for v in value[1:-1].split(",") if v.strip()]
        elif value.lower() in ("none", "null", "-"):
            meta[key] = []
        else:
            meta[key] = value.strip("`")
    return meta


def parse_plan(text: str) -> list[Task]:
    tasks: list[Task] = []
    seen: set[str] = set()
    for m in TASK_RE.finditer(text):
        task_id, body = m.group(1), m.group(2)
        if task_id in seen:
            raise PlanError(f"duplicate task id {task_id}")
        seen.add(task_id)
        sections = _split_sections(body)
        meta = _parse_meta(sections.get("meta", []))
        prompt = _first_fenced_block(sections.get("prompt", []))
        if prompt is None:
            prompt = "\n".join(sections.get("prompt", [])).strip()
        read_only = str(meta.get("read_only", "false")).lower() == "true"
        verify_only = str(meta.get("verify_only", "false")).lower() == "true"
        task = Task(
            id=task_id,
            title=str(meta.get("title", task_id)),
            depends_on=list(meta.get("depends_on", [])),
            target_files=[p.replace("\\", "/") for p in meta.get("target_files", [])],
            test_commands=list(meta.get("test_commands", [])),
            timeout_sec=int(meta.get("timeout_sec", DEFAULT_TIMEOUT_S)),
            max_retries=int(meta.get("max_retries", DEFAULT_RETRIES)),
            read_only=read_only,
            verify_only=verify_only,
            context="\n".join(sections.get("context", [])).strip(),
            prompt=prompt.strip(),
            body_hash=hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
        )
        tasks.append(task)
    if not tasks:
        raise PlanError("no tasks found: expected TASK_START / TASK_END comment pairs")
    _validate(tasks)
    return tasks


def _validate(tasks: list[Task]) -> None:
    ids = {t.id for t in tasks}
    for t in tasks:
        if not t.prompt and not t.verify_only:
            raise PlanError(f"{t.id}: empty Prompt section")
        if not t.read_only and not t.verify_only and not t.target_files:
            raise PlanError(f"{t.id}: target_files is required (or set read_only: true)")
        if not t.read_only and not t.test_commands:
            raise PlanError(f"{t.id}: test_commands is required (or set read_only: true)")
        for d in t.depends_on:
            if d not in ids:
                raise PlanError(f"{t.id}: depends_on unknown task {d}")
    order = {t.id: i for i, t in enumerate(tasks)}
    for t in tasks:
        for d in t.depends_on:
            if order[d] >= order[t.id]:
                raise PlanError(f"{t.id}: depends_on {d}, which is not listed before it")


# ------------------------------------------------------------------------- checkpoint


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Checkpoint:
    def __init__(self, path: Path, plan_file: str):
        self.path = path
        self.data: dict[str, Any] = {"version": 1, "plan_file": plan_file, "updated_at": None, "tasks": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("tasks"), dict):
                    self.data = loaded
            except (OSError, ValueError):
                # An unreadable checkpoint is kept aside, never silently overwritten.
                shutil.copy2(path, path.with_suffix(".corrupt.json"))

    def get(self, task_id: str) -> dict[str, Any]:
        return self.data["tasks"].get(task_id, {})

    def update(self, task_id: str, **fields: Any) -> None:
        self.data["tasks"].setdefault(task_id, {}).update(fields)
        self.save()

    def reset(self) -> None:
        self.data["tasks"] = {}
        self.save()

    def save(self) -> None:
        self.data["updated_at"] = utc_now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)  # atomic: a crash never leaves half a checkpoint


# ----------------------------------------------------------------------------- git/files


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()
    except OSError:
        return None


def git_state(repo: Path, ignore: list[str]) -> dict[str, str | None]:
    """{relative posix path: content digest} for every path git reports as changed or new."""
    proc = run_git(repo, "status", "--porcelain", "-z", "-uall")
    if proc.returncode != 0:
        raise RuntimeError(f"git status failed: {proc.stderr.strip()}")
    entries = proc.stdout.split("\0")
    state: dict[str, str | None] = {}
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        if code[0] in "RC":
            i += 1  # the rename/copy source follows as its own entry
        rel = rel.replace("\\", "/")
        if any(rel == g or fnmatch.fnmatch(rel, g) or rel.startswith(g.rstrip("/") + "/") for g in ignore):
            continue
        state[rel] = file_digest(repo / rel)
    return state


def is_tracked(repo: Path, rel: str) -> bool:
    return run_git(repo, "ls-files", "--error-unmatch", "--", rel).returncode == 0


def in_scope(rel: str, targets: list[str]) -> bool:
    p = PurePosixPath(rel)
    return any(rel == t or p.match(t) or fnmatch.fnmatch(rel, t) for t in targets)


def snapshot(repo: Path, targets: list[str]) -> dict[str, bytes | None]:
    snap: dict[str, bytes | None] = {}
    for t in targets:
        if any(ch in t for ch in "*?["):
            continue  # a glob target cannot be snapshotted file by file
        path = repo / t
        snap[t] = path.read_bytes() if path.is_file() else None
    return snap


def restore(repo: Path, snap: dict[str, bytes | None]) -> None:
    for rel, content in snap.items():
        path = repo / rel
        if content is None:
            if path.is_file():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def write_diff(repo: Path, snap: dict[str, bytes | None], path: Path) -> None:
    """Unified diff of each target file against the task's snapshot, written to `path`.

    The Master reviews from this file and runs no git: it must cover untracked files and keep what
    a failed attempt wrote, because the runner restores the files right after.
    """
    chunks: list[str] = []
    for rel, old in snap.items():
        current = repo / rel
        new = current.read_bytes() if current.is_file() else None
        if new == old:
            continue
        a = (old or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        b = (new or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}"))
    path.write_text("".join(chunks), encoding="utf-8", newline="")


def enforce_scope(repo: Path, before: dict[str, str | None], after: dict[str, str | None],
                  targets: list[str], revert: bool) -> list[str]:
    """Return paths the sub-agent changed outside its targets. Revert them when allowed."""
    violations = [
        rel for rel, digest in after.items()
        if (rel not in before or before[rel] != digest) and not in_scope(rel, targets)
    ]
    if revert:
        for rel in violations:
            if rel in before:
                continue  # was already dirty before the task: cannot restore it safely
            if is_tracked(repo, rel):
                run_git(repo, "checkout", "--", rel)
            else:
                try:
                    (repo / rel).unlink()
                except OSError:
                    pass
    return violations


# ------------------------------------------------------------------------ sub-agent call


def find_claude() -> str | None:
    env = os.environ.get("CLAUDE_BIN")
    if env and Path(env).exists():
        return env
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(fallback) if fallback.exists() else None


def sub_agent_env(model: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "ANTHROPIC_BASE_URL": OLLAMA_URL,
        "ANTHROPIC_AUTH_TOKEN": "ollama",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "FLOORLINE_ROLE": "subagent",
    })
    return env


def claude_command(claude_bin: str, max_turns: int) -> list[str]:
    cmd = [
        claude_bin, "-p", "--output-format", "text",
        "--permission-mode", "acceptEdits",
        "--allowedTools", ALLOWED_TOOLS,
        "--disallowedTools", DISALLOWED_TOOLS,
        "--max-turns", str(max_turns),
        # The Master's skills must not reach the local model: they cost tokens and invite it to act as the Master.
        "--disable-slash-commands",
    ]
    extra = os.environ.get("CLAUDE_EXTRA_ARGS", "")
    return cmd + (shlex.split(extra) if extra else [])


def kill_tree(proc: subprocess.Popen[str]) -> None:
    """Kill the process and its children (claude spawns helpers; plain kill() leaves them)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        proc.kill()


def run_with_timeout(cmd: list[str], stdin_text: str, cwd: Path, env: dict[str, str],
                     timeout: int) -> tuple[int | None, str, str, bool]:
    kwargs: dict[str, Any] = dict(
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
    )
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
        return proc.returncode, out, err, False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        return None, out or "", err or "", True


def build_prompt(task: Task, feedback: str | None, attempt: int, total: int) -> str:
    scope = "none (read-only task: change nothing)" if task.read_only else ", ".join(task.target_files)
    head = (
        f"ROLE: SUB-AGENT (implementer), invoked by automation_runner.py. Task {task.id}: {task.title}.\n"
        "You are NOT the Master Agent: ignore the Master-only rules in CLAUDE.md and follow its "
        "SUB-AGENT rules.\n"
        f"You may change ONLY: {scope}. You cannot run shell commands: the runner runs the tests "
        "after you finish.\n"
        "When done, reply with at most 10 lines: the files you changed and one line per change.\n"
    )
    parts = [head]
    if task.context:
        parts.append("CONTEXT\n" + task.context + "\n")
    parts.append("TASK\n" + task.prompt)
    if feedback:
        parts.append(
            f"\n---\nYOUR PREVIOUS ATTEMPT FAILED (attempt {attempt - 1} of {total}). "
            "The files were restored to their original state. Reason and output:\n"
            f"{feedback}\n"
            "Fix only the cause of this failure. Do not change anything outside the allowed files."
        )
    return "\n".join(parts)


# ------------------------------------------------------------------------------- tests


def run_tests(commands: list[str], repo: Path) -> tuple[bool, str]:
    log: list[str] = []
    for raw in commands:
        cwd, cmd = repo, raw
        m = re.match(r"^\[([^\]]+)\]\s+(.*)$", raw)  # "[frontend] npm test" runs in repo/frontend
        if m:
            cwd, cmd = repo / m.group(1), m.group(2)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=cwd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=TEST_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            log.append(f"$ {raw}\nTIMEOUT after {TEST_TIMEOUT_S}s")
            return False, "\n".join(log)
        output = (proc.stdout or "") + (proc.stderr or "")
        log.append(f"$ {raw}\nexit code {proc.returncode}\n{output}")
        if proc.returncode != 0:
            return False, "\n".join(log)
    return True, "\n".join(log)


def tail(text: str, lines: int = 40, chars: int = 3500) -> str:
    out = "\n".join(text.strip().splitlines()[-lines:])
    return out[-chars:]


# ----------------------------------------------------------------------------- one task


@dataclass
class Options:
    repo: Path
    model: str
    claude_bin: str
    max_turns: int
    no_tests: bool
    no_revert: bool
    keep_failed: bool
    timeout_override: int | None
    runs_dir: Path


def run_verify_task(task: Task, opts: Options, cp: Checkpoint) -> bool:
    """
    A task with no model call: its test_commands run once and their output is the result.

    Used to check or measure what already exists. A failing command is a finding to read,
    not something to retry, so there is one attempt and nothing is restored.
    """
    run_dir = opts.runs_dir / task.id
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cp.update(task.id, status="running", prompt_hash=task.body_hash, started_at=utc_now(),
              attempts=0, last_error=None, title=task.title)
    print(f"[{task.id}] verify-only: running {len(task.test_commands)} command(s) ...", flush=True)
    ok, test_log = run_tests(task.test_commands, opts.repo)
    took = time.monotonic() - started
    (run_dir / "attempt_1.log").write_text(
        f"task: {task.id}  verify-only  duration: {took:.1f}s\n\n"
        f"=== TESTS ===\n{test_log}\n\n=== RESULT ===\n{'OK' if ok else 'TESTS FAILED'}\n",
        encoding="utf-8",
    )
    error = None if ok else "TESTS FAILED:\n" + tail(test_log)
    cp.update(task.id, attempts=1, last_error=error, last_attempt_at=utc_now(),
              status=STATUS_DONE if ok else STATUS_FAILED, finished_at=utc_now(), files_changed=[],
              duration_s=round(took, 1), tests="passed" if ok else "failed")
    print(f"[{task.id}] verify-only: {'OK' if ok else 'FAILED - ' + error.splitlines()[0]}", flush=True)
    return ok


def run_task(task: Task, opts: Options, cp: Checkpoint) -> bool:

    total = task.max_retries + 1
    timeout = opts.timeout_override or task.timeout_sec
    run_dir = opts.runs_dir / task.id
    run_dir.mkdir(parents=True, exist_ok=True)
    ignore = [str(opts.runs_dir.relative_to(opts.repo)).replace("\\", "/"), "orchestrator/checkpoint*"]
    snap = snapshot(opts.repo, task.target_files)
    cp.update(task.id, status="running", prompt_hash=task.body_hash, started_at=utc_now(),
              attempts=0, last_error=None, title=task.title)
    feedback: str | None = None
    started = time.monotonic()

    for attempt in range(1, total + 1):
        label = f"[{task.id}] attempt {attempt}/{total}"
        before = git_state(opts.repo, ignore)
        prompt = build_prompt(task, feedback, attempt, total)
        print(f"{label}: calling sub-agent ({opts.model}, timeout {timeout}s) ...", flush=True)
        t0 = time.monotonic()
        code, out, err, timed_out = run_with_timeout(
            claude_command(opts.claude_bin, opts.max_turns), prompt, opts.repo,
            sub_agent_env(opts.model), timeout,
        )
        took = time.monotonic() - t0
        after = git_state(opts.repo, ignore)

        error: str | None = None
        if timed_out:
            error = f"TIMEOUT: the sub-agent did not finish within {timeout}s and was killed."
        elif code != 0:
            error = f"the claude CLI exited with code {code}.\n{tail(err or out)}"

        violations = enforce_scope(opts.repo, before, after, task.target_files, not opts.no_revert)
        if violations and error is None:
            error = ("SCOPE VIOLATION: you changed files outside the allowed list: "
                     + ", ".join(violations) + (" (reverted)" if not opts.no_revert else ""))

        changed = [r for r, d in after.items() if (r not in before or before[r] != d) and in_scope(r, task.target_files)]
        if error is None and task.read_only and any(r not in before or before[r] != d for r, d in after.items()):
            error = "READ-ONLY task, but files were changed."
        if error is None and not task.read_only and not changed:
            error = "NO CHANGE: none of the target files was modified."

        test_log = ""
        if error is None and not task.read_only and not opts.no_tests:
            ok, test_log = run_tests(task.test_commands, opts.repo)
            if not ok:
                error = "TESTS FAILED:\n" + tail(test_log)

        (run_dir / f"attempt_{attempt}.log").write_text(
            f"task: {task.id}  attempt: {attempt}/{total}  duration: {took:.1f}s  exit: {code}  "
            f"timed_out: {timed_out}\n\n=== PROMPT ===\n{prompt}\n\n=== STDOUT ===\n{out}\n\n"
            f"=== STDERR ===\n{err}\n\n=== SCOPE ===\nchanged: {changed}\nviolations: {violations}\n\n"
            f"=== TESTS ===\n{test_log}\n\n=== RESULT ===\n{error or 'OK'}\n",
            encoding="utf-8",
        )
        write_diff(opts.repo, snap, run_dir / f"attempt_{attempt}.diff")
        cp.update(task.id, attempts=attempt, last_error=error, last_attempt_at=utc_now())

        if error is None:
            if task.read_only:
                (run_dir / "answer.md").write_text(out, encoding="utf-8")
            cp.update(task.id, status=STATUS_DONE, finished_at=utc_now(), files_changed=changed,
                      duration_s=round(time.monotonic() - started, 1),
                      tests="skipped" if (opts.no_tests or task.read_only) else "passed")
            print(f"{label}: OK ({', '.join(changed) or 'read-only'})", flush=True)
            return True

        print(f"{label}: FAILED - {error.splitlines()[0]}", flush=True)
        feedback = error
        if not opts.keep_failed:
            restore(opts.repo, snap)

    cp.update(task.id, status=STATUS_FAILED, finished_at=utc_now(),
              duration_s=round(time.monotonic() - started, 1))
    return False


# --------------------------------------------------------------------------------- main


def preflight(opts_repo: Path, claude_bin: str | None, model: str) -> int:
    ok = True
    print(f"repo:        {opts_repo}")
    print(f"claude CLI:  {claude_bin or 'NOT FOUND (set CLAUDE_BIN or add ~/.local/bin to PATH)'}")
    if claude_bin:
        try:
            v = subprocess.run([claude_bin, "--version"], capture_output=True, text=True, timeout=30)
            print(f"  version:   {(v.stdout or v.stderr).strip()}")
        except Exception as exc:  # noqa: BLE001
            print(f"  version check failed: {exc}")
            ok = False
    else:
        ok = False
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as resp:
            names = [m.get("name") for m in json.load(resp).get("models", [])]
        print(f"ollama:      reachable at {OLLAMA_URL}; local models: {', '.join(names) or 'none'}")
        if model not in names and not model.endswith("-cloud"):
            print(f"  WARNING: model {model} is not pulled (ollama pull {model})")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"ollama:      NOT reachable at {OLLAMA_URL} ({exc})")
        ok = False
    print(f"model:       {model}")
    git = run_git(opts_repo, "status", "--porcelain")
    if git.returncode != 0:
        print("git:         not a git repository")
        ok = False
    else:
        dirty = [line for line in git.stdout.splitlines() if line.strip()]
        print(f"git:         {len(dirty)} changed path(s) before the run (they are protected from scope reverts)")
    return 0 if ok else 2


def write_report(tasks: list[Task], cp: Checkpoint, runs_dir: Path) -> Path:
    lines = ["# Runner report", "", f"Generated {utc_now()}", "",
             "| Task | Status | Attempts | Tests | Files changed | Last error |", "|---|---|---|---|---|---|"]
    for t in tasks:
        s = cp.get(t.id)
        err = (s.get("last_error") or "").splitlines()
        lines.append("| {} | {} | {} | {} | {} | {} |".format(
            t.id, s.get("status", STATUS_PENDING), s.get("attempts", 0), s.get("tests", "-"),
            ", ".join(s.get("files_changed", [])) or "-", (err[0][:90] if err else "-")))
    lines += ["", "Logs per attempt: `orchestrator/runs/<TASK>/attempt_N.log`. Next: review `git diff`."]
    path = runs_dir / "report.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Run execution_plan.md tasks through a local sub-agent.")
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--plan", type=Path, default=None)
    ap.add_argument("--checkpoint", type=Path, default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--timeout", type=int, default=None, help=f"seconds per model call (default {DEFAULT_TIMEOUT_S})")
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    ap.add_argument("--only", default="", help="comma-separated task ids")
    ap.add_argument("--check", action="store_true", help="preflight only")
    ap.add_argument("--dry-run", action="store_true", help="parse and list the plan, call nothing")
    ap.add_argument("--reset", action="store_true", help="forget the checkpoint, then run")
    ap.add_argument("--retry-failed", action="store_true", help="also rerun tasks marked failed")
    ap.add_argument("--no-tests", action="store_true")
    ap.add_argument("--no-revert", action="store_true", help="report scope violations, do not revert them")
    ap.add_argument("--keep-failed", action="store_true", help="keep a failed attempt's edits for inspection")
    args = ap.parse_args(argv)

    repo = args.repo.resolve()
    orch = repo / "orchestrator"
    plan_path = args.plan or orch / "execution_plan.md"
    cp_path = args.checkpoint or orch / "checkpoint.json"
    runs_dir = orch / "runs"
    claude_bin = find_claude()

    if args.check:
        return preflight(repo, claude_bin, args.model)

    try:
        tasks = parse_plan(plan_path.read_text(encoding="utf-8"))
    except (OSError, PlanError) as exc:
        print(f"PLAN ERROR: {exc}", file=sys.stderr)
        return 2

    only = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = only - {t.id for t in tasks}
    if unknown:
        print(f"unknown task id(s): {', '.join(sorted(unknown))}", file=sys.stderr)
        return 2

    if args.dry_run:
        for t in tasks:
            print(f"{t.id:6} {t.title}\n       deps={t.depends_on or '-'} targets={t.target_files or '(read-only)'} "
                  f"timeout={t.timeout_sec}s retries={t.max_retries} prompt={len(t.prompt)} chars")
        return 0

    if claude_bin is None and not all(t.verify_only for t in tasks):
        print("claude CLI not found. Run with --check. Set CLAUDE_BIN or add ~/.local/bin to PATH.", file=sys.stderr)
        return 2
    runs_dir.mkdir(parents=True, exist_ok=True)
    cp = Checkpoint(cp_path, str(plan_path.name))
    if args.reset:
        cp.reset()

    opts = Options(repo, args.model, claude_bin, args.max_turns, args.no_tests, args.no_revert,
                   args.keep_failed, args.timeout, runs_dir)
    exit_code = 0
    for task in tasks:
        if only and task.id not in only:
            continue
        state = cp.get(task.id)
        if state.get("status") == STATUS_DONE and state.get("prompt_hash") == task.body_hash and not task.verify_only:
            print(f"[{task.id}] already done (checkpoint), skipping")
            continue
        if state.get("status") == STATUS_FAILED and state.get("prompt_hash") == task.body_hash \
                and not args.retry_failed:
            print(f"[{task.id}] failed earlier and the task is unchanged; use --retry-failed to rerun")
            exit_code = 1
            continue
        waiting = [d for d in task.depends_on if cp.get(d).get("status") != STATUS_DONE]
        if waiting:
            cp.update(task.id, status=STATUS_BLOCKED, last_error=f"waiting for {', '.join(waiting)}")
            print(f"[{task.id}] blocked: depends on {', '.join(waiting)}")
            exit_code = 1
            continue
        run_one = run_verify_task if task.verify_only else run_task
        if not run_one(task, opts, cp):
            exit_code = 1

    report = write_report(tasks, cp, runs_dir)
    print(f"\nreport: {report}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
