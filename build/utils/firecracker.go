package utils

import (
	"crypto/rand"
	"encoding/gob"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"

	"github.com/pkg/sftp"
	"golang.org/x/crypto/ssh"
)

type Firecracker struct {
	c *ssh.Client
	s *ssh.Session
	w io.WriteCloser
	r io.Reader

	tx *gob.Encoder
	rx *gob.Decoder
}

func NewFirecracker(bin, addr, user, key string) (*Firecracker, error) {
	fc := &Firecracker{}
	return fc, fc.init(bin, addr, user, key)
}

func (fc *Firecracker) Close() {
	if fc.s != nil {
		fc.tx.Encode(message{cmdShutdown, nil})

		fc.s.Wait()
		fc.s.Close()
		fc.s = nil
	}

	if fc.c != nil {
		fc.c.Close()
		fc.c = nil
	}
}

func (fc *Firecracker) Command(name string, args ...string) *Cmd {
	return Command(name, args...).Via(fc)
}

func (fc *Firecracker) Run(cmd *exec.Cmd) error {
	if fc.tx == nil {
		return fmt.Errorf("Firecracker not initialised")
	}

	fmt.Fprintf(os.Stderr, "::debug::(FC) executing: %q\n", cmd.Args)

	if err := fc.tx.Encode(message{cmdExec, execute{Args: cmd.Args, Env: cmd.Env, Dir: cmd.Dir}}); err != nil {
		return err
	}

	var errIn, errOut error
	var wg sync.WaitGroup

	wg.Go(func() {
		if cmd.Stdin != nil {
			b := make([]byte, 16 * 1024)

			for {
				n, err := cmd.Stdin.Read(b)

				if n > 0 {
					if errIn = fc.tx.Encode(message{cmdStdin, b[:n]}); errIn != nil {
						errIn = fmt.Errorf("could not send %d to stdin: %w", n, errIn)
						return
					}
				}

				if err == io.EOF {
					break
				} else if err != nil {
					errIn = fmt.Errorf("could not read stdin: %w", err)
					return
				}
			}
		}

		errIn = fc.tx.Encode(message{cmdEOF, nil})
	})

	wg.Go(func() {
		var m message

		for {
			if errOut = fc.rx.Decode(&m); errOut != nil {
				return
			}

			switch m.Command {
			case cmdStdout:
				if cmd.Stdout != nil {
					if _, errOut = cmd.Stdout.Write(m.Data.([]byte)); errOut != nil {
						errOut = fmt.Errorf("could not pipe %d to stdout: %w", len(m.Data.([]byte)), errOut)
						return
					}
				}

			case cmdExited:
				if s, ok := m.Data.(string); ok {
					errOut = fmt.Errorf("command exited with error: %s", s)
				}

				return

			default:
				errOut = fmt.Errorf("unexpected message from remote: %q", m.Command)
				return
			}
		}
	})

	wg.Wait()
	return errors.Join(errIn, errOut)
}

func (fc *Firecracker) init(bin, addr, user, key string) error {
	kf, err := os.ReadFile(key)
	if err != nil {
		return fmt.Errorf("could not read private key %q: %w", key, err)
	}

	signer, err := ssh.ParsePrivateKey(kf)
	if err != nil {
		return fmt.Errorf("could not parse private key %q: %w", key, err)
	}

	if fc.c, err = ssh.Dial("tcp", addr, &ssh.ClientConfig{
		User:            user,
		Auth:            []ssh.AuthMethod{ssh.PublicKeys(signer)},
		HostKeyCallback: ssh.InsecureIgnoreHostKey(),
	}); err != nil {
		return fmt.Errorf("could not ssh to %q@%q: %w", user, addr, err)
	}

	exe, err := os.Open(bin)
	if err != nil {
		return fmt.Errorf("could not read executable %q: %w", bin, err)
	}
	defer exe.Close()

	var sf *sftp.Client
	if sf, err = sftp.NewClient(fc.c); err != nil {
		return fmt.Errorf("could not sftp to %q: %w", addr, err)
	}
	defer sf.Close()

	dst := "/tmp/build-" + rand.Text()

	up, err := sf.Create(dst)
	if err != nil {
		return fmt.Errorf("could not create executable on %q: %w", addr, err)
	}
	defer up.Close()

	if _, err := io.Copy(up, exe); err != nil {
		return fmt.Errorf("could not upload executable on %q: %w", addr, err)
	}

	if err = sf.Chmod(dst, 0o700); err != nil {
		return fmt.Errorf("could not chmod executable on %q: %w", addr, err)
	}

	if fc.s, err = fc.c.NewSession(); err != nil {
		return fmt.Errorf("could not open session on %q: %w", addr, err)
	}

	fc.s.Stderr = os.Stderr

	if fc.w, err = fc.s.StdinPipe(); err != nil {
		return fmt.Errorf("could not connect stdin for %q: %w", addr, err)
	}

	if fc.r, err = fc.s.StdoutPipe(); err != nil {
		return fmt.Errorf("could not connect stdout for %q: %w", addr, err)
	}

	if err = fc.s.Start(fmt.Sprintf("env GITHUB_EVENT_PATH=/dev/null GITHUB_TOKEN=x %s serve", dst)); err != nil {
		return fmt.Errorf("could not run self on %q: %w", addr, err)
	}

	fc.tx = gob.NewEncoder(fc.w)
	fc.rx = gob.NewDecoder(fc.r)

	return nil
}

