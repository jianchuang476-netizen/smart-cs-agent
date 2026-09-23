from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.agent import AgentRuntime


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        default="data/eval/after_sales_eval.jsonl",
        help="JSONL evaluation dataset path",
    )
    args = parser.parse_args()

    records = [
        json.loads(line)
        for line in Path(args.dataset).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    route_correct = 0
    for record in records:
        route, _intent, _risk = AgentRuntime._heuristic_route(record["question"])
        route_correct += route == record["expected_route"]

    total = len(records) or 1
    print(
        json.dumps(
            {"cases": len(records), "route_accuracy": route_correct / total},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
