# NetworkManager

**What it is.** What owns the Wi-Fi on both sides — the base station broadcasting a
network, and the screens joining it.

**How we use it.** The base station *is* the network. There is no router and no
internet:

```
base station ──broadcasts──► "EdgeAthlete"  (192.168.4.1)
                                  ▲
        rack screens · coach tablet · wall ─┘  join as clients
```

**Where it lives.** A host service, not a container. Base station AP in
`scripts/basestation/startup.sh`; the client join in
`scripts/rack-screen/rack-kiosk-setup.sh`, saved as the `EdgeAthlete-client`
connection.

**Worth knowing.** ⚠️ That client connection carries
`autoconnect-priority 100`. Without it a tablet that has ever joined a home network
picks whichever it likes and boots looking perfectly connected to the wrong one.

If the adapter cannot do AP mode there is no gym Wi-Fi — the app still comes up over
a cable, and the startup log says so rather than failing silently.

**More:** {doc}`../journal/scripts` · {doc}`../guides/rack-screen`
