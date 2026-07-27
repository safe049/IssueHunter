"""GitHub API client for Issue Hunter."""

from __future__ import annotations

import os
import re
import time

import requests

from .models import Issue, SearchResult

GITHUB_API_BASE = "https://api.github.com"
SEARCH_ISSUES_ENDPOINT = f"{GITHUB_API_BASE}/search/issues"
PER_PAGE = 30
MAX_PAGES = 10  # GitHub search caps at 1000 results (≈34 pages of 30)

# Regex patterns for detecting PR references in issue bodies
_PR_KEYWORD_RE = re.compile(
    r"(?:fix(?:es|ed)?|clos(?:es|ed)?|resolv(?:es|ed)?|address(?:es|ed)?)\s+"
    r"(?:https?://github\.com/[\w.-]+/[\w.-]+/pull/(\d+)"
    r"|[#](\d+))",
    re.IGNORECASE,
)
_PR_URL_RE = re.compile(
    r"https?://github\.com/[\w.-]+/[\w.-]+/pull/\d+", re.IGNORECASE
)


class GitHubClient:
    """Thin wrapper around the GitHub REST API for issue searching."""

    def __init__(self, token: str | None = None, timeout: int = 30) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        if self.token:
            self._session.headers["Authorization"] = f"Bearer {self.token}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_issues(
        self,
        repo: str,
        labels: list[str] | None = None,
        query: str = "",
        max_results: int = 100,
        include_pr_check: bool = True,
    ) -> SearchResult:
        """Search a repository for open, unassigned issues nobody is fixing.

        Parameters
        ----------
        repo:
            Repository in ``owner/name`` format.
        labels:
            Optional list of label names to filter by (e.g. ``["bug"]``).
        query:
            Free-text search terms.
        max_results:
            Maximum number of filtered issues to return.
        include_pr_check:
            When *True* (default), each candidate issue is checked for
            linked pull requests via multiple detection strategies.
            Issues with an open linked PR are excluded.
        """
        q_parts = [f"repo:{repo}", "is:issue", "is:open", "no:assignee"]
        if labels:
            for label in labels:
                q_parts.append(f'label:"{label}"')
        if query:
            q_parts.append(query)

        q = " ".join(q_parts)
        issues: list[Issue] = []
        total_count = 0

        for page in range(1, MAX_PAGES + 1):
            if len(issues) >= max_results:
                break

            data = self._search_page(q, page)
            if data is None:
                break

            total_count = data.get("total_count", 0)
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                issue = Issue.from_api(item, repository=repo)
                if not issue.is_unassigned:
                    continue
                if include_pr_check:
                    has_pr, method = self._detect_linked_pr(
                        repo, issue.number, issue.body
                    )
                    if has_pr:
                        issue.has_linked_pr = True
                        issue.pr_detection_method = method
                        continue
                issues.append(issue)
                if len(issues) >= max_results:
                    break

            # Respect rate limits
            self._wait_if_rate_limited()

        return SearchResult(
            issues=issues[:max_results],
            total_count=total_count,
            query=q,
            repository=repo,
        )

    def discover_issues(
        self,
        min_stars: int = 1000,
        max_stars: int | None = None,
        labels: list[str] | None = None,
        query: str = "",
        language: str = "",
        max_results: int = 50,
        include_pr_check: bool = True,
        sort: str = "created",
    ) -> SearchResult:
        """Discover huntable issues across GitHub filtered by repo stars.

        Strategy: first find qualifying repositories via the repository
        search API (which supports the ``stars:`` qualifier), then search
        for open unassigned issues within each qualifying repo.

        Parameters
        ----------
        min_stars:
            Minimum number of stars the repository must have.
        max_stars:
            Optional upper bound on stars.
        labels:
            Optional label filter.
        query:
            Free-text search terms.
        language:
            Programming language filter (e.g. ``python``, ``javascript``).
        max_results:
            Maximum issues to return.
        include_pr_check:
            Whether to exclude issues that already have linked PRs.
        sort:
            Sort order – ``created``, ``updated``, or ``comments``.
        """
        # Step 1: Find qualifying repositories
        repos = self._find_repos_by_stars(
            min_stars=min_stars,
            max_stars=max_stars,
            language=language,
            max_repos=100,
        )

        if not repos:
            return SearchResult(
                issues=[],
                total_count=0,
                query=f"stars>={min_stars}",
                repository=f"GitHub (stars>={min_stars})",
            )

        # Step 2: Search for issues in each qualifying repo
        issues: list[Issue] = []
        total_count = 0

        for repo_name, repo_stars in repos:
            if len(issues) >= max_results:
                break

            q_parts = [
                f"repo:{repo_name}",
                "is:issue",
                "is:open",
                "no:assignee",
            ]
            if labels:
                for label in labels:
                    q_parts.append(f'label:"{label}"')
            if query:
                q_parts.append(query)

            q = " ".join(q_parts)

            data = self._search_page(q, page=1, sort=sort)
            if data is None:
                continue

            total_count += data.get("total_count", 0)
            items = data.get("items", [])

            for item in items:
                issue = Issue.from_api(item, repository=repo_name)
                issue.repo_stars = repo_stars

                if not issue.is_unassigned:
                    continue

                if include_pr_check:
                    has_pr, method = self._detect_linked_pr(
                        repo_name, issue.number, issue.body
                    )
                    if has_pr:
                        issue.has_linked_pr = True
                        issue.pr_detection_method = method
                        continue

                issues.append(issue)
                if len(issues) >= max_results:
                    break

            self._wait_if_rate_limited()

        return SearchResult(
            issues=issues[:max_results],
            total_count=total_count,
            query=f"stars>={min_stars}",
            repository=f"GitHub (stars>={min_stars})",
        )

    def check_rate_limit(self) -> dict:
        """Return current rate-limit info."""
        resp = self._session.get(
            f"{GITHUB_API_BASE}/rate_limit", timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # PR Detection – multi-strategy
    # ------------------------------------------------------------------

    def _detect_linked_pr(
        self, repo: str, issue_number: int, body: str
    ) -> tuple[bool, str]:
        """Detect whether an issue already has a linked pull request.

        Uses three strategies in order of reliability:
        1. Timeline events API (cross-referenced events from PRs)
        2. Body text scanning for PR URLs / "fixes #N" patterns
        3. Search API for open PRs referencing the issue

        Returns (has_pr, detection_method).
        """
        # Strategy 1: Timeline events (most reliable)
        if self._check_timeline_for_pr(repo, issue_number):
            return True, "timeline"

        # Strategy 2: Scan issue body for PR references
        if self._check_body_for_pr_refs(body):
            return True, "body_scan"

        # Strategy 3: Search for PRs that mention this issue
        if self._search_prs_referencing_issue(repo, issue_number):
            return True, "pr_search"

        return False, ""

    def _check_timeline_for_pr(self, repo: str, issue_number: int) -> bool:
        """Check timeline events for cross-references from pull requests."""
        url = (
            f"{GITHUB_API_BASE}/repos/{repo}/issues/{issue_number}/timeline"
        )
        headers = {
            "Accept": "application/vnd.github.mockingbird-preview+json"
        }
        try:
            resp = self._session.get(
                url,
                headers=headers,
                params={"per_page": 100},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return False

            for event in resp.json():
                event_type = event.get("event", "")

                # Direct "connected" / "cross-referenced" events
                if event_type == "cross-referenced":
                    source = event.get("source", {})
                    source_issue = source.get("issue", {})
                    if "pull_request" in source_issue:
                        pr_state = source_issue["pull_request"].get(
                            "state", ""
                        )
                        if pr_state in ("open", "closed"):
                            return True

                # "connected" event (issue linked to PR via UI)
                if event_type in ("connected", "disconnected"):
                    # If connected and not disconnected, there's a PR
                    if event_type == "connected":
                        return True

        except (requests.RequestException, ValueError):
            pass
        return False

    def _check_body_for_pr_refs(self, body: str) -> bool:
        """Scan issue body text for PR URLs or 'fixes #N' patterns."""
        if not body:
            return False

        # Check for explicit PR URLs
        if _PR_URL_RE.search(body):
            return True

        # Check for "fixes/closes/resolves #N" patterns
        if _PR_KEYWORD_RE.search(body):
            return True

        return False

    def _search_prs_referencing_issue(
        self, repo: str, issue_number: int
    ) -> bool:
        """Use the search API to find open PRs that reference this issue."""
        q = f"repo:{repo} is:pr is:open {issue_number}"
        try:
            resp = self._session.get(
                SEARCH_ISSUES_ENDPOINT,
                params={"q": q, "per_page": 5},
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                return False

            data = resp.json()
            items = data.get("items", [])
            for item in items:
                # Verify the PR actually references our issue number
                pr_body = item.get("body", "") or ""
                pr_title = item.get("title", "") or ""
                combined = f"{pr_title} {pr_body}"
                # Look for #N or the issue URL
                if (
                    f"#{issue_number}" in combined
                    or f"/issues/{issue_number}" in combined
                ):
                    return True
        except (requests.RequestException, ValueError):
            pass
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_repos_by_stars(
        self,
        min_stars: int = 1000,
        max_stars: int | None = None,
        language: str = "",
        max_repos: int = 100,
    ) -> list[tuple[str, int]]:
        """Find repositories matching star criteria via the repo search API.

        Returns a list of (full_name, stargazers_count) tuples sorted by
        stars descending.
        """
        # Build the stars qualifier
        if max_stars is not None:
            stars_q = f"stars:{min_stars}..{max_stars}"
        else:
            stars_q = f"stars:>={min_stars}"

        q_parts = [stars_q]
        if language:
            q_parts.append(f"language:{language}")

        q = " ".join(q_parts)
        repos: list[tuple[str, int]] = []

        # Paginate through repo search results
        per_page = min(max_repos, 100)
        pages_needed = (max_repos + per_page - 1) // per_page

        for page in range(1, pages_needed + 1):
            try:
                resp = self._session.get(
                    f"{GITHUB_API_BASE}/search/repositories",
                    params={
                        "q": q,
                        "sort": "stars",
                        "order": "desc",
                        "per_page": per_page,
                        "page": page,
                    },
                    timeout=self.timeout,
                )
                if resp.status_code == 403:
                    retry_after = int(
                        resp.headers.get("Retry-After", "5")
                    )
                    time.sleep(retry_after)
                    resp = self._session.get(
                        f"{GITHUB_API_BASE}/search/repositories",
                        params={
                            "q": q,
                            "sort": "stars",
                            "order": "desc",
                            "per_page": per_page,
                            "page": page,
                        },
                        timeout=self.timeout,
                    )
                if resp.status_code != 200:
                    break

                data = resp.json()
                items = data.get("items", [])
                if not items:
                    break

                for item in items:
                    full_name = item.get("full_name", "")
                    stars = item.get("stargazers_count", 0)
                    if full_name:
                        repos.append((full_name, stars))

                if len(repos) >= max_repos:
                    break

            except (requests.RequestException, ValueError):
                break

        return repos[:max_repos]

    def _search_page(
        self, q: str, page: int, sort: str = "created"
    ) -> dict | None:
        params = {
            "q": q,
            "sort": sort,
            "order": "desc",
            "per_page": PER_PAGE,
            "page": page,
        }
        resp = self._session.get(
            SEARCH_ISSUES_ENDPOINT, params=params, timeout=self.timeout
        )
        if resp.status_code == 403:
            # Secondary rate limit – back off briefly
            retry_after = int(resp.headers.get("Retry-After", "5"))
            time.sleep(retry_after)
            resp = self._session.get(
                SEARCH_ISSUES_ENDPOINT, params=params, timeout=self.timeout
            )
        if resp.status_code != 200:
            return None
        return resp.json()

    def _get_repo_stars(self, repo: str) -> int:
        """Fetch the star count for a repository (cached per session)."""
        if not hasattr(self, "_star_cache"):
            self._star_cache: dict[str, int] = {}
        if repo in self._star_cache:
            return self._star_cache[repo]

        try:
            resp = self._session.get(
                f"{GITHUB_API_BASE}/repos/{repo}", timeout=self.timeout
            )
            if resp.status_code == 200:
                stars = resp.json().get("stargazers_count", 0)
                self._star_cache[repo] = stars
                return stars
        except (requests.RequestException, ValueError):
            pass
        self._star_cache[repo] = 0
        return 0

    def _wait_if_rate_limited(self) -> None:
        """Sleep if we're close to hitting the rate limit."""
        remaining = int(
            self._session.headers.get("X-RateLimit-Remaining", "999")
        )
        if remaining < 5:
            reset_ts = int(
                self._session.headers.get("X-RateLimit-Reset", "0")
            )
            wait = max(reset_ts - int(time.time()), 1)
            time.sleep(min(wait, 60))