import typer

app = typer.Typer()


@app.command()
def ingest(repo: str, pr: int) -> None:
    raise NotImplementedError


@app.command()
def review(feature_scope: str) -> None:
    raise NotImplementedError


if __name__ == "__main__":
    app()
