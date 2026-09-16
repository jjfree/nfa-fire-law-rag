import json
from pathlib import Path
from typing import Annotated

import typer

from app.crawler.categories import category_urls_for_codes
from app.ingest import (
    crawl_categories,
    crawl_category,
    probe_category,
    reprocess_current_laws,
)

app = typer.Typer(help="台灣消防法規 RAG management CLI")


@app.command("init-db")
def init_db_command():
    """Create the configured storage schema and SQLite FTS5 index."""
    from app.db import init_db

    init_db()
    typer.echo("Database initialized.")


@app.command("rebuild-fts")
def rebuild_fts_command():
    """Rebuild the SQLite FTS5 index from current law versions."""
    from app.db import rebuild_fts, session_scope

    with session_scope() as db:
        rebuild_fts(db)
    typer.echo("FTS index rebuilt (or skipped for PostgreSQL).")


@app.command("probe")
def probe_command(max_laws: int = typer.Option(default=3, min=1, max=50)):
    """Fetch/parse a few live NFA laws without requiring PostgreSQL."""
    try:
        result = probe_category(max_laws=max_laws)
    except Exception as exc:
        typer.echo(
            json.dumps(
                {"status": "error", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
                indent=2,
            ),
            err=True,
        )
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("crawl")
def crawl_command(
    max_laws: int | None = typer.Option(default=None, min=1),
    categories: str | None = typer.Option(
        default=None,
        help="Comma-separated supported NFA category codes, for example A001,A002,A003.",
    ),
):
    """Crawl one or more NFA categories and ingest changed laws."""
    if categories:
        category_urls = category_urls_for_codes(categories.split(","))
        result = crawl_categories(category_urls, max_laws=max_laws)
    else:
        result = crawl_category(max_laws=max_laws)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("reprocess-current")
def reprocess_current_command(
    apply: Annotated[
        bool,
        typer.Option(help="Apply changes. Without this flag the command is a read-only dry-run."),
    ] = False,
    law_id: Annotated[
        list[int] | None,
        typer.Option(min=1, help="Limit processing; repeat --law-id as needed."),
    ] = None,
):
    """Reparse stored current versions after a parser revision, without crawling."""
    result = reprocess_current_laws(apply=apply, law_ids=law_id)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


@app.command("eval")
def eval_command(
    path: Path = typer.Option(Path("eval/phase2_queries.json"), exists=True, dir_okay=False),
    top_k: int = typer.Option(default=8, min=1, max=50),
):
    """Evaluate retrieval hit-rate against the Phase-2 query set."""
    from app.evaluation import evaluate_retrieval, load_eval_cases

    result = evaluate_retrieval(load_eval_cases(path), top_k=top_k)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    app()
