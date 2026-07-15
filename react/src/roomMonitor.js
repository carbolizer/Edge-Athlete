/* Validates public MQTT invalidations before they can trigger REST reconciliation. */

export const ROOM_STATE_TOPIC = "edgeathlete/dashboard/state";

export function parseMonitoringEvent(rawMessage) {
  try {
    const event = JSON.parse(rawMessage.toString());
    if (
      event?.schema_version !== 1 ||
      event?.type !== "room_state_changed" ||
      !Number.isInteger(event?.revision) ||
      event.revision < 1 ||
      typeof event?.event_id !== "string"
    ) {
      return null;
    }
    return event;
  } catch {
    return null;
  }
}

export function shouldReconcile(currentRevision, event) {
  return Boolean(event && event.revision > (currentRevision || 0));
}
