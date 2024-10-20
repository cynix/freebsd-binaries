#!/usr/bin/env python3

from ruamel.yaml import YAML


def main(containers: list[str]) -> None:
    yaml = YAML()
    yaml.indent(sequence=4, offset=2)

    with open('dispatch.yaml') as y:
        dispatch = yaml.load(y)

    dispatch['on']['workflow_dispatch']['inputs'] = {x: {'type': 'boolean', 'required': True, 'default': False} for x in containers}
    dispatch['jobs']['dispatch']['strategy']['matrix']['container'] = containers

    with open('.github/workflows/dispatch.yaml', 'w') as f:
        yaml.dump(dispatch, f)


if __name__ == "__main__":
    with open('containers.yaml') as y:
        main(list(YAML().load(y)))
