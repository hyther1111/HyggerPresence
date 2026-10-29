# Hygger Presence 2.3.3

A smaller download, nothing new to learn. Your library, settings and playtime
are untouched, and the app looks and works the same.

## Changed

- **The exe is about 23 MB instead of 33 MB.** Most of the old file was code
  the app never ran: Qt's own translations for some fifty languages, Qt's
  network module and its plugins, image formats nothing here reads, three copies
  of the same VC++ runtime and Python modules that only build tools use. They
  are left out now. Covers in jpg, png, webp and gif, and the window and tray
  icon, all load as before.

- **Web requests go through Windows itself.** VNDB lookups, cover downloads, the
  update check and the update download now use WinHTTP, the HTTP stack built
  into Windows, instead of Python's `requests` and OpenSSL. Certificates are
  checked against the Windows certificate store, and the proxy set in Windows
  (Settings → Network & Internet → Proxy, including automatic setup scripts) is
  used. A proxy given only through the `HTTPS_PROXY` environment variable is no
  longer picked up.

- The icon is stored more compactly; it shows the same pixels at every size.

## Download

`HyggerPresence.exe` — about 23 MB, down from 33 MB. It is still a plain
single-file build; nothing is packed with UPX, which antivirus tools often
flag. Replacing the old exe keeps your data, which lives in
`%APPDATA%\HyggerPresence`.

Building from source is unchanged: `build.bat`, then `dist\HyggerPresence.exe`.
`requirements.txt` no longer lists `requests` or `Pillow`.
