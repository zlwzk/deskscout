"""应用图标：从 exe/ico 提取图标，失败时生成首字母色块；带缓存."""

from __future__ import annotations

import ctypes
import io
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


class RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint,
]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
user32.FillRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(RECT), ctypes.c_void_p]
user32.FillRect.restype = ctypes.c_int

_cache: dict[tuple[str, int], object] = {}
_DIB_WHITE = 0x00FFFFFF
_DIB_BLACK = 0x00000000
_DI_NORMAL = 0x0003


def resource_path(*parts: str) -> str:
    base = getattr(
        sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    return os.path.join(base, *parts)


gdi32.GdiFlush.argtypes = []
gdi32.GdiFlush.restype = wintypes.BOOL


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
        rr = min(255, int(r * scale))
        gg = min(255, int(g * scale))
        bb = min(255, int(b * scale))
        pixels.append((rr, gg, bb, alpha))
    return Image.new("RGBA", (size, size)), pixels


def _image_from_icon(hicon, size: int):
    try:
        canvas, pixels = _hicon_to_image(hicon, size)
        canvas.putdata(pixels)
        return canvas
    except (OSError, ValueError, ctypes.ArgumentError):
        return None


def _load_file_image(path: str, size: int):
    lower = path.casefold()
    try:
        if lower.endswith((".ico", ".png", ".bmp")):
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


def get_icon(path: str, name: str, size: int = 32):
    """返回可放到 Label 的 PhotoImage；失败返回 None."""
    if not _PIL_OK:
        return None
    key = (path or name, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    image = None
    if path and os.path.exists(path):
        image = _load_file_image(path, size)
    if image is None and path and path.casefold().endswith(".exe"):
        large = ctypes.c_void_p()
        small = ctypes.c_void_p()
        try:
            count = shell32.ExtractIconExW(path, 0, ctypes.byref(large), ctypes.byref(small), 1)
            if count and large.value:
                image = _image_from_icon(large, size)
        finally:
            if large.value:
                user32.DestroyIcon(large)
            if small.value:
                user32.DestroyIcon(small)
    if image is None:
        image = _letter_tile(name, size)
    try:
        photo = ImageTk.PhotoImage(image)
    except (RuntimeError, TypeError):
        return None
    _cache[key] = photo
    return photo


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
