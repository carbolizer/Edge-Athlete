# Nginx

**What it is.** The front door. One address for the whole app, so a browser never
needs to know which service answers what.

**How we use it.** It splits on the path:

```
http://basestation/          ──► the built React files (static)
http://basestation/api/…     ──► django
```

Live data does **not** pass through it — browsers talk to Mosquitto directly on
9001. Nginx is out of the real-time path entirely.

**Where it lives.** Container `edgeathlete-nginx`, image `nginx:alpine`, the only
service publishing a port (**80**). Config in `nginx/`.

**Worth knowing.** It serves plain HTTP, and that is deliberate — an offline gym has
no way to get a trusted certificate. The cost is that `http://basestation` is a
**non-secure origin**, which switches off service workers, app install and Web
Bluetooth. `localhost` is exempt, which is why things work on the base station's own
screen and not on a rack.

**More:** {doc}`../journal/scripts` · {doc}`chromium`
