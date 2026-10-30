"""Run a plan in docs/ (layout-plan.md, quality-plan.md) phase by phase with Claude Code.

Where a plan stands is read from its PRs on GitHub (branches ``<plan>/phase-N``, and
``layout/phase-5-<part>`` for the layout plan's Phase 5): the next phase is the first
whose PR isn't merged. Each phase's effort is at the end of its heading in the plan
("## Phase 2: ... (medium)"). The layout plan's Phase 5 needs the user's choice of parts.
Without ``--plan``, the first plan not yet done.

Inside Claude Code, ``/pdf-layout-plan [quality]`` does one phase per call, reading the
next step from ``--next`` (JSON).

In a terminal (not inside Claude Code, whose commands time out):
    .venv/bin/python tools/run_plan.py [--plan quality] [--yes] [--parts a,b | none]
runs each phase as a headless session (``claude -p``) at the phase's effort, merges its
PR (asking first unless --yes), updates main and runs the fast tests, until the plan is
done or needs the parts. ``--dry-run`` shows the next step. Each session's reply goes to
scratch/logs/plan_<branch>.json; ``claude --resume ID`` opens a session that stopped.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GH_REPO = "fonsthefons/pdf-worker"
PLANS = {"layout": "docs/layout-plan.md", "quality": "docs/quality-plan.md"}
PHASE_RE = re.compile(r"^## Phase (\d+): .*\((low|medium|high)\)\s*$", re.MULTILINE)
PARTS = ("bibliography", "contents", "paragraphs", "footnotes", "margin-notes", "headings")
PROMPT = """Do Phase {phase} of {doc}{part}.

You run unattended (tools/run_plan.py or /pdf-layout-plan): nobody will answer questions.
Follow CLAUDE.md, PROGRESS.md and the plan's "How to work" section, and decide as they
say. Work on the branch `{branch}`, made from an up-to-date origin/main (if it exists
already, an earlier run stopped: carry on from where it is). Finish by pushing it and
opening a PR against main with `gh pr create`; don't merge it.{extra}

If a check fails in a way the plan doesn't cover, or the plan says to ask the user: write
what happened in PROGRESS.md, commit and push it, open the PR as a draft
(`gh pr create --draft`), and make the last line of your reply `STOPPED: <reason>`.
Otherwise make the last line `PR: <url>`."""
PHASE_4 = """ The plan's "stop and ask the user" after Phase 4 is done by whoever
started you: open a normal PR with the report and your recommendation per part, and end
there."""
PICK_PARTS = (
    "Phase 4 is merged: its numbers and a recommendation per part are in PROGRESS.md."
    f" Choose the parts for Phase 5 ({', '.join(PARTS)}, or none) and pass them with"
    " --parts (/pdf-layout-plan <parts> inside Claude Code)."
)


def efforts(plan: str) -> dict[int, str]:
    """Each phase of the plan and its effort, from the end of its heading."""
    text = (REPO / PLANS[plan]).read_text(encoding="utf-8")
    return {int(phase): effort for phase, effort in PHASE_RE.findall(text)}


def next_step(prs: list[dict], parts: list[str] | None, plan: str, effort: dict[int, str]) -> dict:
    """The first phase whose PR isn't merged: {"plan", "phase", "branch", "effort",
    "prompt"}, and "pr" ({"number", "url", "isDraft"}) when its PR is open.
    {"needs": "parts"} when the layout plan's Phase 5 is next and no parts were given or
    have PRs; {"done": True} at the end. ``effort``: ``efforts(plan)``.

    ``prs``: ``gh pr list --json number,url,state,isDraft,headRefName`` rows. Without
    ``parts``, Phase 5's parts are those with a PR (``[]``: none chosen, skip it)."""
    by_branch: dict[str, list[dict]] = {}
    for pr in prs:
        by_branch.setdefault(pr["headRefName"], []).append(pr)
    prefix = "layout/phase-5-"
    started = sorted(b.removeprefix(prefix) for b in by_branch if b.startswith(prefix))
    for phase in sorted(effort):
        items: list[str | None] = [None]
        if plan == "layout" and phase == 5:
            items = list(parts if parts is not None else started)
            if parts is None and not started:
                return {"needs": "parts"}
        for part in items:
            branch = f"{plan}/phase-{phase}" + (f"-{part}" if part else "")
            found = by_branch.get(branch, [])
            if any(pr["state"] == "MERGED" for pr in found):
                continue
            step = {
                "plan": plan,
                "phase": phase,
                "branch": branch,
                "effort": effort[phase],
                "prompt": PROMPT.format(
                    phase=phase,
                    doc=PLANS[plan],
                    part=f", for one part only: {part}" if part else "",
                    branch=branch,
                    extra=PHASE_4 if plan == "layout" and phase == 4 else "",
                ),
            }
            if waiting := [pr for pr in found if pr["state"] == "OPEN"]:
                step["pr"] = {key: waiting[0][key] for key in ("number", "url", "isDraft")}
            return step
    return {"done": True}


def github_prs() -> list[dict]:
    command = ["gh", "pr", "list", "--repo", GH_REPO, "--state", "all", "--limit", "300"]
    fields = ["--json", "number,url,state,isDraft,headRefName"]
    listed = subprocess.run([*command, *fields], check=True, text=True, capture_output=True)
    return json.loads(listed.stdout)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, text=True, capture_output=True
    ).stdout


