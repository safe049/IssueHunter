"""Data models for Issue Hunter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Label:
    """A GitHub issue label."""

    name: str
    color: str = ""

    @classmethod
    def from_api(cls, data: dict) -> Label:
        return cls(name=data.get("name", ""), color=data.get("color", ""))


@dataclass
class Issue:
    """A GitHub issue with metadata relevant to hunting."""

    number: int
    title: str
    html_url: str
    state: str
    created_at: datetime
    updated_at: datetime
    labels: list[Label] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comments: int = 0
    body: str = ""
    repository: str = ""
    author: str = ""
    has_linked_pr: bool = False
    repo_stars: int = 0
    pr_detection_method: str = ""

    @classmethod
    def from_api(cls, data: dict, repository: str = "") -> Issue:
        labels = [Label.from_api(l) for l in data.get("labels", [])]
        assignees = [a.get("login", "") for a in data.get("assignees", [])]
        author = data.get("user", {}).get("login", "")

        created_at = _parse_datetime(data.get("created_at", ""))
        updated_at = _parse_datetime(data.get("updated_at", ""))

        return cls(
            number=data.get("number", 0),
            title=data.get("title", ""),
            html_url=data.get("html_url", ""),
            state=data.get("state", ""),
            created_at=created_at,
            updated_at=updated_at,
            labels=labels,
            assignees=assignees,
            comments=data.get("comments", 0),
            body=data.get("body", "") or "",
            repository=repository,
            author=author,
        )

    @property
    def is_unassigned(self) -> bool:
        """Return True if no assignees are set."""
        return len(self.assignees) == 0

    @property
    def label_names(self) -> list[str]:
        return [l.name for l in self.labels]

    @property
    def age_days(self) -> int:
        """Days since the issue was created."""
        now = datetime.now(self.created_at.tzinfo)
        return (now - self.created_at).days


@dataclass
class SearchResult:
    """Aggregated search results."""

    issues: list[Issue] = field(default_factory=list)
    total_count: int = 0
    query: str = ""
    repository: str = ""

    @property
    def filtered_count(self) -> int:
        return len(self.issues)


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO 8601 datetime string from the GitHub API."""
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min