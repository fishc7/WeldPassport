from collections.abc import Callable
from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request, urlopen


Transport = Callable[[str, dict[str, str]], object]


@dataclass(frozen=True, slots=True)
class GitHubOverview:
    default_branch: str
    open_pull_requests: int
    latest_ci_conclusion: str | None


def _http_transport(path: str, headers: dict[str, str]) -> object:
    request = Request(f"https://api.github.com{path}", headers=headers, method="GET")
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed GitHub host
        return json.loads(response.read().decode("utf-8"))


class GitHubClient:
    def __init__(self, token: str, transport: Transport = _http_transport) -> None:
        self._transport = transport
        self._headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "WeldPassport-Project-Control",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def overview(self, owner: str, repository: str) -> GitHubOverview:
        root = f"/repos/{owner}/{repository}"
        repository_data = self._as_dict(self._transport(root, self._headers))
        pulls = self._as_list(
            self._transport(f"{root}/pulls?state=open", self._headers)
        )
        workflows = self._as_dict(
            self._transport(f"{root}/actions/runs?per_page=1", self._headers)
        )
        runs = self._as_list(workflows.get("workflow_runs", []))
        latest_conclusion = (
            self._as_dict(runs[0]).get("conclusion") if runs else None
        )
        return GitHubOverview(
            default_branch=str(repository_data["default_branch"]),
            open_pull_requests=len(pulls),
            latest_ci_conclusion=(
                str(latest_conclusion) if latest_conclusion is not None else None
            ),
        )

    @staticmethod
    def _as_dict(value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("GitHub вернул объект неожиданного формата")
        return value

    @staticmethod
    def _as_list(value: object) -> list[Any]:
        if not isinstance(value, list):
            raise ValueError("GitHub вернул список неожиданного формата")
        return value
