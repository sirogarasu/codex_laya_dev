#!/usr/bin/env bash

if codex login status >/dev/null 2>&1; then
    echo "Codex already logged in."
else
    echo "Codex is not logged in. Run: codex login --device-auth"
fi

echo "Laya API: http://laya-api:8000"
