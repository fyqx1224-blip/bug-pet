import ctypes, os, winreg
from pathlib import Path

WP = str(Path(__file__).resolve().parent / "wallpaper" / "bug_room_wallpaper_1920x1080.png")
assert os.path.isfile(WP), "missing: " + WP
print("file OK:", WP, os.path.getsize(WP), "bytes")

key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE)
winreg.SetValueEx(key, "WallpaperStyle", 0, winreg.REG_SZ, "10")
winreg.SetValueEx(key, "TileWallpaper", 0, winreg.REG_SZ, "0")
winreg.CloseKey(key)
print("style=Fill set")

SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02
ret = ctypes.windll.user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, WP, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
print("apply ret:", ret)
print("APPLIED" if ret else "FAILED")