#!/usr/bin/env bash
set -euo pipefail

FLOWOPS_SETUP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
        exec "$candidate" "$FLOWOPS_SETUP_ROOT/scripts/setup.py" "$@"
    fi
done
echo "Instale Python 3.12+ e execute o setup novamente." >&2
exit 1
