# Edge Athlete Project Vision and Architecture

High-level product and architecture brief for developers and coding agents.

- Source: Product owner vision supplied on 2026-08-10
- Status: Long-term north star, not an immediate implementation specification

## 1. Overall Goal

Edge Athlete is intended to become a cloud-hosted velocity-based training (VBT)
platform for coaches and athletes.

The finished product should require as little local setup as possible. A gym
should not need to:

- Host its own Edge Athlete server.
- Install PostgreSQL, Django, or React locally.
- Run Docker on rack laptops.
- Configure a Raspberry Pi.
- Configure networking between Edge Athlete components.
- Manually transfer workout data between computers.

The ideal gym setup is:

```text
Internet-connected laptop + Bluetooth VBT device
```

The backend, application data, and browser synchronization should be hosted
centrally. The narrowly scoped Rack Helper keeps BLE, rep detection, and its bounded
outage queue on the rack laptop.

### Network Decision

The cloud product does not require or manage a dedicated Edge Athlete Wi-Fi access
point. Coaches, Rack browsers, and Dashboard browsers use the customer's ordinary
internet connection and local network. No daily workflow may depend on a Raspberry
Pi, private SSID, local Django server, local MQTT broker, or Edge Athlete network
configuration.

The existing Pi/private-AP deployment remains a selectable compatibility profile.
It is not the target customer architecture. The native Rack Helper is the primary
hosted BLE path. Web Bluetooth may provide an optional zero-install path on
qualified browser, OS, and hardware combinations. Neither path may require Edge
Athlete to operate the customer's network.

## 2. Intended User Experience

A coach should be able to visit the Edge Athlete website and:

1. Create an account.
2. Create and manage athletes.
3. Organize athletes into groups or teams where applicable.
4. Create exercises.
5. Create workouts and programming.
6. Assign workouts to athletes.
7. View completed workouts.
8. View VBT measurements and historical performance.
9. Monitor athletes and racks where appropriate.

The coach should be able to do this from a normal internet-connected computer.

## 3. Rack System

A Rack represents the computer used at a physical lifting station. Each station
has a laptop and VBT device. The native Rack Helper is the primary hosted BLE path;
Web Bluetooth is optional where it passes qualification.

The desired workflow is:

```text
Open Edge Athlete website
  -> Log in or enter Rack mode
  -> Select athlete and workout
  -> Select Launch Helper; signed Download Rack Helper is available beside it
  -> If no intent-bound helper check-in appears, follow start or pairing guidance
  -> Pair the helper during first-time setup
  -> Rack Helper reconnects to the assigned VBT device
  -> Begin workout
```

Once connected, the Rack interface should display VBT measurements in real time.

## 4. Bluetooth Architecture

The production direction uses a downloadable Rack Helper. The available
Linux/browser environment exposed no Web Bluetooth API, and the supported release
matrix has not been selected:

```text
VBT sensor
  -> Bluetooth Low Energy
Rack laptop
  -> Native Rack Helper
  -> Local rep detection and bounded offline queue
  -> Outbound HTTPS
Edge Athlete cloud
  -> Authenticated invalidation and HTTPS reconciliation
React Rack interface
```

The proposed helper would make outbound cloud connections only, expose no LAN
service, store a revocable credential in the operating-system keychain, and upload
derived rep events rather than raw IMU frames. Browser-restart and offline-queue
behavior require implementation and qualification. Pairing would use a short-lived
code displayed by the Rack page; the code would not be the persistent credential.

Web Bluetooth remains an optional zero-install path where it passes qualification.
It is not the production dependency and cannot block supported rack hardware.

## 5. Current VBT Hardware

Current development and testing hardware is a WitMotion BLE IMU. A Linux/Bleak
test connected to the WT901, received notifications from `FFE4` under service
`FFE5`, decoded 20-byte `55 61` frames, and restored the connection after tested
disconnects. The decoder implements the current conversion factors; physical
measurement and detector accuracy remain unqualified. Future qualification must
still document:

- BLE device identification.
- Command and configuration characteristics.
- Sampling frequency.
- Timestamp behavior.
- Connection and disconnection behavior.

The existing Python/Bleak work is the protocol and rep-detection reference for the
proposed packaged Rack Helper. Platform support remains an open release decision.

## 6. VBT Processing

The sensor provides IMU measurements such as acceleration, gyroscope, and
potentially orientation or angle information. Edge Athlete needs to derive:

- Rep detection.
- Mean concentric velocity.
- Peak velocity.
- Rep duration.
- Set information.
- Velocity loss.
- Potential range of motion or displacement.

The processing location can evolve. A likely architecture is:

```text
IMU -> BLE -> Rack Helper -> Rep detection and VBT processing -> Cloud API -> Rack browser
```

Time-sensitive signal processing should occur locally so network latency does not
affect rep detection. The cloud should primarily receive meaningful workout
measurements instead of every raw IMU sample. Raw samples may be retained during
development and debugging when explicitly required.

## 7. Offline and Network Failure Handling

The Rack should eventually tolerate temporary internet interruptions:

```text
Sensor -> Rack Helper -> Durable bounded local queue
Internet unavailable -> Workout continues
Internet restored -> Buffered reps synchronize to the server
```

