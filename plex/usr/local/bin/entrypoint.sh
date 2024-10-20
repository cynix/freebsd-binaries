#!/bin/sh

export SUPPORT_PATH="$1"

if [ -z "$SUPPORT_PATH" -o ! -d "$SUPPORT_PATH"]; then
  echo "Missing Plex Media Player support path" >&2
  exit 1
fi

export HOME="$SUPPORT_PATH/Plex Media Server"

export PLEX_MEDIA_SERVER_INFO_VENDOR=FreeBSD
export PLEX_MEDIA_SERVER_INFO_DEVICE=NAS
export PLEX_MEDIA_SERVER_INFO_MODEL="$(uname -m)"
export PLEX_MEDIA_SERVER_INFO_PLATFORM_VERSION="$(uname -r)"

export SCRIPTPATH="/usr/local/share/plexmediaserver"
export PYTHONHOME="$SCRIPTPATH/Resources/Python"
export PATH="$SCRIPTPATH/Resources/Python/bin:$PATH"
export LD_LIBRARY_PATH="$SCRIPTPATH/lib"

export LC_ALL="en_US.UTF-8"
export LANG="en_US.UTF-8"

export PLEX_MEDIA_SERVER_HOME="$SCRIPTPATH"
export PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR="$SUPPORT_PATH"
export PLEX_MEDIA_SERVER_LOG_DIR="$SUPPORT_PATH/Plex Media Server/Logs"
export PLEX_MEDIA_SERVER_MAX_PLUGIN_PROCS="${MAX_PLUGIN_PROCS:-6}"
export PLEX_MEDIA_SERVER_PIDFILE="/tmp/plex.pid"

ulimit -s 3000

mkdir -p "$HOME"
mkdir -p "$SUPPORT_PATH/Plex"

exec /usr/local/share/plexmediaserver/Plex_Media_Server
