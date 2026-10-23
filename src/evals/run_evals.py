"""Run every case in cases.yaml N times and save one row per run to evals/results.csv.

Run from the project root:  uv run src/evals/run_evals.py
"""

import asyncio
import csv
import re
import statistics
import sys
import yaml
from pathlib import Path
from judge import judge  # noqa: E402

# Make graph.py importable (it lives in a sibling folder)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "data_incident_investigator_agent"))
from graph import CASES_FILE, investigate  # noqa: E402
from tracing import flush  # noqa: E402
from datetime import datetime

RUNS_PER_CASE = 3
RESULTS_FILE = Path("src/evals/results__.csv")
FIELDS = ["case_id", "run", "expected", "predicted", "verdict_correct",
          "steps", "n_sql", "input_tokens", "output_tokens", "latency_s", 
          "findings_score", "missing_findings", "unsupported_claims", "judge_reasons"]
RUN_ID = datetime.now().strftime("eval-%Y%m%d-%H%M")

def predicted_verdict(answer: str) -> str:
    """Rule-based grading: read the text right after 'Verdict' in the answer."""
    match = re.search(r"VERDICT:\s*(DATA_BUG|BUSINESS_CHANGE)", answer)
    return match.group(1).lower() if match else "unclear"


async def main() -> None:
    with open(CASES_FILE) as f:
        cases = yaml.safe_load(f)

    RESULTS_FILE.parent.mkdir(exist_ok=True)
    rows = []
    for case in cases:
        expected = "data_bug" if case["is_data_bug"] else "business_change"
        for run in range(1, RUNS_PER_CASE + 1):  # one after another, so latencies are clean
            print(f"\n######## {case['id']}  run {run}/{RUNS_PER_CASE} ########")
            result = await investigate(case["id"], run_id=f"{RUN_ID}")
            grades = judge(result["answer"], case["expected_findings"])
            predicted = predicted_verdict(result["answer"])
            rows.append({
                "case_id": case["id"], "run": run,
                "expected": expected, "predicted": predicted,
                "verdict_correct": predicted == expected,
                **grades,
                **{k: result[k] for k in ["steps", "n_sql", "input_tokens", "output_tokens", "latency_s"]},
            })

            # Write after every run, so a crash halfway doesn't lose the results so far
            with open(RESULTS_FILE, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)

    # Summary: one line per case, then overall
    print("\n=================== SUMMARY ===================")
    print(f"{'case':16} {'correct':>8} {'findings':>9} {'steps':>6} {'sql':>5} {'in_tok':>8} {'latency':>8}")
    for case in cases:
        r = [row for row in rows if row["case_id"] == case["id"]]
        print(f"{case['id']:16} "
              f"{sum(x['verdict_correct'] for x in r)}/{len(r):<6} "
              f"{statistics.mean(x['findings_score'] for x in r):>9.2f} "
              f"{statistics.median(x['steps'] for x in r):>6} "
              f"{statistics.median(x['n_sql'] for x in r):>5} "
              f"{statistics.median(x['input_tokens'] for x in r):>8} "
              f"{statistics.median(x['latency_s'] for x in r):>7}s")
    total = sum(r["verdict_correct"] for r in rows)
    print(f"\nVerdict accuracy: {total}/{len(rows)} = {total / len(rows):.0%}")
    print(f"Saved {len(rows)} rows to {RESULTS_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        flush()