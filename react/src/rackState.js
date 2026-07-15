export const MAX_LIVE_REPS = 100;

export function createDeviceId(cryptoObject = globalThis.crypto, random = Math.random) {
  if (typeof cryptoObject?.randomUUID === "function") return cryptoObject.randomUUID();
  const bytes = new Uint8Array(16);
  if (typeof cryptoObject?.getRandomValues === "function") cryptoObject.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function repTopic(nodeId) {
  return `edgeathlete/node/${nodeId}/rep`;
}

export function hasVelocityTarget(program) {
  return Number.isFinite(program?.velocity_zone_min) && Number.isFinite(program?.velocity_zone_max);
}

export function classifyVelocity(meanVelocity, minimum, maximum) {
  if (meanVelocity < minimum) return "Below target";
  if (meanVelocity > maximum) return "Above target";
  return "On target";
}

export function repKey(rep) {
  return `${rep.node_id}:${rep.rep_number}:${rep.timestamp}`;
}

export function shouldRefreshRack(currentRevision, event, processedEventIds, limit = 100) {
  if (!event || event.revision <= currentRevision || processedEventIds.has(event.event_id)) return false;
  processedEventIds.add(event.event_id);
  if (processedEventIds.size > limit) processedEventIds.delete(processedEventIds.values().next().value);
  return true;
}

export function parseRepMessage(rawMessage, topic, expectedNodeId, now = null) {
  if (!expectedNodeId || topic !== repTopic(expectedNodeId)) return null;
  if (rawMessage.length > 2048) return null;

  try {
    const rep = JSON.parse(rawMessage.toString());
    const timestamp = typeof rep?.timestamp === "string" ? Date.parse(rep.timestamp) : NaN;
    const timezoneAware = typeof rep?.timestamp === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(rep.timestamp);
    if (
      rep?.node_id !== expectedNodeId ||
      !Number.isInteger(rep?.rep_number) || rep.rep_number < 1 || rep.rep_number > 100 ||
      !Number.isFinite(rep?.mean_velocity) || rep.mean_velocity < 0 || rep.mean_velocity > 10 ||
      !Number.isFinite(rep?.peak_velocity) || rep.peak_velocity < rep.mean_velocity || rep.peak_velocity > 10 ||
      !Number.isInteger(rep?.duration_ms) || rep.duration_ms < 0 || rep.duration_ms > 60000 ||
      !Number.isFinite(timestamp) || !timezoneAware ||
      (now !== null && (timestamp < now - 300_000 || timestamp > now + 30_000))
    ) {
      return null;
    }
    return rep;
  } catch {
    return null;
  }
}

export function appendLiveRep(reps, rep, limit = MAX_LIVE_REPS) {
  const key = repKey(rep);
  if (reps.some((existing) => repKey(existing) === key)) return reps;
  const arrivalNumber = (reps.at(-1)?.arrival_number || 0) + 1;
  return [...reps, { ...rep, arrival_number: arrivalNumber }].slice(-limit);
}
