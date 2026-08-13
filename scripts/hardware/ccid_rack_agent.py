#!/usr/bin/env python3
"""Read one contactless CCID reader and expose one-time rack taps over a private UDS."""

import argparse
import asyncio
import ipaddress
import json
import os
import re
import stat
import struct
import time


VENDOR_ID = 0x2CE3
PRODUCT_ID = 0x9567
CONTACTLESS_INTERFACE = 1
BULK_OUT_ENDPOINT = 0x04
BULK_IN_ENDPOINT = 0x85
INTERRUPT_IN_ENDPOINT = 0x86
MAX_RESPONSE_BYTES = 4096
MAX_HEADER_BYTES = 4096
MAX_CONNECTIONS = 8
REQUEST_TIMEOUT_SECONDS = 2
TAG_PATTERN = re.compile(r"^[0-9A-F]{8,32}$")
DEFAULT_HTTP_PORT = 8766
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost,http://127.0.0.1,"
    "http://basestation,http://192.168.4.1"
)


class ApiError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status = status
        self.code = code


def normalize_tag_id(value):
    if not isinstance(value, str):
        raise ValueError("tag ID must be text")
    normalized = re.sub(r"[^0-9A-Fa-f]", "", value).upper()
    if TAG_PATTERN.fullmatch(normalized) is None or len(normalized) % 2:
        raise ValueError("invalid tag ID")
    return normalized


class DirectCcidReader:
    """Minimal CCID transport for the reader's contactless interface."""

    def __init__(self):
        import usb.core
        import usb.util

        readers = list(usb.core.find(
            find_all=True, idVendor=VENDOR_ID, idProduct=PRODUCT_ID,
        ))
        if len(readers) != 1:
            raise RuntimeError("exactly one configured NFC reader is required")
        self._usb_util = usb.util
        self._reader = readers[0]
        self._reader.set_configuration()
        if self._reader.is_kernel_driver_active(CONTACTLESS_INTERFACE):
            self._reader.detach_kernel_driver(CONTACTLESS_INTERFACE)
        self._usb_util.claim_interface(self._reader, CONTACTLESS_INTERFACE)
        self._sequence = 0

    def close(self):
        self._usb_util.release_interface(self._reader, CONTACTLESS_INTERFACE)

    def read_uid(self):
        status, _error, _payload = self._command(0x65)
        if status & 0x03 == 2:
            return None
        status, error, _atr = self._command(0x62)
        if status & 0x40 or error:
            return None
        status, error, payload = self._command(0x6F, b"\xFF\xCA\x00\x00\x00")
        if status & 0x40 or error or len(payload) < 6 or payload[-2:] != b"\x90\x00":
            return None
        return normalize_tag_id(payload[:-2].hex())

    def wait_for_change(self, timeout_seconds):
        import usb.core

        try:
            packet = bytes(self._reader.read(
                INTERRUPT_IN_ENDPOINT,
                4,
                timeout=max(1, int(timeout_seconds * 1000)),
            ))
        except usb.core.USBTimeoutError:
            return False
        if len(packet) < 2 or packet[0] != 0x50:
            raise RuntimeError("invalid CCID slot-change notification")
        return bool(packet[1] & 0x02)

    def _command(self, kind, payload=b"", timeout=1000):
        self._sequence = (self._sequence + 1) & 0xFF
        packet = (
            bytes([kind])
            + struct.pack("<I", len(payload))
            + bytes([0, self._sequence, 0, 0, 0])
            + payload
        )
        self._reader.write(BULK_OUT_ENDPOINT, packet, timeout=timeout)
        response = bytes(self._reader.read(BULK_IN_ENDPOINT, 272, timeout=timeout))
        if len(response) < 10 or response[6] != self._sequence:
            raise RuntimeError("invalid CCID response")
        length = struct.unpack_from("<I", response, 1)[0]
        if length > len(response) - 10:
            raise RuntimeError("truncated CCID response")
        return response[7], response[8], response[10:10 + length]


