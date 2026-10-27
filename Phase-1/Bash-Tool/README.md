# Linux Security Audit Tool (Bash)

## Tool Name
**Linux Security Audit Tool** — `tool.sh`

## Objective
Provide a quick, **read-only local security overview** of a Linux system. Useful when a SOC analyst or system administrator wants to review basic exposure and system posture before doing a more detailed investigation.

## Features
- Interactive menu with numbered options.
- Display hostname, operating system, kernel, user, uptime, and global IP addresses.
- List local **listening TCP and UDP ports** with `ss` (or `netstat` fallback).
- Inspect UFW and firewalld status when present; show the first 40 lines of nftables rules when running as root.
- Show up to 25 currently running systemd services (process-list fallback).
- Display up to 25 available APT package updates using **cached package metadata**.
- Run all checks together and automatically save a timestamped `.txt` report in `reports/`.
- Support individual checks from the command line for simple automation.
- Does **not** change firewall settings, update packages, or stop services.

## Requirements
- A Linux system such as **Ubuntu 22.04+ or Kali Linux**.
- Bash 4+ and standard utilities (`date`, `hostname`, `uname`, `id`, `sed`, `grep`, `cut`, `tee`).
- Recommended: `iproute2` (`ss`, `ip`) and `procps` (`ps`).
- Optional: `ufw`, `firewalld`, `nftables`, `systemd` and `apt`, depending on the Linux distribution.
- Normal user permissions are sufficient for many checks. Root permissions may be needed to view firewall rules.

No third-party Bash package or external API is required. Some checks may show an informational message when their Linux utility is unavailable.

## How to Run

Open a Linux terminal in the `Bash-Tool/` directory:

```bash
chmod +x tool.sh
./tool.sh
```

Choose menu option **6** to run the complete audit and save a report.

You can also run without using the menu:

```bash
./tool.sh --all
./tool.sh --ports
./tool.sh --firewall
./tool.sh --services
./tool.sh --updates
./tool.sh --system
./tool.sh --help
```

To inspect firewall rules with elevated permissions:

```bash
sudo ./tool.sh --all
```

To choose a different report directory:

```bash
SEC_AUDIT_REPORT_DIR="$HOME/audit-reports" ./tool.sh --all
```

> **Note:** The report may contain hostnames, IP addresses, and service details. Keep reports private and redact sensitive information in public screenshots and repositories.

## Example Usage

```bash
./tool.sh --ports
```

To generate a full report:

```bash
./tool.sh --all
```

## Example Output

**Illustrative output** — the actual values depend on your Linux machine:

```text
------------------------------------------------------------
2. LISTENING NETWORK PORTS (TCP / UDP)
------------------------------------------------------------
Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port
tcp   LISTEN 0      128    0.0.0.0:22          0.0.0.0:*
[i] Listening ports are not necessarily reachable through the firewall.

[+] Report saved: /home/user/Phase-1/Bash-Tool/reports/audit-YYYYMMDD-HHMMSS-PID.txt
```

The report filename includes the date/time and a process ID to reduce accidental collisions.

## Challenges Faced
- **Linux tools differ across distributions.** The script checks whether utilities exist and provides a useful message when a check cannot run.
- **Firewall visibility depends on privileges.** Detailed nftables rule inspection is performed only when running as root; the report clearly identifies limited access.
- **Package information can be stale.** The updates check uses locally cached APT metadata and does not pretend to perform a fresh internet check.
- **Systemd is not always available.** The script uses a basic process-list fallback when it cannot retrieve running systemd services.

## Future Improvements
- Export structured JSON/CSV results.
- Analyze risky open ports using user-defined rules.
- Support other package managers such as DNF and Pacman.
- Provide configurable audit policies and severity labels.
- Add automated test coverage across more Linux distributions.

## Screenshots to Capture
After testing on **your own Linux lab**, save real screenshots in `screenshots/`, for example:

1. `01-main-menu.png` — menu shown after `./tool.sh`.
2. `02-open-ports.png` — option 2 or `./tool.sh --ports`.
3. `03-firewall-status.png` — option 3 or `./tool.sh --firewall`.
4. `04-complete-audit.png` — audit completion and saved report location.

## Limitations & Safety
This is a **basic local configuration overview**, not a penetration test, full vulnerability scanner, or proof that a host is secure. A listening port does not imply internet accessibility. The script never modifies the target system's security settings. Run it only on systems you own or are authorized to administer.
