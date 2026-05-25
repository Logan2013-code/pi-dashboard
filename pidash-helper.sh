#!/bin/bash
# Restricted helper for PiDash service management.
# Installed to /usr/local/bin/pidash-helper with a matching sudoers entry
# so the dashboard can manage only pidash-* services without full root.

set -euo pipefail

PREFIX="pidash-"
ACTION="${1:-}"
NAME="${2:-}"
LINES="${3:-150}"

case "$ACTION" in
    status)
        systemctl is-active "${PREFIX}${NAME}" 2>/dev/null || true
        ;;
    status-detail)
        systemctl status "${PREFIX}${NAME}" --no-pager 2>/dev/null || true
        ;;
    start|stop|restart|enable|disable)
        systemctl "$ACTION" "${PREFIX}${NAME}"
        ;;
    reload)
        systemctl daemon-reload
        ;;
    logs)
        journalctl -u "${PREFIX}${NAME}" -n "$LINES" --no-pager -o short-iso 2>/dev/null || true
        ;;
    write-service)
        cat > "/etc/systemd/system/${PREFIX}${NAME}.service"
        ;;
    remove-service)
        rm -f "/etc/systemd/system/${PREFIX}${NAME}.service"
        ;;
    *)
        echo "Unknown action: $ACTION" >&2
        exit 1
        ;;
esac
