#!/usr/bin/env bash

# Shared logging foundation for EverSpark Forge.
# Source this file; do not execute it directly.

core_log_timestamp() {
  date '+%Y-%m-%dT%H:%M:%S%:z'
}

core_log_level_value() {
  case "${1^^}" in
    DEBUG) printf '%s\n' 10 ;;
    INFO) printf '%s\n' 20 ;;
    OK) printf '%s\n' 25 ;;
    WARN|WARNING) printf '%s\n' 30 ;;
    ERROR) printf '%s\n' 40 ;;
    *) return 1 ;;
  esac
}

core_log_redact() {
  printf '%s' "$1" | sed -E \
    's/((api[_-]?key|authorization|cookie|credential|passwd|password|secret|token)[[:space:]]*=[[:space:]]*)[^[:space:]]+/\1[REDACTED]/Ig'
}

core_log_field_is_sensitive() {
  case "${1,,}" in
    *api_key*|*api-key*|*authorization*|*cookie*|*credential*|*passwd*|*password*|*secret*|*token*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

core_log_json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

core_log_generate_run_id() {
  printf '%s-%s-%s\n' "$(date -u '+%Y%m%dT%H%M%SZ')" "$$" "${RANDOM:-0}"
}

core_log_init() {
  local component="${1:-core}"
  local log_file="${2:-${CORE_LOG_FILE:-}}"
  local level="${EVERSPARK_LOG_LEVEL:-INFO}"
  local format="${EVERSPARK_LOG_FORMAT:-text}"
  local console="${EVERSPARK_LOG_CONSOLE:-1}"

  if [[ ! "$component" =~ ^[A-Za-z0-9_.-]+$ ]]; then
    printf 'EverSpark logging: invalid component: %s\n' "$component" >&2
    return 2
  fi

  level="${level^^}"
  [ "$level" != "WARNING" ] || level="WARN"
  if ! core_log_level_value "$level" >/dev/null; then
    printf 'EverSpark logging: invalid EVERSPARK_LOG_LEVEL: %s\n' "$level" >&2
    return 2
  fi

  format="${format,,}"
  if [ "$format" != "text" ] && [ "$format" != "json" ]; then
    printf 'EverSpark logging: invalid EVERSPARK_LOG_FORMAT: %s\n' "$format" >&2
    return 2
  fi

  if [ "$console" != "0" ] && [ "$console" != "1" ]; then
    printf 'EverSpark logging: EVERSPARK_LOG_CONSOLE must be 0 or 1\n' >&2
    return 2
  fi

  CORE_LOG_COMPONENT="$component"
  CORE_LOG_FILE="$log_file"
  EVERSPARK_LOG_LEVEL="$level"
  EVERSPARK_LOG_FORMAT="$format"
  EVERSPARK_LOG_CONSOLE="$console"
  EVERSPARK_RUN_ID="${EVERSPARK_RUN_ID:-$(core_log_generate_run_id)}"

  export CORE_LOG_COMPONENT CORE_LOG_FILE
  export EVERSPARK_LOG_LEVEL EVERSPARK_LOG_FORMAT
  export EVERSPARK_LOG_CONSOLE EVERSPARK_RUN_ID

  if [ -n "$CORE_LOG_FILE" ]; then
    local log_parent
    log_parent="$(dirname "$CORE_LOG_FILE")"
    umask 027
    mkdir -p "$log_parent" || return 1
    chmod 750 "$log_parent" 2>/dev/null || true
    touch "$CORE_LOG_FILE" || return 1
    chmod 640 "$CORE_LOG_FILE" 2>/dev/null || true
  fi

  CORE_LOG_INITIALIZED=1
  export CORE_LOG_INITIALIZED
}

core_log_ensure_init() {
  if [ "${CORE_LOG_INITIALIZED:-0}" != "1" ]; then
    core_log_init "${CORE_LOG_COMPONENT:-core}" "${CORE_LOG_FILE:-}"
  fi
}

core_log_should_emit() {
  local requested configured
  requested="$(core_log_level_value "$1")" || return 1
  configured="$(core_log_level_value "${EVERSPARK_LOG_LEVEL:-INFO}")" || return 1
  [ "$requested" -ge "$configured" ]
}

core_log_normalize_call() {
  CORE_LOG_EVENT="message"
  CORE_LOG_MESSAGE=""
  CORE_LOG_FIELDS=()

  if [ "$#" -ge 2 ] && [[ "$1" =~ ^[a-z0-9][a-z0-9_.-]*$ ]]; then
    CORE_LOG_EVENT="$1"
    CORE_LOG_MESSAGE="$2"
    shift 2
    CORE_LOG_FIELDS=("$@")
  else
    CORE_LOG_MESSAGE="$*"
  fi
}

core_log_render_text() {
  local timestamp="$1" level="$2" event="$3" message="$4"
  shift 4

  printf '%s %-5s %s %s run_id=%s pid=%s message=%s' \
    "$timestamp" "$level" "${CORE_LOG_COMPONENT:-core}" "$event" \
    "${EVERSPARK_RUN_ID:-unknown}" "$$" "$message"

  local field key value
  for field in "$@"; do
    if [[ "$field" == *=* ]]; then
      key="${field%%=*}"
      value="${field#*=}"
    else
      key="field"
      value="$field"
    fi
    if core_log_field_is_sensitive "$key"; then
      value="[REDACTED]"
    else
      value="$(core_log_redact "$value")"
    fi
    printf ' %s=%s' "$key" "$value"
  done
  printf '\n'
}

core_log_render_json() {
  local timestamp="$1" level="$2" event="$3" message="$4"
  shift 4

  printf '{"timestamp":"%s","level":"%s","component":"%s","event":"%s","message":"%s","run_id":"%s","pid":%s,"fields":{' \
    "$(core_log_json_escape "$timestamp")" \
    "$(core_log_json_escape "$level")" \
    "$(core_log_json_escape "${CORE_LOG_COMPONENT:-core}")" \
    "$(core_log_json_escape "$event")" \
    "$(core_log_json_escape "$message")" \
    "$(core_log_json_escape "${EVERSPARK_RUN_ID:-unknown}")" \
    "$$"

  local field key value separator=""
  for field in "$@"; do
    if [[ "$field" == *=* ]]; then
      key="${field%%=*}"
      value="${field#*=}"
    else
      key="field"
      value="$field"
    fi
    if core_log_field_is_sensitive "$key"; then
      value="[REDACTED]"
    else
      value="$(core_log_redact "$value")"
    fi
    printf '%s"%s":"%s"' "$separator" \
      "$(core_log_json_escape "$key")" "$(core_log_json_escape "$value")"
    separator=","
  done
  printf '}}\n'
}

core_log_write() {
  local level="$1" line="$2"
  local stream_fd=1
  [ "$level" != "ERROR" ] || stream_fd=2

  if [ "${EVERSPARK_LOG_CONSOLE:-1}" = "1" ]; then
    printf '%s\n' "$line" >&"$stream_fd"
  fi

  if [ -n "${CORE_LOG_FILE:-}" ]; then
    if ! printf '%s\n' "$line" >> "$CORE_LOG_FILE"; then
      printf 'EverSpark logging: unable to append to %s\n' "$CORE_LOG_FILE" >&2
    fi
  fi

  return 0
}

core_log() {
  local level="${1^^}"
  shift
  [ "$level" != "WARNING" ] || level="WARN"

  core_log_ensure_init || return 1
  core_log_should_emit "$level" || return 0
  core_log_normalize_call "$@"

  local timestamp message line
  timestamp="$(core_log_timestamp)"
  message="$(core_log_redact "$CORE_LOG_MESSAGE")"

  if [ "${EVERSPARK_LOG_FORMAT:-text}" = "json" ]; then
    line="$(core_log_render_json "$timestamp" "$level" "$CORE_LOG_EVENT" "$message" "${CORE_LOG_FIELDS[@]}")"
  else
    line="$(core_log_render_text "$timestamp" "$level" "$CORE_LOG_EVENT" "$message" "${CORE_LOG_FIELDS[@]}")"
  fi

  core_log_write "$level" "$line"
}

core_debug() { core_log DEBUG "$@"; }
core_info() { core_log INFO "$@"; }
core_ok() { core_log OK "$@"; }
core_warn() { core_log WARN "$@"; }
core_error() { core_log ERROR "$@"; }

core_die() {
  core_error "$@"
  return 1
}

core_section() {
  core_info section "$*"
}

core_step_start() {
  local name="$1"
  shift
  CORE_LOG_STEP_NAME="$name"
  CORE_LOG_STEP_STARTED_AT="$(date '+%s')"
  export CORE_LOG_STEP_NAME CORE_LOG_STEP_STARTED_AT
  core_info step.start "Step started: $name" "step=$name" "$@"
}

core_step_end() {
  local name="$1" status="${2:-ok}"
  shift 2 2>/dev/null || true
  local now duration=0 level="OK"
  now="$(date '+%s')"
  if [ "${CORE_LOG_STEP_NAME:-}" = "$name" ] && [ -n "${CORE_LOG_STEP_STARTED_AT:-}" ]; then
    duration=$((now - CORE_LOG_STEP_STARTED_AT))
  fi
  [ "$status" = "ok" ] || level="ERROR"
  core_log "$level" step.end "Step finished: $name" \
    "step=$name" "status=$status" "duration_seconds=$duration" "$@"
}

core_run_step() {
  local name="$1"
  shift
  local command_name="${1:-unknown}"
  core_step_start "$name" "command=$command_name"
  if "$@"; then
    core_step_end "$name" ok
    return 0
  else
    local exit_code=$?
    core_step_end "$name" failed "exit_code=$exit_code"
    return "$exit_code"
  fi
}

core_run_optional_step() {
  local name="$1"
  shift
  local command_name="${1:-unknown}"
  core_step_start "$name" "command=$command_name" "optional=true"
  if "$@"; then
    core_step_end "$name" ok "optional=true"
    return 0
  else
    local exit_code=$?
    local now duration=0
    now="$(date '+%s')"
    if [ "${CORE_LOG_STEP_NAME:-}" = "$name" ] && [ -n "${CORE_LOG_STEP_STARTED_AT:-}" ]; then
      duration=$((now - CORE_LOG_STEP_STARTED_AT))
    fi
    core_warn step.end "Optional step failed; continuing: $name" \
      "step=$name" "status=failed" "exit_code=$exit_code" \
      "duration_seconds=$duration" "optional=true"
    return 0
  fi
}
