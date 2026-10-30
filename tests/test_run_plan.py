import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "run_plan", Path(__file__).resolve().parent.parent / "tools" / "run_plan.py"
)
run_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_plan)


def _merged(branch):
    return {"number": 1, "url": "u", "state": "MERGED", "isDraft": False, "headRefName": branch}


def test_each_plan_reads_its_phases_and_efforts_from_its_file():
    assert run_plan.efforts("layout") == {
        0: "medium", 1: "high", 2: "medium", 3: "medium", 4: "high", 5: "high", 6: "high"
    }  # fmt: skip
    quality = run_plan.efforts("quality")
    assert sorted(quality) == list(range(7)) and set(quality.values()) <= {"low", "medium"}


def test_the_quality_plan_goes_on_from_its_own_merged_prs():
    effort = run_plan.efforts("quality")
    prs = [_merged("quality/phase-0"), _merged("layout/phase-1")]

    step = run_plan.next_step(prs, None, "quality", effort)

    assert step["branch"] == "quality/phase-1" and step["effort"] == effort[1]
    assert "docs/quality-plan.md" in step["prompt"] and "quality/phase-1" in step["prompt"]


def test_the_layout_plan_still_waits_for_its_parts():
    prs = [_merged(f"layout/phase-{n}") for n in range(5)]

    assert run_plan.next_step(prs, None, "layout", run_plan.efforts("layout")) == {"needs": "parts"}
