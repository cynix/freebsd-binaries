package utils

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"os/exec"
	"os/user"
	"strings"
)

type Cmd struct {
	c *exec.Cmd
	n string
	b bytes.Buffer
	x bool
}

func Command(name string, args ...string) *Cmd {
	c := &Cmd{c: exec.Command(name, args...), n: name}
	c.c.Stdout = &c.b
	c.c.Stderr = os.Stderr
	return c
}

func (c *Cmd) In(cwd string) *Cmd {
	c.c.Dir = cwd
	return c
}

func (c *Cmd) WithEnv(env ...string) *Cmd {
	c.c.Env = append(c.c.Env, env...)
	return c
}

func (c *Cmd) WithInput(input any) *Cmd {
	switch x := input.(type) {
	case io.Reader:
		c.c.Stdin = x
	case []byte:
		c.c.Stdin = bytes.NewReader(x)
	case string:
		c.c.Stdin = strings.NewReader(x)
	}
	return c
}

func (c *Cmd) Cross(arch string) *Cmd {
	c.x = true

	if arch != "" {
		c.WithEnv("FREEBSD_ARCH=" + arch)
	}

	return c
}

func (c *Cmd) Run() error {
	c.c.Stdout = os.Stdout
	return c.run()
}

func (c *Cmd) Each(yield func(int, string) bool) error {
	if err := c.run(); err != nil {
		return err
	}

	i := 0

	for line := range strings.Lines(c.b.String()) {
		if line = strings.TrimSpace(line); line == "" {
			continue
		}

		if !yield(i, line) {
			break
		}

		i++
	}

	return nil
}

func (c *Cmd) First() (string, error) {
	var first string

	err := c.Each(func(_ int, line string) bool {
		first = line
		return false
	})

	return first, err
}

func (c *Cmd) run() (err error) {
	if c.x {
		if c.c.Path, err = exec.LookPath("docker"); err != nil {
			return
		}

		cwd := c.c.Dir
		c.c.Dir = ""

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
			"run",
			"--rm",
			"--pull=always",
			fmt.Sprintf("--volume=%s:/work", cwd),
			"--env=BUILDER_USER=" + u.Username,
			"--env=BUILDER_GROUP=" + u.Username,
			"--env=BUILDER_UID=" + u.Uid,
			"--env=BUILDER_GID=" + u.Gid,
		}

		for _, e := range c.c.Env {
			args = append(args, "--env="+e)
		}

		args = append(args, "ghcr.io/cynix/dockcross-freebsd:latest", c.n)
		c.c.Args = append(args, c.c.Args...)
	} else {
		if len(c.c.Env) > 0 {
			c.c.Env = append(os.Environ(), c.c.Env...)
		}
	}

	return c.c.Run()
}
