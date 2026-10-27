# Scripting & Automation — Phase 1

**IqraSec Academy | Submission-ready project structure (screenshots pending user testing)**

This project contains the two required command-line tools.

| Folder | Script | What it does | Requirements |
|---|---|---|---|
| `Bash-Tool/` | `tool.sh` | Read-only Linux security audit | Linux + Bash |
| `Python-Tool/` | `tool.py` | SHA-256 file hash and integrity verification | Python 3.9+ |

## Project Layout

```text
Phase-1/
├── README.md
├── Bash-Tool/
│   ├── tool.sh
│   ├── README.md
│   └── screenshots/
└── Python-Tool/
    ├── tool.py
    ├── README.md
    └── screenshots/
```

Each tool's README includes the name, objective, features, requirements, run commands, sample usage and output, implementation challenges, future improvements, and screenshot instructions.

## Quick Start

Linux Bash script:

```bash
cd Bash-Tool
chmod +x tool.sh
./tool.sh
# Or run and save a report:
./tool.sh --all
```

Python integrity checker:

```bash
cd Python-Tool
python3 tool.py --help
# Create a demo.txt file in your editor first, then:
python3 tool.py baseline demo.txt
python3 tool.py verify demo.txt
```

On Windows, use `python` rather than `python3` if needed.

## Before Submitting

- [ ] Run both tools in your authorized lab.
- [ ] Check that outputs match your environment.
- [ ] Capture **real screenshots** in each `screenshots/` directory.
- [ ] Remove generated private audit reports, real-world IPs, secrets, and unnecessary data from your public repository.
- [ ] If necessary, update the **Challenges Faced** sections to reflect your actual testing experience.
- [ ] Commit both project folders together to one GitHub repository or upload the folder to Google Drive.

**Submission window:** November 1–5, 2026. **Final deadline:** November 5, 2026.

**Safety:** Run cybersecurity tooling only on systems you own or are authorized to test.
