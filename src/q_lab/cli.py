from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from q_lab.adapters.hyperliquid import (
    HyperliquidPaperAdapter,
    HyperliquidPaperConfig,
)
from q_lab.config import load_config
from q_lab.evaluators.deterministic import DeterministicEvaluator
from q_lab.leaderboard import Leaderboard
from q_lab.models import ExperimentSpec
from q_lab.runner import ExperimentRunner
from q_lab.scheduler import ListExperimentSource, SchedulerLoop
from q_lab.store import JsonlResultsStore


def _coerce_value(raw: str) -> object:
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _parse_params(items: list[str]) -> dict[str, object]:
    params: dict[str, object] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --param '{item}'. Expected KEY=VALUE.")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError("Parameter key cannot be empty.")
        params[key] = _coerce_value(value)
    return params


def _run_once(args: argparse.Namespace) -> int:
    evaluator = DeterministicEvaluator()
    store = JsonlResultsStore(args.results_path)
    runner = ExperimentRunner(evaluator=evaluator, store=store)
    spec = ExperimentSpec(
        experiment_id=args.experiment_id,
        strategy=args.strategy,
        params=_parse_params(args.param),
    )
    result = runner.run(spec)
    print(
        f"run_id={result.run_id} strategy={spec.strategy} "
        f"score={result.evaluation.score:.6f} store={args.results_path}"
    )
    return 0


def _run_schedule(args: argparse.Namespace) -> int:
    app_config = load_config(args.config)
    evaluator = DeterministicEvaluator()
    store = JsonlResultsStore(app_config.store.results_path)
    runner = ExperimentRunner(evaluator=evaluator, store=store)
    source = ListExperimentSource(app_config.experiments)
    scheduler = SchedulerLoop(
        source=source,
        runner=runner,
        poll_interval_seconds=app_config.scheduler.poll_interval_seconds,
    )
    stats = scheduler.run(max_cycles=app_config.scheduler.max_cycles)
    print(
        f"cycles={stats.cycles} runs={stats.runs_executed} "
        f"failures={stats.failures} store={app_config.store.results_path}"
    )
    return 0


def _show_leaderboard(args: argparse.Namespace) -> int:
    store = JsonlResultsStore(args.results_path)
    board = Leaderboard(store).top(limit=args.limit)
    if not board:
        print("No experiment runs found.")
        return 0

    for entry in board:
        print(
            f"{entry.rank}. run_id={entry.run_id} "
            f"experiment_id={entry.experiment_id} strategy={entry.strategy} "
            f"score={entry.score:.6f}"
        )
    return 0


def _paper_order_demo(args: argparse.Namespace) -> int:
    adapter = HyperliquidPaperAdapter(
        HyperliquidPaperConfig(mode=args.mode, account_address=args.account)
    )
    order = adapter.place_order(
        symbol=args.symbol,
        side=args.side,
        quantity=args.quantity,
        limit_price=args.limit_price,
    )
    print(adapter.safety_warning)
    print(json.dumps(asdict(order), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="q-lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one experiment now.")
    run_parser.add_argument("--experiment-id", default="manual-experiment")
    run_parser.add_argument("--strategy", required=True)
    run_parser.add_argument("--param", action="append", default=[], help="KEY=VALUE")
    run_parser.add_argument("--results-path", default="data/results.jsonl")
    run_parser.set_defaults(func=_run_once)

    schedule_parser = subparsers.add_parser("schedule", help="Run configured scheduler loop.")
    schedule_parser.add_argument(
        "--config", type=Path, default=Path("config/examples/mvp.toml")
    )
    schedule_parser.set_defaults(func=_run_schedule)

    board_parser = subparsers.add_parser("leaderboard", help="Show top experiment runs.")
    board_parser.add_argument("--results-path", default="data/results.jsonl")
    board_parser.add_argument("--limit", type=int, default=10)
    board_parser.set_defaults(func=_show_leaderboard)

    paper_parser = subparsers.add_parser(
        "paper-order-demo",
        help="Demonstrate Hyperliquid adapter in paper-only mode.",
    )
    paper_parser.add_argument("--mode", default="paper")
    paper_parser.add_argument("--account", default=None)
    paper_parser.add_argument("--symbol", default="BTC-USD")
    paper_parser.add_argument("--side", choices=["buy", "sell"], default="buy")
    paper_parser.add_argument("--quantity", type=float, default=0.01)
    paper_parser.add_argument("--limit-price", type=float, default=None)
    paper_parser.set_defaults(func=_paper_order_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
