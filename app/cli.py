import json
from pathlib import Path

import typer

from app.ingest import crawl_category, probe_category

app = typer.Typer(help="NFA Fire Law RAG management CLI")


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
def crawl_command(max_laws: int | None = typer.Option(default=None, min=1)):
    """Crawl the configured NFA category and ingest changed laws."""
    result = crawl_category(max_laws=max_laws)
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