func (fc *Firecracker) serve() (err error) {
	fmt.Fprintf(os.Stderr, "[FC] serving\n")

	var m message

	for {
		if err = fc.rx.Decode(&m); err != nil {
			return
		}

		switch m.Command {
		case cmdExec:
			if err = fc.run(m.Data.(execute)); err != nil {
				return
			}

		case cmdStdin:
			fallthrough
		case cmdEOF:
			// Stray message from failed command
			continue

		case cmdShutdown:
			return exec.Command("halt", "-p").Run()

		default:
			return fmt.Errorf("unexpected message from remote: %q", m.Command)
		}
	}
}

func (fc *Firecracker) run(ex execute) (err error) {
	cmd := exec.Command(ex.Args[0], ex.Args[1:]...)

	if len(ex.Env) > 0 {
		cmd.Env = append(os.Environ(), ex.Env...)
	}

	cmd.Dir = ex.Dir
	cmd.Stderr = os.Stderr

	var stdin io.WriteCloser
	var stdout io.ReadCloser

	if stdin, err = cmd.StdinPipe(); err != nil {
		return fmt.Errorf("could not connect stdin: %w", err)
	}

	if stdout, err = cmd.StdoutPipe(); err != nil {
		return fmt.Errorf("could not connect stdout: %w", err)
	}

	fmt.Fprintf(os.Stderr, "::debug::[FC] executing: %q\n", cmd.Args)

	if err = cmd.Start(); err != nil {
		if err = fc.tx.Encode(message{cmdExited, err.Error()}); err != nil {
			return fmt.Errorf("could not send exit status: %w", err)
		}
	}

	var errIn, errOut error
	var wg sync.WaitGroup

	wg.Go(func() {
		var m message

		for {
			if errIn = fc.rx.Decode(&m); errIn != nil {
				return
			}

			switch m.Command {
			case cmdStdin:
				if _, errIn = stdin.Write(m.Data.([]byte)); errIn != nil {
					errIn = fmt.Errorf("could not pipe %d to stdin: %w", len(m.Data.([]byte)), errIn)
					return
				}

			case cmdEOF:
				stdin.Close()
				return

			default:
				errIn = fmt.Errorf("unexpected message from remote: %q", m.Command)
				return
			}
		}
	})

	wg.Go(func() {
		b := make([]byte, 16 * 1024)

		for {
			n, err := stdout.Read(b)

			if n > 0 {
				if errOut = fc.tx.Encode(message{cmdStdout, b[:n]}); errOut != nil {
					return
				}
			}

			if err != nil {
				if err != io.EOF {
					errOut = err
				}
				return
			}
		}
	})

	wg.Wait()

	if err = cmd.Wait(); err != nil {
		err = fc.tx.Encode(message{cmdExited, err.Error()})
	} else {
		err = fc.tx.Encode(message{cmdExited, nil})
	}

	if err != nil {
		err = fmt.Errorf("could not send exit status: %w", err)
	}

	return
}

func ServeFirecracker() error {
	fc := &Firecracker{
		tx: gob.NewEncoder(os.Stdout),
		rx: gob.NewDecoder(os.Stdin),
	}
	return fc.serve()
}

type command int

type message struct {
	Command command
	Data    any
}

type execute struct {
	Args []string
	Env  []string
	Dir  string
}

const (
	cmdExec command = iota
	cmdStdin
	cmdStdout
	cmdEOF
	cmdExited
	cmdShutdown
)

func init() {
	gob.Register(execute{})
}
