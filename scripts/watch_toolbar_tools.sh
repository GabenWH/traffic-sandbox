#!/usr/bin/env bash
# Keep ui_tools/toolbar.json in sync with newly added *_tool.py modules.
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
tools_dir="$project_dir/ui_tools/tools"

if ! command -v inotifywait >/dev/null 2>&1; then
    echo "Missing inotifywait. On Arch/KDE install it with: sudo pacman -S inotify-tools" >&2
    exit 1
fi

cd "$project_dir"
python3 -m ui_tools.sync_toolbar
echo "Watching $tools_dir; press Ctrl+C to stop."

inotifywait --monitor --quiet \
    --event create --event moved_to --event delete --event close_write "$tools_dir" |
while read -r changed_dir event changed_name; do
    case "$changed_name" in
        *_tool.py) python3 -m ui_tools.sync_toolbar ;;
    esac
done
