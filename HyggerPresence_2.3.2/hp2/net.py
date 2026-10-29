"""Hygger Presence 2.3.2 - HTTP through Windows' own WinHTTP.

The app makes a handful of plain requests: the VNDB API and cover page, cover
images, the GitHub release check and the update download. requests did that by
bundling urllib3, certifi and Python's OpenSSL (about 3 MB of the exe); WinHTTP
ships with Windows, verifies TLS against the Windows certificate store, follows
the system proxy settings and follows redirects on its own.

The surface is the small part of requests the app used: get() / post() return
a Response with status_code, headers, content, text, json(),
raise_for_status() and iter_content().
"""
import ctypes
import json as _json
import threading
from ctypes import wintypes
from urllib.parse import urlsplit

DEFAULT_AGENT = "HyggerPresence/2.3.2 (+https://github.com/hyther1111/HyggerPresence)"

_ACCESS_TYPE_DEFAULT_PROXY = 0
_ACCESS_TYPE_AUTOMATIC_PROXY = 4           # Windows 8.1+: WPAD, PAC and IE settings
_FLAG_SECURE = 0x00800000
_OPTION_DECOMPRESSION = 118
_DECOMPRESSION_GZIP_DEFLATE = 0x3
_OPTION_REDIRECT_POLICY = 88
_REDIRECT_POLICY_ALWAYS = 2                # requests follows https -> http too
_QUERY_STATUS_CODE = 19
_QUERY_STATUS_TEXT = 20
_QUERY_RAW_HEADERS_CRLF = 22
_QUERY_FLAG_NUMBER = 0x20000000
_ADDREQ_FLAG_ADD = 0x20000000
_ADDREQ_FLAG_REPLACE = 0x80000000
_ERROR_INSUFFICIENT_BUFFER = 122

_HINTERNET = ctypes.c_void_p
_winhttp = ctypes.WinDLL("winhttp", use_last_error=True)


def _proto(name, restype, *argtypes):
    function = getattr(_winhttp, name)
    function.restype = restype
    function.argtypes = argtypes
    return function


