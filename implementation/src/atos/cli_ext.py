from __future__ import annotations

import argparse
import json

from atos.evaluator import Evaluator
from atos.state_service import StateService
from atos.timer import FixedTimer


def main() -> None:
    parser = argparse.ArgumentParser(prog="atos-ext")
    parser.add_argument("command", choices=["state", "evaluate", "timer"])
    args = parser.parse_args()

    if args.command == "state":
        output = StateService({"mode": "paper"}).current().to_dict()
    elif args.command == "evaluate":
        output = {"summary": Evaluator().summarize([0.1, -0.2, 0.3, 0.0]).to_dict(), "walk_forward": Evaluator().walk_forward_windows([0.1, 0.2, -0.1, 0.0, 0.3], train=2, test=1)}
    else:
        count = {"n": 0}
        def inc():
            count["n"] += 1
        result = FixedTimer().run(inc, runs=2)
        output = {"timer": result.to_dict(), "count": count["n"]}

    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
