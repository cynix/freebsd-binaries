import re
from fnmatch import fnmatchcase
from functools import partial

from github import Github
from github.GitRelease import GitRelease


def get_version(rls: GitRelease) -> str:
    ver = rls.tag_name

    if m := re.match("v?(.+)", ver):
        ver = m.group(1)

    return ver


def get_release(gh: Github, repo: str, match: str | None) -> tuple[GitRelease, str]:
    r = gh.get_repo(repo)

    if not match:
        rls = r.get_latest_release()
        return rls, get_version(rls)

    if match.startswith("/") and match.endswith("/"):
        regex = re.compile(f"^{match[1:-1]}$")
        test = partial(re.search, regex)
    elif "*" in match:
        test = partial(fnmatchcase, pat=match)
    else:
        test = partial(lambda a, b: a == b, match)

    for rls in r.get_releases():
        if rls.prerelease:
            continue

        if m := test(rls.tag_name):
            return rls, get_version(rls) if m is True else m.group("version")

    raise RuntimeError(f"No matching release: {match}")
