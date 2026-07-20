"""Publish the links-only cloud data straight to the GitHub Pages site.

The cloud organizer (web/index.html, deployed on the `gh-pages` branch) reads a
`data.json` next to it on load. This module writes that file — plus a refreshed
copy of the page itself — onto `gh-pages` and pushes it, so every device (Mac,
phone, anything) shows the latest with no file to shuttle around.

Everything happens in an isolated `git worktree`, so the user's current branch
and working tree are never touched. Uses the machine's own git push auth (the
same GitHub account the repo was cloned with) — no tokens, no server.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import db, repo

_TIMEOUT = 120


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, timeout=_TIMEOUT
    )


def _repo_root() -> Path:
    """Locate the code repo (where .git lives) — distinct from the data dir."""
    here = Path(__file__).resolve()
    r = _run(["git", "rev-parse", "--show-toplevel"], here.parent)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    raise RuntimeError("could not locate the git repository for this checkout")


def publish_to_web() -> dict:
    """Push the current cloud backup to gh-pages. Returns a small status dict."""
    root = _repo_root()
    with db.get_conn() as conn:
        payload = repo.cloud_backup(conn)
    count = len(payload.get("reels", {}))
    data_json = json.dumps(payload, indent=2)

    worktree = Path(tempfile.mkdtemp(prefix="reeler-ghp-"))
    try:
        _run(["git", "fetch", "origin", "gh-pages"], root)
        add = _run(
            ["git", "worktree", "add", "--force", str(worktree), "gh-pages"], root
        )
        if add.returncode != 0:
            # No local gh-pages branch yet — base it on the remote.
            add = _run(
                ["git", "worktree", "add", "--force", "-B", "gh-pages",
                 str(worktree), "origin/gh-pages"],
                root,
            )
            if add.returncode != 0:
                return {"ok": False,
                        "error": f"could not check out gh-pages: {add.stderr.strip()[:300]}"}

        (worktree / "data.json").write_text(data_json, encoding="utf-8")
        # Refresh the page too, so a first publish also ships the auto-load code.
        src_index = root / "web" / "index.html"
        if src_index.exists():
            shutil.copyfile(src_index, worktree / "index.html")

        _run(["git", "add", "-A"], worktree)
        status = _run(["git", "status", "--porcelain"], worktree)
        if not status.stdout.strip():
            return {"ok": True, "pushed": False, "count": count,
                    "note": "site already up to date"}

        commit = _run(
            ["git", "-c", "user.email=reeler@local", "-c", "user.name=Reeler",
             "commit", "-m", "Update cloud data"],
            worktree,
        )
        if commit.returncode != 0:
            return {"ok": False,
                    "error": f"commit failed: {commit.stderr.strip()[:300]}"}

        push = _run(["git", "push", "origin", "gh-pages"], worktree)
        if push.returncode != 0:
            return {"ok": False, "pushed": False,
                    "error": ("push failed — you may need to sign in to GitHub on "
                              f"this PC once: {push.stderr.strip()[:300]}")}
        return {"ok": True, "pushed": True, "count": count}
    finally:
        _run(["git", "worktree", "remove", "--force", str(worktree)], root)
        shutil.rmtree(worktree, ignore_errors=True)
