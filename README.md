# 🎯 Issue Hunter

Search GitHub for **open, unassigned issues** that nobody is fixing yet — perfect for finding your next open-source contribution.

## Features

- 🔍 Searches any public GitHub repository for open issues with **no assignee**
- 🌍 **Global discover mode** — find huntable issues across all of GitHub, filtered by repository stars
- 🚫 Automatically excludes issues that already have a **linked pull request** using multi-strategy detection:
  - Timeline events API (cross-referenced PRs)
  - Issue body scanning for PR URLs and "fixes #N" patterns
  - Search API for open PRs referencing the issue
- 🏷️ Filter by **labels** (e.g. `bug`, `good first issue`, `help wanted`)
- 📝 Free-text **query** support
- 🌐 Filter by **programming language** (discover mode)
- ⭐ Filter by **repository stars** (discover mode)
- 📊 Rich terminal table output or **JSON** export
- 🔑 Optional GitHub token support for higher rate limits
- ⚡ Rate-limit aware — backs off automatically when limits are low

## Installation

## PyPI
```bash
pip install issuehunter
```

## Source
```bash
pip install -e .
```

## Usage

### Basic hunt (single repo)

```bash
issuehunter hunt facebook/react
```

### Filter by labels

```bash
issuehunter hunt facebook/react -l "bug" -l "good first issue"
```

### Free-text search

```bash
issuehunter hunt microsoft/vscode -q "memory leak"
```

### Limit results

```bash
issuehunter hunt torvalds/linux -n 10
```

### JSON output (for scripting)

```bash
issuehunter hunt python/cpython --json | jq '.[].title'
```

### Skip PR check (faster)

```bash
issuehunter hunt rust-lang/rust --no-pr-check
```

---

### 🌍 Global discover mode

Find huntable issues across **all of GitHub** without specifying a repository:

```bash
# Issues in repos with 1000+ stars (default)
issuehunter discover

# Issues in repos with 5000+ stars
issuehunter discover --min-stars 5000

# Star range: 500–2000 stars
issuehunter discover --min-stars 500 --max-stars 2000

# Filter by language
issuehunter discover --language python --min-stars 1000

# Filter by label
issuehunter discover -l "good first issue" --min-stars 500

# Sort by most commented
issuehunter discover --sort comments

# JSON output with repo stars
issuehunter discover --json
```

### Check rate limits

```bash
issuehunter ratelimit
```

## Authentication

Set a GitHub personal access token to increase API rate limits (60 → 5000 requests/hour):

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

Or pass it directly:

```bash
issuehunter hunt owner/repo --token ghp_your_token_here
```

## How it works

1. Uses the GitHub **Search Issues API** with qualifiers: `is:issue is:open no:assignee`
2. For each candidate, runs **multi-strategy PR detection**:
   - **Timeline events** — checks for `cross-referenced` and `connected` events from PRs
   - **Body scanning** — regex-matches PR URLs and "fixes/closes/resolves #N" patterns
   - **PR search** — queries the Search API for open PRs mentioning the issue number
3. Issues with a linked PR (open or closed) are excluded
4. In discover mode, repository star counts are fetched and cached for display
5. Results are sorted by creation date (newest first) by default

## License

MIT
