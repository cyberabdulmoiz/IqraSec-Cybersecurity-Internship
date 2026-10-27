# Simple File Integrity Checker (Python)

## Tool Name
**Simple File Integrity Checker** — `tool.py`

## Objective
Use **SHA-256** to detect whether the contents of a selected file have changed since an earlier trusted snapshot (called a *baseline*). This demonstrates a fundamental blue-team security concept: **file integrity monitoring (FIM)**.

## Features
- Calculate a file's SHA-256 cryptographic hash.
- Save a **baseline** with hash, filename, file size, and creation timestamp in JSON format.
- Verify whether the file still matches the saved baseline.
- Display a clear **PASS** result when unchanged or **ALERT** when changed.
- Read large files in 1 MiB chunks instead of loading the entire file into RAM.
- Use only Python's standard library (no `pip install` required).
- Return meaningful command exit codes for automation.
- Prevent accidental baseline overwriting unless `--force` is explicitly provided.

## Requirements
- Python **3.9 or later** (Python 3.10+ recommended).
- Windows, Ubuntu, Kali Linux, or another OS with Python installed.
- Read access to the file to be checked; write access to the location where the baseline will be saved.

No third-party modules and no internet connection are required.

## How to Run

Open a terminal or command prompt in the `Python-Tool/` directory.

On Linux:

```bash
python3 tool.py --help
```

On Windows (if `python` is available):

```powershell
python tool.py --help
```

Prepare a small **test file** such as `demo.txt` (create it in the same directory using any text editor).

**Step 1: Calculate the current hash**

```bash
python3 tool.py hash demo.txt
```

**Step 2: Save the baseline**

```bash
python3 tool.py baseline demo.txt
```

This writes `demo.txt.sha256.json` in the same directory.

**Step 3: Verify the unchanged file**

```bash
python3 tool.py verify demo.txt
```

**Step 4: Edit `demo.txt`, save it, then verify again**

```bash
python3 tool.py verify demo.txt
```

This time the program should print an **ALERT** because the file content changed.

To intentionally reset the baseline after approving a change:

```bash
python3 tool.py baseline demo.txt --force
```

Optional custom baseline path:

```bash
python3 tool.py baseline demo.txt --db evidence/demo-baseline.json
python3 tool.py verify demo.txt --db evidence/demo-baseline.json
```

The parent directory (such as `evidence/`) must already exist.

> **Windows users:** Replace `python3` with `python` in the examples if that is your installed command.

## Example Usage

```text
$ python3 tool.py baseline demo.txt
[OK] SHA-256 baseline created.
File:     demo.txt
Baseline: demo.txt.sha256.json
SHA256:   <64-character SHA-256 digest>
```

## Example Output

**Unchanged file:**

```text
$ python3 tool.py verify demo.txt
File:     demo.txt
Baseline: demo.txt.sha256.json
Expected: <saved SHA-256 digest>
Actual:   <same SHA-256 digest>
[PASS] File content matches the saved baseline.
```

**Modified file:**

```text
$ python3 tool.py verify demo.txt
File:     demo.txt
Baseline: demo.txt.sha256.json
Expected: <saved SHA-256 digest>
Actual:   <different SHA-256 digest>
[ALERT] File content has CHANGED since the baseline was created!
```

Exit codes: `0` = success/match; `1` = changed file detected during verification; `2` = invalid arguments, missing files/baseline, or other input/output error.

## Challenges Faced
- **Large files:** Using chunk-based hashing keeps memory usage low even for large files.
- **Preventing accidental baseline loss:** The program refuses to overwrite an existing baseline unless `--force` is given.
- **Distinguishing changes from errors:** Verification returns different exit codes for a modified file versus missing or invalid inputs.
- **Baseline trust:** Hashes only provide a meaningful integrity check if the original baseline is trusted and protected.

## Future Improvements
- Verify an entire directory, not just one selected file.
- Maintain several baselines and a change history.
- Export a CSV report for a collection of files.
- Schedule periodic integrity checks.
- Add digital signatures or protected central storage for baselines.

## Screenshots to Capture
After your own test, save genuine screenshots in `screenshots/`:

1. `01-hash-calculation.png` — output of `hash demo.txt`.
2. `02-baseline-created.png` — output of `baseline demo.txt`.
3. `03-unchanged-file.png` — output of `verify demo.txt` before modification.
4. `04-modified-file-alert.png` — output of `verify demo.txt` after modification.

## Limitations & Safety
- This tool checks the **contents of one file**. It does not continuously watch files or automatically detect changes in real time.
- SHA-256 does **not** prove who modified the file. Metadata such as timestamps or permissions are not independently checked.
- If an attacker can modify **both the file and its baseline**, the comparison can be defeated. For real security monitoring, protect the baseline in a separate trusted location.
- Use it only for files you own or have authorization to inspect.
