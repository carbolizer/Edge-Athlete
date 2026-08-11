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
        return self.values.get((service, name))

    def set_password(self, service, name, value):
        self._check(service)
        self.values[(service, name)] = value

    def delete_password(self, service, name):
        self._check(service)
        del self.values[(service, name)]

    def _check(self, service):
        if self.fail:
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

    def test_legacy_origin_namespace_is_never_reused(self):
        keyring = FakeKeyring()
        keyring.values[("Edge Athlete Rack Helper Development", "credential")] = "legacy-secret"
        store = KeyringStore(keyring, platform="linux")

        self.assertIsNone(store.get("credential"))
        store.set("credential", "new-secret")
        self.assertEqual(keyring.values[(SERVICE, "credential")], "new-secret")
        self.assertEqual(
            keyring.values[("Edge Athlete Rack Helper Development", "credential")],
            "legacy-secret",
        )

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
        keyring.values[(SERVICE, "dispatch")] = "[]"
        store = KeyringStore(keyring, platform="linux")
        with self.assertRaises(KeychainUnavailable):
            store.get_json("dispatch")


if __name__ == "__main__":
    unittest.main()
