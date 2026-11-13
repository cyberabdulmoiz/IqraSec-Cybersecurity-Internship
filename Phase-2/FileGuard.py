"""FileGuard: a small, local file integrity monitor for Windows.

Only the selected folder is scanned. FileGuard reads monitored files to hash them;
it never changes their contents. Baseline changes always require user approval.
"""
from __future__ import annotations

import hashlib
import os
import queue
import sqlite3
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "FileGuard"
INTERVALS = {"15 minutes": 15, "30 minutes": 30, "1 hour": 60,
             "6 hours": 360, "12 hours": 720, "24 hours": 1440}


def app_data_dir() -> Path:
    """Return a per-user writable data directory (works without admin rights)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        folder = Path(base) / APP_NAME
    else:
        folder = Path.home() / ".fileguard"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def timestamp() -> str:
    # Use the computer's local clock without forcing a timezone label such as PKT.
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_folder(folder: Path, cancel: threading.Event, progress):
    """Hash regular files without following symlinks; errors make scan incomplete."""
    files, errors = {}, []
    root = folder.resolve()
    def walk_error(exc):
        errors.append(f"{getattr(exc, 'filename', root)}: {exc}")
    for current, dirs, names in os.walk(root, topdown=True, onerror=walk_error, followlinks=False):
        if cancel.is_set():
            return files, errors, False
        current_path = Path(current)
        # Drop directory symlinks/junctions and inaccessible entries from traversal.
        kept = []
        for name in dirs:
            child = current_path / name
            try:
                if child.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(child)):
                    continue
                kept.append(name)
            except OSError as exc:
                errors.append(f"{child}: {exc}")
        dirs[:] = kept
        for name in names:
            if cancel.is_set():
                return files, errors, False
            path = current_path / name
            try:
                if path.is_symlink() or (hasattr(os.path, "isjunction") and os.path.isjunction(path)) or not path.is_file():
                    continue
                stat = path.stat()
                rel = path.relative_to(root).as_posix()
                files[rel] = {"hash": sha256_file(path), "size": stat.st_size,
                              "mtime": stat.st_mtime}
            except (OSError, ValueError) as exc:
                errors.append(f"{path}: {exc}")
            progress(len(files), str(path))
    return files, errors, not cancel.is_set()


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS baseline(path TEXT PRIMARY KEY, hash TEXT NOT NULL,
                size INTEGER NOT NULL, mtime REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, started TEXT NOT NULL,
                finished TEXT, scanned INTEGER NOT NULL DEFAULT 0, new INTEGER NOT NULL DEFAULT 0,
                modified INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
                renamed INTEGER NOT NULL DEFAULT 0, moved INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0, error_details TEXT NOT NULL DEFAULT '', status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
                kind TEXT NOT NULL, old_path TEXT, path TEXT, old_hash TEXT, hash TEXT,
                size INTEGER, mtime REAL, detected TEXT NOT NULL, approved INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(scan_id) REFERENCES scans(id));
            """)
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('folder','')")
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('baseline_ready','0')")
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('interval','30 minutes')")
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('auto','0')")
            db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('theme','Light')")
            columns = {row[1] for row in db.execute("PRAGMA table_info(scans)")}
            if "error_details" not in columns:
                db.execute("ALTER TABLE scans ADD COLUMN error_details TEXT NOT NULL DEFAULT ''")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def get(self, key):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row[0] if row else ""

    def set(self, key, value):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def baseline(self):
        with self.lock, self.connect() as db:
            return {r["path"]: dict(r) for r in db.execute("SELECT * FROM baseline")}

    def count(self):
        with self.lock, self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM baseline").fetchone()[0]

    def has_baseline(self):
        return self.get("baseline_ready") == "1"

    def create_baseline(self, files):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM baseline")
            db.executemany("INSERT INTO baseline(path,hash,size,mtime) VALUES(?,?,?,?)",
                           [(p, v["hash"], v["size"], v["mtime"]) for p, v in files.items()])
        self.set("baseline_ready", "1")

    def begin_scan(self):
        with self.lock, self.connect() as db:
            cur = db.execute("INSERT INTO scans(started,status) VALUES(?, 'Scanning')", (timestamp(),))
            return cur.lastrowid

    def finish_scan(self, scan_id, files, errors, complete, base):
        """Persist changes; missing-file events are emitted only for a complete scan."""
        now = timestamp()
        found = set(files) - set(base)
        missing = set(base) - set(files) if complete and not errors else set()
        changes = []
        # A same-hash one-to-one match is strong evidence for rename/move.
        old_by_hash, new_by_hash = {}, {}
        for p in missing:
            old_by_hash.setdefault(base[p]["hash"], []).append(p)
        for p in found:
            new_by_hash.setdefault(files[p]["hash"], []).append(p)
        paired_old, paired_new = set(), set()
        for digest, olds in old_by_hash.items():
            news = new_by_hash.get(digest, [])
            if len(olds) == len(news) == 1:
                old, new = olds[0], news[0]
                kind = "RENAMED" if Path(old).parent == Path(new).parent else "MOVED"
                changes.append((kind, old, new, digest, digest, files[new], now))
                paired_old.add(old); paired_new.add(new)
        for p in found - paired_new:
            changes.append(("NEW", None, p, None, files[p]["hash"], files[p], now))
        for p in missing - paired_old:
            changes.append(("DELETED", p, None, base[p]["hash"], None, None, now))
        for p in set(files) & set(base):
            if files[p]["hash"] != base[p]["hash"]:
                changes.append(("MODIFIED", p, p, base[p]["hash"], files[p]["hash"], files[p], now))
        counts = {k: sum(c[0] == k for c in changes) for k in ("NEW", "MODIFIED", "DELETED", "RENAMED", "MOVED")}
        status = "Cancelled" if not complete else ("Completed with errors" if errors else "Completed")
        with self.lock, self.connect() as db:
            for kind, old, path, old_hash, digest, data, detected in changes:
                db.execute("INSERT INTO changes(scan_id,kind,old_path,path,old_hash,hash,size,mtime,detected) VALUES(?,?,?,?,?,?,?,?,?)",
                           (scan_id, kind, old, path, old_hash, digest,
                            data["size"] if data else None, data["mtime"] if data else None, detected))
            db.execute("UPDATE scans SET finished=?,scanned=?,new=?,modified=?,deleted=?,renamed=?,moved=?,errors=?,error_details=?,status=? WHERE id=?",
                       (now, len(files), counts["NEW"], counts["MODIFIED"], counts["DELETED"], counts["RENAMED"], counts["MOVED"], len(errors), "\n".join(errors), status, scan_id))
        return changes, counts

    def pending(self):
        with self.lock, self.connect() as db:
            return [dict(r) for r in db.execute("SELECT c.*,s.started FROM changes c JOIN scans s ON s.id=c.scan_id WHERE c.approved=0 ORDER BY c.id DESC")]

    def approve(self, change_id):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM changes WHERE id=? AND approved=0", (change_id,)).fetchone()
            if not row: return False
            if row["kind"] in ("RENAMED", "MOVED"):
                db.execute("DELETE FROM baseline WHERE path=?", (row["old_path"],))
            if row["kind"] == "DELETED":
                db.execute("DELETE FROM baseline WHERE path=?", (row["old_path"],))
            elif row["path"]:
                db.execute("INSERT INTO baseline(path,hash,size,mtime) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET hash=excluded.hash,size=excluded.size,mtime=excluded.mtime",
                           (row["path"], row["hash"], row["size"], row["mtime"]))
            db.execute("UPDATE changes SET approved=1 WHERE id=?", (change_id,))
            return True

    def approve_scan(self, scan_id):
        with self.lock, self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM changes WHERE scan_id=? AND approved=0", (scan_id,))]
        for cid in ids: self.approve(cid)
        return len(ids)

    def history(self):
        with self.lock, self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM scans ORDER BY id DESC")]

    def changes_for_scan(self, scan_id):
        with self.lock, self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM changes WHERE scan_id=? ORDER BY id", (scan_id,))]

    def clear_history(self):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM changes"); db.execute("DELETE FROM scans")


class FileGuardApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FileGuard — File Integrity Monitor")
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        window_width = min(1120, max(540, int(screen_width * 0.90)))
        window_height = min(740, max(420, int(screen_height * 0.88)))
        x = max(0, (screen_width - window_width) // 2)
        y = max(0, (screen_height - window_height) // 2)
        self.geometry(f"{window_width}x{window_height}+{x}+{y}")
        self.minsize(min(900, window_width), min(620, window_height))
        self.resizable(True, True)
        database_path = app_data_dir() / "fileguard.sqlite3"
        if not database_path.exists():
            messagebox.showinfo(
                "FileGuard local data file",
                "FileGuard is about to create its database at:\n\n"
                f"{database_path}\n\n"
                "The database stays on this computer and stores your selected folder, "
                "file baseline, scan history, detected changes, and settings."
            )
        self.store = Store(database_path)
        self.events = queue.Queue(); self.cancel = threading.Event(); self.scanning = False
        self.current_page = "Dashboard"
        self.colors = {}
        self._build(); self.apply_theme(self.store.get("theme") or "Light")
        self.refresh_dashboard(); self.show_page("Dashboard")
        self.after(200, self._poll); self.after(1000, self._auto_tick)
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        self.columnconfigure(1, weight=1); self.rowconfigure(0, weight=1)
        self.sidebar = tk.Frame(self, width=205); self.sidebar.grid(row=0,column=0,sticky="nsw"); self.sidebar.grid_propagate(False)
        tk.Label(self.sidebar,text="FILEGUARD",font=("Segoe UI",18,"bold")).pack(anchor="w",padx=20,pady=(24,3))
        tk.Label(self.sidebar,text="FILE INTEGRITY MONITOR",font=("Segoe UI",8)).pack(anchor="w",padx=21,pady=(0,25))
        self.nav = {}
        for name in ("Dashboard","Change Review","Scan History","Settings"):
            btn=tk.Button(self.sidebar,text="  "+name,anchor="w",relief="flat",font=("Segoe UI",10),command=lambda n=name:self.show_page(n))
            btn.pack(fill="x",padx=10,pady=3,ipady=10); self.nav[name]=btn
        tk.Label(self.sidebar,text="Local monitoring\nChanges need your approval",justify="left",font=("Segoe UI",9)).pack(side="bottom",anchor="w",padx=20,pady=20)
        self.main=tk.Frame(self); self.main.grid(row=0,column=1,sticky="nsew",padx=28,pady=24); self.main.columnconfigure(0,weight=1); self.main.rowconfigure(1,weight=1)
        self.header=tk.Frame(self.main); self.header.grid(row=0,column=0,sticky="ew",pady=(0,16)); self.header.columnconfigure(0,weight=1)
        self.page_title=tk.Label(self.header,text="",font=("Segoe UI",22,"bold")); self.page_title.grid(row=0,column=0,sticky="w")
        self.page_body=tk.Frame(self.main); self.page_body.grid(row=1,column=0,sticky="nsew"); self.page_body.columnconfigure(0,weight=1); self.page_body.rowconfigure(0,weight=1)

    def apply_theme(self, theme):
        dark=theme=="Dark"
        bg="#111827" if dark else "#f3f5f8"; panel="#1f2937" if dark else "#ffffff"; fg="#f3f4f6" if dark else "#172033"; muted="#aab4c3" if dark else "#667085"
        self.colors={"bg":bg,"panel":panel,"fg":fg,"muted":muted,"accent":"#536dfe","border":"#374151" if dark else "#e3e8ef"}
        self.configure(bg=bg)
        for w in (self.sidebar,self.main,self.header,self.page_body): w.configure(bg=bg)
        for w in self.sidebar.winfo_children():
            if isinstance(w,tk.Label): w.configure(bg=bg,fg=fg)
            elif isinstance(w,tk.Button): w.configure(bg=bg,fg=fg,activebackground=panel,activeforeground=fg)
        self.page_title.configure(bg=bg,fg=fg)
        self.store.set("theme",theme)
        if hasattr(self,"theme_var"): self.theme_var.set(theme)
        self.show_page(self.current_page)

    def show_page(self,name):
        self.current_page=name
        for w in self.page_body.winfo_children(): w.destroy()
        self.page_title.configure(text=name)
        for key,button in self.nav.items():
            button.configure(bg=self.colors["panel"] if key==name else self.colors["bg"],fg=self.colors["fg"])
        if name=="Dashboard": self._dashboard()
        elif name=="Change Review": self._review()
        elif name=="Scan History": self._history_page()
        else: self._settings()

    def card(self,parent,title,value,sub=""):
        f=tk.Frame(parent,bg=self.colors["panel"],highlightthickness=1,highlightbackground=self.colors["border"])
        tk.Label(f,text=title.upper(),bg=self.colors["panel"],fg=self.colors["muted"],font=("Segoe UI",9,"bold")).pack(anchor="w",padx=17,pady=(14,3))
        tk.Label(f,text=value,bg=self.colors["panel"],fg=self.colors["fg"],font=("Segoe UI",23,"bold")).pack(anchor="w",padx=17)
        if sub: tk.Label(f,text=sub,bg=self.colors["panel"],fg=self.colors["muted"],font=("Segoe UI",9)).pack(anchor="w",padx=17,pady=(0,14))
        return f

    def _dashboard(self):
        b=self.page_body; b.columnconfigure((0,1,2),weight=1); b.rowconfigure(4,weight=1)
        folder=self.store.get("folder") or "No folder selected"
        pathbox=tk.Frame(b,bg=self.colors["panel"],highlightthickness=1,highlightbackground=self.colors["border"]); pathbox.grid(row=0,column=0,columnspan=3,sticky="ew",pady=(0,14)); pathbox.columnconfigure(0,weight=1)
        tk.Label(pathbox,text="MONITORED FOLDER",bg=self.colors["panel"],fg=self.colors["muted"],font=("Segoe UI",9,"bold")).grid(row=0,column=0,sticky="w",padx=16,pady=(12,2))
        tk.Label(pathbox,text=folder,bg=self.colors["panel"],fg=self.colors["fg"],anchor="w",font=("Segoe UI",10),wraplength=700).grid(row=1,column=0,sticky="ew",padx=16,pady=(0,12))
        self.button(pathbox,"Select Folder",self.select_folder).grid(row=0,column=1,rowspan=2,padx=15,pady=12)
        self.total_var=tk.StringVar(); self.last_var=tk.StringVar(); self.status_var=tk.StringVar()
        self.card(b,"Baseline files",str(self.store.count()),"Files in the saved baseline").grid(row=1,column=0,sticky="ew",padx=(0,8),pady=7)
        hist=self.store.history(); last=hist[0] if hist else None
        self.card(b,"Last scan",last["finished"] or last["started"] if last else "Never",last["status"] if last else "Create a baseline to start").grid(row=1,column=1,sticky="ew",padx=8,pady=7)
        pending=len(self.store.pending())
        self.card(b,"Pending review",str(pending),"Detected changes awaiting your decision").grid(row=1,column=2,sticky="ew",padx=(8,0),pady=7)
        stats=[("New", "NEW", "#2583eb"),("Modified","MODIFIED","#dd8a13"),("Deleted","DELETED","#dc3545"),("Renamed","RENAMED","#8250df"),("Moved","MOVED","#8250df")]
        row=2
        for i,(label,kind,color) in enumerate(stats):
            count=sum(1 for c in self.store.pending() if c["kind"]==kind)
            f=self.card(b,label,str(count),"Pending"); f.grid(row=row+i//3,column=i%3,sticky="ew",padx=(0,8) if i%3==0 else (8,0),pady=7)
            for child in f.winfo_children():
                if isinstance(child,tk.Label) and child.cget("text")==str(count): child.configure(fg=color)
        controls=tk.Frame(b,bg=self.colors["bg"]); controls.grid(row=4,column=0,columnspan=3,sticky="ew",pady=(18,0))
        self.button(controls,"Create Baseline",self.create_baseline).pack(side="left",padx=(0,8))
        self.scan_button=self.button(controls,"Scan Now",self.start_scan); self.scan_button.pack(side="left",padx=8)
        self.button(controls,"View Changes",lambda:self.show_page("Change Review")).pack(side="left",padx=8)
        self.button(controls,"Scan History",lambda:self.show_page("Scan History")).pack(side="left",padx=8)
        self.progress=ttk.Progressbar(controls,mode="indeterminate",length=180)
        self.progress_label=tk.Label(controls,text="",bg=self.colors["bg"],fg=self.colors["muted"])

    def button(self,parent,text,command):
        return tk.Button(parent,text=text,command=command,bg=self.colors["accent"],fg="white",activebackground="#4058dc",activeforeground="white",relief="flat",font=("Segoe UI",9,"bold"),padx=14,pady=9,cursor="hand2")

    def select_folder(self):
        selected=filedialog.askdirectory(title="Select the folder to monitor",mustexist=True)
        if not selected:return
        root=Path(selected).resolve(); dbpath=self.store.path.resolve()
        try: dbpath.relative_to(root)
        except ValueError: pass
        else:
            messagebox.showerror("Folder not allowed","FileGuard's own data folder cannot be monitored."); return
        old=self.store.get("folder")
        if old and Path(old).resolve()!=root:
            if not messagebox.askyesno("Change monitored folder","Changing folders starts a separate baseline. Existing scan history will remain. Continue?"):return
            with self.store.connect() as db: db.execute("DELETE FROM baseline")
            self.store.set("baseline_ready", "0")
        self.store.set("folder",str(root)); self.refresh_dashboard()
        if not self.store.has_baseline(): self.create_baseline()

    def create_baseline(self):
        folder=self.store.get("folder")
        if not folder or not Path(folder).is_dir():
            messagebox.showinfo("Select a folder","Choose an existing folder before creating a baseline."); return
        if self.store.has_baseline() and not messagebox.askyesno("Replace baseline?","This replaces the current baseline with the folder's current contents. Continue?"):return
        self._run_worker("baseline",Path(folder))

    def start_scan(self):
        if self.scanning:return
        folder=self.store.get("folder")
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Folder unavailable","Select an existing folder before scanning."); return
        if not self.store.has_baseline():
            if messagebox.askyesno("No baseline","Create the initial baseline now?"): self.create_baseline()
            return
        self._run_worker("scan",Path(folder))

    def _run_worker(self,mode,folder):
        if self.scanning:return
        self.scanning=True; self.cancel.clear()
        if hasattr(self,"scan_button"): self.scan_button.configure(text="Cancel Scan",command=self.cancel_scan)
        if hasattr(self,"progress"):
            self.progress.pack(side="right",padx=8)
            self.progress_label.configure(text="Starting…")
            self.progress_label.pack(side="right",padx=8)
            self.progress.start(10)
        snapshot=self.store.baseline(); scan_id=self.store.begin_scan() if mode=="scan" else None
        def progress(n,path): self.events.put(("progress",n,path))
        def work():
            try:
                files,errors,complete=scan_folder(folder,self.cancel,progress)
                if mode=="baseline": self.events.put(("baseline_done",files,errors,complete))
                else: self.events.put(("scan_done",scan_id,files,errors,complete,snapshot))
            except Exception as exc: self.events.put(("failure",str(exc),mode,scan_id))
        threading.Thread(target=work,daemon=True).start()

    def cancel_scan(self): self.cancel.set(); self.progress_label.configure(text="Cancelling…")

    def _poll(self):
        try:
            while True:
                event=self.events.get_nowait(); typ=event[0]
                if typ=="progress": self.progress_label.configure(text=f"Checked {event[1]} files…")
                elif typ=="baseline_done":
                    _,files,errors,complete=event; self.scanning=False; self._worker_finished()
                    if complete and not errors: self.store.create_baseline(files); messagebox.showinfo("Baseline created",f"Saved {len(files)} files to the baseline.")
                    else: messagebox.showerror("Baseline incomplete","The baseline was not saved because scanning was cancelled or files could not be read.\n"+"\n".join(errors[:8]))
                    self.refresh_dashboard()
                elif typ=="scan_done":
                    _,sid,files,errors,complete,base=event
                    changes,counts=self.store.finish_scan(sid,files,errors,complete,base)
                    self.scanning=False; self._worker_finished(); self.refresh_dashboard()
                    if errors: messagebox.showwarning("Scan finished with errors",f"Checked {len(files)} readable files; {len(errors)} item(s) could not be read. Missing files were not marked deleted.\n\n"+"\n".join(errors[:5]))
                    elif not complete: messagebox.showinfo("Scan cancelled","Scan cancelled. No deletion events were recorded.")
                    else: messagebox.showinfo("Scan complete",f"Checked {len(files)} files.\nNew: {counts['NEW']}  Modified: {counts['MODIFIED']}  Deleted: {counts['DELETED']}\nRenamed: {counts['RENAMED']}  Moved: {counts['MOVED']}")
                elif typ=="failure":
                    _,err,mode,sid=event; self.scanning=False; self._worker_finished()
                    if sid:
                        with self.store.connect() as db: db.execute("UPDATE scans SET finished=?,status='Failed' WHERE id=?",(timestamp(),sid))
                    messagebox.showerror("Operation failed",err)
                self.update_idletasks()
        except queue.Empty: pass
        self.after(200,self._poll)

    def _worker_finished(self):
        if hasattr(self,"progress"):
            self.progress.stop()
            self.progress.pack_forget()
            self.progress_label.pack_forget()
            self.progress_label.configure(text="")
        if hasattr(self,"scan_button"): self.scan_button.configure(text="Scan Now",command=self.start_scan)

    def refresh_dashboard(self):
        if self.current_page=="Dashboard": self.show_page("Dashboard")

    def _review(self):
        b=self.page_body; b.rowconfigure(0,weight=1); b.columnconfigure(0,weight=1)
        top=tk.Frame(b,bg=self.colors["bg"]); top.grid(row=0,column=0,sticky="nsew"); top.rowconfigure(1,weight=1); top.columnconfigure(0,weight=1)
        actions=tk.Frame(top,bg=self.colors["bg"]); actions.grid(row=0,column=0,sticky="ew",pady=(0,10))
        self.button(actions,"Approve all from a scan…",self.approve_all).pack(side="left")
        tk.Label(actions,text="Approval updates the baseline for the selected change.",bg=self.colors["bg"],fg=self.colors["muted"]).pack(side="left",padx=14)
        cols=("kind","old_path","path","old_hash","hash","detected")
        tree=ttk.Treeview(top,columns=cols,show="headings",selectmode="browse")
        labels={"kind":"Type","old_path":"Previous path","path":"Current path","old_hash":"Previous SHA-256","hash":"Current SHA-256","detected":"Detected"}
        for col in cols: tree.heading(col,text=labels[col]); tree.column(col,width=165 if "hash" not in col else 240,anchor="w")
        tree.grid(row=1,column=0,sticky="nsew"); sb=ttk.Scrollbar(top,orient="vertical",command=tree.yview); sb.grid(row=1,column=1,sticky="ns"); tree.configure(yscrollcommand=sb.set)
        rows=self.store.pending()
        self.review_map={}
        for r in rows:
            tree.insert("","end",iid=str(r["id"]),values=(r["kind"],r["old_path"] or "—",r["path"] or "—",r["old_hash"] or "—",r["hash"] or "—",r["detected"]))
            self.review_map[r["id"]]=r
        bottom=tk.Frame(top,bg=self.colors["bg"]); bottom.grid(row=2,column=0,sticky="ew",pady=10)
        self.button(bottom,"Approve selected change",lambda:self.approve_selected(tree)).pack(side="left")
        if not rows: tk.Label(top,text="No pending changes. Run a scan to check the folder.",bg=self.colors["bg"],fg=self.colors["muted"]).grid(row=3,column=0,pady=18)

    def approve_selected(self,tree):
        sel=tree.selection()
        if not sel:return messagebox.showinfo("Select a change","Choose a change to approve.")
        row=self.review_map[int(sel[0])]
        prompt=f"Approve this {row['kind'].lower()} change into the baseline?"
        if row["kind"]=="DELETED": prompt="Confirm removing this missing file from the baseline?\n\n"+(row["old_path"] or "")
        if messagebox.askyesno("Approve change",prompt): self.store.approve(int(sel[0])); self.show_page("Change Review"); self.refresh_dashboard()

    def approve_all(self):
        scans={r["scan_id"] for r in self.store.pending()}
        if not scans:return messagebox.showinfo("Nothing to approve","There are no pending changes.")
        choice=tk.Toplevel(self); choice.title("Approve scan changes"); choice.transient(self); choice.grab_set(); choice.configure(bg=self.colors["bg"])
        tk.Label(choice,text="Choose a scan's changes to approve together:",bg=self.colors["bg"],fg=self.colors["fg"]).pack(padx=20,pady=15)
        labels={}
        for sid in sorted(scans,reverse=True):
            hist=next((h for h in self.store.history() if h["id"]==sid),None)
            label=f"Scan {sid} — {hist['started'] if hist else ''}"
            labels[label]=sid
        var=tk.StringVar(value=next(iter(labels))); combo=ttk.Combobox(choice,textvariable=var,values=list(labels),state="readonly",width=45); combo.pack(padx=20,pady=5)
        def approve():
            sid=labels.get(var.get())
            if sid and messagebox.askyesno("Confirm approval","Approve every detected change from this scan? Deleted files will be removed from the baseline.",parent=choice):
                self.store.approve_scan(sid); choice.destroy(); self.show_page("Change Review"); self.refresh_dashboard()
        self.button(choice,"Approve scan",approve).pack(pady=15)

    def _history_page(self):
        b=self.page_body; b.rowconfigure(0,weight=1); b.columnconfigure(0,weight=1)
        frame=tk.Frame(b,bg=self.colors["bg"]); frame.grid(row=0,column=0,sticky="nsew"); frame.rowconfigure(0,weight=1); frame.columnconfigure(0,weight=1)
        cols=("started","status","scanned","new","modified","deleted","renamed","moved","errors")
        tree=ttk.Treeview(frame,columns=cols,show="headings"); labels={"started":"Started","status":"Status","scanned":"Files","new":"New","modified":"Modified","deleted":"Deleted","renamed":"Renamed","moved":"Moved","errors":"Errors"}
        for c in cols: tree.heading(c,text=labels[c]); tree.column(c,width=130 if c in ("started","status") else 72,anchor="w")
        tree.grid(row=0,column=0,sticky="nsew"); sb=ttk.Scrollbar(frame,command=tree.yview); sb.grid(row=0,column=1,sticky="ns"); tree.configure(yscrollcommand=sb.set)
        for r in self.store.history(): tree.insert("","end",iid=str(r["id"]),values=tuple(r[c] if r[c] is not None else "—" for c in cols))
        actions=tk.Frame(frame,bg=self.colors["bg"]); actions.grid(row=1,column=0,sticky="ew",pady=10)
        self.button(actions,"View changes for selected scan",lambda:self.view_scan(tree)).pack(side="left")
        self.button(actions,"Delete all history…",self.delete_history).pack(side="right")

    def view_scan(self,tree):
        sel=tree.selection()
        if not sel:return messagebox.showinfo("Select a scan","Choose a scan first.")
        rows=self.store.changes_for_scan(int(sel[0]))
        text="\n\n".join(f"{r['kind']}  {r['old_path'] or ''} → {r['path'] or ''}\nPrevious: {r['old_hash'] or '—'}\nCurrent: {r['hash'] or '—'}\nDetected: {r['detected']}  |  {'Approved' if r['approved'] else 'Pending'}" for r in rows) or "No changes were detected in this scan."
        win=tk.Toplevel(self); win.title("Scan changes"); win.geometry("800x500"); view=tk.Text(win,wrap="word",font=("Consolas",10)); view.pack(fill="both",expand=True,padx=12,pady=12); view.insert("1.0",text); view.configure(state="disabled")

    def delete_history(self):
        if messagebox.askyesno("Delete scan history?","This permanently deletes scan history and associated change records. The current baseline is kept."): self.store.clear_history(); self.show_page("Scan History"); self.refresh_dashboard()

    def _settings(self):
        b=self.page_body; b.columnconfigure(0,weight=1)
        panel=tk.Frame(b,bg=self.colors["panel"],highlightthickness=1,highlightbackground=self.colors["border"]); panel.grid(row=0,column=0,sticky="new"); panel.columnconfigure(1,weight=1)
        tk.Label(panel,text="Scanning",bg=self.colors["panel"],fg=self.colors["fg"],font=("Segoe UI",14,"bold")).grid(row=0,column=0,columnspan=2,sticky="w",padx=20,pady=(20,14))
        self.auto_var=tk.BooleanVar(value=self.store.get("auto")=="1")
        tk.Checkbutton(panel,text="Enable automatic scanning",variable=self.auto_var,command=lambda:self.store.set("auto","1" if self.auto_var.get() else "0"),bg=self.colors["panel"],fg=self.colors["fg"],selectcolor=self.colors["bg"],activebackground=self.colors["panel"]).grid(row=1,column=0,sticky="w",padx=20,pady=8)
        tk.Label(panel,text="Scan interval",bg=self.colors["panel"],fg=self.colors["fg"]).grid(row=2,column=0,sticky="w",padx=20,pady=8)
        self.interval_var=tk.StringVar(value=self.store.get("interval")); combo=ttk.Combobox(panel,textvariable=self.interval_var,values=list(INTERVALS),state="readonly",width=20); combo.grid(row=2,column=1,sticky="w",padx=10,pady=8); combo.bind("<<ComboboxSelected>>",lambda e:self.store.set("interval",self.interval_var.get()))
        tk.Label(panel,text="Appearance",bg=self.colors["panel"],fg=self.colors["fg"]).grid(row=3,column=0,sticky="w",padx=20,pady=8)
        self.theme_var=tk.StringVar(value=self.store.get("theme") or "Light"); theme=ttk.Combobox(panel,textvariable=self.theme_var,values=("Light","Dark"),state="readonly",width=20); theme.grid(row=3,column=1,sticky="w",padx=10,pady=8); theme.bind("<<ComboboxSelected>>",lambda e:self.apply_theme(self.theme_var.get()))
        note="FileGuard reads files to calculate SHA-256 hashes. It does not change monitored files.\nAutomatic scans detect changes but never approve or update the baseline."
        tk.Label(panel,text=note,bg=self.colors["panel"],fg=self.colors["muted"],justify="left").grid(row=4,column=0,columnspan=2,sticky="w",padx=20,pady=(15,22))
        tk.Label(b,text="Data is stored locally in your Windows user application data folder. History remains until you delete it.",bg=self.colors["bg"],fg=self.colors["muted"],wraplength=700,justify="left").grid(row=1,column=0,sticky="w",pady=20)

    def _auto_tick(self):
        if self.store.get("auto")=="1" and not self.scanning:
            interval=INTERVALS.get(self.store.get("interval"),30)*60
            last=self.store.history()
            if not last or last[0]["status"]!="Scanning" and last[0]["finished"] and time.time()-time.mktime(datetime.strptime(last[0]["finished"][:19],"%Y-%m-%d %H:%M:%S").timetuple())>=interval:
                folder=self.store.get("folder")
                if folder and Path(folder).is_dir() and self.store.has_baseline(): self._run_worker("scan",Path(folder))
        self.after(15000,self._auto_tick)

    def _close(self):
        if self.scanning:self.cancel.set()
        self.destroy()


if __name__ == "__main__":
    FileGuardApp().mainloop()
