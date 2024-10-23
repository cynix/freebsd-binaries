#!/usr/bin/env python3

import os
import shutil
import subprocess
import sys
import tarfile
import yaml
from collections import defaultdict
from textwrap import dedent
from typing import Any


def main(name: str, config: dict[str, Any]) -> None:
    arch = config.get('arch', ['amd64', 'arm64'])

    with open('Containerfile', 'w') as cf:
        base = config.get('base', 'freebsd:minimal' if 'pkg' in config else 'freebsd:static')
        copy = defaultdict(list)

        for d, _, f in os.walk(name):
            if not f:
                continue

            if not d.endswith('/'):
                d += '/'

            if not d.startswith(f"{name}/"):
                continue

            copy[d[len(name):]].extend(f)

        if user := config.get('user'):
            if '=' in user:
                user, uid = user.split('=')

                print(dedent(f"""\
                    FROM ghcr.io/cynix/freebsd:minimal AS builder
                    RUN pw groupadd -n {user} -g {uid}
                    RUN pw useradd -n {user} -u {uid} -g {user} -d /nonexistent -s /sbin/nologin
                    """), file=cf)

                copy['!/etc/'].extend(['group', 'master.passwd', 'passwd', 'pwd.db', 'spwd.db'])

        print(f"FROM ghcr.io/cynix/{base}", file=cf)

        if pkg := config.get('pkg'):
            print(f"RUN pkg install -y {' '.join(pkg)} && pkg clean -a -y && rm -rf /var/db/pkg/repos", file=cf)

            if 'entrypoint' not in config:
                config['entrypoint'] = f"/usr/local/bin/{pkg[0]}"

        else:
            urls, binary = config['tarball'].split('#')
            config['entrypoint'] = f"/usr/local/bin/{binary}"

            for a in arch:
                os.makedirs(f"bin/{a}")

                url = urls.format(arch=a)
                subprocess.check_call(['curl', '-sSL', '-o', f"bin/{a}.tarball", url])

                with tarfile.open(f"bin/{a}.tarball") as tarball:
                    while member := tarball.next():
                        if not member.isfile() or (member.mode & 0o111) != 0o111:
                            continue

                        if os.path.basename(member.name) == binary:
                            bin = f"bin/{a}/{binary}"

                            with open(bin, "wb") as dst:
                                src = tarball.extractfile(member)
                                assert src
                                shutil.copyfileobj(src, dst)

                            os.chmod(bin, 0o755)
                            break
                    else:
                        raise RuntimeError(f"{binary} not found in {url}")

            print('ARG TARGETARCH', file=cf)
            print(f"COPY bin/${{TARGETARCH}}/{binary} /usr/local/bin/{binary}", file=cf)

        for dst, files in copy.items():
            if not files:
                continue

            if dst.startswith('!'):
                cmd = 'COPY --from=builder'
                dst = dst[1:]
                src = ' '.join([f"{dst}{x}" for x in files])
            else:
                cmd = 'COPY'
                src = ' '.join([f"{name}{dst}{x}" for x in files])

            print(f"{cmd} {src} {dst}", file=cf)

        if user:
            print(f"USER {user}:{user}", file=cf)

        for env, value in config.get('env', {}):
            print(f"ENV {env}={value}", file=cf)

        print(f"ENTRYPOINT [\"{config['entrypoint']}\"]", file=cf)

    with open('build.sh', 'w') as sh:
        platform = ','.join([f"freebsd/{x}" for x in arch])
        print(f"buildah build --manifest=ghcr.io/cynix/{name}:latest --network=host --platform={platform} --pull=always .", file=sh)
        print(f"buildah manifest push --all ghcr.io/cynix/{name}:latest docker://ghcr.io/cynix/{name}:latest", file=sh)

    os.chmod('build.sh', 0o755)


if __name__ == "__main__":
    name = sys.argv[1]

    with open('containers.yaml') as y:
        main(name, yaml.safe_load(y)[name])
