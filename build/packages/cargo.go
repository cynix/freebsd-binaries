package packages

import (
	"fmt"
	"maps"

	"github.com/bobg/go-generics/v4/slices"
	"github.com/cynix/freebsd-binaries/build/container"
	"github.com/cynix/freebsd-binaries/build/project"
	"github.com/google/go-github/v74/github"
)

type CargoProject struct {
	PackageProject `yaml:",inline"`
	Packages       map[string]CargoPackage
	Defaults       struct {
		Package   CargoConfig
		Container ContainerConfig
	}
}

type CargoPackage struct {
	CargoConfig `yaml:",inline"`
	Binaries    []string
	Container   *ContainerConfig
}

type CargoConfig struct {
	RustConfig `yaml:",inline"`
	Files      []string
}

func (gp *CargoProject) Hydrate(name string) {
	gp.Name = name

	if len(gp.Arch) == 0 {
		gp.Arch = []string{"amd64", "arm64"}
	}

	if len(gp.Packages) == 0 {
		gp.Packages = map[string]CargoPackage{name: {}}
	}

	for k, v := range gp.Packages {
		if len(v.Binaries) == 0 {
			v.Binaries = []string{k}
		}

		v.Hydrate(gp.Defaults.Package)

		if v.Container != nil {
			v.Container.Hydrate(gp.Defaults.Container.ContainerConfig)

			slices.Insert(v.Container.Assets, 0, container.Asset{
				Deployable: container.FileAsset{
					URLAsset: container.URLAsset{
						URL: "https://github.com/cynix/freebsd-binaries/releases/download/{project}-v{version}/{package}-v{version}-{triple}.tar.gz",
					},
				},
			})
		}

		gp.Packages[k] = v
	}
}

func (gp *CargoProject) Job(gh *github.Client) (j project.ProjectJob, err error) {
	j.Project = gp.Name

	var ref string
	if ref, j.Version, err = gp.Source.RefVersion(gh); err != nil {
		return
	}

	for _, k := range slices.Sorted(maps.Keys(gp.Packages)) {
		j.Packages = append(j.Packages, project.PackageJob{Package: k, Builder: gp.Builder, Repo: gp.Source.Repo, Ref: ref})

		if gp.Packages[k].Container != nil {
			j.Containers = append(j.Containers, k)
		}
	}

	return
}

func (gp *CargoProject) BuildPackage(gh *github.Client, version, name string) error {
	return fmt.Errorf("not implemented")
}

func (gp *CargoProject) BuildContainer(gh *github.Client, version, name string) error {
	return fmt.Errorf("not implemented")
}

func (c *CargoConfig) Hydrate(defaults CargoConfig) {
	if c.Manifest == "" {
		if c.Manifest = defaults.Manifest; c.Manifest == "" {
			c.Manifest = "Cargo.toml"
		}
	}

	if c.Profile == "" {
		if c.Profile = defaults.Profile; c.Profile == "" {
			c.Profile = "release"
		}
	}

	if len(c.Features) == 0 {
		c.Features = slices.Clone(defaults.Features)
	}

	if len(c.Files) == 0 {
		if c.Files = slices.Clone(defaults.Files); len(c.Files) == 0 {
			c.Files = []string{"COPYING*", "LICENSE*"}
		}
	}
}
