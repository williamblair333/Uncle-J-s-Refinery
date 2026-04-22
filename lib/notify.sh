#!/usr/bin/env bash
# Notification dispatcher. Source this file in alert scripts.
# Reads NOTIFY_CHANNEL (default: telegram) and delegates to the implementation.

_NOTIFY_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

notify_send_pitch() {
  local message=$1 keyboard_json=$2
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      # shellcheck source=lib/notify-telegram.sh
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_send_pitch "$message" "$keyboard_json"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}

notify_poll_reply() {
  local message_id=$1
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_poll_reply "$message_id"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}

notify_send_text() {
  local message=$1
  case "${NOTIFY_CHANNEL:-telegram}" in
    telegram)
      source "$_NOTIFY_LIB_DIR/notify-telegram.sh"
      _tg_send_text "$message"
      ;;
    *)
      echo "[notify] Unknown NOTIFY_CHANNEL: ${NOTIFY_CHANNEL}" >&2
      return 1
      ;;
  esac
}
