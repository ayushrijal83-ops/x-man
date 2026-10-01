"""Web Push sender (M12): RFC 8291 payload encryption (aes128gcm) + RFC 8292 VAPID, on `cryptography`.

Server credentials come from the environment (VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY / VAPID_SUBJECT);
the private key never leaves this module. Generate a pair with `flask push-keys`.
"""
import base64
import json
import os
import struct
import time
from urllib.parse import urlsplit

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hmac import HMAC

RECORD_SIZE = 4096
TIMEOUT_SECONDS = 5


def b64url_decode(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _public_bytes(public_key):
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hmac(key, data):
    h = HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize()


def generate_vapid_keys():
    """(public, private) as base64url: uncompressed P-256 point, raw 32-byte scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url_encode(_public_bytes(key.public_key())), \
        b64url_encode(key.private_numbers().private_value.to_bytes(32, 'big'))


def encrypt(payload, ua_public_b64, auth_secret_b64, salt=None, sender_key=None):
    """RFC 8291 §3.4 / RFC 8188: one aes128gcm record. salt/sender_key only for test vectors."""
    ua_public = b64url_decode(ua_public_b64)
    auth_secret = b64url_decode(auth_secret_b64)
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    salt = salt or os.urandom(16)
    as_public = _public_bytes(sender_key.public_key())
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = sender_key.exchange(ec.ECDH(), ua_key)

    # HKDF with a single output block (all lengths <= 32), written out per the RFC
    prk_key = _hmac(auth_secret, ecdh_secret)
    ikm = _hmac(prk_key, b'WebPush: info\x00' + ua_public + as_public + b'\x01')
    prk = _hmac(salt, ikm)
    cek = _hmac(prk, b'Content-Encoding: aes128gcm\x00\x01')[:16]
    nonce = _hmac(prk, b'Content-Encoding: nonce\x00\x01')[:12]

    if len(payload) + 1 + 16 > RECORD_SIZE:
        raise ValueError('Push payload too large')
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b'\x02', None)  # 0x02: last record, no padding
    return salt + struct.pack('!IB', RECORD_SIZE, len(as_public)) + as_public + ciphertext


def vapid_header(endpoint, public_b64, private_b64, subject, now=None):
    """RFC 8292 Authorization header: ES256 JWT for the push service origin."""
    parts = urlsplit(endpoint)
    claims = {'aud': f'{parts.scheme}://{parts.netloc}', 'exp': int(now or time.time()) + 12 * 3600, 'sub': subject}
    signing_input = '.'.join(b64url_encode(json.dumps(obj, separators=(',', ':')).encode())
                             for obj in ({'typ': 'JWT', 'alg': 'ES256'}, claims))
    key = ec.derive_private_key(int.from_bytes(b64url_decode(private_b64), 'big'), ec.SECP256R1())
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    signature = b64url_encode(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))
    return f'vapid t={signing_input}.{signature}, k={public_b64}'


def endpoint_allowed(endpoint, allowed_hosts):
    """Only https endpoints on a known push service (the server POSTs to this URL: no SSRF)."""
    try:
        parts = urlsplit(endpoint)
    except ValueError:
        return False
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not host or parts.username or parts.password or len(endpoint) > 1000:
        return False
    return any(host == allowed or host.endswith('.' + allowed) for allowed in allowed_hosts)


def send(endpoint, p256dh, auth, payload, config, urgency='high', ttl=3600):
    """POST one encrypted message. Returns the HTTP status code (0 = network failure)."""
    body = encrypt(json.dumps(payload, separators=(',', ':')).encode(), p256dh, auth)
    headers = {
        'Authorization': vapid_header(endpoint, config['VAPID_PUBLIC_KEY'], config['VAPID_PRIVATE_KEY'],
                                      config['VAPID_SUBJECT']),
        'Content-Encoding': 'aes128gcm',
        'Content-Type': 'application/octet-stream',
        'TTL': str(ttl),
        'Urgency': urgency,
    }
    try:
        return requests.post(endpoint, data=body, headers=headers, timeout=TIMEOUT_SECONDS).status_code
    except requests.RequestException:
        return 0
