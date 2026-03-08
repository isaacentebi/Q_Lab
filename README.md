# Q_Lab

Q_Lab is an MVP autonomous quant experiment operating system focused on safe, reproducible research workflows.

This scaffold is intentionally paper-trading only. It provides a minimal framework for running strategy experiments, scoring them with evaluator interfaces, recording immutable results with git lineage metadata, and ranking outcomes on a leaderboard.

## Core Principles

- Safety first: no live trading support, no real-funds movement paths, Hyperliquid integration locked to paper mode.
- Reproducibility: every run stores git lineage metadata for traceability.
- Extensibility: evaluator and scheduling interfaces are composable and easy to swap.
- Operational hygiene: typed Python package layout, CLI entrypoint, config examples, and tests.

## Architecture

```text
q-lab CLI
  -> config loader (TOML)
  -> scheduler loop
      -> experiment runner
          -> evaluator interface implementation(s)
          -> feature sources (market + exogenous)
          -> git lineage utilities
          -> results store (JSONL)
  -> leaderboard view
  -> Hyperliquid paper adapter stub (simulated orders only)
```

### Package layout

```text
src/q_lab/
  adapters/hyperliquid.py     # paper-trading-only Hyperliquid stub
  evaluators/base.py          # evaluator protocol + abstract base class
  evaluators/deterministic.py # deterministic MVP evaluator
  cli.py                      # q-lab command line entrypoint
  config.py                   # TOML config loader
  features.py                 # Polymarket / Kalshi / exogenous feature interfaces
  git_utils.py                # commit/branch/dirty metadata
  leaderboard.py              # ranking logic
  models.py                   # shared dataclasses
  runner.py                   # experiment execution unit
  scheduler.py                # poll loop and source interface
  store.py                    # JSONL results persistence
```

## Safety Notes (Read First)

- Live trading is explicitly disabled in this MVP.
- Hyperliquid adapter refuses any mode other than `paper`.
- Simulated order placement returns synthetic order IDs and statuses only.
- This project is not a brokerage integration and does not transmit private keys.
- Treat all adapters and strategies as research code until a separate, audited execution stack exists.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run sample experiments:

```bash
q-lab schedule --config config/examples/mvp.toml
q-lab leaderboard --results-path data/results.jsonl
```

Run tests:

```bash
python3 -m unittest discover -s tests -p "test_*.py"
```

## Extension Points

- Add new evaluators by implementing `Evaluator` in `q_lab.evaluators.base`.
- Add alternate stores by implementing `ResultsStore`.
- Plug in new experiment sources by implementing `ExperimentSource`.
- Keep safety controls explicit when adding any exchange or broker adapter.

## Initial research scope

First-pass research pack:
- Venue: Hyperliquid perps
- Assets: BTC + ETH first
- Positioning: simple long / flat / short, no leverage
- Model families: baseline rules, linear models, boosting models
- Exogenous features: Polymarket + Kalshi event-market signals

Planned Polymarket / Kalshi feature families:
- contract implied probabilities
- probability change / momentum
- dispersion across related contracts
- disagreement between venues
- event proximity / resolution-window flags
- macro/risk sentiment overlays mapped onto crypto regime features

These are intended as **exogenous research features**, not as direct execution signals by themselves.

## Roadmap (post-MVP)

- Add experiment registry and queue backends (SQLite/Redis).
- Add structured risk evaluator pipeline.
- Add Polymarket/Kalshi ingestion adapters and feature normalization.
- Add reporting artifacts and richer metrics schema.
- Add secrets management and policy checks for production environments.
