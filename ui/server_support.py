from __future__ import annotations

import ipaddress
import os
import subprocess


def background_process_kwargs() -> dict:
    """Launch long-running UI child processes without opening a console window."""
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if flags:
            kwargs["creationflags"] = flags
        try:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startup.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startup
        except AttributeError:
            pass
    else:
        kwargs["start_new_session"] = True
    return kwargs


def is_loopback_host(host: str) -> bool:
    value = str(host or "").strip().lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


__all__ = ["background_process_kwargs", "is_loopback_host"]
