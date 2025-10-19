#!/bin/sh
set -eu

mkdir -p /usr/local/etc/pkg/repos
echo 'FreeBSD: { url: "pkg+https://pkg.freebsd.org/${ABI}/latest" }' >> /usr/local/etc/pkg/repos/FreeBSD.conf
echo 'FreeBSD-kmods: { enabled: no }' >> /usr/local/etc/pkg/repos/FreeBSD.conf

echo "::group::Setting up FreeBSD VM"

sysctl net.inet.ip.forwarding=1
pkg install -y go125 podman-suite

echo "::endgroup::"
