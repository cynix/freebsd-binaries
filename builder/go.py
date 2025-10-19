import subprocess

from actions import core
from ruamel.yaml import YAML

from .utils import action_group, apply_patches, dockcross


def build_go():
    yaml = YAML()
    yaml.width = 4096
    yaml.indent(sequence=4, offset=2)

    project = core.get_input("project")
    package = core.get_input("package")

    with open("projects.yaml") as f:
        config = yaml.load(f)[project]
        go = config["go"]

    goreleaser = {
        "version": 2,
        "project_name": package,
        "dist": "../dist",
        "archives": [
            {
                "formats": ["tar.gz"],
                "name_template": '{{ .ProjectName }}-{{ .Version }}-{{ .Os }}_{{ .Arch }}{{ with .Arm }}v{{ . }}{{ end }}{{ with .Mips }}_{{ . }}{{ end }}{{ if not (eq .Amd64 "v1") }}{{ .Amd64 }}{{ end }}',
                "files": go.get("files", ["LICENSE"]),
            }
        ],
        "release": {
            "disable": True,
        },
    }

    if b := go.get("before", []):
        goreleaser["before"] = {"hooks": b}

    template = go.get("build", {})

    template["flags"] = template.get("flags", []) + ["-trimpath"]
    template["ldflags"] = template.get("ldflags", []) + [
        "-buildid=",
        "-extldflags=-static",
        "-s",
        "-w",
    ]
    template["targets"] = [
        f"freebsd_{x}" for x in config.get("arch", ["amd64", "arm64"])
    ]

    if "env" not in template:
        template["env"] = []

    if go.get("cgo"):
        template["env"].extend(
            [
                "CGO_ENABLED=1",
                'CGO_CFLAGS=--target={{ if eq .Arch "amd64" }}x86_64{{ else }}aarch64{{ end }}-unknown-freebsd --sysroot=/freebsd/{{ .Arch }}',
                'CGO_LDFLAGS=--target={{ if eq .Arch "amd64" }}x86_64{{ else }}aarch64{{ end }}-unknown-freebsd --sysroot=/freebsd/{{ .Arch }} -fuse-ld=lld',
                "PKG_CONFIG_SYSROOT_DIR=/freebsd/{{ .Arch }}",
                "PKG_CONFIG_PATH=/freebsd/{{ .Arch }}/usr/local/libdata/pkgconfig",
            ]
        )
    else:
        template["env"].append("CGO_ENABLED=0")

    goreleaser["builds"] = []

    for binary in go["packages"][package].get("binaries", [package]):
        build = template | {"id": binary, "binary": binary}
        build["main"] = build.get("main", "./cmd/{binary}").format(binary=binary)
        goreleaser["builds"].append(build)

    with action_group("Generating .goreleaser.yaml"):
        with open(".goreleaser.yaml", "w") as f:
            yaml.dump(goreleaser, f)
        subprocess.run(["cat", ".goreleaser.yaml"])

    apply_patches(project)

    cmd = [
        "sh",
        "-c",
        "cd src; goreleaser release --config=../.goreleaser.yaml --clean --skip=validate",
    ]

    if go.get("cgo"):
        dockcross(cmd)
    else:
        subprocess.check_call(cmd)
