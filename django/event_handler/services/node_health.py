"""Defines whether an assigned sensor is safe to use for rack mutations."""

from datetime import timedelta

from django.utils import timezone

from event_handler.models import Node


WT901_FRESHNESS = timedelta(seconds=2)


def node_is_usable(node, now=None):
    if not node.is_active or node.is_simulated:
        return False
    if node.acquisition_kind != Node.ACQUISITION_WT901_BLE:
        return True
    now = now or timezone.now()
    return bool(node.last_seen and now - WT901_FRESHNESS <= node.last_seen <= now + WT901_FRESHNESS)