class TapAgent:
    def __init__(self, reader, rack_number=1, clock=time.monotonic, tap_ttl_seconds=5):
        self._reader = reader
        self._rack_number = rack_number
        self._clock = clock
        self._tap_ttl = tap_ttl_seconds
        self._held_tag = None
        self._pending = None
        self._available = True

    def poll(self):
        tag_id = self._reader.read_uid()
        self._available = True
        if tag_id is None:
            self._held_tag = None
            self._expire()
            return
        tag_id = normalize_tag_id(tag_id)
        if tag_id != self._held_tag:
            self._held_tag = tag_id
            self._pending = {"tag_id": tag_id, "expires": self._clock() + self._tap_ttl}

    def consume(self, rack_number):
        if rack_number != self._rack_number:
            raise ApiError(404, "rack_reader_not_found")
        if not self._available:
            raise ApiError(503, "reader_unavailable")
        self._expire()
        if self._pending is None:
            return {"schema_version": 1, "status": "none"}
        pending = self._pending
        self._pending = None
        return {"schema_version": 1, "status": "tap", "tag_id": pending["tag_id"]}

    def reader_failed(self):
        self._available = False
        self._pending = None

    def replace_reader(self, reader):
        self._reader = reader
        self._available = True
        self._held_tag = None
        self._pending = None

    def _expire(self):
        if self._pending is not None and self._pending["expires"] <= self._clock():
            self._pending = None


async def route_request(agent, method, path, body):
    if method == "POST" and path == "/v1/taps/consume":
        if not isinstance(body, dict) or set(body) != {"rack_number"}:
            raise ApiError(400, "invalid_request_body")
        if type(body["rack_number"]) is not int:
            raise ApiError(400, "invalid_rack_number")
        return 200, agent.consume(body["rack_number"])
    if path == "/v1/taps/consume":
        raise ApiError(405, "method_not_allowed")
    raise ApiError(404, "not_found")


async def handle_connection(agent, reader, writer):
    try:
        headers_raw = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
        if len(headers_raw) > MAX_HEADER_BYTES:
            raise ApiError(431, "headers_too_large")
        lines = headers_raw.decode("ascii").split("\r\n")
        method, path, version = lines[0].split(" ")
        if version != "HTTP/1.1":
            raise ApiError(400, "invalid_request")
        headers = {}
        for line in lines[1:]:
            if not line:
                continue
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        if method != "POST" or headers.get("content-type") != "application/json":
            body = None
        else:
            length = int(headers.get("content-length", "-1"))
            if length < 2 or length > MAX_RESPONSE_BYTES:
                raise ApiError(400, "invalid_body_size")
            body = json.loads((await asyncio.wait_for(
                reader.readexactly(length), timeout=REQUEST_TIMEOUT_SECONDS,
            )).decode("utf-8"))
        status, payload = await route_request(agent, method, path, body)
    except ApiError as error:
        status, payload = error.status, {"code": error.code}
    except Exception:
        status, payload = 400, {"code": "invalid_request"}
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed", 431: "Request Header Fields Too Large", 503: "Service Unavailable"}[status]
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\n"
        f"Content-Length: {len(encoded)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
        + encoded
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


