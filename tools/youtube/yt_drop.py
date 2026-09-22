#!/usr/bin/env python3
"""
yt_drop.py - the drop-folder front end for youtube_upload_show.py (macOS)

Drop a zip of one night's clips into a watched folder; a launchd agent runs
`intake`, which unzips, scans, writes the default manifest, and leaves
double-clickable buttons next to the clips for the steps that need a human
in between. Every button is a thin wrapper around a stage that already
exists; nothing here talks to YouTube directly.

  ~/Bootlegs/inbox/                          the watched folder (zips go here)
  ~/Bootlegs/2026-09-19-lake-street-dive/    one folder per show, renamed from
      PXL_*.mp4 ...                          the show the scan resolved
      SCAN.txt                               the scan output to sanity-check
      README.txt                             the sequence, one paragraph
      1 - Upload.command
      2 - Edit setlist.command
      3 - Publish everything.command
      Open manifest.command
      Rescan with a date.command             only when the scan could not
                                             resolve the show

SUBCOMMANDS

  intake            what launchd runs: process every zip in the inbox
  rescan DIR        re-run the scan on a folder (with --show DATE), then buttons
  buttons DIR       (re)write the .command files and README for a folder
  upload DIR        lint -> --upload --dry-run -> confirm -> --upload
  edit DIR          --identify then --edit
  publish DIR       lint -> --apply --dry-run -> confirm -> --apply --publish
                    -> youtube_fetch.py -> youtube_create_playlists.py
                    --new-show -> print the playlist URL -> cleanup
  cleanup DIR       manifest triple to manifests/published/, clip folder to
                    the Trash (only after a publish, unless --force)
  install           write the LaunchAgent plist and load it
  uninstall         unload and remove it
  status            what is in flight

WHY .command FILES

  Finder runs a .command file in a Terminal window on double-click, so the
  stage's own output is visible and the window waits for a keypress before
  closing. That is the right shape for an operator who is comfortable with CLI
  output and lazy enough to want a button. Each file bakes in the absolute
  paths of the venv python, this script and its own folder, so it works from
  anywhere and never depends on the shell's cwd or PATH.

WHY THE FOLDER IDENTIFIES THE SHOW

  Every stage is called with --clips <this folder>. The scan records its
  folder in the manifest's .scan.json sidecar, and youtube_upload_show.py
  resolves the show from that, so two shows can be in flight at once and a
  published manifest left behind does not confuse the next one. Cleanup
  still moves published manifests out of the way, because the by-hand flow
  without --clips still counts them.

WHAT STAYS MANUAL

  Rotating sideways clips (before Upload), the Studio pass for monetization
  and Submit Rating (before Publish; no API), and pasting the playlist link
  into the playlist issue.
"""

import argparse
import glob
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
sys.path.insert(0, SCRIPT_DIR)
from yt_clipscan import VIDEO_EXTENSIONS  # noqa: E402
from yt_common import slugify  # noqa: E402

BOOTLEGS = os.path.expanduser("~/Bootlegs")
INBOX = os.path.join(BOOTLEGS, "inbox")
PROCESSED = os.path.join(INBOX, ".processed")
LOG = os.path.join(BOOTLEGS, "drop.log")
LOCK = os.path.join(INBOX, ".intake.lock")
MANIFEST_DIR = os.path.join(SCRIPT_DIR, "manifests")
PUBLISHED_DIR = os.path.join(MANIFEST_DIR, "published")
AGENT_LABEL = "net.redhat-bootlegs.bootleg-drop"
AGENT_PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{AGENT_LABEL}.plist")

UPLOAD = os.path.join(SCRIPT_DIR, "youtube_upload_show.py")
FETCH = os.path.join(SCRIPT_DIR, "youtube_fetch.py")
PLAYLISTS = os.path.join(SCRIPT_DIR, "youtube_create_playlists.py")
LINT = os.path.join(SCRIPT_DIR, "lint_manifest.py")

