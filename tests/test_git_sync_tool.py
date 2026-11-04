"""Seam for git.sync: rebase onto a remote branch, or abort on conflict."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "tools/git/sync"


def _identity() -> dict[str, str]:
    return {
        "GIT_AUTHOR_NAME": "Ada",
        "GIT_AUTHOR_EMAIL": "ada@example.com",
        "GIT_COMMITTER_NAME": "Ada",
        "GIT_COMMITTER_EMAIL": "ada@example.com",
    }


def _run(env: dict, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    for key in list(merged):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            merged.pop(key, None)
    merged.update(_identity())
    merged.update(env)
    merged.setdefault("TK_DRY_RUN", "0")
    return subprocess.run(
        [sys.executable, str(SYNC)],
        capture_output=True,
        text=True,
        env=merged,
        cwd=str(cwd) if cwd is not None else None,
    )


def _split_and(fix: str) -> list[list[str]]:
    commands: list[list[str]] = [[]]
    for token in shlex.split(fix):
        if token == "&&":
            if not commands[-1]:
                raise AssertionError(f"empty command in {fix}")
            commands.append([])
            continue
        commands[-1].append(token)
    if not commands[-1]:
        raise AssertionError(f"trailing && in {fix}")
    return commands


def _shell_env(
    cwd: Path,
    extra: dict[str, str] | None = None,
    *,
    identity: bool = True,
) -> dict[str, str]:
    """Minimal env. Nothing is inherited, so no editor variable can leak in."""
    env = {
        "PATH": str(ROOT) + os.pathsep + os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", str(cwd)),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "TERM": "dumb",
        "GIT_TERMINAL_PROMPT": "0",
        "TK_NO_TELEMETRY": "1",
        "TK_STATE_DIR": str(cwd / "tk-state"),
    }
    if identity:
        env.update(_identity())
    if extra:
        env.update(extra)
    return env


def _run_shell(
    fix: str,
    cwd: Path,
    extra: dict[str, str] | None = None,
    *,
    identity: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "-c", fix],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=_shell_env(cwd, extra, identity=identity),
        stdin=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


def _error_name(proc: subprocess.CompletedProcess[str]) -> str:
    if proc.returncode == 0:
        return ""
    return str(json.loads(proc.stderr)["error"])


def _last_json(proc: subprocess.CompletedProcess[str]) -> dict:
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def _run_fix(fix: str, cwd: Path) -> list[subprocess.CompletedProcess[str]]:
    env = os.environ.copy()
    env.update(_identity())
    env["TK_NO_TELEMETRY"] = "1"
    env["TK_STATE_DIR"] = str(cwd.parent / "tk-state")
    env["PATH"] = str(ROOT) + os.pathsep + env.get("PATH", "")
    for key in list(env):
        if key.startswith("TK_ARG_") or key == "TK_DRY_RUN":
            env.pop(key, None)
    results: list[subprocess.CompletedProcess[str]] = []
    for argv in _split_and(fix):
        results.append(
            subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        )
        if results[-1].returncode != 0:
            break
    return results


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(_identity())
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _ok(repo: Path, *args: str) -> None:
    proc = _git(repo, *args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def _pair(tmp: Path) -> tuple[Path, Path, Path]:
    origin = tmp / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(origin)],
        check=True,
        capture_output=True,
        text=True,
    )
    clone_a = tmp / "clone_a"
    _ok(tmp, "init", "-b", "main", str(clone_a))
    _ok(clone_a, "config", "user.name", "Ada")
    _ok(clone_a, "config", "user.email", "ada@example.com")
    (clone_a / "shared.txt").write_text("base\n", encoding="utf-8")
    (clone_a / "local.txt").write_text("keep\n", encoding="utf-8")
    _ok(clone_a, "add", "shared.txt", "local.txt")
    _ok(clone_a, "commit", "-m", "base")
    _ok(clone_a, "remote", "add", "origin", str(origin))
    _ok(clone_a, "push", "-u", "origin", "main")
    clone_b = tmp / "clone_b"
    subprocess.run(
        ["git", "clone", str(origin), str(clone_b)],
        check=True,
        capture_output=True,
        text=True,
    )
    _ok(clone_b, "config", "user.name", "Ada")
    _ok(clone_b, "config", "user.email", "ada@example.com")
    return origin, clone_a, clone_b


class GitSyncTests(unittest.TestCase):
    def test_rebases_and_keeps_unstaged_dirty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, clone_a, clone_b = _pair(Path(tmp))
            (clone_a / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(clone_a, "add", "shared.txt")
            _ok(clone_a, "commit", "-m", "ahead on a")
            _ok(clone_a, "push", "origin", "main")
            _ok(clone_b, "checkout", "-b", "feature")
            dirty = clone_b / "local.txt"
            dirty.write_text("keep\ndirty\n", encoding="utf-8")
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone_b),
                    "TK_ARG_REMOTE": "origin",
                    "TK_ARG_BRANCH": "main",
                }
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["status"], "rebased")
            self.assertIs(payload["rebased"], True)
            self.assertEqual(payload["behind"], 0)
            self.assertEqual(dirty.read_text(encoding="utf-8"), "keep\ndirty\n")
            self.assertEqual((clone_b / "shared.txt").read_text(encoding="utf-8"), "from-a\n")
            porcelain = _git(clone_b, "status", "--porcelain")
            self.assertIn("local.txt", porcelain.stdout)

    def test_dry_run_plan_is_fetch_and_pull_rebase_autostash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, _clone_a, clone_b = _pair(Path(tmp))
            _ok(clone_b, "checkout", "-b", "feature")
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone_b),
                    "TK_ARG_REMOTE": "origin",
                    "TK_ARG_BRANCH": "main",
                    "TK_DRY_RUN": "1",
                }
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIs(payload["dry_run"], True)
            self.assertEqual(payload["branch"], "feature")
            self.assertEqual(len(payload["plan"]), 3)
            self.assertEqual(
                payload["plan"],
                [
                    "git fetch origin main",
                    "git pull --rebase --autostash origin main",
                    "git push --force-with-lease --set-upstream origin feature",
                ],
            )
            self.assertIn("push", " ".join(payload["plan"]))

    def _assert_dry_run_matches_refusal(
        self,
        clone: Path,
        origin: Path,
        base: str,
        error: str,
        branch: str,
    ) -> None:
        before = _git(origin, "rev-parse", "refs/heads/main").stdout
        env = {"TK_ARG_REPO": str(clone), "TK_ARG_BRANCH": base}
        dry = _run({**env, "TK_DRY_RUN": "1"})
        real = _run({**env, "TK_DRY_RUN": "0"})
        self.assertNotEqual(dry.returncode, 0, dry.stdout)
        self.assertEqual(dry.returncode, real.returncode)
        self.assertEqual(dry.stdout.strip(), "")
        self.assertEqual(real.stdout.strip(), "")
        dry_payload = json.loads(dry.stderr)
        self.assertEqual(dry_payload, json.loads(real.stderr))
        self.assertEqual(dry_payload["error"], error)
        self.assertTrue(dry_payload["why"])
        self.assertIn(branch, dry_payload["why"])
        fix = str(dry_payload["fix"])
        self.assertIn(f"git -C {shlex.quote(str(clone))} checkout -b fix/sync && ", fix)
        self.assertIn("tk run git.sync --repo ", fix)
        self.assertNotIn("<", fix)
        self.assertNotIn(">", fix)
        self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout, before)
        self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), branch)
        checkout = fix.split(" && ", 1)[0]
        ran = subprocess.run(
            checkout,
            shell=True,
            cwd=str(clone),
            capture_output=True,
            text=True,
            env={**os.environ, **_identity()},
            check=False,
        )
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")

    def test_dry_run_on_main_matches_real_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, _clone_a, clone_b = _pair(Path(tmp))
            self._assert_dry_run_matches_refusal(clone_b, origin, "main", "on_main", "main")

    def test_dry_run_on_base_matches_real_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, _clone_a, clone_b = _pair(Path(tmp))
            _ok(clone_b, "checkout", "-b", "develop")
            self._assert_dry_run_matches_refusal(clone_b, origin, "develop", "on_base", "develop")

    def test_on_base_fix_echoes_quoted_flags_and_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "space dir"
            root.mkdir()
            origin = root / "origin.git"
            subprocess.run(
                ["git", "init", "--bare", "-b", "main", str(origin)],
                check=True,
                capture_output=True,
                text=True,
            )
            clone = root / "my clone"
            _ok(root, "init", "-b", "main", str(clone))
            _ok(clone, "config", "user.name", "Ada")
            _ok(clone, "config", "user.email", "ada@example.com")
            (clone / "shared.txt").write_text("base\n", encoding="utf-8")
            _ok(clone, "add", "shared.txt")
            _ok(clone, "commit", "-m", "base")
            _ok(clone, "remote", "add", "upstream", str(origin))
            _ok(clone, "push", "-u", "upstream", "main")
            _ok(clone, "checkout", "-b", "develop")
            _ok(clone, "push", "-u", "upstream", "develop")
            before = _git(origin, "rev-parse", "refs/heads/main").stdout
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone),
                    "TK_ARG_REMOTE": "upstream",
                    "TK_ARG_BRANCH": "develop",
                }
            )
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "on_base")
            fix = str(payload["fix"])
            self.assertIn(shlex.quote(str(clone)), fix)
            self.assertIn(shlex.quote("upstream"), fix)
            self.assertIn(shlex.quote("develop"), fix)
            commands = _split_and(fix)
            self.assertEqual(
                commands[0],
                ["git", "-C", str(clone), "checkout", "-b", "fix/sync"],
            )
            tk_argv = commands[-1]
            self.assertEqual(tk_argv[:3], ["tk", "run", "git.sync"])
            self.assertEqual(tk_argv[tk_argv.index("--repo") + 1], str(clone))
            self.assertEqual(tk_argv[tk_argv.index("--remote") + 1], "upstream")
            self.assertEqual(tk_argv[tk_argv.index("--branch") + 1], "develop")
            results = _run_fix(fix, clone)
            self.assertGreaterEqual(len(results), 2)
            self.assertEqual(results[0].returncode, 0, results[0].stderr)
            last = results[-1]
            self.assertEqual(last.returncode, 0, last.stderr + last.stdout)
            synced = json.loads(last.stdout)
            self.assertNotEqual(synced.get("error"), "on_base")
            self.assertEqual(synced["branch"], "fix/sync")
            self.assertEqual(synced["base"], "develop")
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")
            self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout, before)

    def test_branch_fix_acts_on_target_repo_not_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin, _clone_a, clone = _pair(root)
            _ok(clone, "checkout", "-b", "develop")
            _ok(clone, "push", "-u", "origin", "develop")
            outside = root / "outside"
            _ok(root, "init", "-b", "main", str(outside))
            _ok(outside, "config", "user.name", "Ada")
            _ok(outside, "config", "user.email", "ada@example.com")
            (outside / "note.txt").write_text("x\n", encoding="utf-8")
            _ok(outside, "add", "note.txt")
            _ok(outside, "commit", "-m", "outside")
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone),
                    "TK_ARG_REMOTE": "origin",
                    "TK_ARG_BRANCH": "develop",
                }
            )
            self.assertEqual(proc.returncode, 2, proc.stderr)
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "on_base")
            fix = str(payload["fix"])
            checkout = _split_and(fix)[0]
            self.assertEqual(checkout[:3], ["git", "-C", str(clone)])
            self.assertEqual(checkout[3:], ["checkout", "-b", "fix/sync"])
            results = _run_fix(fix, outside)
            self.assertEqual(results[0].returncode, 0, results[0].stderr)
            self.assertEqual(_git(clone, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")
            self.assertEqual(_git(outside, "symbolic-ref", "--short", "HEAD").stdout.strip(), "main")
            self.assertNotIn("fix/sync", _git(outside, "branch", "--list").stdout)
            self.assertEqual(results[-1].returncode, 0, results[-1].stderr + results[-1].stdout)

    def test_real_fetch_keeps_ssh_command_and_askpass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _origin, _clone_a, clone = _pair(root)
            _ok(clone, "checkout", "-b", "feature")
            _ok(clone, "remote", "set-url", "origin", "ssh://git@example.invalid/repo.git")
            marker = root / "ssh-marker"
            script = root / "ssh-wrap"
            script.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$GIT_ASKPASS\" > {shlex.quote(str(marker))}\n"
                "exit 1\n",
                encoding="utf-8",
            )
            script.chmod(0o755)
            askpass = "askpass-sentinel"
            proc = _run(
                {
                    "TK_ARG_REPO": str(clone),
                    "TK_ARG_REMOTE": "origin",
                    "TK_ARG_BRANCH": "main",
                    "GIT_SSH_COMMAND": str(script),
                    "GIT_ASKPASS": askpass,
                }
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout)
            self.assertIn("git_failed", proc.stderr)
            self.assertTrue(marker.is_file(), proc.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), askpass)

    def test_dry_run_not_a_repo_matches_real_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "space dir"
            root.mkdir()
            missing = root / "not a repo"
            missing.mkdir()
            env = {"TK_ARG_REPO": str(missing), "TK_ARG_REMOTE": "origin", "TK_ARG_BRANCH": "develop"}
            dry = _run({**env, "TK_DRY_RUN": "1"})
            real = _run(env)
            self.assertEqual(dry.returncode, 2, dry.stdout + dry.stderr)
            self.assertEqual(dry.returncode, real.returncode)
            self.assertEqual(dry.stdout.strip(), "")
            self.assertEqual(real.stdout.strip(), "")
            self.assertEqual(json.loads(dry.stderr), json.loads(real.stderr))
            payload = json.loads(dry.stderr)
            self.assertEqual(payload["error"], "not_a_repo")
            self.assertIn(str(missing), payload["why"])
            fix = str(payload["fix"])
            self.assertNotIn("<", fix)
            self.assertNotIn(">", fix)
            self.assertNotIn("user.email", fix)
            self.assertNotIn("user.name", fix)
            self.assertNotIn("ada@example.com", fix)
            self.assertNotIn("tk run git.sync", fix)
            self.assertIn(shlex.quote(str(missing)), fix)
            commands = _split_and(fix)
            self.assertEqual(commands[-1], ["git", "init", "-b", "fix/sync", "--", str(missing)])
            self.assertFalse((missing / ".git").exists())
            outside = root / "elsewhere"
            outside.mkdir()
            results = _run_fix(fix, outside)
            last = results[-1]
            self.assertEqual(last.returncode, 0, last.stderr + last.stdout)
            self.assertTrue((missing / ".git").is_dir())
            self.assertFalse((outside / ".git").exists())

    def test_fresh_folder_fixes_advance_until_remote_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "space dir"
            root.mkdir()
            folder = root / "fresh repo"
            folder.mkdir()
            outside = root / "elsewhere"
            outside.mkdir()
            env = {"TK_ARG_REPO": str(folder), "TK_ARG_REMOTE": "origin", "TK_ARG_BRANCH": "main"}
            seen: list[tuple[str, str, str]] = []
            for _ in range(6):
                dry = _run({**env, "TK_DRY_RUN": "1"})
                real = _run(env)
                self.assertEqual(real.returncode, 2, real.stdout + real.stderr)
                self.assertEqual(dry.returncode, real.returncode)
                self.assertEqual(dry.stdout, real.stdout)
                self.assertEqual(dry.stderr, real.stderr)
                payload = json.loads(real.stderr)
                key = (str(payload["error"]), str(payload["why"]), str(payload["fix"]))
                self.assertNotIn(key, seen, payload)
                self.assertNotIn(key[0], [item[0] for item in seen])
                seen.append(key)
                self.assertNotIn("user.email", payload["fix"])
                self.assertNotIn("user.name", payload["fix"])
                self.assertNotIn("ada@example.com", payload["fix"])
                if payload["error"] == "no_remote":
                    break
                results = _run_fix(str(payload["fix"]), outside)
                self.assertEqual(results[0].returncode, 0, results[0].stderr + results[0].stdout)
            else:
                self.fail(f"refusals did not stop for a remote URL: {seen}")
            self.assertEqual([item[0] for item in seen], ["not_a_repo", "no_commits", "no_remote"])
            self.assertIn("fix/sync", seen[1][1])
            self.assertIn("--allow-empty", seen[1][2])
            url_fix = seen[2][2]
            self.assertIn(
                '"${REMOTE_URL:?set REMOTE_URL to the URL for remote origin}"',
                url_fix,
            )
            self.assertIn(url_fix, seen[2][1])
            self.assertIn("&&", url_fix)
            self.assertNotIn(" origin URL", url_fix)
            self.assertNotIn("https://", url_fix)
            self.assertNotIn("git@", url_fix)
            author = _git(folder, "log", "-1", "--format=%an %ae")
            self.assertEqual(author.stdout.strip(), "Ada ada@example.com")
            self.assertTrue((folder / ".git").is_dir())
            self.assertFalse((outside / ".git").exists())

    def test_not_a_repo_fix_creates_missing_parent_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "no pe" / "deep repo"
            outside = root / "elsewhere"
            outside.mkdir()
            env = {"TK_ARG_REPO": str(missing)}
            dry = _run({**env, "TK_DRY_RUN": "1"})
            real = _run(env)
            self.assertEqual(real.returncode, 2, real.stdout + real.stderr)
            self.assertEqual(dry.returncode, real.returncode)
            self.assertEqual(dry.stderr, real.stderr)
            payload = json.loads(real.stderr)
            self.assertEqual(payload["error"], "not_a_repo")
            fix = str(payload["fix"])
            self.assertEqual(
                _split_and(fix)[0],
                ["git", "init", "-b", "fix/sync", "--", str(missing)],
            )
            self.assertNotIn("git -C ", fix)
            self.assertFalse(missing.parent.exists())
            results = _run_fix(fix, outside)
            self.assertEqual(results[-1].returncode, 0, results[-1].stderr + results[-1].stdout)
            self.assertTrue((missing / ".git").is_dir())
            self.assertFalse((outside / ".git").exists())
            follow = _run(env)
            self.assertEqual(follow.returncode, 2, follow.stdout + follow.stderr)
            self.assertEqual(json.loads(follow.stderr)["error"], "no_commits")

    def test_dry_run_detached_head_matches_real_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, _clone_a, clone_b = _pair(Path(tmp))
            _ok(clone_b, "checkout", "--detach")
            before = _git(origin, "rev-parse", "refs/heads/main").stdout
            env = {"TK_ARG_REPO": str(clone_b), "TK_ARG_REMOTE": "origin"}
            dry = _run({**env, "TK_DRY_RUN": "1"})
            real = _run(env)
            self.assertEqual(dry.returncode, 2, dry.stdout + dry.stderr)
            self.assertEqual(dry.returncode, real.returncode)
            self.assertEqual(dry.stdout.strip(), "")
            self.assertEqual(real.stdout.strip(), "")
            self.assertEqual(dry.stderr, real.stderr)
            payload = json.loads(dry.stderr)
            self.assertEqual(payload["error"], "detached_head")
            fix = str(payload["fix"])
            self.assertNotIn("<", fix)
            self.assertNotIn(">", fix)
            self.assertIn(shlex.quote(str(clone_b)), fix)
            self.assertIn("--remote", fix)
            self.assertNotEqual(_git(clone_b, "symbolic-ref", "--short", "HEAD").returncode, 0)
            self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout, before)
            results = _run_fix(fix, clone_b)
            last = results[-1]
            self.assertEqual(last.returncode, 0, last.stderr + last.stdout)
            synced = json.loads(last.stdout)
            self.assertNotEqual(synced.get("error"), "detached_head")
            self.assertEqual(_git(clone_b, "symbolic-ref", "--short", "HEAD").stdout.strip(), "fix/sync")
            self.assertEqual(_git(origin, "rev-parse", "refs/heads/main").stdout, before)

    def test_catalog_smoke_dry_run_plans_a_temp_feature_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)
            proc = _run({"TK_ARG_REPO": "example", "TK_DRY_RUN": "1"}, cwd=scratch)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertIs(payload["dry_run"], True)
            self.assertIsInstance(payload["plan"], list)
            self.assertGreaterEqual(len(payload["plan"]), 1)
            self.assertIn("fetch", " ".join(str(step) for step in payload["plan"]))
            self.assertFalse((scratch / "example").exists())
            named = _run(
                {"TK_ARG_REPO": "example", "TK_ARG_REMOTE": "origin", "TK_DRY_RUN": "1"},
                cwd=scratch,
            )
            self.assertEqual(named.returncode, 2, named.stdout)
            self.assertEqual(json.loads(named.stderr)["error"], "not_a_repo")

    def test_catalog_smoke_ignores_inherited_git_dir(self) -> None:
        git_dir = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--absolute-git-dir"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        before = _git(ROOT, "rev-parse", "HEAD").stdout
        branch = _git(ROOT, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        readme = ROOT / "README.md"
        readme_bytes = readme.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            proc = _run(
                {
                    "TK_ARG_REPO": "example",
                    "TK_DRY_RUN": "1",
                    "GIT_DIR": git_dir,
                    "GIT_INDEX_FILE": str(Path(git_dir) / "index"),
                },
                cwd=Path(tmp),
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIs(payload["dry_run"], True)
        self.assertTrue(payload["plan"])
        self.assertEqual(_git(ROOT, "rev-parse", "HEAD").stdout, before)
        self.assertEqual(_git(ROOT, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip(), branch)
        self.assertEqual(readme.read_bytes(), readme_bytes)
        self.assertFalse((ROOT / "README").exists())

    def test_conflict_aborts_rebase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, clone_a, clone_b = _pair(Path(tmp))
            (clone_a / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(clone_a, "add", "shared.txt")
            _ok(clone_a, "commit", "-m", "a edit")
            _ok(clone_a, "push", "origin", "main")
            _ok(clone_b, "checkout", "-b", "feature")
            (clone_b / "shared.txt").write_text("from-b\n", encoding="utf-8")
            _ok(clone_b, "add", "shared.txt")
            _ok(clone_b, "commit", "-m", "b edit")
            proc = _run({"TK_ARG_REPO": str(clone_b)})
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("rebase_conflict", proc.stderr)
            self.assertEqual(proc.stdout.strip(), "")
            head = _git(clone_b, "symbolic-ref", "--short", "HEAD")
            self.assertEqual(head.stdout.strip(), "feature")
            rebase = _git(clone_b, "rev-parse", "--git-path", "rebase-merge")
            path = Path(rebase.stdout.strip())
            if not path.is_absolute():
                path = clone_b / path
            self.assertFalse(path.exists())
            self.assertEqual((clone_b / "shared.txt").read_text(encoding="utf-8"), "from-b\n")

    def test_conflict_fix_restarts_rebase_for_the_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _origin, clone_a, clone_b = _pair(Path(tmp))
            (clone_a / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(clone_a, "add", "shared.txt")
            _ok(clone_a, "commit", "-m", "a edit")
            _ok(clone_a, "push", "origin", "main")
            _ok(clone_b, "checkout", "-b", "feature")
            (clone_b / "shared.txt").write_text("from-b\n", encoding="utf-8")
            _ok(clone_b, "add", "shared.txt")
            _ok(clone_b, "commit", "-m", "b edit")
            env = {"TK_ARG_REPO": str(clone_b)}
            proc = _run(env)
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "rebase_conflict")
            fix = str(payload["fix"])
            self.assertEqual(_split_and(fix), [["git", "-C", str(clone_b), "rebase", "origin/main"]])
            self.assertIn("core.editor=true", payload["why"])
            self.assertIn("rebase --continue", payload["why"])
            self.assertIn(" add ", payload["why"])
            ran = subprocess.run(
                shlex.split(fix),
                capture_output=True,
                text=True,
                env={**os.environ, **_identity()},
                check=False,
            )
            self.assertNotEqual(ran.returncode, 0, ran.stdout)
            rebase = _git(clone_b, "rev-parse", "--git-path", "rebase-merge")
            path = Path(rebase.stdout.strip())
            if not path.is_absolute():
                path = clone_b / path
            self.assertTrue(path.is_dir(), rebase.stdout)
            dry = _run({**env, "TK_DRY_RUN": "1"})
            real = _run(env)
            self.assertEqual(real.returncode, 2, real.stdout + real.stderr)
            self.assertEqual(dry.returncode, real.returncode)
            self.assertEqual(dry.stdout, real.stdout)
            self.assertEqual(dry.stderr, real.stderr)
            again = json.loads(real.stderr)
            self.assertEqual(again["error"], "rebase_in_progress")
            self.assertNotIn("detached_head", real.stderr)
            self.assertNotIn("rebase_conflict", real.stderr)
            self.assertEqual(
                _split_and(str(again["fix"]))[0],
                ["git", "-C", str(clone_b), "-c", "core.editor=true", "rebase", "--continue"],
            )
            self.assertIn("tk run git.sync", again["fix"])
            self.assertIn("core.editor=true", again["fix"])
            self.assertTrue(path.is_dir())

    def test_no_remote_fix_rejects_an_unset_url_then_syncs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            origin, _clone_a, clone = _pair(root)
            _ok(clone, "checkout", "-b", "feature")
            _ok(clone, "remote", "remove", "origin")
            outside = root / "outside"
            outside.mkdir()
            env = {"TK_ARG_REPO": str(clone), "TK_ARG_REMOTE": "origin", "TK_ARG_BRANCH": "main"}
            proc = _run(env)
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "no_remote")
            fix = str(payload["fix"])
            marker = '"${REMOTE_URL:?set REMOTE_URL to the URL for remote origin}"'
            self.assertIn(marker, fix)
            self.assertIn(marker, payload["why"])
            blocked = _run_shell(fix, outside)
            self.assertNotEqual(blocked.returncode, 0, blocked.stdout + blocked.stderr)
            self.assertIn("REMOTE_URL", blocked.stderr)
            self.assertEqual(_git(clone, "remote").stdout.strip(), "")
            self.assertEqual(_error_name(_run(env)), "no_remote")
            ran = _run_shell(fix, outside, {"REMOTE_URL": str(origin)})
            self.assertEqual(ran.returncode, 0, ran.stderr + ran.stdout)
            synced = _last_json(ran)
            self.assertIs(synced["pushed"], True)
            self.assertEqual(synced["branch"], "feature")
            self.assertEqual(_git(clone, "remote", "get-url", "origin").stdout.strip(), str(origin))
            self.assertEqual(_error_name(_run(env)), "")

    def test_no_remote_fix_retries_with_an_existing_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _origin, _clone_a, clone = _pair(root)
            _ok(clone, "checkout", "-b", "feature")
            _ok(clone, "remote", "rename", "origin", "upstream")
            outside = root / "outside"
            outside.mkdir()
            env = {"TK_ARG_REPO": str(clone), "TK_ARG_REMOTE": "origin", "TK_ARG_BRANCH": "main"}
            proc = _run(env)
            payload = json.loads(proc.stderr)
            self.assertEqual(payload["error"], "no_remote")
            fix = str(payload["fix"])
            self.assertNotIn("REMOTE_URL", fix)
            self.assertIn("--remote upstream", fix)
            self.assertIn("--branch main", fix)
            self.assertIn(fix, str(payload["why"]))
            ran = _run_shell(fix, outside)
            self.assertEqual(ran.returncode, 0, ran.stderr + ran.stdout)
            synced = _last_json(ran)
            self.assertEqual(synced["remote"], "upstream")
            self.assertIs(synced["pushed"], True)
            self.assertNotIn("origin", _git(clone, "remote").stdout.split())
            again = _run_shell(fix, outside)
            self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
            self.assertNotEqual(_last_json(again).get("error"), "no_remote")

    def test_each_fix_advances_one_step_without_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside"
            outside.mkdir()
            for key in ("EDITOR", "VISUAL", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR"):
                self.assertNotIn(key, _shell_env(outside, identity=False))

            folder = root / "space dir" / "fresh"
            folder.parent.mkdir()
            folder.mkdir()
            fresh = {"TK_ARG_REPO": str(folder)}
            first = _run(fresh)
            self.assertEqual(_error_name(first), "not_a_repo")
            self.assertEqual(_run_shell(json.loads(first.stderr)["fix"], outside).returncode, 0)
            self.assertEqual(_error_name(_run(fresh)), "no_commits")
            commits = _run(fresh)
            self.assertEqual(_error_name(commits), "no_commits")
            _run_shell(json.loads(commits.stderr)["fix"], outside)
            self.assertEqual(_error_name(_run(fresh)), "no_remote")

            origin, clone_a, clone_b = _pair(root)
            self._assert_branch_fix_advances(clone_b, outside, "on_main", {})
            _ok(clone_a, "checkout", "-b", "develop")
            _ok(clone_a, "push", "-u", "origin", "develop")
            self._assert_branch_fix_advances(
                clone_a,
                outside,
                "on_base",
                {"TK_ARG_BRANCH": "develop"},
            )
            third = root / "detached"
            subprocess.run(
                ["git", "clone", str(origin), str(third)],
                check=True,
                capture_output=True,
                text=True,
            )
            _ok(third, "config", "user.name", "Ada")
            _ok(third, "config", "user.email", "ada@example.com")
            _ok(third, "checkout", "--detach")
            self._assert_branch_fix_advances(third, outside, "detached_head", {})

            rebase_root = root / "rebase"
            rebase_root.mkdir()
            _origin, left, right = _pair(rebase_root)
            (left / "shared.txt").write_text("from-a\n", encoding="utf-8")
            _ok(left, "add", "shared.txt")
            _ok(left, "commit", "-m", "a edit")
            _ok(left, "push", "origin", "main")
            _ok(right, "checkout", "-b", "feature")
            (right / "shared.txt").write_text("from-b\n", encoding="utf-8")
            _ok(right, "add", "shared.txt")
            _ok(right, "commit", "-m", "b edit")
            conflict_env = {"TK_ARG_REPO": str(right)}
            conflict = _run(conflict_env)
            self.assertEqual(_error_name(conflict), "rebase_conflict")
            conflict_fix = str(json.loads(conflict.stderr)["fix"])
            self.assertIn("core.editor=true", json.loads(conflict.stderr)["why"])
            self.assertNotEqual(_run_shell(conflict_fix, outside).returncode, 0)
            self.assertEqual(_error_name(_run(conflict_env)), "rebase_in_progress")
            (right / "shared.txt").write_text("merged\n", encoding="utf-8")
            _ok(right, "add", "shared.txt")
            again = _run(conflict_env)
            self.assertEqual(_error_name(again), "rebase_in_progress")
            continue_fix = str(json.loads(again.stderr)["fix"])
            self.assertIn("-c core.editor=true rebase --continue", continue_fix)
            continued = _run_shell(continue_fix, outside, identity=False)
            self.assertEqual(continued.returncode, 0, continued.stderr + continued.stdout)
            self.assertIs(_last_json(continued)["pushed"], True)
            self.assertNotEqual(_error_name(_run(conflict_env)), "rebase_in_progress")

    def _assert_branch_fix_advances(
        self,
        clone: Path,
        outside: Path,
        error: str,
        extra_env: dict[str, str],
    ) -> None:
        env = {"TK_ARG_REPO": str(clone), **extra_env}
        proc = _run(env)
        self.assertEqual(_error_name(proc), error, proc.stderr)
        fix = str(json.loads(proc.stderr)["fix"])
        if "rebase --continue" in fix:
            self.assertIn("core.editor=true", fix)
        ran = _run_shell(fix, outside)
        self.assertEqual(ran.returncode, 0, ran.stderr + ran.stdout)
        self.assertNotEqual(_last_json(ran).get("error"), error)
        self.assertNotEqual(_error_name(_run(env)), error)


if __name__ == "__main__":
    unittest.main()
