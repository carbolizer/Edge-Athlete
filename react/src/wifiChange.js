// wifiChange.js — reading the base station's "the Wi-Fi password is changing"
// broadcast.
//
// The wall display and rack tablets get told the new Wi-Fi password over MQTT
// just before the network drops, so they can show it to whoever is standing
// there to type into that device's settings. This is the one tiny bit of logic
// worth testing on its own: given a message off the broker, is it a real
// password-change and what is the password? Everything else (showing it,
// remembering it) is UI.

// Pulls the new password out of a broadcast, or null if this isn't one. Strict
// on purpose: the broker is a shared channel, so anything that isn't exactly a
// well-formed change message is ignored rather than shown as a bogus password.
export function passwordFromWifiChange(message) {
  if (!message || message.type !== 'wifi_password_changing') return null
  const password = message.password
  if (typeof password !== 'string' || password.length === 0) return null
  return password
}