def is_loopback_bind(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def serve(agent, socket_path):
    try:
        existing = os.stat(socket_path)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISSOCK(existing.st_mode):
            raise ValueError("NFC Agent socket path exists and is not a socket")
        os.unlink(socket_path)
    semaphore = asyncio.Semaphore(MAX_CONNECTIONS)

    async def limited_connection(reader, writer):
        async with semaphore:
            await handle_connection(agent, reader, writer)

    server = await asyncio.start_unix_server(
        limited_connection,
        path=socket_path,
        limit=MAX_HEADER_BYTES + 1,
    )
    os.chmod(socket_path, 0o600)
    return server


async def serve_http(agent, host, port, allowed_origins):
    """The rack browser's front door to the reader.

    The rack screen lives on the same laptop as the NFC reader, so it reads taps
    directly from this loopback endpoint instead of going through the base
    station's Django. That keeps the reader local to the rack while Django still
    resolves the tag to an athlete (server-authoritative). The Unix socket above
    stays for a reader attached to the base station itself.
    """
    if not is_loopback_bind(host):
        raise ValueError("NFC Agent HTTP must bind to a loopback address")
    origins = {origin.strip() for origin in allowed_origins.split(",") if origin.strip()}

    async def handle(reader, writer):
        try:
            request = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=2)
            if len(request) > MAX_HEADER_BYTES:
                raise ApiError(431, "headers_too_large")
            lines = request.decode("latin-1").split("\r\n")
            method, path, _version = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    headers[key.lower()] = value.strip()
            origin = headers.get("origin")
            allowed = origin is None or origin in origins
            if not allowed:
                status, payload = 403, {"code": "origin_not_allowed"}
            elif method == "OPTIONS":
                status, payload = 204, None
            elif method == "GET" and path == "/v1/taps/consume":
                try:
                    tap = agent.consume(agent._rack_number)
                except ApiError as error:
                    status, payload = error.status, {"code": error.code}
                else:
                    status, payload = 200, tap
            else:
                status, payload = 404, {"code": "not_found"}
            encoded = b"" if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
            reason = {200: "OK", 204: "No Content", 403: "Forbidden", 404: "Not Found", 431: "Request Header Fields Too Large"}[status]
            response_headers = [
                f"HTTP/1.1 {status} {reason}",
                "Content-Type: application/json",
                f"Content-Length: {len(encoded)}",
                "Cache-Control: no-store",
                "Connection: close",
            ]
            if origin and allowed:
                response_headers.extend([
                    f"Access-Control-Allow-Origin: {origin}",
                    "Vary: Origin",
                    "Access-Control-Allow-Methods: GET, OPTIONS",
                    "Access-Control-Allow-Headers: Content-Type",
                ])
            writer.write(("\r\n".join(response_headers) + "\r\n\r\n").encode() + encoded)
            await writer.drain()
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ValueError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    return await asyncio.start_server(handle, host, port)


async def run_poll_cycle(agent, reader, poll_seconds, clock=time.monotonic, sleep=asyncio.sleep):
    started_at = clock()
    if await asyncio.to_thread(reader.wait_for_change, poll_seconds):
        await asyncio.to_thread(agent.poll)
    await sleep(max(0, poll_seconds - (clock() - started_at)))


async def run(options):
    reader = DirectCcidReader()
    agent = TapAgent(reader, rack_number=options.rack_number, tap_ttl_seconds=options.tap_ttl_seconds)
    server = await serve(agent, options.socket_path)
    http_server = await serve_http(
        agent, options.http_host, options.http_port, options.allowed_origins,
    )
    last_error_type = None
    reconnect_at = 0.0
    try:
        async with server, http_server:
            while True:
                if reader is None:
                    if time.monotonic() < reconnect_at:
                        await asyncio.sleep(options.poll_seconds)
                        continue
                    try:
                        reader = await asyncio.to_thread(DirectCcidReader)
                        agent.replace_reader(reader)
                        print("NFC reader available.", flush=True)
                        last_error_type = None
                    except Exception as error:
                        error_type = type(error).__name__
                        if error_type != last_error_type:
                            print(f"NFC reader unavailable ({error_type}).", flush=True)
                            last_error_type = error_type
                        reconnect_at = time.monotonic() + 2
                        await asyncio.sleep(options.poll_seconds)
                        continue
                try:
                    await run_poll_cycle(agent, reader, options.poll_seconds)
                except Exception as error:
                    agent.reader_failed()
                    error_type = type(error).__name__
                    if error_type != last_error_type:
                        print(f"NFC reader unavailable ({error_type}).", flush=True)
                        last_error_type = error_type
                    try:
                        reader.close()
                    except Exception:
                        pass
                    reader = None
                    reconnect_at = time.monotonic() + 2
    finally:
        server.close()
        await server.wait_closed()
        if reader is not None:
            reader.close()
        try:
            os.unlink(options.socket_path)
        except FileNotFoundError:
            pass


def parse_args(args=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--rack-number", type=int, default=1)
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    parser.add_argument("--tap-ttl-seconds", type=float, default=5)
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=DEFAULT_HTTP_PORT)
    parser.add_argument("--allowed-origins", default=DEFAULT_ALLOWED_ORIGINS)
    options = parser.parse_args(args)
    if options.rack_number < 1 or options.poll_seconds <= 0 or options.tap_ttl_seconds <= 0:
        parser.error("rack number and timing values must be positive")
    if not is_loopback_bind(options.http_host):
        parser.error("--http-host must be a loopback address")
    if options.http_port <= 0 or options.http_port > 65535:
        parser.error("--http-port must be a valid TCP port")
    return options


def main():
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
