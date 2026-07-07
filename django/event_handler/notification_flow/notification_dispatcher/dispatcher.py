from event_handler.notification_flow.notification_dispatcher.ntfy import send_ntfy_motion_alert


def dispatch_motion_notification(motion_event) -> None:
    """Send saved motion event to notification backends. @param motion_event saved MotionEvent record"""
    
    # Ntfy (IOS + Android)
    try:
        send_ntfy_motion_alert(motion_event)  # First notification backend
        print(f"[DISPATCH] Ntfy alert sent for: {motion_event}")

    except Exception as error:
        print(f"[DISPATCH] Failed to send notification: {error}")

    # Linux

    # Windows

    # MacOS

    # Web

    # Android Alt