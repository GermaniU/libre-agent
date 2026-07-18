#!/usr/bin/env bash
# Arranca el bot de Telegram de LocalCowork.
set -e
cd "$(dirname "$0")"
exec ./.venv/bin/python telegram_bot.py
