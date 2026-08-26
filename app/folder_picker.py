"""Open Windows' own Browse-for-Folder dialog from the server (spec §2.5).

WHY the server and not the page: a browser never reveals a folder's real
address to a web page. The server runs on the analyst's own PC under their
login, so it can show the dialog and hand the address back — the one thing
that turns "type \\\\server\\share\\..." into a click.
"""
from __future__ import annotations

import os
import subprocess
import threading

_lock = threading.Lock()

# -STA: WinForms dialogs need a single-threaded apartment. The owner form is
# TopMost so the dialog is not lost behind the browser window (a dialog with no
# owner opens behind the foreground app).
_SCRIPT = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true; $owner.ShowInTaskbar = $false; $owner.Opacity = 0
$owner.Size = New-Object System.Drawing.Size 1,1
$owner.StartPosition = 'Manual'; $owner.Location = New-Object System.Drawing.Point -32000,-32000
$owner.Show(); $owner.Activate()
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = 'Choose the JLBC Search budget folder'
$d.ShowNewFolderButton = $false
$d.RootFolder = 'MyComputer'
if ($d.ShowDialog($owner) -eq 'OK') { [Console]::Out.Write($d.SelectedPath) }
$owner.Close()
"""


class PickerBusy(RuntimeError):
    """A dialog is already open; the analyst must answer it first."""


def supported() -> bool:
    return os.name == "nt"


def pick_folder(timeout_s: float = 300) -> str | None:
    """The chosen folder's address, or None if cancelled / unsupported."""
    if not supported():
        return None
    if not _lock.acquire(blocking=False):
        raise PickerBusy()
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-STA",
             "-Command", _SCRIPT],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout_s, creationflags=flags,
        )
        chosen = (proc.stdout or "").strip()
        return chosen or None
    finally:
        _lock.release()
