#!/bin/sh
# Repository convenience wrapper. The hosted installer source lives in install/.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "${script_dir}/../install/install.sh" "$@"