PARTIAL_SUFFIXES = (".crdownload", ".download", ".part", ".partial")
STABLE_SECONDS = 30       # a zip must hold its size this long before it is touched
STABLE_TIMEOUT = 15 * 60  # give up waiting for a still-growing download after this
EXIT_NO_SHOW, EXIT_AMBIGUOUS = 2, 3   # youtube_upload_show.py --scan

PLAYLIST_URL = re.compile(r"https://www\.youtube\.com/playlist\?list=[\w-]+")


# ---- small helpers -----------------------------------------------------------

def python():
    """The interpreter the buttons should use: the repo venv when it exists."""
    venv = os.path.join(REPO_ROOT, ".venv", "bin", "python3")
    return venv if os.path.exists(venv) else sys.executable


def log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{stamp}  {msg}"
    print(line)
    os.makedirs(BOOTLEGS, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def notify(title, text):
    """macOS notification; silently a no-op elsewhere."""
    if sys.platform != "darwin":
        return
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    subprocess.run(["osascript", "-e",
                    f'display notification "{esc(text)}" with title "{esc(title)}"'],
                   check=False, capture_output=True)


def run(cmd, cwd=SCRIPT_DIR, capture=False, env_extra=None):
    """Run a stage. Output always streams to the terminal as it happens; with
    capture=True it is also returned, so a wrapper can look for a phrase
    (invalid_grant, a playlist URL) after the fact without going silent
    during a long upload. PYTHONUNBUFFERED keeps the child from block-
    buffering its progress lines behind the pipe."""
    env = dict(os.environ, PYTHONUNBUFFERED="1", **(env_extra or {}))
    if not capture:
        p = subprocess.run(cmd, cwd=cwd, env=env)
        return p.returncode, ""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, bufsize=1,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines = []
    assert p.stdout is not None
    for line in p.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    p.wait()
    return p.returncode, "".join(lines)


def confirm(prompt):
    try:
        return input(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def sidecar_for(clip_dir):
    """(sidecar path, payload) for the manifest scanned from clip_dir, else (None, {})."""
    wanted = os.path.abspath(clip_dir)
    for path in sorted(glob.glob(os.path.join(MANIFEST_DIR, "*.scan.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            continue
        if os.path.abspath(data.get("clip_dir", "")) == wanted:
            return path, data
    return None, {}


def manifest_triple(sidecar):
    """The three files that make up one manifest, from its sidecar path."""
    base = sidecar[:-len(".scan.json")]
    return [base + ".tsv", base + ".machine.json", sidecar]


def video_files(folder):
    return [n for n in os.listdir(folder)
            if os.path.splitext(n)[1].lower() in VIDEO_EXTENSIONS and not n.startswith(".")]


# ---- buttons -------------------------------------------------------------------

README = """\
{title}

Scan output is in SCAN.txt. Check three things before pressing Upload:
  - the segment count matches the real breaks (support / headliner / encore)
  - the [skip] rows are really false starts
  - Set Artist is right for each segment (open the manifest to change it)
Rotate any sideways clips first - no script makes that call.

1 - Upload.command             uploads every "got" row, private. Re-press to resume.
2 - Edit setlist.command       seeds song IDs, then opens the setlist editor.
                               Do the Studio pass (monetization + Submit Rating)
                               before step 3.
3 - Publish everything.command titles, publishes, builds the playlist, prints its
                               URL, then archives the manifest and trashes this
                               folder. Paste the URL into the playlist issue.
Open manifest.command          the lean TSV, in your default editor.

Every button can be pressed again. Nothing here uploads twice.
"""

BUTTON = """\
#!/bin/bash
# Generated by yt_drop.py - safe to delete; `yt_drop.py buttons DIR` rewrites it.
printf '\\033]0;%s\\007' "{label}"
cd "{folder}" || exit 1
"{py}" "{driver}" {sub} "{folder}"{extra}
status=$?
echo
if [ $status -eq 0 ]; then echo "Done."; else echo "Exited with status $status."; fi
read -n 1 -s -r -p "Press any key to close this window."
echo
"""


def write_button(folder, name, sub, extra=""):
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(BUTTON.format(label=name[:-len(".command")], folder=folder,
                              py=python(), driver=os.path.abspath(__file__),
                              sub=sub, extra=extra))
    os.chmod(path, 0o755)
    return path


def cmd_buttons(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    for stale in glob.glob(os.path.join(folder, "*.command")):
        os.remove(stale)
    sidecar, meta = sidecar_for(folder)
    if not sidecar:
        write_button(folder, "Rescan with a date.command", "rescan", " --ask-date")
        print("No manifest is scanned from this folder yet - wrote the rescan button only.")
        return 0
    title = f"{meta.get('artist', '?')} - {meta.get('show_date', '?')} - {meta.get('venue', '')}".rstrip(" -")
    write_button(folder, "1 - Upload.command", "upload")
    write_button(folder, "2 - Edit setlist.command", "edit")
    write_button(folder, "3 - Publish everything.command", "publish")
    write_button(folder, "Open manifest.command", "open-manifest")
    with open(os.path.join(folder, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README.format(title=title))
    print(f"Buttons written in {folder}")
    return 0


# ---- intake --------------------------------------------------------------------

def wait_for_stable_zips():
    """Zips in the inbox whose size has held for STABLE_SECONDS; waits for
    still-growing downloads up to STABLE_TIMEOUT."""
    deadline = time.time() + STABLE_TIMEOUT
    last = {}
    while True:
        names = sorted(n for n in os.listdir(INBOX)
                       if n.lower().endswith(".zip") and not n.startswith("."))
        partial = [n for n in os.listdir(INBOX) if n.lower().endswith(PARTIAL_SUFFIXES)]
        sizes = {n: os.path.getsize(os.path.join(INBOX, n)) for n in names}
        if names and sizes == last and not partial:
            return names
        if not names and not partial:
            return []
        if time.time() > deadline:
            log(f"gave up waiting for downloads to settle: {partial or 'sizes still changing'}")
            return []
        last = sizes
        time.sleep(STABLE_SECONDS)


def extract_all(zips, batch):
    """Every video from every zip lands flat in batch/. Name collisions across
    zips get a numeric prefix rather than a silent overwrite."""
    os.makedirs(batch, exist_ok=True)
    count = 0
    for i, name in enumerate(zips, 1):
        with zipfile.ZipFile(os.path.join(INBOX, name)) as zf:
            for info in zf.infolist():
                if info.is_dir() or "__MACOSX" in info.filename:
                    continue
                base = os.path.basename(info.filename)
                if not base or base.startswith("."):
                    continue
                if os.path.splitext(base)[1].lower() not in VIDEO_EXTENSIONS:
                    continue
                target = os.path.join(batch, base)
                if os.path.exists(target):
                    target = os.path.join(batch, f"{i:02d}-{base}")
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                # keep the capture mtime the zip carried, in case the scan needs it
                ts = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (ts, ts))
                count += 1
    return count


def scan(folder, show=None):
    cmd = [python(), UPLOAD, "--scan", "--clips", folder]
    if show:
        cmd += ["--show", show]
    rc, out = run(cmd, capture=True)
    with open(os.path.join(folder, "SCAN.txt" if rc == 0 else "SCAN-FAILED.txt"),
              "w", encoding="utf-8") as f:
        f.write(out)
    return rc, out


def settle(folder):
    """After a successful scan: rename the folder from the resolved show, fix
    the sidecar to point at the new name, write the buttons."""
    sidecar, meta = sidecar_for(folder)
    if not sidecar:
        log(f"scan reported success but no sidecar records {folder}")
        return folder
    wanted = os.path.join(os.path.dirname(folder),
                          f"{meta['show_date']}-{slugify(meta['artist'])}")
    if os.path.abspath(folder) != os.path.abspath(wanted):
        if os.path.exists(wanted):
            wanted = wanted + "-" + datetime.now().strftime("%H%M")
        os.rename(folder, wanted)
        meta["clip_dir"] = os.path.abspath(wanted)
        with open(sidecar, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
            f.write("\n")
        folder = wanted
    failed = os.path.join(folder, "SCAN-FAILED.txt")
    if os.path.exists(failed):
        os.remove(failed)
    cmd_buttons(argparse.Namespace(dir=folder))
    return folder


def cmd_intake(args):
    os.makedirs(INBOX, exist_ok=True)
    os.makedirs(PROCESSED, exist_ok=True)
    if os.path.exists(LOCK):
        try:
            age = time.time() - os.path.getmtime(LOCK)
        except OSError:
            age = 0
        if age < STABLE_TIMEOUT + 60:
            log("intake already running - skipping")
            return 0
    with open(LOCK, "w") as f:
        f.write(str(os.getpid()))
    try:
        zips = wait_for_stable_zips()
        if not zips:
            return 0
        batch = os.path.join(BOOTLEGS, "incoming-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        log(f"extracting {len(zips)} zip(s): {', '.join(zips)}")
        n = extract_all(zips, batch)
        log(f"{n} clip(s) in {batch}")
        for name in zips:
            shutil.move(os.path.join(INBOX, name), os.path.join(PROCESSED, name))
        if n == 0:
            notify("Bootleg drop", "The zip(s) held no video files.")
            return 1
        rc, out = scan(batch)
        if rc == 0:
            folder = settle(batch)
            _, meta = sidecar_for(folder)
            notify("Bootleg drop: scanned",
                   f"{meta.get('artist', '?')} {meta.get('show_date', '')}: "
                   f"{meta.get('got', '?')} got, {meta.get('skip', 0)} skip, "
                   f"{meta.get('segments', '?')} segment(s). Check SCAN.txt.")
            log(f"ready: {folder}")
        else:
            cmd_buttons(argparse.Namespace(dir=batch))
            why = {EXIT_NO_SHOW: "no show matches the clip dates",
                   EXIT_AMBIGUOUS: "clips span two shows"}.get(rc, f"scan exited {rc}")
            notify("Bootleg drop: needs you", f"{why}. See SCAN-FAILED.txt in {os.path.basename(batch)}.")
            log(f"scan failed ({why}): {batch}")
        return 0
    finally:
        try:
            os.remove(LOCK)
        except OSError:
            pass


def cmd_rescan(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    show = args.show
    if not show and args.ask_date:
        try:
            show = input("Show date (YYYY-MM-DD), or blank to let the scan resolve it: ").strip()
        except EOFError:
            show = ""
    rc, out = scan(folder, show or None)
    print(out)
    if rc != 0:
        print(f"Scan failed (status {rc}). The output is in SCAN-FAILED.txt.")
        return rc
    settle(folder)
    return 0


# ---- the buttons' subcommands --------------------------------------------------

def _require_manifest(folder):
    sidecar, meta = sidecar_for(folder)
    if not sidecar:
        sys.exit(f"No manifest is scanned from {folder}. Press 'Rescan with a date' first.")
    return sidecar, meta


def _lint(sidecar):
    manifest = manifest_triple(sidecar)[0]
    print(f"== lint {os.path.basename(manifest)}")
    rc, _ = run([python(), LINT, "--manifest", manifest])
    if rc != 0:
        print("\nThe manifest has problems the linter can name. Fix them and press again.")
    return rc


def _token_hint(out):
    if "invalid_grant" in out:
        print("\nThe cached token is stale. From the repo root:\n"
              "  rm token.json\n"
              "then press the button again and pick the @dan2bit BRAND channel in the "
              "consent screen - not the gmail account, not redhat.bootlegs.")


def cmd_upload(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    sidecar, meta = _require_manifest(folder)
    print(f"{meta.get('artist')} - {meta.get('show_date')} - {meta.get('venue', '')}")
    print(f"manifest: {manifest_triple(sidecar)[0]}\n")
    if _lint(sidecar) != 0:
        return 1
    base = [python(), UPLOAD, "--upload", "--clips", folder]
    print("\n== dry run")
    rc, _ = run(base + ["--dry-run"])
    if rc != 0:
        return rc
    if not confirm("\nUpload these clips (private)?"):
        print("Not uploaded.")
        return 0
    rc, out = run(base, capture=True)
    _token_hint(out)
    if rc == 0:
        print("\nNext: give YouTube a while to finish its Content ID scan, then press "
              "'2 - Edit setlist'. Re-press this button to resume if anything stopped.")
    return rc


def cmd_edit(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    _require_manifest(folder)
    print("== identify (seeds song titles; never overwrites one you typed)")
    rc, _ = run([python(), UPLOAD, "--identify", "--clips", folder])
    if rc != 0:
        print("\nIdentify failed; opening the editor anyway so you can title by ear.")
    print("\n== edit (opens the browser; close this window when you are done saving)")
    rc, _ = run([python(), UPLOAD, "--edit", "--clips", folder])
    return rc


def cmd_open_manifest(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    sidecar, _ = _require_manifest(folder)
    manifest = manifest_triple(sidecar)[0]
    if sys.platform == "darwin":
        subprocess.run(["open", "-t", manifest], check=False)
    else:
        print(manifest)
    return 0


def cmd_publish(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    sidecar, meta = _require_manifest(folder)
    date = meta.get("show_date", "")
    print(f"{meta.get('artist')} - {date} - {meta.get('venue', '')}\n")
    if _lint(sidecar) != 0:
        return 1
    base = [python(), UPLOAD, "--apply", "--clips", folder]
    print("\n== apply, dry run")
    rc, _ = run(base + ["--dry-run"])
    if rc != 0:
        return rc
    print("\nHave you done the Studio pass (monetization + Submit Rating) for every clip?")
    if not confirm("Write titles, publish every clip, and build the playlist?"):
        print("Nothing published.")
        return 0
    print("\n== apply --publish")
    rc, out = run(base + ["--publish"], capture=True)
    _token_hint(out)
    if rc != 0:
        print("\nPublish refused or failed - nothing further was run. Fix and press again.")
        return rc
    print("\n== youtube_fetch.py")
    rc, _ = run([python(), FETCH])
    if rc != 0:
        print("\nFetch failed; the playlist step needs it. Press again to retry from here "
              "(apply is idempotent).")
        return rc
    print("\n== youtube_create_playlists.py --new-show")
    rc, out = run([python(), PLAYLISTS, "--new-show", date, "--update-history"], capture=True)
    if rc != 0:
        return rc
    urls = PLAYLIST_URL.findall(out)
    print("\n" + "=" * 72)
    if urls:
        print(f"PLAYLIST: {urls[-1]}")
        print("Paste that into the playlist issue body as `Playlist: <url>` and close it.")
    else:
        print("Playlist step finished but printed no playlist URL - check the output above.")
    print("=" * 72)
    return cmd_cleanup(argparse.Namespace(dir=folder, force=False, published=True))


def cmd_cleanup(args):
    folder = os.path.abspath(os.path.expanduser(args.dir))
    sidecar, meta = sidecar_for(folder)
    if sidecar:
        if not (getattr(args, "published", False) or args.force):
            print("Cleanup runs after 'Publish everything'. Pass --force to do it anyway.")
            return 1
        os.makedirs(PUBLISHED_DIR, exist_ok=True)
        for path in manifest_triple(sidecar):
            if os.path.exists(path):
                shutil.move(path, os.path.join(PUBLISHED_DIR, os.path.basename(path)))
        print(f"manifest archived to {PUBLISHED_DIR}")
    trash(folder)
    log(f"cleaned up: {folder}")
    return 0


def trash(path):
    """Finder's Trash on macOS (recoverable); a .trash folder elsewhere."""
    if sys.platform == "darwin":
        r = subprocess.run(["osascript", "-e",
                            f'tell application "Finder" to delete POSIX file "{path}"'],
                           capture_output=True, text=True)
        if r.returncode == 0:
            print(f"moved to the Trash: {path}")
            return
        print(f"Finder could not trash it ({r.stderr.strip()}); leaving it in place.")
        return
    dest = os.path.join(BOOTLEGS, ".trash", os.path.basename(path))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(path, dest)
    print(f"moved to {dest}")


# ---- launchd -------------------------------------------------------------------

def cmd_install(args):
    inbox = os.path.abspath(os.path.expanduser(args.inbox or INBOX))
    os.makedirs(os.path.join(inbox, ".processed"), exist_ok=True)
    plist = {
        "Label": AGENT_LABEL,
        "ProgramArguments": [python(), os.path.abspath(__file__), "intake"],
        "WatchPaths": [inbox],
        "RunAtLoad": False,
        "ThrottleInterval": 30,
        "StandardOutPath": LOG,
        "StandardErrorPath": LOG,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
    }
    os.makedirs(os.path.dirname(AGENT_PLIST), exist_ok=True)
    with open(AGENT_PLIST, "wb") as f:
        plistlib.dump(plist, f)
    print(f"wrote {AGENT_PLIST}")
    if sys.platform != "darwin":
        print("(not macOS - not loading it)")
        return 0
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}", AGENT_PLIST],
                   capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", AGENT_PLIST],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"launchctl bootstrap failed: {r.stderr.strip()}")
        return 1
    print(f"loaded. Watching {inbox}; log at {LOG}")
    print("ffprobe on PATH? " + ("yes" if shutil.which("ffprobe") else
                                 "NO - brew install ffmpeg, or durations fall back to a size proxy"))
    return 0


def cmd_uninstall(args):
    if sys.platform == "darwin" and os.path.exists(AGENT_PLIST):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", AGENT_PLIST],
                       capture_output=True)
    if os.path.exists(AGENT_PLIST):
        os.remove(AGENT_PLIST)
        print(f"removed {AGENT_PLIST}")
    return 0


def cmd_status(args):
    print(f"inbox: {INBOX}")
    if os.path.isdir(INBOX):
        zips = [n for n in os.listdir(INBOX) if n.lower().endswith(".zip")]
        print(f"  {len(zips)} zip(s) waiting")
    print(f"agent: {'installed' if os.path.exists(AGENT_PLIST) else 'not installed'}")
    print("in flight:")
    found = False
    for sidecar in sorted(glob.glob(os.path.join(MANIFEST_DIR, "*.scan.json"))):
        try:
            with open(sidecar, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        found = True
        folder = meta.get("clip_dir", "?")
        here = "" if os.path.isdir(folder) else "  (folder missing)"
        print(f"  {meta.get('show_date', '?')}  {meta.get('artist', '?'):<32} {folder}{here}")
    if not found:
        print("  nothing")
    return 0


# ---- main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("intake")
    p = sub.add_parser("rescan"); p.add_argument("dir"); p.add_argument("--show"); p.add_argument("--ask-date", action="store_true")
    for name in ("buttons", "upload", "edit", "publish", "open-manifest"):
        sub.add_parser(name).add_argument("dir")
    p = sub.add_parser("cleanup"); p.add_argument("dir"); p.add_argument("--force", action="store_true")
    sub.add_parser("install").add_argument("--inbox")
    sub.add_parser("uninstall")
    sub.add_parser("status")
    args = ap.parse_args()
    handler = {
        "intake": cmd_intake, "rescan": cmd_rescan, "buttons": cmd_buttons,
        "upload": cmd_upload, "edit": cmd_edit, "publish": cmd_publish,
        "open-manifest": cmd_open_manifest, "cleanup": cmd_cleanup,
        "install": cmd_install, "uninstall": cmd_uninstall, "status": cmd_status,
    }[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
