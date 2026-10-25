"""Windows CMD launcher; restart only this checkout's virtualenv web process."""
import argparse
import ctypes
import json
import ntpath
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def split_windows_command_line(command):
    """Use Windows' argument parser so project paths containing spaces are safe."""
    from ctypes import wintypes
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    parse = shell.CommandLineToArgvW
    parse.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    parse.restype = ctypes.POINTER(wintypes.LPWSTR)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    args = parse(command, ctypes.byref(count))
    if not args:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [args[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(ctypes.cast(args, ctypes.c_void_p))


def project_process_ids(processes, root, parse=split_windows_command_line):
    normalize = lambda path: ntpath.normcase(ntpath.normpath(str(path)))
    python = normalize(ntpath.join(str(root), '.venv', 'Scripts', 'python.exe'))
    script = normalize(ntpath.join(str(root), 'web_ui.py'))
    found = []
    for process in processes:
        if normalize(process.get('ExecutablePath') or '') != python:
            continue
        command = process.get('CommandLine')
        if not command:
            continue
        argv = parse(command)
        # Only an exact absolute script argument is accepted, never a substring.
        if len(argv) > 1 and normalize(argv[0]) == python:
            args = argv[1:]
            while args and args[0] in ('-u', '-B', '-E', '-s', '-S', '-I'):
                args = args[1:]
            if args and normalize(args[0]) == script:
                found.append(int(process['ProcessId']))
    return found


def running_processes():
    command = ("$ErrorActionPreference='Stop'; [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding; "
               "@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\") | "
               'Select-Object ProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress')
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            check=True, stdout=subprocess.PIPE, encoding='utf-8', errors='strict')
    data = json.loads(result.stdout.lstrip('\ufeff').strip() or '[]')
    return data if isinstance(data, list) else [data]


def main(argv=None):
    parser = argparse.ArgumentParser(description='Start/restart iCloud HME on Windows')
    parser.add_argument('action', choices=['start', 'restart'])
    args, extra = parser.parse_known_args(argv)
    if os.name != 'nt':
        parser.error('Use start.sh on macOS/Linux; this launcher is for Windows.')
    python = ROOT / '.venv' / 'Scripts' / 'python.exe'
    if not python.is_file():
        print('Missing .venv. Run: py -3 -m venv .venv', file=sys.stderr)
        return 1
    try:
        pids = project_process_ids(running_processes(), ROOT)
        if pids and args.action == 'start':
            print('This project is already running. Use restart.cmd to restart it.')
            return 0
        for pid in pids:
            # Do not kill by image name or port: other Python projects must stay running.
            subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'], check=True)
        command = [str(python), '-u', str(ROOT / 'web_ui.py'), '--host', '127.0.0.1',
                   '--port', '2224', '--no-sync', *extra]
        print('Starting iCloud HME: http://127.0.0.1:2224', flush=True)
        return subprocess.call(command, cwd=ROOT)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Cannot start/restart service: '+str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
