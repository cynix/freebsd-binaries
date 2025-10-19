import re
from collections.abc import Callable
from fnmatch import fnmatchcase
from functools import partial

from githubkit import GitHub
from githubkit.versions.latest.models import Release
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


def get_release(gh: GitHub, repo: str, match: str | None) -> tuple[Release, str]:
    o, r = repo.split("/", 1)

    if not match:
        rls = gh.rest.repos.get_latest_release(owner=o, repo=r).parsed_data
        return rls, rls.tag_name

    if match.startswith("/") and match.endswith("/"):
        regex = re.compile(f"^{match[1:-1]}$")
        test = regex.search
    elif "*" in match:
        test = partial(fnmatchcase, pat=match)
    else:
        test = partial(lambda a, b: a == b, match)

    for rls in gh.rest.paginate(gh.rest.repos.list_releases, owner=o, repo=r):
        if rls.prerelease:
            continue

        if ver := _parse_version(rls.tag_name, test):
            return rls, str(ver)

    raise RuntimeError(f"No matching release in {repo}: {match}")


def get_tag(gh: GitHub, repo: str, match: str | None) -> tuple[str, str]:
    o, r = repo.split("/", 1)
    test = _match_fn(match)

    try:
        tag, ver = max(
            [
                (x.name, _parse_version(x.name, test))
                for x in gh.rest.paginate(gh.rest.repos.list_tags, owner=o, repo=r)
            ],
            key=lambda x: x[1] or Version("0"),
        )
        return tag, str(ver)
    except Exception:
        raise RuntimeError(f"No matching tag in {repo}: {match}")
