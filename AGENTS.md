# Edge Athlete Agent Instructions

Read `docs/_PROJECT_VISION_ARCHITECTURE.md` before making product or architecture
decisions. It defines the long-term cloud-hosted Rack and VBT north star.

Read `docs/_RACK_DASHBOARD_TEAM_REGISTRATION.md` before changing account tenancy,
TrainingGroups, rack/dashboard identity, pairing, endpoint credentials,
leaderboards, or team-scoped APIs.

Treat the vision as migration direction, not permission to replace working
prototype paths without acceptance criteria, pattern discovery, and an incremental
plan. Preserve working behavior unless an accepted change explicitly replaces it.

Document precedence is: `_SPEC.md` for accepted system behavior, an accepted ADR
for a locked design decision, an accepted feature spec for its narrower behavior,
and the vision document for migration direction. Draft feature specs and ADRs do
not authorize implementation. `_MESSAGE_CONTRACT.md` owns exact accepted wire
formats; a proposal that changes one must revise it before implementation.
