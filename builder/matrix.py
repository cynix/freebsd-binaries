import json

from actions import core
from actions.github import get_githubkit
from githubkit import GitHub
from ruamel.yaml import YAML

from .utils import get_release, get_tag


def _get_tag(gh: GitHub, project) -> tuple[str, str]:
    tag, ver = (
        get_tag(gh, project["repo"], project.get("match"))
        if project.get("tag")
        else get_release(gh, project["repo"], project.get("match"))
    )
    return (tag, ver) if isinstance(tag, str) else (tag.tag_name, ver)


def matrix():
    with open("projects.yaml") as f:
        y = YAML().load(f)

    projects = core.get_input("projects")
    rebuild = core.get_boolean_input("rebuild")

    gh = get_githubkit()

    releases = (
        []
        if rebuild
        else [
            x.tag_name
            for x in gh.rest.paginate(
                gh.rest.repos.list_releases, owner="cynix", repo="freebsd-binaries"
            )
            if not x.prerelease
        ]
    )
    matrix = []

    for name in sorted(
        y.keys() if projects == "all" else set(x.strip() for x in projects.split(","))
    ):
        config = y[name]

        project = {"project": name}
        packages = []
        containers = []

        if go := config.get("go"):
            tag, ver = _get_tag(gh, go)
            project["version"] = ver

            if f"{name}-v{ver}" not in releases:
                packages.extend(
                    {
                        "package": k,
                        "type": "go",
                        "repo": go["repo"],
                        "ref": tag,
                        "cgo": go.get("cgo", False),
                    }
                    for k in sorted(go["packages"].keys())
                )

            containers = [
                k
                for k in sorted(go["packages"].keys())
                if "container" in go["packages"][k]
            ]
        elif kv := next(
            ((k, config[k]) for k in ("maturin", "rust", "wheel") if k in config), None
        ):
            tag, ver = _get_tag(gh, kv[1])
            project["version"] = ver

            if f"{name}-v{ver}" not in releases:
                packages.extend(
                    {
                        "package": p,
                        "type": kv[0],
                        "repo": kv[1]["repo"],
                        "ref": tag,
                    }
                    for p in sorted(kv[1].get("packages", {name: None}).keys())
                )
        elif "container" in config:
            containers = [name]
        else:
            core.set_failed("Unknown project type")
            return 1

        if packages:
            project["packages"] = json.dumps(packages)
        if containers:
            project["containers"] = json.dumps(containers)

        matrix.append(project)

    core.set_output("matrix", {"include": matrix})
