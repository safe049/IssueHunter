"""Command-line interface for Issue Hunter."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .github_client import GitHubClient
from .models import Issue

console = Console()


@click.group()
@click.version_option(package_name="issuehunter")
def main() -> None:
    """Issue Hunter – find open, unassigned GitHub issues nobody is fixing."""


@main.command()
@click.argument("repo")
@click.option(
    "-l",
    "--label",
    "labels",
    multiple=True,
    help="Filter by label (repeatable).",
)
@click.option(
    "-q",
    "--query",
    default="",
    help="Free-text search terms.",
)
@click.option(
    "-n",
    "--max-results",
    default=20,
    show_default=True,
    help="Maximum number of issues to display.",
)
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    default="",
    help="GitHub personal access token (or set GITHUB_TOKEN env var).",
)
@click.option(
    "--no-pr-check",
    is_flag=True,
    default=False,
    help="Skip the linked-PR check (faster, less accurate).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output results as JSON instead of a table.",
)
def hunt(
    repo: str,
    labels: tuple[str, ...],
    query: str,
    max_results: int,
    token: str,
    no_pr_check: bool,
    output_json: bool,
) -> None:
    """Hunt for unassigned, unfixed issues in REPO (owner/name)."""
    client = GitHubClient(token=token or None)

    with console.status(
        f"[bold cyan]Searching {repo} for huntable issues…",
        spinner="dots",
    ):
        result = client.search_issues(
            repo=repo,
            labels=list(labels) if labels else None,
            query=query,
            max_results=max_results,
            include_pr_check=not no_pr_check,
        )

    if output_json:
        _print_json(result.issues)
        return

    if not result.issues:
        console.print(
            f"[yellow]No huntable issues found in [bold]{repo}[/bold].[/yellow]"
        )
        return

    _print_table(result.issues, repo)
    console.print(
        f"\n[dim]Found {result.filtered_count} huntable issue(s) "
        f"(total matching: {result.total_count})[/dim]"
    )


@main.command()
@click.option(
    "--min-stars",
    default=1000,
    show_default=True,
    help="Minimum repository stars.",
)
@click.option(
    "--max-stars",
    default=None,
    type=int,
    help="Maximum repository stars (optional upper bound).",
)
@click.option(
    "-l",
    "--label",
    "labels",
    multiple=True,
    help="Filter by label (repeatable).",
)
@click.option(
    "-q",
    "--query",
    default="",
    help="Free-text search terms.",
)
@click.option(
    "--language",
    default="",
    help="Filter by programming language (e.g. python, javascript).",
)
@click.option(
    "-n",
    "--max-results",
    default=20,
    show_default=True,
    help="Maximum number of issues to display.",
)
@click.option(
    "--sort",
    type=click.Choice(["created", "updated", "comments"]),
    default="created",
    show_default=True,
    help="Sort order for results.",
)
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    default="",
    help="GitHub personal access token (or set GITHUB_TOKEN env var).",
)
@click.option(
    "--no-pr-check",
    is_flag=True,
    default=False,
    help="Skip the linked-PR check (faster, less accurate).",
)
@click.option(
    "--json",
    "output_json",
    is_flag=True,
    default=False,
    help="Output results as JSON instead of a table.",
)
def discover(
    min_stars: int,
    max_stars: int | None,
    labels: tuple[str, ...],
    query: str,
    language: str,
    max_results: int,
    sort: str,
    token: str,
    no_pr_check: bool,
    output_json: bool,
) -> None:
    """Discover huntable issues across GitHub (no repo required).

    Searches all of GitHub for open, unassigned issues in repositories
    with at least MIN_STARS stars.  Useful for finding contribution
    opportunities in popular projects.
    """
    client = GitHubClient(token=token or None)

    star_desc = f"stars>={min_stars}"
    if max_stars:
        star_desc = f"stars:{min_stars}..{max_stars}"

    with console.status(
        f"[bold cyan]Discovering issues across GitHub ({star_desc})…",
        spinner="dots",
    ):
        result = client.discover_issues(
            min_stars=min_stars,
            max_stars=max_stars,
            labels=list(labels) if labels else None,
            query=query,
            language=language,
            max_results=max_results,
            include_pr_check=not no_pr_check,
            sort=sort,
        )

    if output_json:
        _print_json(result.issues, include_repo=True)
        return

    if not result.issues:
        console.print(
            "[yellow]No huntable issues found matching criteria.[/yellow]"
        )
        return

    _print_discover_table(result.issues)
    console.print(
        f"\n[dim]Found {result.filtered_count} huntable issue(s) "
        f"(total matching: {result.total_count})[/dim]"
    )


@main.command()
@click.option(
    "--token",
    envvar="GITHUB_TOKEN",
    default="",
    help="GitHub personal access token.",
)
def ratelimit(token: str) -> None:
    """Show current GitHub API rate-limit status."""
    client = GitHubClient(token=token or None)
    info = client.check_rate_limit()
    core = info.get("resources", {}).get("core", {})
    search = info.get("resources", {}).get("search", {})

    table = Table(title="GitHub API Rate Limits")
    table.add_column("Resource", style="cyan")
    table.add_column("Limit", justify="right")
    table.add_column("Remaining", justify="right")
    table.add_column("Reset", justify="right")

    for name, data in [("core", core), ("search", search)]:
        table.add_row(
            name,
            str(data.get("limit", "?")),
            str(data.get("remaining", "?")),
            str(data.get("reset", "?")),
        )
    console.print(table)


# ------------------------------------------------------------------
# Output helpers
# ------------------------------------------------------------------


def _print_table(issues: list[Issue], repo: str) -> None:
    table = Table(
        title=f"🎯 Huntable Issues in {repo}",
        show_lines=True,
        title_style="bold magenta",
    )
    table.add_column("#", style="dim", width=6, justify="right")
    table.add_column("Title", style="bold", max_width=60)
    table.add_column("Labels", style="cyan", max_width=30)
    table.add_column("Age", justify="right", width=8)
    table.add_column("Comments", justify="right", width=9)

    for issue in issues:
        label_str = ", ".join(issue.label_names) if issue.label_names else "—"
        age = f"{issue.age_days}d"
        table.add_row(
            str(issue.number),
            issue.title,
            label_str,
            age,
            str(issue.comments),
        )

    console.print(table)
    console.print()
    for issue in issues:
        console.print(f"  [dim]#{issue.number}[/dim] {issue.html_url}")


def _print_discover_table(issues: list[Issue]) -> None:
    table = Table(
        title="🌍 Discovered Huntable Issues",
        show_lines=True,
        title_style="bold magenta",
    )
    table.add_column("Repo", style="green", max_width=30)
    table.add_column("#", style="dim", width=6, justify="right")
    table.add_column("Title", style="bold", max_width=50)
    table.add_column("Labels", style="cyan", max_width=25)
    table.add_column("⭐", justify="right", width=7)
    table.add_column("Age", justify="right", width=7)

    for issue in issues:
        label_str = ", ".join(issue.label_names) if issue.label_names else "—"
        age = f"{issue.age_days}d"
        stars = f"{issue.repo_stars:,}" if issue.repo_stars else "—"
        table.add_row(
            issue.repository,
            str(issue.number),
            issue.title,
            label_str,
            stars,
            age,
        )

    console.print(table)
    console.print()
    for issue in issues:
        console.print(f"  [dim]{issue.repository} #{issue.number}[/dim] {issue.html_url}")


def _print_json(issues: list[Issue], include_repo: bool = False) -> None:
    import json

    data = []
    for i in issues:
        entry = {
            "number": i.number,
            "title": i.title,
            "url": i.html_url,
            "labels": i.label_names,
            "comments": i.comments,
            "created_at": i.created_at.isoformat(),
            "age_days": i.age_days,
            "author": i.author,
            "repository": i.repository,
        }
        if include_repo:
            entry["repo_stars"] = i.repo_stars
        data.append(entry)

    click.echo(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()