"""CLI:  python -m app.evaluation.run_evaluation [--datasets a b] [--max-cases N] [--no-judge] [--calibrate]"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid


async def _main(args) -> None:
    from app.agents.graph import build_graph
    from app.config import get_settings
    from app.core.logging import setup_logging
    from app.database.connection import dispose_engine, get_sessionmaker, init_engine, init_schema
    from app.database.seed import seed_database
    from app.dependencies import resources
    from app.evaluation.runners.dataset_runner import run_evaluation
    from app.main import _init_checkpointer

    s = get_settings()
    setup_logging(s.log_level)
    init_engine(s)
    await init_schema(s)
    await seed_database(get_sessionmaker(), s.seed_file)
    saver, pool = await _init_checkpointer(s)
    resources.checkpointer = saver
    try:
        if args.calibrate:
            from app.evaluation.judges.llm_judge import calibrate_judge
            print(json.dumps(await calibrate_judge(), indent=2))
            return
        eid = uuid.uuid4().hex[:12]
        report = await run_evaluation(eid, build_graph(saver), datasets=args.datasets, max_cases=args.max_cases,
                                      use_judge=not args.no_judge)
        print(json.dumps(report["summary"], indent=2, ensure_ascii=False))
        print(f"\nreport: {s.reports_dir / (eid + '.json')}\nfailed: {report['failed_cases']}")
    finally:
        if pool is not None:
            await pool.close()
        await dispose_engine()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--datasets", nargs="*")
    ap.add_argument("--max-cases", type=int)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--calibrate", action="store_true", help="check the judge against human-labelled reference examples")
    asyncio.run(_main(ap.parse_args()))


if __name__ == "__main__":
    main()
