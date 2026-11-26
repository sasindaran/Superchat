#!/bin/sh
# Avoid resolving the uv project and rebuilding its environment on every prompt.
root=${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT is required}
event=$1

if [ -x "$root/.venv/Scripts/python.exe" ]; then
    "$root/.venv/Scripts/python.exe" -m superchat hook "$event"
    result=$?
elif [ -x "$root/.venv/bin/python" ]; then
    "$root/.venv/bin/python" -m superchat hook "$event"
    result=$?
else
    uv run --directory "$root" superchat hook "$event"
    result=$?
fi

# A broken reminder or session hook must not prevent the user's prompt.
if [ "$event" = user-prompt ] || [ "$event" = session-start ]; then
    exit 0
fi
exit "$result"
