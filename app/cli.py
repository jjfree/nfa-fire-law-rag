import json

import typer

from app.db import init_db
from app.ingest import crawl_category

app = typer.Typer(help="NFA Fire Law RAG management CLI")


@app.command("init-db")
def init_db_command():
    """Create PostgreSQL extensions and tables."""
    init_db()
    typer.echo("Database initialized.")


@app.command("crawl")
def crawl_command(max_laws: int | None = typer.Option(default=None, min=1)):
    """Crawl the configured NFA category and ingest changed laws."""
    result = crawl_category(max_laws=max_laws)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    app()
