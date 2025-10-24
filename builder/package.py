import os
import subprocess
import sys
import tarfile
from functools import partial
from pathlib import Path

from actions import core
from ruamel.yaml import YAML

from .config import (
    Architecture,
    BuilderType,
    CargoPackage,
    Config,
    GoPackage,
    MaturinPackage,
    PackageProject,
    UvPackage,
)
from .utils import action_group, apply_patches, dockcross


def _root_owner(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = 0
    ti.gid = 0
    ti.uname = ""
    ti.gname = ""
    return ti


def _build_go(
    project: str,
    version: str,
    name: str,
    package: GoPackage,
    archs: list[Architecture],
    cgo: bool,
):
    goreleaser = {
        "version": 2,
        "project_name": name,
        "dist": "../dist",
        "archives": [
            {
                "formats": ["tar.gz"],
                "name_template": '{{ .ProjectName }}-{{ .Version }}-{{ .Os }}_{{ .Arch }}{{ with .Arm }}v{{ . }}{{ end }}{{ with .Mips }}_{{ . }}{{ end }}{{ if not (eq .Amd64 "v1") }}{{ .Amd64 }}{{ end }}',
                "files": package.files,
            }
        ],
        "release": {
            "disable": True,
        },
    }

    if package.before:
        goreleaser["before"] = {"hooks": package.before}

    template = {
        "flags": package.flags + ["-trimpath"],
        "ldflags": package.ldflags
        + [
            "-buildid=",
            "-extldflags=-static",
            "-s",
            "-w",
        ],
        "tags": package.tags,
        "targets": [f"freebsd_{x.value}" for x in archs],
        "env": [],
    }

    if cgo:
        template["env"].extend(
            [
                "CGO_ENABLED=1",
                'CGO_CFLAGS=--target={{ if eq .Arch "amd64" }}x86_64{{ else }}aarch64{{ end }}-unknown-freebsd --sysroot=/freebsd/{{ .Arch }}',
                'CGO_LDFLAGS=--target={{ if eq .Arch "amd64" }}x86_64{{ else }}aarch64{{ end }}-unknown-freebsd --sysroot=/freebsd/{{ .Arch }} -fuse-ld=lld',
                "PKG_CONFIG_LIBDIR=/freebsd/{{ .Arch }}/usr/libdata/pkgconfig:/freebsd/{{ .Arch }}/usr/local/libdata/pkgconfig",
                "PKG_CONFIG_PATH=",
                "PKG_CONFIG_SYSROOT_DIR=/freebsd/{{ .Arch }}",
            ]
        )
    else:
        template["env"].append("CGO_ENABLED=0")

    goreleaser["builds"] = []

    for binary in package.binaries:
        build = template | {
            "id": binary,
            "binary": binary,
            "main": package.main.format(binary=binary),
        }
        goreleaser["builds"].append(build)

    with action_group("Generating .goreleaser.yaml"):
        with open(".goreleaser.yaml", "w") as f:
            YAML(typ="safe", pure=True).dump(goreleaser, f)
        subprocess.run(["cat", ".goreleaser.yaml"])

    cmd = [
        "sh",
        "-c",
        "cd src; goreleaser release --config=../.goreleaser.yaml --clean --skip=validate",
    ]

    if cgo:
        dockcross(cmd)
    else:
        subprocess.check_call(cmd)


def _build_package():
    project = core.get_input("project")
    version = core.get_input("version")
    name = core.get_input("package")

    apply_patches(project)

    config = Config.from_yaml("projects.yaml").root[project]
    assert isinstance(config, PackageProject)

    package = config.packages[name]

    if isinstance(package, UvPackage):
        if not sys.platform.startswith("freebsd"):
            raise RuntimeError("Wheels must be built on FreeBSD")
        archs = [Architecture.AMD64]
    else:
        archs = config.arch

    if isinstance(package, GoPackage):
        _build_go(
            project, version, name, package, archs, config.builder == BuilderType.CGO
        )
        return

    for arch in archs:
        env = None

        if isinstance(package, CargoPackage):
            cmd = ["cargo", "build"]
        elif isinstance(package, MaturinPackage):
            cmd = ["uvx", "--no-config", "maturin", "build", "--locked", "--out=dist"]
            env = {"MATURIN_FREEBSD_VERSION": "14.3"}
        else:
            assert isinstance(package, UvPackage)
            cmd = [
                "uv",
                "build",
                "--wheel",
                "--locked",
                "--out-dir=dist",
                "--find-links=https://github.com/cynix/freebsd-binaries/releases/download/maturin-v1.9.6/wheels.html",
                "--find-links=https://github.com/cynix/freebsd-binaries/releases/download/uv-v0.9.5/wheels.html",
            ]

        triple = f"{'x86_64' if arch == 'amd64' else 'aarch64'}-unknown-freebsd"

        if isinstance(package, UvPackage):
            run = subprocess.check_call
            cmd.extend(["--python=3.12", f"--package={name}"])
        else:
            run = partial(dockcross, arch=arch)
            cmd.extend(
                [
                    f"--target={triple}",
                    f"--profile={package.profile}",
                    f"--manifest-path={package.manifest}",
                    "--strip"
                    if isinstance(package, MaturinPackage)
                    else f'--config=profile.{package.profile}.strip="symbols"',
                ]
            )

            if package.features:
                if "-default" in package.features:
                    cmd.append("--no-default-features")
                cmd.append(
                    f"--features={','.join(x for x in package.features if not x.startswith('-'))}"
                )

            if arch == Architecture.ARM64:
                cmd.extend(["-Z", "build-std=core,std,alloc,proc_macro,panic_abort"])

        core.info(f"Running {cmd}")
        run(cmd, cwd="src", env=env)

        if isinstance(package, CargoPackage):
            os.makedirs("src/dist", exist_ok=True)
            tgz = f"src/dist/{name}-v{version}-{triple}.tar.gz"

            with action_group(f"Creating {tgz}"):
                with tarfile.open(tgz, "w:gz", compresslevel=2) as tar:
                    base = Path(f"src/target/{triple}/{package.profile}")

                    for bin in [base / x for x in package.binaries]:
                        bin: Path
                        if not bin.is_file() or bin.stat().st_mode & 0o111 != 0o111:
                            raise RuntimeError(f"{bin} is not an executable")

                        core.info(f"Adding {bin}")
                        tar.add(bin, bin.name, filter=_root_owner)

                    base = Path("src")

                    for glob in package.files:
                        for f in base.glob(glob):
                            core.info(f"Adding {f}")
                            tar.add(f, filter=_root_owner)

    os.rename("src/dist", "dist")


def build_package():
    try:
        _build_package()
    except Exception as e:
        core.set_failed(e)
        return 1
