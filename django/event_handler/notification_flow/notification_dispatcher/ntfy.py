import requests
from django.conf import settings


def send_ntfy_motion_alert(motion_event) -> bool:
    """Send motion alert through Ntfy. @param motion_event saved MotionEvent json record"""
    url = f"{settings.NTFY_URL}/{settings.NTFY_TOPIC}"

    message = f"Motion detected at {motion_event.location or 'Unknown Location'} from {motion_event.node_id}"

    response = requests.post(
        url,
        data=message.encode("utf-8"),
        headers={
            "Title": "Edge Athlete Motion Detected",
            "Priority": "high",
            "Tags": "warning",
        },
        timeout=5,
    )

    response.raise_for_status()
    return True