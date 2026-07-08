# process_pulse.py - updates a Node's live health from its heartbeat. 
#
# every pulse tells us a node is alive and what shape it's in 
# this is the only thing a pulse should ever do
from typing import Any, Optional 

from django.utils import timezone 

from event_handler.models import Node 

def process_pulse_event(payload: dict[str, Any]) -> Optional[Node]:
    """
    Update-or-create a Node's live health fields from a pulse payload. 
    Does not create a Rep or Set records 
    """

    try: 
        if payload["event_type"] not in ["pulse", "heartbeat"]:
            print(f"[PULSE] Ignored non-pulse event: {payload['event_type']}")
            return None 
        
        node_id = payload["node_id"]

        node, created = Node.objects.update_or_create(
            node_id=node_id, 
            defaults={
                "battery_level": payload.get("battery_level"),
                "signal_strength": payload.get("signal_strength"),
                "firmware_version": payload.get("firmware_version"),
                "last_seen": timezone.now(),
                "is_active": True,
            },
        )

        if created: 
            print(f"[PULSE] Registered new node: {node}")
        else: 
            print(f"[PULSE] Updated node health: {node}")

        return node 
    
    except Exception as error: 
        print(f"[PULSE] Failed to process pulse event: {error}")
        return None