def up_to_date_main(branch: str = "") -> None:
    """Switch to an up-to-date main, unless tracked files have uncommitted changes
    (the layout plan's Phase 0 commits its PROGRESS.md entry and CLAUDE.md rule itself)."""
    setup = ("PROGRESS.md", "CLAUDE.md") if branch == "layout/phase-0" else ()
    changed = [
        line[3:]
        for line in git("status", "--porcelain").splitlines()
        if not line.startswith("??") and line[3:] not in setup
    ]
    if changed:
        sys.exit(f"Uncommitted changes in {', '.join(changed)}: commit or discard them first.")
    git("switch", "main")
    git("pull", "--ff-only")


def run_session(step: dict) -> str:
    """One headless Claude Code session for the step's phase; returns how to reopen it."""
    up_to_date_main(step["branch"])
    branch, effort = step["branch"], step["effort"]
    print(f"{time.strftime('%H:%M')} {branch}: running at {effort} effort...", flush=True)
    command = [
        "claude", "-p", step["prompt"],
        "--model", "opus",
        "--effort", effort,
        "--permission-mode", "auto",
        "--permission-prompts", "none",  # nobody to ask: what would ask is refused
        "--allowedTools", "Bash(gh pr create *)",  # the one step a phase can't do without
        "--name", f"{step['plan']} plan {branch}",
        "--output-format", "json",
    ]  # fmt: skip
    started = time.time()
    done = subprocess.run(command, cwd=REPO, text=True, capture_output=True)
    log = REPO / "scratch" / "logs" / f"plan_{branch.replace('/', '_')}.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(done.stdout or done.stderr, encoding="utf-8")
    try:
        reply = json.loads(done.stdout)
    except json.JSONDecodeError:
        reply = {"result": done.stderr.strip() or "no reply", "is_error": True}
    last = (str(reply.get("result", "")).strip().splitlines() or [""])[-1]
    print(f"{branch}: {(time.time() - started) / 60:.0f} min. {last}")
    reopen = f"claude --resume {reply['session_id']}" if reply.get("session_id") else str(log)
    if reply.get("is_error"):
        sys.exit(f"{branch} failed: {last}\nSee {log}, or open the session: {reopen}")
    return reopen


def merge(step: dict, yes: bool) -> None:
    pr = step["pr"]
    if pr["isDraft"]:
        sys.exit(f"{step['branch']} stopped: read {pr['url']} and the top of PROGRESS.md.")
    if not yes and input(f"Merge {pr['url']}? [y/N] ").strip().lower() != "y":
        sys.exit("Not merged. Merge it yourself, or run again to be asked again.")
    number = str(pr["number"])
    command = ["gh", "pr", "merge", number, "--repo", GH_REPO, "--merge", "--delete-branch"]
    subprocess.run(command, cwd=REPO, check=True)
    up_to_date_main()
    tests = [str(REPO / ".venv" / "bin" / "pytest"), "-m", "not integration", "-q", str(REPO)]
    if subprocess.run(tests, cwd=REPO).returncode:
        sys.exit(f"The fast tests fail on main after merging {pr['url']}.")


def current_step(plan: str | None, parts: list[str] | None) -> dict:
    """The next step of ``plan``, or without one, of the first plan not done."""
    prs = github_prs()
    step: dict = {"done": True}
    for name in [plan] if plan else PLANS:
        step = next_step(prs, parts, name, efforts(name))
        if not step.get("done"):
            break
    return step


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--plan", choices=PLANS, help="default: the first plan not done")
    parser.add_argument(
        "--parts", help=f"the layout plan's Phase 5 parts: some of {', '.join(PARTS)}, or none"
    )
    parser.add_argument("--yes", action="store_true", help="merge each PR without asking")
    parser.add_argument("--dry-run", action="store_true", help="show the next step only")
    parser.add_argument("--next", action="store_true", help="print the next step as JSON")
    args = parser.parse_args()
    parts = None
    if args.parts is not None:
        parts = [p.strip() for p in args.parts.split(",") if p.strip() and p.strip() != "none"]
        if unknown := set(parts) - set(PARTS):
            parser.error(f"unknown parts {sorted(unknown)}; choose from {', '.join(PARTS)}")
    if args.next:
        print(json.dumps(current_step(args.plan, parts), ensure_ascii=False, indent=1))
        return
    if os.environ.get("CLAUDECODE") and not args.dry_run:
        sys.exit("Run this in a terminal (in Claude Code use /pdf-layout-plan): it would time out.")
    reopen, ran = "", ""
    while True:
        step = current_step(args.plan, parts)
        if step.get("done"):
            done = PLANS[args.plan] if args.plan else " and ".join(PLANS.values())
            print(f"All phases of {done} are merged.")
            return
        if "needs" in step:
            print(PICK_PARTS)
            return
        if args.dry_run:
            waiting = f", PR waiting: {step['pr']['url']}" if "pr" in step else ""
            print(f"--- {step['branch']}, effort {step['effort']}{waiting}\n{step['prompt']}")
            return
        if "pr" in step:
            merge(step, args.yes)
            continue
        if step["branch"] == ran:
            sys.exit(f"{ran} ended without a PR. Open the session: {reopen}")
        ran, reopen = step["branch"], run_session(step)


if __name__ == "__main__":
    main()
