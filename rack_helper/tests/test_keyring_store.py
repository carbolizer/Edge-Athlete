import unittest

from edgeathlete_rack_helper.keyring_store import KeychainUnavailable, KeyringStore, SERVICE


SecretServiceBackend = type("Keyring", (), {"__module__": "keyring.backends.SecretService"})
PlaintextBackend = type("Keyring", (), {"__module__": "keyring.backends.file"})


class FakeKeyring:
    def __init__(self, backend=None):
        self.backend = backend or SecretServiceBackend()
        self.values = {}
        self.fail = False

    def get_keyring(self):
        return self.backend

    def get_password(self, service, name):
        self._check(service)
        return self.values.get(name)

    def set_password(self, service, name, value):
        self._check(service)
        self.values[name] = value

    def delete_password(self, service, name):
        self._check(service)
        del self.values[name]

    def _check(self, service):
        if service != SERVICE or self.fail:
            raise RuntimeError("backend failure with private detail")


class KeyringStoreTests(unittest.TestCase):
    def test_approved_keyring_persists_and_deletes_values(self):
        keyring = FakeKeyring()
        store = KeyringStore(keyring, platform="linux")
        store.set("credential", "secret")
        store.set_json("dispatch", {"request": "id"})
        self.assertEqual(store.get("credential"), "secret")
        self.assertEqual(store.get_json("dispatch"), {"request": "id"})
        store.clear_identity()
        self.assertEqual(keyring.values, {})

    def test_plaintext_and_unknown_backends_fail_closed(self):
        with self.assertRaises(KeychainUnavailable):
            KeyringStore(FakeKeyring(PlaintextBackend()), platform="linux")
        with self.assertRaises(KeychainUnavailable):
            KeyringStore(FakeKeyring(), platform="darwin")

    def test_locked_keyring_maps_to_bounded_failure(self):
        keyring = FakeKeyring()
        store = KeyringStore(keyring, platform="linux")
        keyring.fail = True
        with self.assertRaisesRegex(KeychainUnavailable, "^keychain_unavailable$"):
            store.get("credential")

    def test_invalid_metadata_never_falls_back_to_a_file(self):
        keyring = FakeKeyring()
        keyring.values["dispatch"] = "[]"
        store = KeyringStore(keyring, platform="linux")
        with self.assertRaises(KeychainUnavailable):
            store.get_json("dispatch")


if __name__ == "__main__":
    unittest.main()
