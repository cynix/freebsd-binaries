import os
import re
import shutil
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from fnmatch import fnmatch
from pathlib import Path
from textwrap import dedent

import requests
from actions import core
from actions.github import get_github
from ruamel.yaml import YAML

from .utils import get_release


def buildah(*args: str, text: bool = True) -> str:
    cmd = ["buildah"]
    cmd.extend(args)

    if text:
        return subprocess.check_output(cmd, text=True).strip()
    else:
        subprocess.check_call(cmd)
        return ""


def pw(m: Path, *args: str):
    subprocess.check_call(["pw", "-R", m] + list(args))


def pkg(
    version: str, arch: str, m: Path, cmd: str, *args: str, text: bool = False
) -> str:
    major, minor, *_ = version.split("p")[0].split(".")

    with open("/usr/local/etc/pkg/repos/FreeBSD.conf", "w") as f:
        print(
            dedent(f"""
            FreeBSD: {{
              url: "pkg+https://pkg.FreeBSD.org/${{ABI}}/latest"
            }}
            FreeBSD-base: {{
              url: "pkg+https://pkg.FreeBSD.org/${{ABI}}/base_release_{minor}",
              mirror_type: "srv",
              signature_type: "fingerprints",
              fingerprints: "/usr/share/keys/pkg",
              enabled: yes
            }}
            FreeBSD-kmods: {{
              enabled: no
            }}
            """),
            file=f,
        )

    env = dict(os.environ)
    env.update(
        IGNORE_OSVERSION="yes",
        PKG_CACHEDIR="/tmp/cache",
        ABI=f"FreeBSD:{major}:{'aarch64' if arch == 'arm64' else arch}",
    )

    if text:
        return subprocess.check_output(
            ["pkg", "--rootdir", m, cmd] + list(args), env=env, text=True
        ).strip()
    else:
        subprocess.check_call(["pkg", "--rootdir", m, cmd, "-y"] + list(args), env=env)
        return ""


def get_version(version: str | dict[str, str] | None) -> str | None:
    if not version:
        return None

    if isinstance(version, str):
        return version

    body = requests.get(version["url"]).text
    if "regex" not in version:
        return body

    if m := re.search(version["regex"], body):
        return m.group("version")

    return None


@contextmanager
def container(manifest: str, base: str, arch: str):
    c = ""
    m = ""

    try:
        c = buildah("from", f"--arch={arch}", f"ghcr.io/cynix/{base}", text=True)
        m = buildah("mount", c, text=True)
        yield (c, Path(m))
    finally:
        if m:
            buildah("unmount", c)
            buildah("commit", f"--manifest={manifest}", "--rm", c)
        elif c:
            buildah("rm", c)


def calculate_dst(src: str, dst: str) -> str:
    if not dst.startswith("/"):
        core.set_failed(f"Invalid dst: {dst}")
        sys.exit(1)

    if dst.endswith("/"):
        dst = f"{dst}{src.rsplit('/', 1)[-1]}"

    return dst


def extract_tarball(m: Path, url: str, files: list[dict[str, str]]) -> str | None:
    t = m / "tmp/tarball"
    t.mkdir()

    core.info(f"Extracting {url}")

    with requests.get(url, stream=True) as r:
        r.raise_for_status()

        with tarfile.open(fileobj=r.raw, mode="r|*") as tar:
            tar.extractall(str(t))

    entrypoint = None

    for file in files:
        src = file["src"]
        dst = file.get("dst", "/usr/local/bin/")

        if not dst.startswith("/"):
            raise RuntimeError(f"Invalid dst: {dst}")

        dir = src.endswith("/")
        src = src.rstrip("/")

        ok = False

        for s in t.rglob(src):
            if s.is_dir() != dir:
                core.set_failed(f"Unexpected tarball content: {s.relative_to(t)}")
                sys.exit(1)

            d = calculate_dst(s.name, dst)

            if not entrypoint and s.is_file() and s.stat().st_mode & 0o111 == 0o111:
                entrypoint = d

            d = m / d[1:]

            core.info(f"{s.relative_to(t)} -> {d.relative_to(m)}")

            d.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            s.move(d)
            ok = True

        if not ok:
            core.set_failed(f"{src} not found")
            sys.exit(1)

    return entrypoint


