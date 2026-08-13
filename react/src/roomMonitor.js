/* Validates public MQTT invalidations before they can trigger REST reconciliation. */

export const ROOM_STATE_TOPIC = "edgeathlete/dashboard/state";

export function parseMonitoringEvent(rawMessage) {
  if (!rawMessage || rawMessage.length > 2048) return null;
  try {
    const event = JSON.parse(rawMessage.toString());
    if (
      event?.schema_version !== 1 ||
      event?.type !== "room_state_changed" ||
      !Number.isSafeInteger(event?.revision) ||
      event.revision < 1 ||
      typeof event?.event_id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(event.event_id)
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
