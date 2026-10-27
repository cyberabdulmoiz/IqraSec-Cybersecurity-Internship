#!/usr/bin/env bash
# Linux Security Audit Tool — local, read-only system checks.
set -uo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPORT_DIR="${SEC_AUDIT_REPORT_DIR:-${SCRIPT_DIR}/reports}"

line() { printf '%s\n' '------------------------------------------------------------'; }
section() { printf '\n'; line; printf '%s\n' "$1"; line; }
notice() { printf '[i] %s\n' "$1"; }

show_system() {
    section '1. SYSTEM INFORMATION'
    printf 'Date (local): %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
    printf 'Hostname:     %s\n' "$(hostname 2>/dev/null || printf 'Unavailable')"
    if [[ -r /etc/os-release ]]; then
        local os_name
        os_name="$(grep -m 1 '^PRETTY_NAME=' /etc/os-release | cut -d= -f2- | tr -d '"' || true)"
        printf 'Operating OS: %s\n' "${os_name:-Unknown}"
    fi
    printf 'Kernel:       %s\n' "$(uname -r)"
    printf 'Current user: %s\n' "$(id -un)"
    if command -v uptime >/dev/null 2>&1; then
        printf 'Uptime:       %s\n' "$(uptime -p 2>/dev/null || uptime)"
    fi
    if command -v ip >/dev/null 2>&1; then
        notice 'Global IP addresses (where available):'
        ip -brief address show scope global 2>/dev/null || notice 'Could not read addresses.'
    fi
}

show_ports() {
    section '2. LISTENING NETWORK PORTS (TCP / UDP)'
    if command -v ss >/dev/null 2>&1; then
        ss -tuln 2>&1 || notice 'Could not retrieve socket data.'
    elif command -v netstat >/dev/null 2>&1; then
        netstat -tuln 2>&1 || notice 'Could not retrieve socket data.'
    else
        notice 'Neither ss nor netstat is installed. Install iproute2 for ss.'
    fi
    notice 'Listening ports are not necessarily reachable through the firewall.'
}

show_firewall() {
    section '3. FIREWALL STATUS'
    local found=0 output
    if command -v ufw >/dev/null 2>&1; then
        found=1
        notice 'UFW:'
        if output="$(ufw status verbose 2>&1)"; then
            printf '%s\n' "$output"
        else
            notice 'UFW status unavailable (try running the audit with sudo).'
        fi
    fi
    if command -v firewall-cmd >/dev/null 2>&1; then
        found=1
        notice 'firewalld:'
        if output="$(firewall-cmd --state 2>&1)"; then
            printf '%s\n' "$output"
        else
            notice 'firewalld not running or status unavailable.'
        fi
    fi
    if command -v nft >/dev/null 2>&1; then
        found=1
        notice 'nftables:'
        if (( EUID == 0 )); then
            if output="$(nft list ruleset 2>&1)"; then
                if [[ -n "$output" ]]; then
                    printf '%s\n' "$output" | sed -n '1,40p'
                    notice 'Showing at most 40 lines of nftables rules.'
                else
                    notice 'No nftables rules returned.'
                fi
            else
                notice 'Could not inspect nftables rules.'
            fi
        else
            notice 'Run with sudo to inspect nftables rules.'
        fi
    fi
    if (( found == 0 )); then
        notice 'UFW, firewalld, and nft utilities were not found in PATH.'
    fi
    notice 'Review all active firewall backends before drawing security conclusions.'
}

show_services() {
    section '4. RUNNING SERVICES'
    local output
    if command -v systemctl >/dev/null 2>&1; then
        if output="$(systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null)" && [[ -n "$output" ]]; then
            printf '%s\n' "$output" | sed -n '1,25p'
            notice 'Showing at most 25 running systemd services.'
            return
        fi
    fi
    notice 'Running systemd services unavailable (systemd might not be active).'
    if command -v ps >/dev/null 2>&1; then
        notice 'Fallback: first 20 process commands:'
        ps -eo comm= 2>/dev/null | sed -n '1,20p'
    fi
}

show_updates() {
    section '5. AVAILABLE PACKAGE UPDATES (CACHED METADATA)'
    if command -v apt >/dev/null 2>&1; then
        local output
        if output="$(apt list --upgradable 2>/dev/null)"; then
            printf '%s\n' "$output" | sed -n '1,26p'
            notice 'Based on locally cached package lists; does not refresh repositories.'
        else
            notice 'Could not query apt package metadata.'
        fi
    else
        notice 'This check currently supports apt-based distributions only.'
    fi
}

run_all() {
    printf '%s\n' '============================================================'
    printf '%s\n' '               LINUX SECURITY AUDIT TOOL'
    printf '%s\n' '============================================================'
    notice 'Read-only audit. No firewall rules, packages, or services are changed.'
    if (( EUID != 0 )); then
        notice 'Not running as root; some security details may be restricted.'
    fi
    show_system
    show_ports
    show_firewall
    show_services
    show_updates
    section 'AUDIT COMPLETE'
    notice 'Review findings manually; this tool does not assign risk scores.'
}

save_full_report() {
    if ! mkdir -p -- "$REPORT_DIR"; then
        printf 'Error: cannot create report directory: %s\n' "$REPORT_DIR" >&2
        return 1
    fi
    chmod 700 -- "$REPORT_DIR" 2>/dev/null || true
    local path
    path="${REPORT_DIR}/audit-$(date '+%Y%m%d-%H%M%S')-$$.txt"
    if run_all | tee "$path"; then
        chmod 600 -- "$path" 2>/dev/null || true
        printf '\n[+] Report saved: %s\n' "$path"
    else
        printf 'Error: audit or report writing failed.\n' >&2
        return 1
    fi
}

usage() {
    cat <<'HELP'
Usage: bash tool.sh [OPTION]

Options:
  --all       Run full audit and save a text report (default for noninteractive use)
  --system    Show system details
  --ports     List listening TCP/UDP ports
  --firewall  Inspect available firewall status
  --services  List running services
  --updates   Show package updates from cached apt metadata
  --help      Show this help

Run without arguments in an interactive terminal for the menu.
Optional: SEC_AUDIT_REPORT_DIR=/path/to/reports bash tool.sh --all
HELP
}

menu() {
    local choice
    while true; do
        printf '\n======================================\n'
        printf '       LINUX SECURITY AUDIT TOOL\n'
        printf '======================================\n'
        printf '[1] System information\n[2] Open ports\n[3] Firewall status\n'
        printf '[4] Running services\n[5] Available updates\n'
        printf '[6] Full audit + save report\n[0] Exit\n'
        printf 'Choose an option: '
        if ! IFS= read -r choice; then
            printf '\n'
            return 0
        fi
        case "$choice" in
            1) show_system ;;
            2) show_ports ;;
            3) show_firewall ;;
            4) show_services ;;
            5) show_updates ;;
            6) save_full_report ;;
            0) notice 'Goodbye!'; return 0 ;;
            *) notice 'Invalid option. Choose 0 through 6.' ;;
        esac
    done
}

main() {
    if (( $# == 0 )); then
        if [[ -t 0 ]]; then menu; else save_full_report; fi
        return
    fi
    if (( $# != 1 )); then usage >&2; return 2; fi
    case "$1" in
        --all) save_full_report ;;
        --system) show_system ;;
        --ports) show_ports ;;
        --firewall) show_firewall ;;
        --services) show_services ;;
        --updates) show_updates ;;
        --help|-h) usage ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; return 2 ;;
    esac
}

main "$@"
