"""Approved OS-keyring storage for helper credentials and local protocol metadata."""

import json
import sys


SERVICE = "Edge Athlete Rack Helper Development"
APPROVED_BACKENDS = {
    "linux": {"keyring.backends.SecretService.Keyring"},
    "win32": {"keyring.backends.Windows.WinVaultKeyring"},
}


class KeychainUnavailable(Exception):
    pass


class KeyringStore:
    def __init__(self, keyring_module, *, platform=None):
        self.keyring = keyring_module
        self.platform = platform or sys.platform
        try:
            backend = keyring_module.get_keyring()
        except Exception:
            raise KeychainUnavailable("keychain_unavailable") from None
        backend_name = backend.__class__.__module__ + "." + backend.__class__.__name__
        approved = APPROVED_BACKENDS.get(self.platform, set())
        if backend_name not in approved:
            raise KeychainUnavailable("keychain_unavailable")

    def get(self, name):
        try:
            return self.keyring.get_password(SERVICE, name)
        except Exception:
            raise KeychainUnavailable("keychain_unavailable") from None

    def set(self, name, value):
        if not isinstance(value, str):
            raise TypeError("keyring values must be strings")
        try:
            self.keyring.set_password(SERVICE, name, value)
        except Exception:
            raise KeychainUnavailable("keychain_unavailable") from None

    def delete(self, name):
        try:
            if self.keyring.get_password(SERVICE, name) is not None:
                self.keyring.delete_password(SERVICE, name)
        except Exception:
            raise KeychainUnavailable("keychain_unavailable") from None

    def get_json(self, name):
        raw = self.get(name)
        if raw is None:
            return None
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            raise KeychainUnavailable("keychain_unavailable") from None
        if not isinstance(value, dict):
            raise KeychainUnavailable("keychain_unavailable")
        return value

    def set_json(self, name, value):
        self.set(name, json.dumps(value, sort_keys=True, separators=(",", ":")))

    def clear_pending_pairing(self):
        for name in ("bootstrap", "pairing_id", "activation_request_id"):
            self.delete(name)

    def clear_identity(self):
        for name in (
            "credential", "bootstrap", "pairing_id", "activation_request_id",
            "installation_id", "dispatch",
        ):
            self.delete(name)
