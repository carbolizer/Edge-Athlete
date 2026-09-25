#!/usr/bin/env node
// demo-wall-display.js — replay built-in test cases to the real MQTT broker.
// Open http://localhost/dashboard first, then run:
//   npm run demo:wall
// Each case publishes to edgeathlete/dashboard/state — the same topic the wall
// display subscribes to in production — so you are demoing the actual live path,
// not a mock inside React.

import mqtt from "mqtt";
import {
  DASHBOARD_TOPIC,
  DEMO_CASES,
  DEMO_PLAYLISTS,
} from "../src/dashboard/demoCases.js";

function usage() {
  console.log(`
Wall display demo publisher

Usage:
  npm run demo:wall                          Play the full session playlist
  npm run demo:wall -- --playlist quick        Shorter smoke-test playlist
  npm run demo:wall -- --case velocity-pr      Publish one built-in case
  npm run demo:wall -- --list                  List cases and playlists
  npm run demo:wall -- --loop                  Repeat the playlist

Options:
  --host <host>     MQTT broker host (default: localhost)
  --port <port>     MQTT broker port (default: 1883)
  --playlist <id>   Playlist id: full | quick (default: full)
`);
}

function parseArgs(argv) {
  const opts = {
    host: "localhost",
    port: 1883,
    playlist: "full",
    caseId: null,
    list: false,
    loop: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") opts.help = true;
    else if (arg === "--list") opts.list = true;
    else if (arg === "--loop") opts.loop = true;
    else if (arg === "--host") opts.host = argv[++i];
    else if (arg === "--port") opts.port = Number(argv[++i]);
    else if (arg === "--playlist") opts.playlist = argv[++i];
    else if (arg === "--case") opts.caseId = argv[++i];
    else {
      console.error(`Unknown argument: ${arg}`);
      usage();
      process.exit(1);
    }
  }
  return opts;
}

function listAll() {
  console.log("Built-in cases:\n");
  for (const [id, c] of Object.entries(DEMO_CASES)) {
    console.log(`  ${id}`);
    console.log(`    ${c.title}`);
    console.log(`    Expect: ${c.expect}\n`);
  }
  console.log("Playlists:\n");
  for (const [id, p] of Object.entries(DEMO_PLAYLISTS)) {
    console.log(`  ${id} — ${p.name}`);
    console.log(`    ${p.description}`);
    console.log(`    Steps: ${p.steps.map((s) => s.caseId).join(" → ")}\n`);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function connectClient(host, port) {
  const url = `mqtt://${host}:${port}`;
  return new Promise((resolve, reject) => {
    const client = mqtt.connect(url, { reconnectPeriod: 0, connectTimeout: 8000 });
    client.on("connect", () => resolve(client));
    client.on("error", reject);
  });
}

async function publishCase(client, caseId) {
  const entry = DEMO_CASES[caseId];
  if (!entry) throw new Error(`Unknown case "${caseId}". Run with --list.`);

  const body = JSON.stringify(entry.message);
  await new Promise((resolve, reject) => {
    client.publish(DASHBOARD_TOPIC, body, (err) => (err ? reject(err) : resolve()));
  });

  console.log(`✓ ${caseId} — ${entry.title}`);
  console.log(`  Expect: ${entry.expect}`);
}

async function runPlaylist(client, playlistId, loop) {
  const playlist = DEMO_PLAYLISTS[playlistId];
  if (!playlist) throw new Error(`Unknown playlist "${playlistId}". Run with --list.`);

  do {
    console.log(`\n▶ ${playlist.name}`);
    console.log(`  ${playlist.description}\n`);

    for (const step of playlist.steps) {
      await sleep(step.waitMs);
      await publishCase(client, step.caseId);
    }
  } while (loop);

  console.log("\nDone. Leave /dashboard open to keep watching Insights rotate.");
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    usage();
    return;
  }
  if (opts.list) {
    listAll();
    return;
  }

  console.log(`Connecting to mqtt://${opts.host}:${opts.port} …`);
  const client = await connectClient(opts.host, opts.port);
  console.log(`Publishing to ${DASHBOARD_TOPIC}`);
  console.log("Open http://localhost/dashboard (or your Pi URL) before messages arrive.\n");

  try {
    if (opts.caseId) {
      await publishCase(client, opts.caseId);
    } else {
      await runPlaylist(client, opts.playlist, opts.loop);
    }
  } finally {
    client.end(true);
  }
}

main().catch((err) => {
  console.error("\nDemo failed:", err.message);
  console.error("Is the stack up?  docker compose up");
  process.exit(1);
});
