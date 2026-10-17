"""Send ESC/POS bytes to an installed Windows queue without rendering a GDI page."""
import ctypes
from ctypes import wintypes
import os


class DOC_INFO_1(ctypes.Structure):
    _fields_ = [("pDocName", wintypes.LPWSTR), ("pOutputFile", wintypes.LPWSTR),
                ("pDatatype", wintypes.LPWSTR)]


class WindowsSpooler:
    def __init__(self):
        if os.name != "nt":
            raise OSError("O transporte windows_raw exige Windows.")
        self.dll = ctypes.WinDLL("winspool.drv", use_last_error=True)
        signatures = {
            "OpenPrinterW": ([wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID], wintypes.BOOL),
            "StartDocPrinterW": ([wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)], wintypes.DWORD),
            "StartPagePrinter": ([wintypes.HANDLE], wintypes.BOOL),
            "WritePrinter": ([wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            "EndPagePrinter": ([wintypes.HANDLE], wintypes.BOOL),
            "EndDocPrinter": ([wintypes.HANDLE], wintypes.BOOL),
            "AbortPrinter": ([wintypes.HANDLE], wintypes.BOOL),
            "ClosePrinter": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.dll, name)
            function.argtypes, function.restype = args, result

    def checked(self, name, *args):
        result = getattr(self.dll, name)(*args)
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def open(self, name):
        handle = wintypes.HANDLE()
        self.checked("OpenPrinterW", name, ctypes.byref(handle), None)
        return handle

    def start(self, handle):
        info = DOC_INFO_1("Prebeta 4 - ticket ESC/POS", None, "RAW")
        return self.checked("StartDocPrinterW", handle, 1, ctypes.byref(info))

    def write(self, handle, data):
        buffer = ctypes.create_string_buffer(data)
        written = wintypes.DWORD()
        self.checked("WritePrinter", handle, buffer, len(data), ctypes.byref(written))
        return written.value


def send_windows_raw(config, data, *, spooler=None):
    spooler = spooler or WindowsSpooler()
    handle = spooler.open(config.printer_name)
    started = False
    try:
        job_id = spooler.start(handle)
        started = True
        spooler.checked("StartPagePrinter", handle)
        offset = 0
        while offset < len(data):
            written = spooler.write(handle, data[offset:offset + 65536])
            if not 0 < written <= min(65536, len(data) - offset):
                raise OSError("A fila Windows não confirmou a gravação dos bytes.")
            offset += written
        spooler.checked("EndPagePrinter", handle)
        spooler.checked("EndDocPrinter", handle)
        started = False
        return job_id  # Acceptance by the spooler is not proof of physical output.
    except Exception:
        if started:
            try:
                spooler.checked("AbortPrinter", handle)
            except OSError:
                pass
        raise
    finally:
        spooler.checked("ClosePrinter", handle)
