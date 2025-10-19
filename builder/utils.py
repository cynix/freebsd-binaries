import re
from collections.abc import Callable
from fnmatch import fnmatchcase
from functools import partial

from github import Github
from github.GitRelease import GitRelease
from packaging.version import Version


def _match_fn(match: str | None) -> Callable[[str], bool | re.Match[str] | None]:
    if not match:
        return bool
    elif match.startswith("/") and match.endswith("/"):
        regex = re.compile(f"^{match[1:-1]}$")
        return regex.search
    elif "*" in match:
        return partial(fnmatchcase, pat=match)
    else:
        return partial(lambda a, b: a == b, match)


def _parse_version(
    tag: str, test: Callable[[str], bool | re.Match[str] | None]
) -> Version | None:
    m = test(tag)
    if not m:
        return Version("0")

    if m is True:
        return Version(tag.lstrip("v"))

    return Version(m.group("version"))


def get_release(gh: Github, repo: str, match: str | None) -> tuple[GitRelease, str]:
    r = gh.get_repo(repo)

    if not match:
        rls = r.get_latest_release()
        return rls, rls.tag_name.lstrip("v")

    if match.startswith("/") and match.endswith("/"):
        regex = re.compile(f"^{match[1:-1]}$")
        test = regex.search
    elif "*" in match:
        test = partial(fnmatchcase, pat=match)
    else:
        test = partial(lambda a, b: a == b, match)

    for rls in r.get_releases():
        if rls.prerelease:
            continue

        if ver := _parse_version(rls.tag_name, test):
            return rls, str(ver)

    raise RuntimeError(f"No matching release in {repo}: {match}")


def get_tag(gh: Github, repo: str, match: str | None) -> tuple[str, str]:
    test = _match_fn(match)

    try:
        tag, ver = max(
            [
                (x.name, _parse_version(x.name, test))
                for x in gh.get_repo(repo).get_tags()
            ],
            key=lambda x: x[1] or Version("0"),
        )
        return tag, str(ver)
    except Exception:
        raise RuntimeError(f"No matching tag in {repo}: {match}")
