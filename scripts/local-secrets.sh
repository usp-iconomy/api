#!/bin/sh
# Appends any missing local-only Keycloak password to .env with a random value.
# Idempotent: an existing value is never overwritten.
set -eu

env_file=.env
[ -f "$env_file" ] || cp .env.example "$env_file"

for key in KC_ADMIN_PASSWORD KC_SEED_PASSWORD; do
  if ! grep -q "^${key}=." "$env_file"; then
    sed -i.bak "/^${key}=/d" "$env_file" && rm -f "$env_file.bak"
    printf '%s=%s\n' "$key" "$(openssl rand -hex 12)" >> "$env_file"
    echo "generated $key in $env_file"
  fi
done
