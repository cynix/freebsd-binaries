package utils

import (
	"fmt"
	"os/exec"
)

type Mise struct {
	Arch string
	Use  map[string]string
}

func (m *Mise) Command(name string, args ...string) *Cmd {
	return Command(name, args...).Via(m)
}

func (m *Mise) Run(cmd *exec.Cmd) (err error) {
	cmd.Path = "mise"

	args := []string{
		"mise",
		"exec",
	}

	for k, v := range m.Use {
		args = append(args, fmt.Sprintf("%s@%s", k, v))
	}

	args = append(args, "--")
	cmd.Args = append(args, cmd.Args...)

	dx := &Dockcross{Arch: m.Arch}
	return dx.Run(cmd)
}
