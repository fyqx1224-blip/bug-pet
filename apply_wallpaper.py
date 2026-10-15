import ctypes
import os
import winreg
from pathlib import Path

WP = str(Path(__file__).resolve().parent / "wallpaper" / "bug_room_wallpaper_1920x1080.png")

if not os.path.isfile(WP):
    print("ERROR: wallpaper file not found:", WP)
    raise SystemExit(1)
print("wallpaper file OK:", WP, os.path.getsize(WP), "bytes")

# 1) Set display style to Fill (10) so it covers the screen
try:
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "10")
    winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
    winreg.CloseKey(key)
    print("WallpaperStyle=10 (Fill) set")
except Exception as e:
    print("WARN: could not set style:", e)

# 2) Apply wallpaper via SystemParametersInfoW (writes registry + broadcasts change)
SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

ret = ctypes.windll.user32.SystemParametersInfoW(
    SPI_SETDESKWALLPAPER, 0, WP, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
print("SystemParametersInfoW returned:", ret, "| GetLastError:", ctypes.GetLastError())

print("WALLPAPER APPLIED OK" if ret else "FAILED to apply wallpaper")