---
name: pdf-layout-plan
description: pdf-worker only. Run pdf-worker's docs/layout-plan.md phase after phase, each as a subagent at that phase's effort, merging each phase's PR, until the plan needs the user. Use when the user types /pdf-layout-plan (optionally with Phase 5's parts, e.g. "/pdf-layout-plan bibliography,contents" or "/pdf-layout-plan none") or asks to continue pdf-worker's layout plan.
---

## /pdf-layout-plan: run pdf-worker's docs/layout-plan.md

You conduct; subagents do the phases' work. Never do a phase's work yourself. The user
allowed you to merge this plan's PRs (`layout/phase-*`) and no others. Repeat this loop
until it says to stop:

1. Find the next step:
   `/Users/fons/Documents/pdf-worker/.venv/bin/python /Users/fons/Documents/pdf-worker/tools/run_plan.py --next`
   adding `--parts <parts>` when the user gave parts after the command. It prints JSON
   built from the plan's PRs on GitHub:
   - `{"done": true}`: every phase is merged. Say so and stop.
   - `{"needs": "parts"}`: Phase 4 is merged. Read its numbers and its recommendation
     per part in PROGRESS.md, sum them up in a few lines, and ask which parts to switch
     (bibliography, contents, paragraphs, footnotes, margin-notes, headings, or none).
     The user answers with `/pdf-layout-plan <parts>`. Stop.
   - a `pr` with `"isDraft": true`: the phase stopped. Read the PR
     (`gh pr view <number> --repo fonsthefons/pdf-worker`) and the top of PROGRESS.md,
     and tell the user why it stopped and what they could decide. Stop.
   - a `pr` that isn't a draft: merge it with
     `gh pr merge <number> --repo fonsthefons/pdf-worker --merge --delete-branch`, bring
     the checkout up to date (step 2), and run the fast tests:
     `/Users/fons/Documents/pdf-worker/.venv/bin/pytest -m "not integration" /Users/fons/Documents/pdf-worker -q`.
     If they fail, tell the user (the PR and the failures) and stop. Otherwise go back
     to step 1.
   - otherwise (`phase`, `branch`, `effort`, `prompt`): if this phase's subagent already
     ran in this loop and left no PR, say so, quote the end of its report, and stop.
     Else go on.
2. Bring the checkout to an up-to-date main:
   `git -C /Users/fons/Documents/pdf-worker status --porcelain`; if tracked files have
   uncommitted changes, stop and tell the user (before Phase 0 only, changes to
   PROGRESS.md and CLAUDE.md are expected: the plan's entry and merge rule). Then
   `git -C /Users/fons/Documents/pdf-worker switch main` and
   `git -C /Users/fons/Documents/pdf-worker pull --ff-only`.
3. Start one subagent with the Agent tool: `subagent_type` "general-purpose", `effort`
   the JSON's `effort` (the plan sets it per phase), `description` "Layout plan phase
   <phase>", and `prompt` the JSON's `prompt`, word for word. Tell the user in one line
   that phase <phase> is running at <effort> effort (phases take 30 to 90 minutes).
4. When the subagent reports back, tell the user in a few lines what the phase changed
   and its key numbers, then go back to step 1 (which checks its PR on GitHub and
   merges it).
