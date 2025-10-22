#!/bin/sh
set -eu

mkdir -p /usr/local/etc/pkg/repos
echo 'FreeBSD: { url: "pkg+https://pkg.freebsd.org/${ABI}/latest" }' >> /usr/local/etc/pkg/repos/FreeBSD.conf
echo 'FreeBSD-kmods: { enabled: no }' >> /usr/local/etc/pkg/repos/FreeBSD.conf

if [ "$1" = "container" ]; then
  sysctl net.inet.ip.forwarding=1
  pkg install -y podman-suite python312 uv

  truncate -s 16G /var/tmp/z
  mkdir -p /var/db/containers/storage
  zpool create -R /var/db/containers/storage -O mountpoint=/ -O compression=lz4 z /var/tmp/z
elif [ "$1" == "package" ]; then
  pkg install -y git gmake python312 rust uv
  git config --global --add safe.directory '*'

  mkdir -p /root/bin
  ln -s /usr/local/bin/gmake /root/bin/make
else
  echo "Invalid build type: $1" >&2
  exit 1
fi
