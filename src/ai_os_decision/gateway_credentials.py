"""Loopback gateway configuration and native macOS Keychain credentials."""
from __future__ import annotations

import ctypes
import hmac
import os
import sys
from urllib.parse import urlsplit


def normalize_gateway_url(value):
    p = urlsplit(value or "")
    if (p.scheme != "http" or p.hostname not in {"127.0.0.1", "localhost"}
            or p.username is not None or p.password is not None or p.query or p.fragment
            or p.path not in {"", "/", "/v1", "/v1/"}):
        raise ValueError("gateway must be a loopback HTTP URL with optional /v1")
    _ = p.port  # Validate malformed ports.
    return "http://" + p.netloc


def _validate(secret):
    if not isinstance(secret, str) or not 1 <= len(secret) <= 4096 or any(
            ord(c) < 33 or ord(c) > 126 for c in secret):
        raise ValueError("invalid gateway credential")
    return secret


def gateway_key():
    value = os.environ.get("FREELLMAPI_KEY")
    return _validate(value) if value else (_keychain() or "")


def store_gateway_key(secret):
    """Create this integration's item; never rotate an existing different key."""
    secret = _validate(secret)
    existing = _keychain()
    if existing is not None:
        if not hmac.compare_digest(existing, secret):
            raise RuntimeError("gateway credential already exists with a different value")
        return
    _keychain(secret)


def _keychain(secret=None):
    if sys.platform != "darwin":
        if secret is not None:
            raise RuntimeError("macOS Keychain is unavailable")
        return None
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    sec = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
    ptr = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ptr, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringCreateWithCString.restype = ptr
    cf.CFDataCreate.argtypes = [ptr, ptr, ctypes.c_long]
    cf.CFDataCreate.restype = ptr
    cf.CFDictionaryCreate.argtypes = [ptr, ptr, ptr, ctypes.c_long, ptr, ptr]
    cf.CFDictionaryCreate.restype = ptr
    cf.CFRelease.argtypes = [ptr]
    cf.CFDataGetLength.argtypes = [ptr]
    cf.CFDataGetLength.restype = ctypes.c_long
    cf.CFDataGetBytePtr.argtypes = [ptr]
    cf.CFDataGetBytePtr.restype = ptr
    sec.SecItemCopyMatching.argtypes = [ptr, ctypes.POINTER(ptr)]
    sec.SecItemCopyMatching.restype = ctypes.c_int32
    sec.SecItemAdd.argtypes = [ptr, ctypes.POINTER(ptr)]
    sec.SecItemAdd.restype = ctypes.c_int32
    owned = []

    def constant(name):
        return ptr.in_dll(sec, name).value

    def string(value):
        result = cf.CFStringCreateWithCString(None, value.encode(), 0x08000100)
        if not result:
            raise RuntimeError("Keychain allocation failed")
        owned.append(result)
        return result

    try:
        pairs = [(constant("kSecClass"), constant("kSecClassGenericPassword")),
                 (constant("kSecAttrService"), string("ai-os.freellmapi")),
                 (constant("kSecAttrAccount"), string("gateway")),
                 (constant("kSecUseAuthenticationUI"), constant("kSecUseAuthenticationUIFail"))]
        if secret is None:
            pairs += [(constant("kSecReturnData"), ptr.in_dll(cf, "kCFBooleanTrue").value),
                      (constant("kSecMatchLimit"), constant("kSecMatchLimitOne"))]
        else:
            data = secret.encode()
            value = cf.CFDataCreate(None, ctypes.cast(ctypes.c_char_p(data), ptr), len(data))
            owned.append(value)
            pairs.append((constant("kSecValueData"), value))
        keys = (ptr * len(pairs))(*(k for k, _ in pairs))
        values = (ptr * len(pairs))(*(v for _, v in pairs))
        callbacks = [ctypes.addressof((ctypes.c_byte * 1).in_dll(cf, n)) for n in
                     ("kCFTypeDictionaryKeyCallBacks", "kCFTypeDictionaryValueCallBacks")]
        query = cf.CFDictionaryCreate(None, keys, values, len(pairs), *callbacks)
        owned.append(query)
        result = ptr()
        status = (sec.SecItemCopyMatching(query, ctypes.byref(result)) if secret is None
                  else sec.SecItemAdd(query, None))
        if status == -25300 and secret is None:
            return None
        if status:
            raise RuntimeError(f"Keychain unavailable (OSStatus {status})")
        if secret is None:
            owned.append(result.value)
            size = cf.CFDataGetLength(result)
            if not 1 <= size <= 4096:
                raise RuntimeError("invalid Keychain credential size")
            return _validate(ctypes.string_at(cf.CFDataGetBytePtr(result), size).decode())
        return None
    finally:
        for value in reversed(owned):
            if value:
                cf.CFRelease(value)
