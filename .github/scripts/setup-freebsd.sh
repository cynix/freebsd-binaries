#!/bin/sh
set -eu

mkdir -p /usr/local/etc/pkg/repos
echo 'FreeBSD: { url: "pkg+https://pkg.freebsd.org/${ABI}/latest" }' >> /usr/local/etc/pkg/repos/FreeBSD.conf
echo 'FreeBSD-kmods: { enabled: no }' >> /usr/local/etc/pkg/repos/FreeBSD.conf

if [ "$1" != "container" -a "$1" != "package" ]; then
  echo "::error::Invalid build type: $1"
  exit 1
fi

echo "::group::Setup FreeBSD VM"

if [ "$1" = "container" ]; then
  sysctl net.inet.ip.forwarding=1
  pkg install -y podman-suite python312 uv
else
  pkg install -y git gmake python312 rust uv
  git config --global --add safe.directory '*'

  mkdir -p /root/bin
  ln -s /usr/local/bin/gmake /root/bin/make
fi

echo "::endgroup::"
