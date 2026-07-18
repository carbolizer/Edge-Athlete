// db/repBuffer.js — the durability boundary.
//
// This is the most important safety net on the rack screen. Every rep that
// arrives over MQTT is written HERE, to the browser's own IndexedDB, the instant
// it lands — before any UI or network concern. IndexedDB survives reloads, tab
// closes, and WiFi drops, so if the access point blips at the exact moment a set
// ends, the reps are already saved locally and nothing is lost. The buffer is
// only cleared after a set's batch POST to the server succeeds (Phase 11).
//
// Think of it as writing every rep down in a notebook the moment it happens, so
// even if the phone line drops before you can call it in, you still have it.

const DB_NAME = 'edgeathlete'
const STORE = 'reps'

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        // autoIncrement key = arrival order; we keep it out of the rep payload.
        db.createObjectStore(STORE, { keyPath: '_key', autoIncrement: true })
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

// Write one rep immediately on arrival. Returns once it's durably stored.
export async function addRep(rep) {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).add(rep)
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}

// All buffered reps, in arrival order — read at set-end to build the batch POST.
export async function getBufferedReps() {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readonly')
    const req = tx.objectStore(STORE).getAll()
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

// Wipe the buffer — called ONLY after a set's reps are safely saved server-side.
export async function clearBuffer() {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).clear()
    tx.oncomplete = () => resolve()
    tx.onerror = () => reject(tx.error)
  })
}
