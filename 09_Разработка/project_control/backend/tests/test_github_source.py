from app.sources.github import GitHubClient


def test_collects_read_only_github_overview() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def transport(path: str, headers: dict[str, str]) -> object:
        calls.append((path, headers))
        if path.endswith("/pulls?state=open"):
            return [{"number": 12}, {"number": 13}]
        if path.endswith("/actions/runs?per_page=1"):
            return {"workflow_runs": [{"conclusion": "success"}]}
        return {"default_branch": "main"}

    overview = GitHubClient(token="secret", transport=transport).overview(
        "owner", "repo"
    )

    assert overview.default_branch == "main"
    assert overview.open_pull_requests == 2
    assert overview.latest_ci_conclusion == "success"
    assert all(call[1]["Authorization"] == "Bearer secret" for call in calls)
    assert all(call[0].startswith("/repos/owner/repo") for call in calls)