def build_container():
    gh = get_github()

    with open("projects.yaml") as f:
        project = YAML().load(f)[core.get_input("project")]

    name = core.get_input("container")

    if config := project.get("container"):
        pass
    elif go := project.get("go"):
        go = go["packages"][name]
        config = go["container"]
        binaries = go.get("binaries", [name])
        config["assets"] = [
            {
                "release": "cynix/freebsd-binaries",
                "match": f"/{re.escape(name)}-v(?P<version>{re.escape(core.get_input('version'))})/",
                "glob": f"{name}-freebsd_{{arch}}.tar.gz",
                "files": [{"src": f"**/{x}"} for x in binaries]
                + config.pop("files", []),
            }
        ]
    else:
        core.set_failed("Unknown project type")
        return 1

    latest = f"ghcr.io/cynix/{name}:latest"
    tagged = ""
    buildah("manifest", "create", latest)

    base = config.get(
        "base",
        "freebsd:runtime"
        if any("pkg" in x for x in config["assets"])
        else "freebsd:static",
    )

    image = f"ghcr.io/cynix/{base}"
    subprocess.check_call(["podman", "pull", image])
    version = subprocess.check_output(
        [
            "podman",
            "image",
            "inspect",
            '--format={{index .Annotations "org.freebsd.version"}}',
            image,
        ],
        text=True,
    ).strip()

    for arch in project.get("arch", ["amd64", "arm64"]):
        triple = f"{arch.replace('amd64', 'x86_64').replace('arm64', 'aarch64')}-unknown-freebsd"

        with container(latest, base, arch) as (c, m):
            root = Path(name) / "root"
            if root.is_dir():
                shutil.copytree(root, m, symlinks=True, dirs_exist_ok=True)

            if user := config.get("user"):
                if "=" in user:
                    user, uid = user.split("=")
                    pw(m, "groupadd", "-n", user, "-g", uid)
                    pw(
                        m,
                        "useradd",
                        "-n",
                        user,
                        "-u",
                        uid,
                        "-g",
                        user,
                        "-d",
                        "/nonexistent",
                        "-s",
                        "/sbin/nologin",
                    )

            versions = {}

            # Install all packages in one go for efficiency
            if pkgs := [x["pkg"] for x in config["assets"] if "pkg" in x]:
                pkg(version, arch, m, "install", *pkgs)
                versions = {
                    x: pkg(version, arch, m, "query", "%v", x, text=True) for x in pkgs
                }
                shutil.rmtree(m / "var/db/pkg/repos")

                hints = set(["/lib", "/usr/lib", "/usr/local/lib"])

                for conf in (m / "usr/local/libdata/ldconfig").glob("*"):
                    with open(conf) as f:
                        hints.update(x for x in f.read().splitlines() if x)

                # Ensure dirs exist before running `ldconfig` on the host
                for d in hints:
                    os.makedirs(d, 0o755, exist_ok=True)

                subprocess.check_call(
                    ["ldconfig", "-f", m / "var/run/ld-elf.so.hints"] + sorted(hints)
                )

            for asset in config["assets"]:
                if p := asset.get("pkg"):
                    buildah(
                        "config",
                        f"--annotation=org.freebsd.pkg.{p}.version={versions[p]}",
                        c,
                    )

                    if not tagged:
                        tagged = f"ghcr.io/cynix/{name}:{versions[p]}"

                    if "entrypoint" not in config:
                        config["entrypoint"] = f"/usr/local/bin/{pkgs[0]}"

                elif url := asset.get("file"):
                    ver = get_version(asset.get("version"))
                    url = url.format(version=ver, arch=arch, triple=triple)
                    dst = calculate_dst(url, asset.get("dst", f"/usr/local/{name}/"))

                    with requests.get(url, stream=True) as r:
                        r.raise_for_status()

                        out = m / dst[1:]
                        out.parent.mkdir(parents=True, exist_ok=True)

                        with open(out, "wb") as f:
                            shutil.copyfileobj(r.raw, f)

                        if ver and not tagged:
                            tagged = f"ghcr.io/cynix/{name}:{ver}"

                        if "entrypoint" not in config:
                            os.chmod(out, 0o755)
                            config["entrypoint"] = dst

                else:
                    url, ver = None, None

                    if repo := asset.get("release"):
                        rls, ver = get_release(gh, repo, asset.get("match"))
                        glob = asset["glob"].format(arch=arch, triple=triple)

                        for a in rls.get_assets():
                            if fnmatch(a.browser_download_url.rsplit("/", 1)[-1], glob):
                                url = asset.browser_download_url
                                break
                        else:
                            core.set_failed(f"{glob} not found in {rls.name}")
                            return 1
                    elif url := asset.get("tarball"):
                        ver = get_version(asset.get("version"))
                        url = url.format(version=ver, arch=arch, triple=triple)
                    else:
                        core.set_failed(f"Unknown asset type: {asset}")
                        return 1

                    files = asset.get("files", [{"src": f"**/{name}"}])
                    entrypoint = extract_tarball(m, url, files)

                    if ver and not tagged:
                        tagged = f"ghcr.io/cynix/{name}:{ver}"

                    if entrypoint and "entrypoint" not in config:
                        config["entrypoint"] = entrypoint

            if (m / "usr/local/sbin").is_dir():
                os.chmod(m / "usr/local/sbin", 0o711)

            if script := config.get("script"):
                subprocess.run(["sh", "-e"], cwd=m, input=script, text=True, check=True)

            if isinstance(config["entrypoint"], str):
                config["entrypoint"] = [config["entrypoint"]]

            entrypoint = ",".join(f'"{x}"' for x in config["entrypoint"])
            cmd = ["config", f"--entrypoint=[{entrypoint}]", "--cmd="] + [
                f"--env={k}={v}" for k, v in config.get("env", {}).items()
            ]

            if user:
                cmd.append(f"--user={user}:{user}")

            buildah(*cmd, c)

    buildah("manifest", "push", "--all", latest, f"docker://{latest}")

    if tagged:
        buildah("manifest", "push", "--all", latest, f"docker://{tagged}")
