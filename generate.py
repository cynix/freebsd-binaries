#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
import sys
import tarfile


def main(container: dict[str, str]) -> None:
    arch = container.get('arch', 'amd64 arm64').split(' ')

    with open('Containerfile', 'w') as cf:
        base = container.get('base', 'freebsd:minimal' if 'pkg' in container else 'freebsd:static')
        print(f"FROM ghcr.io/cynix/{base}", file=cf)

        if 'pkg' in container:
            print(f"RUN pkg install -y {container['pkg']} && pkg clean -a -y && rm -rf /var/db/pkg/repos")
        else:
            urls, binary = container['tarball'].split('#')
            container['entrypoint'] = f"/usr/local/bin/{binary}"

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

        if 'user' in container:
            print(f"USER {container['user']}", file=cf)

        print(f"ENTRYPOINT [\"{container['entrypoint']}\"]", file=cf)

    with open('build.sh', 'w') as sh:
        name = container['name']
        platform = ','.join([f"freebsd/{x}" for x in arch])
        print(f"podman build --manifest=ghcr.io/cynix/{name}:latest --network=host --platform={platform} --pull=always .", file=sh)
        print(f"podman manifest push ghcr.io/cynix/{name}:latest", file=sh)

    os.chmod('build.sh', 0o755)


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