_open = _proto("WinHttpOpen", _HINTERNET, wintypes.LPCWSTR, wintypes.DWORD,
               wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
_connect = _proto("WinHttpConnect", _HINTERNET, _HINTERNET, wintypes.LPCWSTR,
                  wintypes.WORD, wintypes.DWORD)
_open_request = _proto("WinHttpOpenRequest", _HINTERNET, _HINTERNET, wintypes.LPCWSTR,
                       wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                       ctypes.c_void_p, wintypes.DWORD)
_set_timeouts = _proto("WinHttpSetTimeouts", wintypes.BOOL, _HINTERNET,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
_set_option = _proto("WinHttpSetOption", wintypes.BOOL, _HINTERNET, wintypes.DWORD,
                     ctypes.c_void_p, wintypes.DWORD)
_add_headers = _proto("WinHttpAddRequestHeaders", wintypes.BOOL, _HINTERNET,
                      wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD)
_send = _proto("WinHttpSendRequest", wintypes.BOOL, _HINTERNET, wintypes.LPCWSTR,
               wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
               ctypes.c_size_t)
_receive = _proto("WinHttpReceiveResponse", wintypes.BOOL, _HINTERNET, ctypes.c_void_p)
_query_headers = _proto("WinHttpQueryHeaders", wintypes.BOOL, _HINTERNET, wintypes.DWORD,
                        wintypes.LPCWSTR, ctypes.c_void_p,
                        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD))
_read = _proto("WinHttpReadData", wintypes.BOOL, _HINTERNET, ctypes.c_void_p,
               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
_close = _proto("WinHttpCloseHandle", wintypes.BOOL, _HINTERNET)


class HTTPError(OSError):
    """Raised by raise_for_status() for a 4xx/5xx answer (like requests)."""

    def __init__(self, message, response=None):
        super().__init__(message)
        self.response = response


class NetworkError(OSError):
    """No answer at all: DNS, connection, TLS or timeout."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


def _describe(code):
    """WinHTTP's own text for an error code, e.g. 12002 -> 'The operation timed out'."""
    buffer = ctypes.create_unicode_buffer(512)
    # FORMAT_MESSAGE_FROM_HMODULE | FROM_SYSTEM | IGNORE_INSERTS
    size = ctypes.windll.kernel32.FormatMessageW(
        0x0800 | 0x1000 | 0x0200, ctypes.c_void_p(_winhttp._handle), code, 0,
        buffer, len(buffer), None)
    text = buffer.value[:size].strip() if size else ""
    return "%s (WinHTTP %d)" % (text, code) if text else "WinHTTP error %d" % code


def _fail(what, host=""):
    code = ctypes.get_last_error()
    where = "%s: " % host if host else ""
    raise NetworkError("%s%s failed: %s" % (where, what, _describe(code)), code)


_sessions = {}
_sessions_lock = threading.Lock()


def _session(agent):
    """One WinHTTP session per User-Agent, shared by every thread."""
    with _sessions_lock:
        handle = _sessions.get(agent)
        if handle:
            return handle
        handle = (_open(agent, _ACCESS_TYPE_AUTOMATIC_PROXY, None, None, 0)
                  or _open(agent, _ACCESS_TYPE_DEFAULT_PROXY, None, None, 0))
        if not handle:
            _fail("WinHttpOpen")
        for option, value in ((_OPTION_DECOMPRESSION, _DECOMPRESSION_GZIP_DEFLATE),
                              (_OPTION_REDIRECT_POLICY, _REDIRECT_POLICY_ALWAYS)):
            value = wintypes.DWORD(value)
            _set_option(handle, option, ctypes.byref(value),
                        ctypes.sizeof(value))  # best effort: old Windows lacks some
        _sessions[agent] = handle
        return handle


class Headers(dict):
    """Response headers; get() and [] ignore case like requests' dict."""

    def __getitem__(self, key):
        return dict.__getitem__(self, key.lower())

    def get(self, key, default=None):
        return dict.get(self, key.lower(), default)

    def __contains__(self, key):
        return dict.__contains__(self, key.lower())


class Response:
    def __init__(self, url, request, connection):
        self.url = url
        self._request = request
        self._connection = connection
        self._content = None
        self.status_code = self._number(_QUERY_STATUS_CODE)
        self.reason = self._text(_QUERY_STATUS_TEXT)
        self.headers = Headers()
        for line in self._text(_QUERY_RAW_HEADERS_CRLF).split("\r\n")[1:]:
            name, sep, value = line.partition(":")
            if sep:
                self.headers[name.strip().lower()] = value.strip()

    def _number(self, level):
        value = wintypes.DWORD()
        size = wintypes.DWORD(ctypes.sizeof(value))
        if not _query_headers(self._request, level | _QUERY_FLAG_NUMBER, None,
                              ctypes.byref(value), ctypes.byref(size), None):
            _fail("reading the status", urlsplit(self.url).hostname)
        return value.value

    def _text(self, level):
        size = wintypes.DWORD(0)
        _query_headers(self._request, level, None, None, ctypes.byref(size), None)
        if ctypes.get_last_error() != _ERROR_INSUFFICIENT_BUFFER or not size.value:
            return ""
        buffer = ctypes.create_unicode_buffer(size.value // 2 + 1)
        if not _query_headers(self._request, level, None, buffer, ctypes.byref(size), None):
            return ""
        return buffer.value

    def iter_content(self, chunk_size=1 << 16):
        if self._content is not None:
            for start in range(0, len(self._content), chunk_size):
                yield self._content[start:start + chunk_size]
            return
        buffer = ctypes.create_string_buffer(chunk_size)
        count = wintypes.DWORD()
        try:
            while self._request:
                if not _read(self._request, buffer, chunk_size, ctypes.byref(count)):
                    _fail("download", urlsplit(self.url).hostname)
                if not count.value:
                    break
                yield buffer.raw[:count.value]
        finally:
            self.close()

    @property
    def content(self):
        if self._content is None:
            self._content = b"".join(self.iter_content())
        return self._content

    @property
    def text(self):
        charset = "utf-8"
        for part in (self.headers.get("Content-Type") or "").split(";")[1:]:
            key, _sep, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip("\"' ")
        try:
            return self.content.decode(charset, "replace")
        except LookupError:
            return self.content.decode("utf-8", "replace")

    def json(self):
        return _json.loads(self.content)

    def raise_for_status(self):
        if 400 <= self.status_code < 600:
            kind = "Client" if self.status_code < 500 else "Server"
            raise HTTPError("%d %s Error: %s for url: %s"
                            % (self.status_code, kind, self.reason, self.url), self)

    def close(self):
        request, connection = self._request, self._connection
        self._request = self._connection = None
        if request:
            _close(request)
        if connection:
            _close(connection)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


def _ascii_host(url):
    """Punycode a non-ASCII host name (https://例え.jp/ -> https://xn--r8jz45g.jp/).

    urlsplit() checks such names with unicodedata, which the exe leaves out.
    """
    if url.isascii():
        return url
    scheme, sep, rest = url.partition("//")
    end = min([i for i in (rest.find("/"), rest.find("?"), rest.find("#")) if i >= 0]
              or [len(rest)])
    user, at, host = rest[:end].rpartition("@")
    if host.isascii():
        return url
    name, colon, port = host.partition(":")
    name = ".".join(label if label.isascii()
                    else "xn--" + label.lower().encode("punycode").decode("ascii")
                    for label in name.split("."))
    return scheme + sep + user + at + name + colon + port + rest[end:]


def request(method, url, headers=None, data=None, json=None, timeout=12, stream=False):
    """Send one request; the body is read now unless stream=True."""
    parts = urlsplit(_ascii_host(url))
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Unsupported URL: %r" % (url,))
    headers = dict(headers or {})
    agent = DEFAULT_AGENT
    for key in list(headers):
        if key.lower() == "user-agent":
            agent = headers.pop(key)
    if not any(key.lower() == "accept" for key in headers):
        headers["Accept"] = "*/*"
    if json is not None:
        data = _json.dumps(json).encode("utf-8")
        if not any(key.lower() == "content-type" for key in headers):
            headers["Content-Type"] = "application/json"
    if isinstance(data, str):
        data = data.encode("utf-8")
    if isinstance(timeout, (tuple, list)):
        connect_timeout, read_timeout = timeout
    else:
        connect_timeout = read_timeout = timeout
    connect_ms = int((connect_timeout or 0) * 1000)
    read_ms = int((read_timeout or 0) * 1000)

    secure = parts.scheme == "https"
    port = parts.port or (443 if secure else 80)
    path = (parts.path or "/") + ("?" + parts.query if parts.query else "")
    connection = _connect(_session(agent), parts.hostname, port, 0)
    if not connection:
        _fail("connecting", parts.hostname)
    handle = _open_request(connection, method, path, None, None, None,
                           _FLAG_SECURE if secure else 0)
    if not handle:
        _close(connection)
        _fail("opening the request", parts.hostname)
    response = None
    try:
        _set_timeouts(handle, connect_ms, connect_ms, read_ms, read_ms)
        for key, value in headers.items():
            line = "%s: %s" % (key, value)
            if not _add_headers(handle, line, len(line),
                                _ADDREQ_FLAG_ADD | _ADDREQ_FLAG_REPLACE):
                _fail("adding header %s" % key, parts.hostname)
        body = ctypes.create_string_buffer(data, len(data)) if data else None
        length = len(data) if data else 0
        if not _send(handle, None, 0, body, length, length, 0):
            _fail("sending the request", parts.hostname)
        if not _receive(handle, None):
            _fail("waiting for the answer", parts.hostname)
        response = Response(url, handle, connection)
        if not stream:
            response.content            # read the body now, like requests
        return response
    except BaseException:
        if response is not None:
            response.close()
        else:
            _close(handle)
            _close(connection)
        raise


def get(url, **kwargs):
    return request("GET", url, **kwargs)


def post(url, **kwargs):
    return request("POST", url, **kwargs)
