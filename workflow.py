#!/usr/bin/env python3

from ruamel.yaml import YAML


def main(containers: list[str]) -> None:
    yaml = YAML()
    yaml.indent(sequence=4, offset=2)

    with open('dispatch.yaml') as y:
        dispatch = yaml.load(y)

    for n in range((len(containers) // 10) + 1):
        group = containers[10*n:10*(n+1)]
        dispatch['name'] = f"Dispatch {'/'.join(group)}"
        dispatch['on']['workflow_dispatch']['inputs'] = {x: {'type': 'boolean', 'required': True, 'default': False} for x in group}
        dispatch['jobs']['dispatch']['strategy']['matrix']['container'] = group

        with open(f".github/workflows/dispatch-{n}.yaml", 'w') as f:
            yaml.dump(dispatch, f)


if __name__ == "__main__":
    with open('containers.yaml') as y:
        main(list(YAML().load(y)))
