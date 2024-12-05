#/usr/bin/env python3

import os
import shutil
import subprocess
import sys
import tarfile
import yaml
from contextlib import contextmanager
from pathlib import Path
from textwrap import dedent
from typing import Any


def buildah(*args: str, text: bool = True) -> str:
    cmd = ['buildah']
    cmd.extend(args)

    if text:
        return subprocess.check_output(cmd, text=True).strip()
    else:
        subprocess.check_call(cmd)
        return ''


def pw(m: Path, *args: str):
    subprocess.check_call(['pw', '-R', m] + list(args))


def pkg(version, arch: str, m: Path, cmd: str, *args: str):
    major, minor, *_ = version.split('p')[0].split('.')

    with open('/usr/local/etc/pkg/repos/FreeBSD-base.conf', 'w') as f:
        print(dedent(f"""
            FreeBSD-base: {{
              url: "pkg+https://pkg.FreeBSD.org/${{ABI}}/base_release_{minor}",
              mirror_type: "srv",
              signature_type: "fingerprints",
              fingerprints: "/usr/share/keys/pkg",
              enabled: yes
            }}
            """), file=f)

    env = dict(os.environ)
    env.update(
        IGNORE_OSVERSION='yes',
        PKG_CACHEDIR='/tmp/cache',
        ABI=f"FreeBSD:{major}:{'aarch64' if arch == 'arm64' else arch}",
    )

    subprocess.check_call(['pkg', '--rootdir', m, cmd, '-y'] + list(args), env=env)


@contextmanager
def container(manifest: str, base: str, arch: str):
    c = ''
    m = ''

    try:
        c = buildah('from', f"--arch={arch}", f"ghcr.io/cynix/{base}", text=True)
        m = buildah('mount', c, text=True)
        yield (c, Path(m))
    finally:
        if m:
            buildah('unmount', c)
            buildah('commit', f"--manifest={manifest}", '--rm', c)
        elif c:
            buildah('rm', c)


def main(name: str, config: dict[str, Any]) -> None:
    manifest = f"ghcr.io/cynix/{name}:latest"
    buildah('manifest', 'create', manifest)

    base = config.get('base', 'freebsd:minimal' if 'pkg' in config else 'freebsd:static')

    image = f"ghcr.io/cynix/{base}"
    subprocess.check_call(['podman', 'pull', image])
    version = subprocess.check_output(['podman', 'image', 'inspect', '--format={{index .Annotations "org.freebsd.version"}}', image], text=True).strip()

    for arch in config.get('arch', ['amd64', 'arm64']):
        with container(manifest, base, arch) as (c, m):
            if os.path.exists(name):
                shutil.copytree(name, m, symlinks=True, dirs_exist_ok=True)

            if user := config.get('user'):
                if '=' in user:
                    user, uid = user.split('=')
                    pw(m, 'groupadd', '-n', user, '-g', uid)
                    pw(m, 'useradd', '-n', user, '-u', uid, '-g', user, '-d', '/nonexistent', '-s', '/sbin/nologin')

            if pkgs := config.get('pkg'):
                pkg(version, arch, m, 'install', *pkgs)
                shutil.rmtree(m / 'var/db/pkg/repos')

                hints = set(['/lib', '/usr/lib', '/usr/local/lib'])

                for conf in (m / 'usr/local/libdata/ldconfig').glob('*'):
                    with open(conf) as f:
                        hints.update(x for x in f.read().splitlines() if x)

                for d in hints:
                    os.makedirs(d, 0o755, exist_ok=True)

                subprocess.check_call(['ldconfig', '-f', m / 'var/run/ld-elf.so.hints'] + sorted(hints))

                if 'entrypoint' not in config:
                    config['entrypoint'] = f"/usr/local/bin/{pkgs[0]}"
                elif config['entrypoint'].startswith('/usr/local/sbin/'):
                    os.chmod(m / 'usr/local/sbin', 0o711)
            else:
                urls, binary = config['tarball'].split('#')
                config['entrypoint'] = f"/usr/local/bin/{binary}"

                url = urls.format(arch=arch)
                subprocess.check_call(['fetch', '-o', '/tmp/tarball', url])

                with tarfile.open('/tmp/tarball') as tarball:
                    while member := tarball.next():
                        if not member.isfile() or (member.mode & 0o111) != 0o111:
                            continue

                        if os.path.basename(member.name) == binary:
                            bin = m / 'usr/local/bin' / binary
                            os.makedirs(bin.parent, 0o755, exist_ok=True)

                            with open(bin, "wb") as dst:
                                src = tarball.extractfile(member)
                                assert src
                                shutil.copyfileobj(src, dst)

                            os.chmod(bin, 0o755)
                            break
                    else:
                        raise RuntimeError(f"{binary} not found in {url}")

            cmd = ['config', f"--entrypoint=[\"{config['entrypoint']}\"]"] + [f"--env={k}={v}" for k, v in config.get('env', {}).items()]

            if user:
                cmd.append(f"--user={user}:{user}")

            buildah(*cmd, c)

    buildah('manifest', 'push', '--all', manifest, f"docker://{manifest}")


if __name__ == "__main__":
    name = sys.argv[1]

    with open('containers.yaml') as y:
        main(name, yaml.safe_load(y)[name])
