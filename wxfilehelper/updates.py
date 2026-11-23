"""Read-only GitHub release checks; no installer execution or silent downloads."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from . import __version__, REPOSITORY

RELEASE_API = "https://api.github.com/repos/Watertube-bilibili/wxfilehelper-macos/releases?per_page=20"


def version_key(version: str) -> tuple:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?", version)
    if not match:
        raise ValueError("Unsupported version tag")
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), {"alpha": 0, "beta": 1, "rc": 2, None: 3}[stage], int(number or 0))


@dataclass
class Update:
    version: str
    url: str


def select_update(releases: list, current: str = __version__) -> Update | None:
    current_key = version_key(current)
    candidates = []
    for release in releases:
        if release.get("draft") or (release.get("prerelease") and "-" not in current):
            continue
        try:
            key = version_key(release["tag_name"])
            url = release["html_url"]
            p = urlsplit(url)
            expected = urlsplit(REPOSITORY)
            if p.scheme != "https" or p.netloc != expected.netloc or not p.path.startswith(expected.path + "/releases/tag/"):
                continue
            if key > current_key:
                candidates.append((key, Update(release["tag_name"], url)))
        except (KeyError, TypeError, ValueError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def check_for_update() -> Update | None:
    with requests.get(RELEASE_API, timeout=(8, 12), allow_redirects=False, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "wxfilehelper-macos-update-check"}) as response:
        if response.status_code != 200:
            raise RuntimeError("Update service unavailable / 暂时无法检查更新")
        if len(response.content) > 2 * 1024 * 1024:
            raise RuntimeError("Invalid release response / 更新响应异常")
        data = response.json()
        if not isinstance(data, list):
            raise RuntimeError("Invalid release response / 更新响应异常")
        return select_update(data)
