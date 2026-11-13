    if have ufw; then
        checked=1
        local ufw_status
        ufw_status="$(ufw status 2>&1 || true)"
        printf '%s\n' "$ufw_status"
        if grep -qi 'Status: active' <<< "$ufw_status"; then status_pass 'UFW firewall is active.'
        elif grep -qi 'Status: inactive' <<< "$ufw_status"; then status_warn 'UFW is installed but inactive.'
        else status_unknown 'UFW status could not be determined (permissions or service issue).'; fi
    fi
    if have firewall-cmd; then
        checked=1
        local fw_state
        fw_state="$(firewall-cmd --state 2>&1 || true)"
        printf 'firewalld state: %s\n' "$fw_state"
        if [[ "$fw_state" == 'running' ]]; then status_pass 'firewalld is running.'
        else status_warn 'firewalld is not reported as running.'; fi
    fi
    if (( checked == 0 )); then
        status_unknown 'Neither UFW nor firewall-cmd was found. Other firewall frameworks may still be configured.'
    fi
    status_info 'This check does not change firewall settings.'
}

check_updates() {
    printf '\n%sSystem Updates Check%s\n' "$BOLD" "$RESET"
    if ! have apt; then status_unknown 'APT is unavailable; this update check supports Ubuntu and Kali/Debian-based systems.'; return; fi
    status_info 'Reading the locally cached APT package lists; no package lists are refreshed.'
    local output count
    output="$(apt list --upgradable 2>/dev/null || true)"
    if [[ -z "$output" ]]; then
        status_unknown 'APT did not return update information.'
        return
    fi
    count="$(printf '%s\n' "$output" | awk 'NR>1 && $0 !~ /^Listing/ && NF {n++} END {print n+0}')"
    printf 'Packages with available updates in cached package lists: %s\n' "$count"
    if (( count > 0 )); then
        status_warn "$count package(s) appear to have updates available. Review them with your package manager."
        printf '%s\n' "$output" | sed -n '1,21p'
        (( count > 20 )) && printf '... additional package entries omitted from this display.\n'
    else
        status_pass 'No upgradable packages were listed in the cached package lists.'
    fi
    status_info 'Results may be outdated because package lists were not refreshed.'
}

full_health_check() {
    printf '\n%sFULL SYSTEM HEALTH CHECK%s\n' "$BOLD" "$RESET"
    check_system_info
    check_cpu_memory
    check_disk
    check_services
    check_network
    check_firewall
    check_updates
    printf '\n%sHealth check completed.%s\n' "$GREEN" "$RESET"
    status_info 'Review WARNING, CRITICAL, and UNKNOWN results; this tool reports indicators, not a definitive diagnosis.'
}

view_latest_report() {
    printf '\n%sLatest Diagnostic Report%s\n' "$BOLD" "$RESET"
    if [[ ! -d "$REPORT_DIR" ]]; then status_info 'No reports directory exists yet. Run a diagnostic first.'; return; fi
    local latest
    latest="$(find "$REPORT_DIR" -maxdepth 1 -type f -name 'healthcheck_*.txt' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -n 1 | cut -d' ' -f2-)"
    if [[ -z "$latest" || ! -f "$latest" ]]; then status_info 'No diagnostic reports were found.'; return; fi
    LATEST_REPORT="$latest"
    printf 'Report: %s\n\n' "$latest"
    if have less && [[ -t 0 ]]; then less -- "$latest"
    else cat -- "$latest"; fi
}

show_banner() {
    printf '%s' "$CYAN"
    printf '============================================================\n'
    printf '                 %s v%s\n' "$APP_NAME" "$VERSION"
    printf '          System Health & Troubleshooting Assistant\n'
    printf '============================================================\n'
    printf '%s' "$RESET"
    printf 'Hostname: %s\n' "$(hostname 2>/dev/null || printf 'Unavailable')"
    printf 'OS:       %s\n' "$(get_os_name)"
    printf 'Date:     %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
    printf '\n'
}

show_menu() {
    printf '%s%sMAIN MENU%s\n' "$BOLD" "$BLUE" "$RESET"
    printf '  1. System Information\n'
    printf '  2. CPU & Memory Health\n'
    printf '  3. Disk Usage Analysis\n'
    printf '  4. Failed System Services\n'
    printf '  5. Network Connectivity Check\n'
    printf '  6. Firewall Status\n'
    printf '  7. System Updates Check\n'
    printf '  8. Full System Health Check\n'
    printf '  9. View Latest Report\n'
    printf ' 10. Exit\n\n'
}

main() {
    local choice
    while true; do
        if [[ -t 1 ]]; then clear 2>/dev/null || true; fi
        show_banner
        show_menu
        printf 'Select an option [1-10]: '
        if ! IFS= read -r choice; then printf '\n'; break; fi
        case "$choice" in
            1) run_and_save 'System Information' check_system_info; pause ;;
            2) run_and_save 'CPU & Memory Health' check_cpu_memory; pause ;;
            3) run_and_save 'Disk Usage Analysis' check_disk; pause ;;
            4) run_and_save 'Failed System Services' check_services; pause ;;
            5) run_and_save 'Network Connectivity Check' check_network; pause ;;
            6) run_and_save 'Firewall Status' check_firewall; pause ;;
            7) run_and_save 'System Updates Check' check_updates; pause ;;
            8) run_and_save 'Full System Health Check' full_health_check; pause ;;
            9) view_latest_report; pause ;;
            10) printf '\nGoodbye. No system configuration was changed.\n'; break ;;
            *) status_warn 'Invalid selection. Enter a number from 1 to 10.'; sleep 1 ;;
        esac
    done
}

main "$@"
