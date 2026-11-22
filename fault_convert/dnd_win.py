"""Drag-and-drop of files from Explorer onto Tk widgets, Windows only, no extra packages.

Each target widget's HWND gets DragAcceptFiles and a comctl32 window subclass that turns
WM_DROPFILES into a Python callback (scheduled on the Tk event loop). On other systems
`enable_drop` does nothing and returns False.
"""
import os

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    WM_DROPFILES = 0x0233
    _shell32 = ctypes.windll.shell32
    _comctl32 = ctypes.windll.comctl32
    _user32 = ctypes.windll.user32
    LRESULT = ctypes.c_ssize_t
    SUBCLASSPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                      wintypes.LPARAM, ctypes.c_size_t, ctypes.c_size_t)
    _comctl32.SetWindowSubclass.argtypes = [wintypes.HWND, SUBCLASSPROC, ctypes.c_size_t, ctypes.c_size_t]
    _comctl32.DefSubclassProc.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _comctl32.DefSubclassProc.restype = LRESULT
    _shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    _shell32.DragFinish.argtypes = [wintypes.HANDLE]
    _shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
    _user32.ChangeWindowMessageFilterEx.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.DWORD, ctypes.c_void_p]

_keep = []  # ctypes callbacks must stay alive as long as the window


def enable_drop(widget, callback):
    """callback(list_of_paths) is called on the Tk thread when files are dropped on `widget`."""
    if os.name != "nt":
        return False
    widget.update_idletasks()
    hwnd = widget.winfo_id()

    def proc(h, msg, wparam, lparam, uid, data):
        if msg == WM_DROPFILES:
            n = _shell32.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
            paths = []
            for i in range(n):
                size = _shell32.DragQueryFileW(wparam, i, None, 0) + 1
                buf = ctypes.create_unicode_buffer(size)
                _shell32.DragQueryFileW(wparam, i, buf, size)
                paths.append(buf.value)
            _shell32.DragFinish(wparam)
            widget.after(0, lambda: callback(paths))
            return 0
        return _comctl32.DefSubclassProc(h, msg, wparam, lparam)

    cb = SUBCLASSPROC(proc)
    _keep.append(cb)
    _comctl32.SetWindowSubclass(hwnd, cb, len(_keep), 0)
    _shell32.DragAcceptFiles(hwnd, True)
    try:  # let drops through even when the app runs with higher integrity than Explorer
        for m in (WM_DROPFILES, 0x0049, 0x004A):  # WM_DROPFILES, WM_COPYGLOBALDATA, WM_COPYDATA
            _user32.ChangeWindowMessageFilterEx(hwnd, m, 1, None)
    except Exception:  # noqa: BLE001 - older Windows
        pass
    return True
