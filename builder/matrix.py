import json

from actions import core
from actions.github import get_github
from ruamel.yaml import YAML

from .utils import get_release


def matrix():
    with open("projects.yaml") as f:
        y = YAML().load(f)

    gh = get_github()
    releases = [
        x.name
        for x in gh.get_repo("cynix/freebsd-containers").get_releases()
        if not x.prerelease
    ]

    projects = core.get_input("projects")
    matrix = []

    for name in sorted(
        y.keys() if projects == "all" else set(x.strip() for x in projects.split(","))
    ):
        config = y[name]

        project = {"project": name}
        packages = {}
        containers = []

        if go := config.get("go"):
            rls, project["version"] = get_release(gh, go["repo"], go.get("match"))

            if f"{name}-v{project['version']}" not in releases:
                packages["go"] = [
                    {
                        "repo": go["repo"],
                        "ref": rls.tag_name,
                        "cgo": go.get("cgo", False),
                        "package": k,
                    }
                    for k in sorted(go["packages"].keys())
                ]

            containers = [
                k
                for k in sorted(go["packages"].keys())
                if "container" in go["packages"][k]
            ]
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