A temporary outage should not destroy an athlete's current set or workout.
The helper owns primary acquisition durability. The browser keeps a delivered-event
IndexedDB cache before rendering so a browser restart can reconcile without making
the browser the only durable receiver.

## 8. Cloud Architecture

The primary application should run on a VPS or equivalent cloud infrastructure:

```text
Internet -> edgeathlete.online -> HTTPS -> Nginx
Nginx -> React
Nginx -> Django -> PostgreSQL
```

Docker Compose is appropriate for the initial deployment. Kubernetes is not
currently required. Introduce it only when concrete scaling, redundancy,
orchestration, or infrastructure requirements justify the complexity.

## 9. Backend Responsibilities

Django should eventually be authoritative for:

- Users and coaches.
- Athletes.
- Teams and groups.
- Exercises.
- Workouts and assignments.
- Racks and devices.
- Sets, reps, and VBT measurements.
- Historical performance.

The backend should expose APIs for coach-facing and rack-facing interfaces.

## 10. Real-Time Communication

Features that may need real-time communication include:

- Rack and workout status.
- Live rep results.
- Coach monitoring.
- Device connection state.
- Current athlete, exercise, and set.

Use WebSockets or another real-time mechanism where ordinary HTTP is insufficient.
Do not introduce real-time infrastructure without a concrete product benefit.

## 11. Security

The internet-facing multi-user application must account for:

- Authentication and authorization.
- Coach and athlete ownership boundaries.
- HTTPS.
- Secure session and token handling.
- Input validation and API authorization.
- Rate limiting where appropriate.
- Secrets management.
- Database backups.

A coach must never access another coach's athletes or workouts by changing an API
request or identifier.

## 12. Device Abstraction

Do not tightly couple the application to one WitMotion model. Prefer an abstraction:

```text
VBTDevice
  -> WitMotionDevice
  -> FutureEdgeAthleteDevice
  -> OtherDevice
```

WitMotion is the current development hardware. Edge Athlete may eventually use
purpose-built hardware. Workout and Rack code should consume standardized VBT
measurements rather than WitMotion-specific BLE packets throughout the system.

## 13. Long-Term Custom Hardware

A future Edge Athlete device could expose a custom BLE GATT service:

```text
Edge Athlete VBT Service
  -> Sensor data
  -> Device information
  -> Battery
  -> Configuration
  -> Device status
```

This provides greater control than permanent reliance on a third-party protocol.
The software architecture should make migration to custom hardware practical.

## 14. Product Philosophy

When making architectural decisions, ask:

> Does this make Edge Athlete easier for a coach to deploy and use?

The finished product should feel like a web service, not an IT project.

The ideal customer experience is:

```text
Buy or receive VBT device
  -> Open Edge Athlete
  -> Create account
  -> Create athletes and workouts
  -> Take laptop to rack
  -> Open Rack screen
  -> Connect VBT device
  -> Lift
```

There should be minimal configuration between receiving the hardware and
collecting the first rep.

## 15. Current Development and Long-Term Architecture

Do not assume every current repository component is permanent. Some components
exist because they supported prototypes or earlier requirements.

When modifying existing code:

1. Preserve working functionality unless there is a reason to change it.
2. Prefer incremental migrations over complete rewrites.
3. Separate hardware-specific logic from business logic.
4. Keep cloud deployment as the long-term target.
5. Keep Rack setup extremely simple.
6. Avoid infrastructure complexity without a concrete benefit.

## 16. North-Star Architecture

The long-term system has three layers:

```text
+--------------------------------------------------+
| EDGE ATHLETE CLOUD                               |
| React | Django | PostgreSQL | Authentication     |
| Athletes | Workouts | History | Analytics        |
+------------------------+-------------------------+
                         |
                      Internet
                         |
+------------------------v-------------------------+
| RACK LAPTOP                                      |
| Edge Athlete Rack web interface                  |
| Native Rack Helper (primary)                     |
| BLE rep detection and durable offline queue      |
| Web Bluetooth (optional qualified adapter)       |
+------------------------+-------------------------+
                         |
                    Bluetooth LE
                         |
+------------------------v-------------------------+
| VBT DEVICE                                       |
| Accelerometer and gyroscope                      |
| BLE GATT interface                               |
| Current: WitMotion                               |
| Future: Edge Athlete custom hardware             |
+--------------------------------------------------+
```

## Core Principle

The cloud manages athletes and workouts.

The Rack browser manages the lifting workflow. The Rack Helper manages the local
VBT connection, rep detection, and outage queue.

The detailed contract and implementation blockers are in
[`_RACK_HELPER_SPEC.md`](_RACK_HELPER_SPEC.md).

The VBT device measures movement.

The user should not need to understand the infrastructure connecting them.

## Instruction for Coding Agents

Read this document before making product or architecture decisions. Existing
implementation details may differ from this long-term architecture. Preserve
working functionality while moving incrementally toward the north star.

Do not assume prototype infrastructure is permanent. Favor simple Rack setup,
cloud-hosted business logic and data, local BLE communication, hardware
abstraction, and incremental migration over rewrites or unnecessary infrastructure.
