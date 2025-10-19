import os
import subprocess
import sys
import tarfile
from functools import partial
from pathlib import Path

from actions import core
from ruamel.yaml import YAML

from .utils import action_group, apply_patches, dockcross


def _root_owner(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.uid = 0
    ti.gid = 0
    ti.uname = ""
    ti.gname = ""
    return ti


def build_package():
    yaml = YAML()
    yaml.width = 4096
    yaml.indent(sequence=4, offset=2)

    project = core.get_input("project")
    version = core.get_input("version")
    typ = core.get_input("type")
    name = core.get_input("package")

    apply_patches(project)

    with open("projects.yaml") as f:
        config = yaml.load(f)[project]

    common = config[typ]
    package = common.get("packages", {}).get(name) or {}

    if typ == "wheel":
        if not sys.platform.startswith("freebsd"):
            core.set_failed("Wheels must be built on FreeBSD")
            return 1
        archs = ["amd64"]
    elif typ == "maturin" or typ == "rust":
        archs = config.get("arch", ["amd64", "arm64"])
    else:
        core.set_failed(f"Unknown package type: {typ}")
        return 1

    for arch in archs:
        if typ == "maturin":
            cmd = ["uvx", "--no-config", "maturin", "build", "--locked", "--out=dist"]
        elif typ == "rust":
            cmd = ["cargo", "build"]
        else:
            assert typ == "wheel"
            cmd = ["uv", "build", "--wheel", "--locked", "--out-dir=dist"]

        target = f"{'x86_64' if arch == 'amd64' else 'aarch64'}-unknown-freebsd"
        profile = package.get("profile", common.get("profile", "release"))

        if typ == "wheel":
            run = subprocess.check_call
            cmd.extend(["--python=3.12", f"--package={name}"])
        else:
            run = partial(dockcross, arch=arch)
            cmd.extend(
                [
                    f"--target={target}",
                    f"--profile={profile}",
                    f"--manifest-path={package.get('manifest', 'Cargo.toml')}",
                    "--strip"
                    if typ == "maturin"
                    else f'--config=profile.{profile}.strip="symbols"',
                ]
            )

            if features := package.get("features", common.get("features", [])):
                if features[0] == "-default":
                    features = features[1:]
                    cmd.append("--no-default-features")
                cmd.append(f"--features={','.join(features)}")

            if arch == "arm64":
                cmd.extend(["-Z", "build-std=core,std,alloc,proc_macro,panic_abort"])

        core.info(f"Running {cmd}")
        run(cmd, cwd="src")

        if typ == "rust":
            os.makedirs("dist", exist_ok=True)
            tgz = f"dist/{name}-v{version}-{target}.tar.gz"

            with action_group(f"Creating {tgz}"):
                with tarfile.open(tgz, "w:gz", compresslevel=2) as tar:
                    base = Path(f"src/target/{target}/{profile}")

                    for bin in [base / x for x in package.get("binaries", [name])]:
                        bin: Path
                        if not bin.is_file() or bin.stat().st_mode & 0o111 != 0o111:
                            core.set_failed(f"{bin} is not an executable")
                            return 1

                        core.info(f"Adding {bin}")
                        tar.add(bin, bin.name, filter=_root_owner)

                    base = Path("src")

                    for glob in package.get("files", common.get("files", [])):
                        for f in base.glob(glob):
                            core.info(f"Adding {f}")
                            tar.add(f, filter=_root_owner)

    if typ != "rust":
        os.rename("src/dist", "dist")
