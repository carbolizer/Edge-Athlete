"""Accepted thin helper state machine; this module contains no BLE or ingestion code."""

import base64
from datetime import datetime
import logging
import secrets
import sys
import threading
import uuid

from .config import CONTRACT_VERSION, HEARTBEAT_SECONDS
from .http_client import NetworkError, ResponseError, TransportError
from .keyring_store import KeychainUnavailable


LOGGER = logging.getLogger("edgeathlete_rack_helper")
CODE_ALPHABET = frozenset("0123456789ABCDEFGHJKMNPQRSTVWXYZ")


def _secret():
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def _credential():
    return f"earh1.{uuid.uuid4()}.{_secret()}"


def current_platform():
    if sys.platform == "linux" and sys.maxsize > 2**32:
        return "linux_x64"
    if sys.platform == "win32" and sys.maxsize > 2**32:
        return "windows_x64"
    raise RuntimeError("unsupported_platform")


def valid_pairing_code(value):
    return isinstance(value, str) and len(value) == 8 and all(char in CODE_ALPHABET for char in value)


def valid_credential(value):
    if not isinstance(value, str) or len(value) > 100 or not value.isascii():
        return False
    parts = value.split(".")
    if len(parts) != 3 or parts[0] != "earh1":
        return False
    try:
        credential_id = uuid.UUID(parts[1])
        decoded = base64.b64decode(parts[2] + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        return False
    return bool(
        str(credential_id) == parts[1]
        and len(parts[2]) == 43
        and len(decoded) == 32
        and base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") == parts[2]
    )


class RackHelperRuntime:
    def __init__(self, store, transport, *, platform=None, on_state=None, wait=None):
        self.store = store
        self.transport = transport
        self.platform = platform or current_platform()
        self.on_state = on_state or (lambda state, detail=None: None)
        self.wait = wait or (lambda event, seconds: event.wait(seconds))
        self.stop_event = threading.Event()
        self.boot_id = str(uuid.uuid4())
        self.dispatch_requested = False
        self.heartbeat_thread = None
        self.state = "inert"

    def _state(self, value, detail=None):
        self.state = value
        LOGGER.info("state=%s", value)
        self.on_state(value, detail)

    def start(self, mode):
        if mode == "manual":
            self._state("inert")
            return
        self.dispatch_requested = True
        if self.store.get("credential") is None:
            self._state("unpaired")
            return
        self.consume_launch()

    def pair(self, pairing_code):
        if not valid_pairing_code(pairing_code):
            self._state("pairing_code_invalid")
            return False
        try:
            credential = self.store.get("credential")
            bootstrap = self.store.get("bootstrap")
            if credential is not None and self.store.get("installation_id") is not None:
                if not valid_credential(credential):
                    self.store.clear_identity()
                    self._state("authentication_blocked")
                else:
                    self._state("paired_inert")
                return False
            if (credential is None) != (bootstrap is None):
                self.store.clear_identity()
                credential = bootstrap = None
            if credential is None or bootstrap is None:
                credential, bootstrap = _credential(), _secret()
                self.store.set("credential", credential)
                try:
                    self.store.set("bootstrap", bootstrap)
                except KeychainUnavailable:
                    self.store.delete("credential")
                    raise
            response = self.transport.post("/api/rack-helper/v1/pairings/claim/", {
                "pairing_code": pairing_code,
                "bootstrap_token": bootstrap,
                "credential": credential,
                "platform": self.platform,
                "contract_version": CONTRACT_VERSION,
            })
            self._validate_claim(response)
            self.store.set("pairing_id", response["pairing_id"])
            self._state("confirmation_required", " ".join(response["confirmation_phrase"]))
            return True
        except KeychainUnavailable:
            self._state("keychain_unavailable")
        except ResponseError as exc:
            LOGGER.warning("operation=pair_claim result=%s", exc.code)
            if exc.status == 404:
                self._clear_pending_identity()
            self._state("pairing_rejected")
        except (NetworkError, TransportError):
            LOGGER.warning("operation=pair_claim result=network_or_response_failure")
            self._state("cloud_unavailable")
        return False

    def poll_and_activate(self):
        try:
            pairing_id = self.store.get("pairing_id")
            bootstrap = self.store.get("bootstrap")
            credential = self.store.get("credential")
            if not pairing_id or not bootstrap or not credential:
                self._state("unpaired")
                return False
            if not valid_credential(credential):
                self.store.clear_identity()
                self._state("authentication_blocked")
                return False
            response = self.transport.post("/api/rack-helper/v1/pairings/status/", {
                "pairing_id": pairing_id, "bootstrap_token": bootstrap,
            })
            self._require_exact(response, {
                "pairing_id", "state", "activation_expires_at", "poll_after_seconds",
            })
            if response["pairing_id"] != pairing_id or response["state"] not in {"claimed", "confirmed", "activated"}:
                raise TransportError("invalid_pairing_status")
            if response["poll_after_seconds"] != 2:
                raise TransportError("invalid_pairing_status")
            if response["state"] == "claimed":
                self._state("awaiting_coach_confirmation")
                return False
            return self._activate(pairing_id, credential)
        except KeychainUnavailable:
            self._state("keychain_unavailable")
        except ResponseError as exc:
            LOGGER.warning("operation=pair_status result=%s", exc.code)
            if exc.status == 404 or exc.code in {"activation_unavailable", "helper_authentication_failed"}:
                self._clear_pending_identity()
            self._state("pairing_rejected")
        except (NetworkError, TransportError):
            LOGGER.warning("operation=pair_status result=network_or_response_failure")
            self._state("cloud_unavailable")
        return False

    def _activate(self, pairing_id, credential):
        request_id = self.store.get("activation_request_id")
        if request_id is None:
            request_id = str(uuid.uuid4())
            self.store.set("activation_request_id", request_id)
        response = self.transport.post(
            "/api/rack-helper/v1/pairings/activate/",
            {"pairing_id": pairing_id, "activation_request_id": request_id},
            credential,
        )
        self._require_exact(response, {
            "installation_id", "endpoint_revision", "status_cursor", "launch_intent_bound",
        })
        uuid.UUID(response["installation_id"])
        if (
            not isinstance(response["launch_intent_bound"], bool)
            or not isinstance(response["endpoint_revision"], int)
            or response["endpoint_revision"] < 1
            or not isinstance(response["status_cursor"], int)
            or response["status_cursor"] < 1
        ):
            raise TransportError("invalid_activation_response")
        self.store.set("installation_id", response["installation_id"])
        self.store.clear_pending_pairing()
        self._state("paired_inert")
        if self.dispatch_requested and response["launch_intent_bound"]:
            return self.consume_launch()
        return True

    def _clear_pending_identity(self):
        try:
            if self.store.get("installation_id") is None:
                self.store.clear_identity()
        except KeychainUnavailable:
            pass

    def consume_launch(self):
        try:
            credential = self.store.get("credential")
            if credential is None:
                self._state("unpaired")
                return False
            if not valid_credential(credential):
                self.store.clear_identity()
                self._state("authentication_blocked")
                return False
            dispatch = self.store.get_json("dispatch")
            if dispatch is None:
                dispatch = {"helper_boot_id": self.boot_id, "consume_request_id": str(uuid.uuid4())}
                self.store.set_json("dispatch", dispatch)
            self._validate_dispatch(dispatch)
            try:
                response = self.transport.post(
                    "/api/rack-helper/v1/launch-intents/consume/", dispatch, credential,
                )
            except NetworkError:
                response = self.transport.post(
                    "/api/rack-helper/v1/launch-intents/consume/", dispatch, credential,
                )
            self._require_exact(response, {"intent_id", "acknowledged_at", "ack_cursor", "next"})
            if (
                response["next"] != "reconcile"
                or not isinstance(response["ack_cursor"], int)
                or response["ack_cursor"] < 1
                or not self._valid_timestamp(response["acknowledged_at"])
            ):
                raise TransportError("invalid_consume_response")
            uuid.UUID(response["intent_id"])
            self.store.delete("dispatch")
            self.boot_id = dispatch["helper_boot_id"]
            self._state("no_sensor")
            self.start_heartbeat()
            return True
        except KeychainUnavailable:
            self._state("keychain_unavailable")
        except ResponseError as exc:
            LOGGER.warning("operation=launch_consume result=%s", exc.code)
            if exc.status == 401 and exc.code == "helper_authentication_failed":
                try:
                    self.store.clear_identity()
                except KeychainUnavailable:
                    pass
                self._state("authentication_blocked")
            else:
                if exc.code == "launch_intent_unavailable":
                    try:
                        self.store.delete("dispatch")
                    except KeychainUnavailable:
                        pass
                self._state("inert")
        except (NetworkError, TransportError, ValueError, TypeError):
            LOGGER.warning("operation=launch_consume result=network_or_response_failure")
            self._state("inert")
        return False

    def start_heartbeat(self):
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return
        self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()

    def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            if not self.send_heartbeat():
                return
            if self.wait(self.stop_event, HEARTBEAT_SECONDS):
                return

    def send_heartbeat(self):
        request_id = str(uuid.uuid4())
        body = {"helper_boot_id": self.boot_id, "status_request_id": request_id, "status": "no_sensor"}
        try:
            credential = self.store.get("credential")
            if credential is None:
                self._state("authentication_blocked")
                return False
            if not valid_credential(credential):
                self.store.clear_identity()
                self._state("authentication_blocked")
                return False
            try:
                response = self.transport.post("/api/rack-helper/v1/status/", body, credential)
            except NetworkError:
                response = self.transport.post("/api/rack-helper/v1/status/", body, credential)
            self._require_exact(response, {
                "status", "status_at", "status_cursor", "next_heartbeat_seconds", "stale_after_seconds",
            })
            if (
                response["status"] != "no_sensor"
                or response["next_heartbeat_seconds"] != HEARTBEAT_SECONDS
                or response["stale_after_seconds"] != 60
                or not isinstance(response["status_cursor"], int)
                or response["status_cursor"] < 1
                or not self._valid_timestamp(response["status_at"])
            ):
                raise TransportError("invalid_status_response")
            return True
        except KeychainUnavailable:
            self._state("keychain_unavailable")
        except ResponseError as exc:
            LOGGER.warning("operation=status result=%s", exc.code)
            if exc.status == 401 and exc.code == "helper_authentication_failed":
                try:
                    self.store.clear_identity()
                except KeychainUnavailable:
                    pass
                self._state("authentication_blocked")
            else:
                self._state("inert")
        except (NetworkError, TransportError):
            LOGGER.warning("operation=status result=network_or_response_failure")
            self._state("inert")
        return False

    def quit(self):
        self.stop_event.set()
        thread = self.heartbeat_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._state("disconnected")

    @staticmethod
    def _require_exact(value, keys):
        if not isinstance(value, dict) or set(value) != keys:
            raise TransportError("invalid_response_shape")

    @classmethod
    def _validate_claim(cls, response):
        cls._require_exact(response, {
            "pairing_id", "state", "confirmation_phrase", "expires_at", "poll_after_seconds",
        })
        uuid.UUID(response["pairing_id"])
        phrase = response["confirmation_phrase"]
        if (
            response["state"] != "claimed" or response["poll_after_seconds"] != 2
            or not isinstance(phrase, list) or len(phrase) != 6
            or any(not isinstance(word, str) or not word.isascii() or len(word) > 32 for word in phrase)
        ):
            raise TransportError("invalid_claim_response")

    @staticmethod
    def _validate_dispatch(dispatch):
        if not isinstance(dispatch, dict) or set(dispatch) != {"helper_boot_id", "consume_request_id"}:
            raise TransportError("invalid_dispatch_state")
        for value in dispatch.values():
            parsed = uuid.UUID(value)
            if str(parsed) != value:
                raise TransportError("invalid_dispatch_state")

    @staticmethod
    def _valid_timestamp(value):
        if not isinstance(value, str) or len(value) > 40 or not value.isascii():
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0
