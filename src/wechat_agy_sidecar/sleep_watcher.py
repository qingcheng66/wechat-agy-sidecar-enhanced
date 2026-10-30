"""
Cross-Platform Sleep & Lid-Close Watcher.

Detects when the operating system is going to sleep (or lid closed / suspended):
1. Windows: Win32 hidden window message pump listening for WM_POWERBROADCAST (PBT_APMSUSPEND).
2. macOS: PyObjC NSWorkspace.sharedWorkspace().notificationCenter() listening for NSWorkspaceWillSleepNotification (if pyobjc is available).
3. Universal Heartbeat: Wall-clock time jump monitor. If system suspended and resumes (e.g. DarkWake or wake), it immediately senses the time gap and triggers shutdown.

When sleep is detected, invokes the on_sleep callback, allowing the sidecar to terminate
the agy subprocess and exit cleanly with code 0.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger("wechat_agy_sidecar.sleep_watcher")

# Global reference holder to prevent ctypes function pointers from being GC-ed
_GLOBAL_CTYPES_REFS = []


class SleepWatcher:
    """Monitors system sleep / lid-close events across macOS, Windows, and Linux."""

    def __init__(self, on_sleep_callback: Callable[[str], None]):
        self.on_sleep_callback = on_sleep_callback
        self.system = platform.system()
        self._running = False
        self._triggered = False
        self._lock = threading.Lock()

        self._windows_thread: Optional[threading.Thread] = None
        self._windows_hwnd = None
        self._wnd_proc_cb = None

        self._heartbeat_thread: Optional[threading.Thread] = None
        self._mac_observer_thread: Optional[threading.Thread] = None

    def _trigger_sleep(self, reason: str):
        with self._lock:
            if self._triggered:
                return
            self._triggered = True
        logger.warning("System sleep/lid-close detected (%s)! Triggering callback...", reason)
        try:
            self.on_sleep_callback(reason)
        except Exception as e:
            logger.error("Error in on_sleep_callback: %s", e, exc_info=True)

    def start(self):
        """Start all available platform and fallback sleep monitors."""
        if self._running:
            return
        self._running = True

        # 1. Start universal heartbeat watchdog (works on all platforms as backup/DarkWake detector)
        self._start_heartbeat()

        # 2. Platform-specific pre-sleep monitors
        if self.system == "Windows":
            self._start_windows_monitor()
        elif self.system == "Darwin":
            self._start_macos_monitor()

        logger.info("SleepWatcher started for platform: %s", self.system)

    def stop(self):
        """Stop all monitoring threads cleanly."""
        self._running = False
        if self.system == "Windows" and self._windows_hwnd:
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.PostMessageW.restype = wintypes.BOOL
                user32.PostMessageW(self._windows_hwnd, 0x0010, 0, 0)  # WM_CLOSE
            except Exception as e:
                logger.debug("Error posting WM_CLOSE: %s", e)

        if self._windows_thread and self._windows_thread.is_alive():
            self._windows_thread.join(timeout=1.0)

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=1.0)

        if self._mac_observer_thread and self._mac_observer_thread.is_alive():
            self._mac_observer_thread.join(timeout=1.0)

    # -------------------------------------------------------------------------
    # 1. Universal Heartbeat Watchdog
    # -------------------------------------------------------------------------
    def _start_heartbeat(self):
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="SleepHeartbeatWatchdog",
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        """Detects if system was suspended by checking wall-clock time jumps."""
        check_interval = 1.0
        threshold = 3.5  # If 1s sleep actually took >3.5s, system was suspended
        last_wall_time = time.time()

        while self._running:
            time.sleep(check_interval)
            if not self._running:
                break
            now = time.time()
            elapsed = now - last_wall_time
            if elapsed > threshold:
                logger.warning(
                    "Wall-clock jump detected: elapsed=%.2fs (expected ~%.2fs). System was asleep!",
                    elapsed, check_interval,
                )
                self._trigger_sleep(f"heartbeat_jump_{elapsed:.1f}s")
                break
            last_wall_time = now

    # -------------------------------------------------------------------------
    # 2. Windows Native WM_POWERBROADCAST Monitor
    # -------------------------------------------------------------------------
    def _start_windows_monitor(self):
        self._windows_thread = threading.Thread(
            target=self._windows_loop,
            daemon=True,
            name="WindowsPowerWatchdog",
        )
        self._windows_thread.start()

    def _windows_loop(self):
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            LRESULT = ctypes.c_ssize_t
            WNDPROCTYPE = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

            user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.DefWindowProcW.restype = LRESULT

            class WNDCLASSEXW(ctypes.Structure):
                _fields_ = [
                    ('cbSize', wintypes.UINT),
                    ('style', wintypes.UINT),
                    ('lpfnWndProc', WNDPROCTYPE),
                    ('cbClsExtra', ctypes.c_int),
                    ('cbWndExtra', ctypes.c_int),
                    ('hInstance', wintypes.HINSTANCE),
                    ('hIcon', wintypes.HICON),
                    ('hCursor', wintypes.HICON),
                    ('hbrBackground', wintypes.HBRUSH),
                    ('lpszMenuName', wintypes.LPCWSTR),
                    ('lpszClassName', wintypes.LPCWSTR),
                    ('hIconSm', wintypes.HICON)
                ]

            user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
            user32.RegisterClassExW.restype = wintypes.ATOM

            user32.CreateWindowExW.restype = wintypes.HWND
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
            ]

            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.GetMessageW.restype = wintypes.BOOL

            user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
            user32.DispatchMessageW.restype = LRESULT

            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL

            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL

            user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
            user32.UnregisterClassW.restype = wintypes.BOOL

            WM_CLOSE = 0x0010
            WM_DESTROY = 0x0002
            WM_POWERBROADCAST = 0x0218
            PBT_APMSUSPEND = 0x0004
            PBT_APMSTANDBY = 0x0005

            watcher = self

            def wnd_proc(hwnd, msg, wparam, lparam):
                if msg == WM_POWERBROADCAST:
                    if wparam in (PBT_APMSUSPEND, PBT_APMSTANDBY):
                        logger.warning("Windows WM_POWERBROADCAST suspend event (0x%x)", wparam)
                        watcher._trigger_sleep("windows_power_suspend")
                        return 1
                elif msg == WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                elif msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            # Prevent garbage collection of callback permanently
            self._wnd_proc_cb = WNDPROCTYPE(wnd_proc)
            _GLOBAL_CTYPES_REFS.append(self._wnd_proc_cb)

            hinst = kernel32.GetModuleHandleW(None)
            class_name = f"WeChatSidecarSleepWatcher_{id(self)}_{int(time.time() * 1000)}"

            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wnd_proc_cb
            wc.hInstance = hinst
            wc.lpszClassName = class_name

            atom = user32.RegisterClassExW(ctypes.byref(wc))
            if not atom:
                logger.warning("Failed to register Windows window class for power monitoring.")
                return

            self._windows_hwnd = user32.CreateWindowExW(
                0, class_name, "WeChatSidecarPowerMsgWindow",
                0, 0, 0, 0, 0, None, None, hinst, None
            )

            if not self._windows_hwnd:
                logger.warning("Failed to create Windows hidden message window.")
                return

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            user32.UnregisterClassW(class_name, hinst)

        except Exception as e:
            logger.warning("Windows native power monitoring error: %s", e)

    # -------------------------------------------------------------------------
    # 3. macOS Native NSWorkspaceWillSleepNotification Monitor
    # -------------------------------------------------------------------------
    def _start_macos_monitor(self):
        self._mac_observer_thread = threading.Thread(
            target=self._macos_loop,
            daemon=True,
            name="MacosSleepWatchdog",
        )
        self._mac_observer_thread.start()

    def _macos_loop(self):
        try:
            from AppKit import NSWorkspace, NSWorkspaceWillSleepNotification
            from Foundation import NSObject, NSRunLoop, NSDate

            watcher = self

            class SleepObserver(NSObject):
                def receiveSleepNote_(self, notification):
                    logger.warning("macOS NSWorkspaceWillSleepNotification received")
                    watcher._trigger_sleep("macos_workspace_will_sleep")

            observer = SleepObserver.alloc().init()
            center = NSWorkspace.sharedWorkspace().notificationCenter()
            center.addObserver_selector_name_object_(
                observer,
                "receiveSleepNote:",
                NSWorkspaceWillSleepNotification,
                None,
            )

            run_loop = NSRunLoop.currentRunLoop()
            while self._running:
                # Pump run loop for 1 second intervals
                run_loop.runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(1.0))

            center.removeObserver_(observer)
        except ImportError:
            logger.info("PyObjC not installed. Using heartbeat watchdog for macOS sleep detection.")
        except Exception as e:
            logger.warning("macOS native power monitoring error: %s", e)
