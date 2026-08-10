"""Build ~/Applications/Composter.app — a launcher the TCC picker will accept.

Why this exists (plan §13, risk 5). Two problems, one fix:

1. macOS's Full Disk Access picker will not let you select a loose Unix
   executable like `/Library/Frameworks/.../bin/python3.13`. It wants a bundle.
2. Even if you could, TCC identity follows the binary, so a Python patch
   upgrade can silently invalidate the grant and voice/iOS capture stops
   quietly. A bundle you own is a stable identity that survives upgrades.

The launcher **spawns** Python as a child rather than `exec`ing it. That matters:
`exec` replaces the process image, so TCC would evaluate Python's identity and
the whole point would be lost. As a child, the bundle stays the responsible
process and the grant applies.

    .venv/bin/python scripts/build_app.py
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
APP = Path.home() / "Applications" / "Composter.app"
BUNDLE_ID = "com.adamkuzee.composter"

SWIFT = r'''
import Foundation

// Paths are baked in at build time: this is a personal launcher, not a
// relocatable product. Rebuild with scripts/build_app.py if they change.
let project = "__PROJECT__"
let python  = "__PYTHON__"

let passed = Array(CommandLine.arguments.dropFirst())

// `selftest` answers one question no other check can: does THIS bundle hold
// Full Disk Access? It reads the Voice Memos container from the bundle's own
// process, before any child is spawned. If this succeeds but the Python child
// fails, the grant is real and the problem is TCC attribution of the child.
if passed.first == "selftest" {
    let home = NSHomeDirectory()
    let probes = [
        "/Library/Group Containers/group.com.apple.VoiceMemos.shared",
        "/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings",
        "/Library/Application Support/com.apple.TCC",
        "/Library/Containers/com.apple.VoiceMemos/Data",
    ]
    for p in probes {
        let full = home + p
        do {
            let items = try FileManager.default.contentsOfDirectory(atPath: full)
            let shown = items.prefix(12).joined(separator: ", ")
            print("OK   \(p)\n     \(items.count) entries: \(shown)")
        } catch {
            print("FAIL \(p)\n     \(error.localizedDescription)")
        }
    }
    exit(0)
}

var args = ["-m", "src.main"]
args.append(contentsOf: passed.isEmpty ? ["all"] : passed)

let task = Process()
task.executableURL = URL(fileURLWithPath: python)
task.arguments = args
task.currentDirectoryURL = URL(fileURLWithPath: project)
var env = ProcessInfo.processInfo.environment
env["PYTHONPATH"] = project
env["PYTHONUNBUFFERED"] = "1"
task.environment = env

do {
    // Spawned as a child, NOT exec'd: the bundle must remain the process TCC
    // holds responsible, or the Full Disk Access grant does not apply.
    try task.run()
    task.waitUntilExit()
    exit(task.terminationStatus)
} catch {
    FileHandle.standardError.write("composter launcher failed: \(error)\n"
                                   .data(using: .utf8)!)
    exit(70)
}
'''


def interpreter() -> Path:
    """The venv interpreter, deliberately NOT resolved to the base binary.

    Resolving would drop the venv's site-packages. It is safe here precisely
    because the bundle is what TCC holds responsible — the identity of the
    child process no longer matters, which is the whole reason for the bundle.
    """
    venv = PROJECT / ".venv" / "bin" / "python3"
    return venv if venv.exists() else Path(sys.executable)


def main() -> int:
    if not shutil.which("swiftc"):
        print("swiftc not found — install Xcode command line tools", file=sys.stderr)
        return 1

    macos = APP / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    src = APP / "Contents" / "launcher.swift"
    src.write_text(SWIFT.replace("__PROJECT__", str(PROJECT))
                        .replace("__PYTHON__", str(interpreter())), encoding="utf-8")

    exe = macos / "Composter"
    proc = subprocess.run(["swiftc", "-O", "-o", str(exe), str(src)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"swiftc failed:\n{proc.stderr}", file=sys.stderr)
        return 1
    src.unlink()

    with open(APP / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({
            "CFBundleIdentifier": BUNDLE_ID,
            "CFBundleName": "Composter",
            "CFBundleExecutable": "Composter",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "LSBackgroundOnly": True,      # never shows a Dock icon or window
            "LSMinimumSystemVersion": "13.0",
        }, f)

    # An ad-hoc signature gives the bundle a stable code identity, which is what
    # TCC records the grant against. Without it the grant can be lost on rebuild.
    sign = subprocess.run(["codesign", "--force", "--deep", "-s", "-", str(APP)],
                          capture_output=True, text=True)
    if sign.returncode != 0:
        print(f"codesign failed:\n{sign.stderr}", file=sys.stderr)
        return 1

    print(f"built {APP}")
    print(f"  runs: {interpreter()} -m src.main <verb>   (default: all)")
    print(f"  cwd:  {PROJECT}")
    print()
    print("!! REBUILDING INVALIDATES ANY EXISTING FULL DISK ACCESS GRANT.")
    print("   The ad-hoc signature changes with the binary, and macOS ties the")
    print("   grant to the signature. After every rebuild you must REMOVE the")
    print("   old Composter.app entry in System Settings -> Privacy & Security")
    print("   -> Full Disk Access (select it, press -) and add it again.")
    print("   Verify with:  ~/Applications/Composter.app/Contents/MacOS/Composter selftest")
    print()
    print("Grant: System Settings -> Privacy & Security -> Full Disk Access -> +")
    print(f"       then select {APP}")
    print("       (⌘⇧G and paste ~/Applications if it is not visible)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
