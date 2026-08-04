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

export function motionTopic(nodeId) {
  return `edgeathlete/node/${nodeId}/motion`;
}

export function parseMotionMessage(rawMessage, topic, expectedNodeId, now = null) {
  if (!expectedNodeId || topic !== motionTopic(expectedNodeId) || rawMessage.length > 2048) return null;
  try {
    const motion = JSON.parse(rawMessage.toString());
    if (Object.keys(motion).sort().join(",") !== "event_type,node_id,timestamp,velocity") return null;
    const timestamp = typeof motion?.timestamp === "string" ? Date.parse(motion.timestamp) : NaN;
    const timezoneAware = typeof motion?.timestamp === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(motion.timestamp);
    if (
      motion?.node_id !== expectedNodeId || motion?.event_type !== "motion" ||
      !Number.isFinite(motion?.velocity) || motion.velocity < 0 || motion.velocity > 10 ||
      !Number.isFinite(timestamp) || !timezoneAware ||
      (now !== null && (timestamp < now - 5_000 || timestamp > now + 30_000))
    ) return null;
    return motion;
  } catch {
    return null;
  }
}

export function hasVelocityTarget(program) {
  const minimum = program?.velocity_zone_min ?? program?.velocity_min;
  const maximum = program?.velocity_zone_max ?? program?.velocity_max;
  return Number.isFinite(minimum) && Number.isFinite(maximum);
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

export function buildRackAssignmentPayload(type, workoutId, workoutProgramId, selectedWorkoutId) {
  return type === "workout_program"
    ? { workout_id: Number(selectedWorkoutId), workout_program_id: Number(workoutProgramId) }
    : { workout_id: Number(workoutId), workout_program_id: null };
}

export function buildAthleteIdentityPayload(deviceId, athleteId, sessionId, eventId) {
  return {
    device_id: deviceId,
    athlete_id: Number(athleteId),
    session_id: Number(sessionId),
    event_id: eventId,
  };
}

export function identityActionEvent(currentAction, actionKey, cryptoObject = globalThis.crypto) {
  return currentAction?.key === actionKey
    ? currentAction
    : { key: actionKey, eventId: createDeviceId(cryptoObject) };
}

export function authoritativeIdentitySet(response) {
  return response?.set || null;
}

export function buildRackSetStartPayload(deviceId) {
  return { device_id: deviceId };
}

export function buildSetCompletionPayload(reps, target, isFalseSet = false) {
  if (isFalseSet) return { reps_completed: 0, is_false_set: true, reps: [] };
  const minimum = target?.velocity_zone_min ?? target?.velocity_min;
  const maximum = target?.velocity_zone_max ?? target?.velocity_max;
  return {
    reps_completed: reps.length,
    is_false_set: false,
    reps: reps.map((rep, index) => ({
      rep_number: index + 1,
      mean_velocity: rep.mean_velocity,
      peak_velocity: rep.peak_velocity,
      duration_ms: rep.duration_ms,
      timestamp: rep.timestamp,
      velocity_color: rep.mean_velocity < minimum ? "red" : rep.mean_velocity > maximum ? "yellow" : "green",
    })),
  };
}

export function athleteNameLabels(athletes) {
  const counts = new Map();
  athletes.forEach((athlete) => {
    const key = athlete.name.trim().toLocaleLowerCase();
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return athletes.map((athlete) => {
    const duplicate = counts.get(athlete.name.trim().toLocaleLowerCase()) > 1;
    return { ...athlete, label: duplicate ? `${athlete.name} (athlete ${athlete.id})` : athlete.name };
  });
}

export function eligibleDemoAthletes(athletes) {
  return (athletes || []).filter((athlete) => athlete.demo_wristband_eligible === true);
}

export function randomDemoAthlete(athletes, random = Math.random) {
  const eligible = eligibleDemoAthletes(athletes);
  if (eligible.length === 0) return null;
  return eligible[Math.min(Math.floor(random() * eligible.length), eligible.length - 1)];
}

export function orderedEffectiveExercises(effectiveWorkout) {
  return [...(effectiveWorkout?.exercises || [])].sort((left, right) => left.position - right.position);
}

export function rackProgressView(progress) {
  if (!progress) return null;
  return {
    complete: progress.status === "complete",
    programName: progress.program?.name || "Program unavailable",
    workoutName: progress.current_workout?.name || null,
    workoutPosition: progress.current_workout?.position ?? null,
    exercise: progress.current_exercise || null,
    expectedSetNumber: progress.expected_set_number ?? null,
    activeSet: progress.active_set || null,
    currentExerciseCompletion: progress.current_exercise_completion || null,
    persistedSets: progress.persisted_sets || [],
  };
}

export function rackSetStartMode(progress) {
  if (!progress || progress.status === "complete") return "none";
  if (progress.active_set?.id) return "active";
  const scheduled = Object.hasOwn(progress.program || {}, "schedule_source")
    && typeof progress.program.schedule_source === "string"
    && progress.program.schedule_source.length > 0;
  return scheduled ? "automatic" : "compatibility";
}

export function rackAssignmentChanged(currentRackNumber, nextRackNumber) {
  const current = currentRackNumber === null || currentRackNumber === undefined ? null : Number(currentRackNumber);
  const next = nextRackNumber === null || nextRackNumber === undefined ? null : Number(nextRackNumber);
  return current !== next;
}

export const rackSessionChanged = rackAssignmentChanged;
