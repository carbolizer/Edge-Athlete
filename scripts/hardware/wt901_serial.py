"""USB transport for WT901BLECL5.0's 0x55 0x61 stream (also used over BLE).

Reads only: opening the port never writes sensor settings or changes calibration.
The USB-C unit tested on macOS exposes a CH340 serial port at 115200 baud.
"""
import asyncio
from contextlib import asynccontextmanager


def list_serial_ports():
    from serial.tools import list_ports
    return [
        {"port": port.device, "description": port.description,
         "vid": port.vid, "pid": port.pid}
        for port in list_ports.comports()
    ]


@asynccontextmanager
async def open_sensor_stream(options, on_notification, on_disconnect,
                             service_uuid, notify_uuid):
    """Deliver byte chunks on the asyncio loop for either USB or native BLE."""
    if not getattr(options, "serial_port", None):
        from bleak import BleakClient
        async with BleakClient(options.address, timeout=15,
                               disconnected_callback=on_disconnect) as client:
            service = client.services.get_service(service_uuid)
            if service is None or service.get_characteristic(notify_uuid) is None:
                raise RuntimeError("configured device lacks the WT901BLE notify service")
            await client.start_notify(notify_uuid, on_notification)
            yield client
        return

    import serial
    # A short timeout bounds shutdown and avoids blocking the event loop.
    port = serial.Serial(port=options.serial_port, baudrate=options.baud,
                         timeout=0.2, write_timeout=0.2)

    async def read_stream():
        try:
            while True:
                chunk = await asyncio.to_thread(port.read, min(max(port.in_waiting, 1), 128))
                if chunk:
                    on_notification(None, chunk)
        except asyncio.CancelledError:
            raise
        except Exception:
            on_disconnect(None)
            raise

    reader = asyncio.create_task(read_stream())
    try:
        yield port
    finally:
        reader.cancel()
        try:
            await reader
        except asyncio.CancelledError:
            pass
        finally:
            port.close()
