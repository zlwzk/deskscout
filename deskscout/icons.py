"""应用图标：通过 Shell 缩略图接口取真实图标，失败时退回文件图标/首字母色块.

要点：
- IShellItemImageFactory.GetImage 对 exe、.lnk、以及 Store 应用的
  ``shell:AppsFolder\\<AUMID>`` 都有效，能拿到应用自己的图标而不是通用文件图标。
- 取到的图像会缓存成 PNG / ICO，创建快捷方式时用 ICO，避免桌面出现白纸图标。
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import sys
from ctypes import wintypes

try:
    from PIL import Image, ImageDraw, ImageFont
    import PIL.ImageTk as ImageTk

    _PIL_OK = True
except ImportError:  # pragma: no cover
    _PIL_OK = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

shell32.ExtractIconExW.argtypes = [
    ctypes.c_wchar_p,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.POINTER(ctypes.c_void_p),
    ctypes.c_uint,
]
shell32.ExtractIconExW.restype = ctypes.c_uint
user32.DestroyIcon.argtypes = [ctypes.c_void_p]
user32.DestroyIcon.restype = wintypes.BOOL

user32.GetDC.argtypes = [ctypes.c_void_p]
user32.GetDC.restype = ctypes.c_void_p
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.DrawIconEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
user32.DrawIconEx.restype = wintypes.BOOL

gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.CreateSolidBrush.argtypes = [ctypes.c_uint32]
gdi32.CreateSolidBrush.restype = ctypes.c_void_p
gdi32.GdiFlush.argtypes = []
gdi32.GdiFlush.restype = wintypes.BOOL


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, text: str) -> "GUID":
        parts = text.strip("{}").split("-")
        data4 = bytes.fromhex(parts[3] + parts[4])
        return cls(
            int(parts[0], 16), int(parts[1], 16), int(parts[2], 16),
            (ctypes.c_ubyte * 8)(*data4),
        )


gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint,
]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
gdi32.GetObjectW.restype = ctypes.c_int
gdi32.GetDIBits.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), ctypes.c_uint,
]
gdi32.GetDIBits.restype = ctypes.c_int
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL

shell32.SHCreateItemFromParsingName.argtypes = [
    ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
]
shell32.SHCreateItemFromParsingName.restype = ctypes.c_long

user32.FillRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p]
user32.FillRect.restype = ctypes.c_int

_cache: dict[tuple[str, int], object] = {}
_image_cache: dict[tuple[str, int], object] = {}
_pil_cache: dict[tuple[str, int], object] = {}
_DIB_WHITE = 0x00FFFFFF
_DIB_BLACK = 0x00000000
_DI_NORMAL = 0x0003
_IID_SHELLITEM_IMAGE_FACTORY = GUID.from_string("BCC18B79-BA16-442F-80C4-8A59C30C463B")
_SIIGBF_ICONONLY = 0x00000004
_SIIGBF_BIGGERSIZEOK = 0x00000001


def resource_path(*parts: str) -> str:
    base = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base, *parts)


def icon_cache_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "DeskScout", "icons")
    os.makedirs(path, exist_ok=True)
    return path


def _ensure_com() -> None:
    try:
        ole32.CoInitializeEx(None, 0x00000002)  # COINIT_APARTMENTTHREADED
    except OSError:
        pass


# --------------------------------------------------------------------------
# 基础转换
# --------------------------------------------------------------------------


def _draw_on_background(memdc, hbmp, bits_ptr, hicon, size, color) -> bytes:
    brush = gdi32.CreateSolidBrush(color)
    rect = RECT(0, 0, size, size)
    user32.FillRect(memdc, ctypes.byref(rect), brush)
    gdi32.DeleteObject(brush)
    user32.DrawIconEx(memdc, 0, 0, hicon, size, size, 0, None, _DI_NORMAL)
    gdi32.GdiFlush()
    buffer = (ctypes.c_ubyte * (size * size * 4)).from_address(bits_ptr)
    return bytes(buffer)


def _hicon_to_image(hicon, size: int):
    hdc = user32.GetDC(None)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    hbmp = gdi32.CreateDIBSection(memdc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    old = gdi32.SelectObject(memdc, hbmp)
    try:
        white = _draw_on_background(memdc, hbmp, bits.value, hicon, size, _DIB_WHITE)
        black = _draw_on_background(memdc, hbmp, bits.value, hicon, size, _DIB_BLACK)
    finally:
        gdi32.SelectObject(memdc, old)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(memdc)
        user32.ReleaseDC(None, hdc)

    pixels = []
    for index in range(0, size * size * 4, 4):
        b, g, r = black[index], black[index + 1], black[index + 2]
        bw, gw, rw = white[index], white[index + 1], white[index + 2]
        alpha = 255 - max(abs(rw - r), abs(gw - g), abs(bw - b))
        alpha = max(0, min(255, alpha))
        if alpha == 0:
            pixels.append((0, 0, 0, 0))
            continue
        scale = 255 / alpha
        pixels.append((
            min(255, int(r * scale)),
            min(255, int(g * scale)),
            min(255, int(b * scale)),
            alpha,
        ))
    canvas = Image.new("RGBA", (size, size))
    canvas.putdata(pixels)
    return canvas


def _hbitmap_to_image(hbmp, width: int, height: int):
    hdc = user32.GetDC(None)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buffer = (ctypes.c_ubyte * (width * height * 4))()
    try:
        copied = gdi32.GetDIBits(hdc, hbmp, 0, height, buffer,
                                 ctypes.byref(bmi), 0)  # DIB_RGB_COLORS
    finally:
        user32.ReleaseDC(None, hdc)
    if copied == 0:
        return None

    raw = bytes(buffer)
    if all(raw[i + 3] == 0 for i in range(0, len(raw), 4)):
        image = Image.frombytes("RGB", (width, height), raw, "raw", "BGRX")
        image = image.convert("RGBA")
        return image
    image = Image.frombytes("RGBA", (width, height), raw, "raw", "BGRA")
    return image


def _extract_from_exe(path: str, size: int):
    large = ctypes.c_void_p()
    small = ctypes.c_void_p()
    try:
        count = shell32.ExtractIconExW(path, 0, ctypes.byref(large), ctypes.byref(small), 1)
        if not count:
            return None
        hicon = large.value or small.value
        if not hicon:
            return None
        icon_size = 32 if large.value else 16
        return _hicon_to_image(hicon, icon_size).resize((size, size), Image.LANCZOS)
    finally:
        if large.value:
            user32.DestroyIcon(large)
        if small.value:
            user32.DestroyIcon(small)


def _shell_image(parsing_name: str, size: int):
    """IShellItemImageFactory.GetImage —— 对 exe / lnk / AppsFolder 都有效."""
    _ensure_com()
    shell_item = ctypes.c_void_p()
    try:
        hr = shell32.SHCreateItemFromParsingName(
            parsing_name, None, ctypes.byref(_IID_SHELLITEM_IMAGE_FACTORY),
            ctypes.byref(shell_item),
        )
        if hr != 0 or not shell_item.value:
            return None
        vtable = ctypes.cast(shell_item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        get_image = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
        )(vtable[3])
        hbmp = ctypes.c_void_p()
        hr = get_image(shell_item, SIZE(size, size), _SIIGBF_ICONONLY | _SIIGBF_BIGGERSIZEOK,
                       ctypes.byref(hbmp))
        if hr != 0 or not hbmp.value:
            return None
        info = BITMAP()
        if gdi32.GetObjectW(hbmp, ctypes.sizeof(BITMAP), ctypes.byref(info)) == 0:
            return None
        image = _hbitmap_to_image(hbmp, info.bmWidth, info.bmHeight)
        if image is None:
            return None
        if image.size != (size, size):
            image = image.resize((size, size), Image.LANCZOS)
        return image
    except (OSError, ValueError, ctypes.ArgumentError):
        return None
    finally:
        if shell_item.value:
            try:
                vtable = ctypes.cast(shell_item, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
                release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
                release(shell_item)
            except (OSError, ValueError):  # pragma: no cover
                pass


def _load_file_image(path: str, size: int):
    lower = path.casefold()
    try:
        if lower.endswith((".ico", ".png", ".bmp", ".jpg", ".jpeg")):
            with Image.open(path) as image:
                image = image.convert("RGBA")
                image.thumbnail((size, size), Image.LANCZOS)
                canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
                return canvas
    except (OSError, ValueError):
        return None
    return None


def _letter_tile(name: str, size: int):
    palette = [
        (64, 112, 214), (79, 140, 120), (166, 104, 63),
        (112, 88, 168), (52, 126, 148), (170, 84, 110),
        (88, 110, 60), (60, 60, 72),
    ]
    index = sum(ord(ch) for ch in name) % len(palette)
    color = palette[index]
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    radius = max(3, size // 6)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=color + (255,))
    letter = (name.strip()[:1] or "?").upper()
    font = None
    for candidate in ("msyhbd.ttc", "segoeuib.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(candidate, int(size * 0.52))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    try:
        box = draw.textbbox((0, 0), letter, font=font)
        width, height = box[2] - box[0], box[3] - box[1]
        draw.text(((size - width) / 2 - box[0], (size - height) / 2 - box[1]), letter,
                  font=font, fill=(255, 255, 255, 245))
    except (ValueError, OSError):
        pass
    return canvas


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------


def image_for_path(path: str, size: int = 32):
    """给任意文件/文件夹/AppsFolder 解析名生成图标."""
    if not _PIL_OK or not path:
        return None
    key = (path, size)
    if key in _image_cache:
        return _image_cache[key]

    image = None
    if os.path.exists(path):
        image = _load_file_image(path, size)
        if image is None:
            image = _shell_image(path, size)
        if image is None and path.casefold().endswith(".exe"):
            image = _extract_from_exe(path, size)
    elif path.casefold().startswith("shell:"):
        image = _shell_image(path, size)
    _image_cache[key] = image
    return image


def apps_folder_name(entry) -> str:
    """Store 应用的 shell 解析名."""
    arguments = (getattr(entry, "arguments", "") or "")
    if "AppsFolder" in arguments:
        return arguments.strip()
    return ""


def entry_icon_image(entry, size: int = 32):
    """按条目本身解析图标：Store 应用 -> AppsFolder；普通软件 -> 启动目标/图标文件."""
    if not _PIL_OK:
        return None
    candidates = []
    folder_name = apps_folder_name(entry)
    if folder_name:
        candidates.append(folder_name)
    target = getattr(entry, "target", "") or ""
    if target and os.path.exists(target):
        candidates.append(target)
    icon_path = getattr(entry, "icon_path", "") or ""
    if icon_path:
        parsed = icon_path.split(",", 1)[0].strip().strip('"')
        if os.path.exists(parsed):
            candidates.append(parsed)
    install = getattr(entry, "install_location", "") or ""
    if install and os.path.isdir(install):
        candidates.append(install)

    for candidate in candidates:
        image = image_for_path(candidate, size)
        if image is not None:
            return image
    return _letter_tile(getattr(entry, "name", "?") or "?", size)


def entry_icon_pil(entry, size: int = 32):
    """不给 Tk 的纯 PIL 版本，供后台线程预取图标（ImageTk 只能在主线程建）."""
    if not _PIL_OK:
        return None
    key = (f"pil:{getattr(entry, 'key', '') or getattr(entry, 'name', '')}", size)
    if key in _pil_cache:
        return _pil_cache[key]
    try:
        image = entry_icon_image(entry, size)
    except (OSError, ValueError):
        image = None
    _pil_cache[key] = image
    return image


def tk_photo(image):
    """在主线程把 PIL 图像转成 PhotoImage（后台线程只做 PIL 部分）."""
    if not _PIL_OK or image is None:
        return None
    try:
        return ImageTk.PhotoImage(image)
    except (RuntimeError, TypeError):
        return None


def get_icon(path: str, name: str, size: int = 32):
    """给桌面条目等“只有路径”的场景返回 PhotoImage."""
    if not _PIL_OK:
        return None
    key = (path or name, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    image = image_for_path(path, size) if path else None
    if image is None:
        image = _letter_tile(name, size)
    try:
        photo = ImageTk.PhotoImage(image)
    except (RuntimeError, TypeError):
        return None
    _cache[key] = photo
    return photo


def get_entry_icon(entry, size: int = 32):
    if not _PIL_OK:
        return None
    key = (f"entry:{getattr(entry, 'key', '') or getattr(entry, 'name', '')}", size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    image = entry_icon_image(entry, size)
    try:
        photo = ImageTk.PhotoImage(image)
    except (RuntimeError, TypeError):
        return None
    _cache[key] = photo
    return photo


def shortcut_icon(entry, size: int = 256) -> str:
    """生成/复用一个真实的 .ico 供 .lnk 使用；返回空串表示没有可用图标."""
    if not _PIL_OK:
        return ""
    folder_name = apps_folder_name(entry)
    target = getattr(entry, "target", "") or ""
    key_source = folder_name or target or getattr(entry, "icon_path", "")
    if not key_source:
        return ""
    stamp = ""
    try:
        probe = target if target and os.path.exists(target) else ""
        if probe:
            stat = os.stat(probe)
            stamp = f"{stat.st_mtime_ns}"
    except OSError:
        stamp = ""
    digest = hashlib.sha1(f"{key_source}|{stamp}".encode("utf-8", "ignore")).hexdigest()[:16]
    ico_path = os.path.join(icon_cache_dir(), f"{digest}.ico")

    if os.path.exists(ico_path):
        return ico_path
    image = entry_icon_image(entry, size)
    if image is None:
        return ""
    try:
        if image.width < size:
            image = image.resize((size, size), Image.LANCZOS)
        image.save(ico_path, format="ICO",
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        return ico_path
    except (OSError, ValueError):
        return ""


def load_app_icon(size: int = 64):
    if not _PIL_OK:
        return None
    for name in ("app.png", "icon.png"):
        path = resource_path("assets", name)
        if os.path.exists(path):
            image = _load_file_image(path, size)
            if image is not None:
                return ImageTk.PhotoImage(image)
    return None
