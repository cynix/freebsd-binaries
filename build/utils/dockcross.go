package utils

import (
	"fmt"
	"os"
	"os/exec"
	"os/user"
)

type Dockcross struct {
	Arch string
}

func (dc *Dockcross) Command(name string, args ...string) *Cmd {
	return Command(name, args...).Via(dc)
}

func (dc *Dockcross) Run(cmd *exec.Cmd) (err error) {
	if cmd.Path, err = exec.LookPath("docker"); err != nil {
		return err
	}

	cwd := cmd.Dir
	cmd.Dir = ""

	if cwd == "" {
		if cwd, err = os.Getwd(); err != nil {
			return
		}
	}

	var u *user.User
	if u, err = user.Current(); err != nil {
		return
	}

	args := []string{
		"docker",
		"run",
		"--rm",
		"--pull=always",
		fmt.Sprintf("--volume=%s:/work", cwd),
		"--env=BUILDER_USER=" + u.Username,
		"--env=BUILDER_GROUP=" + u.Username,
		"--env=BUILDER_UID=" + u.Uid,
		"--env=BUILDER_GID=" + u.Gid,
	}

	for _, e := range cmd.Env {
		args = append(args, "--env="+e)
	}

	args = append(args, "ghcr.io/cynix/dockcross-freebsd:latest")
	cmd.Args = append(args, cmd.Args...)
	cmd.Env = nil

	fmt.Fprintf(os.Stderr, "[DX] %q\n", cmd.Args)

	return cmd.Run()
}
