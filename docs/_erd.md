<!--
THE ONE COPY OF THE ENTITY DIAGRAM. Do not paste this anywhere — `{include}` it.

It appears on three pages (reference/database, journal/database, journal/apis) and
three hand-maintained copies would disagree within a month. Deliberately has no
heading, so each page can title it to suit its own table of contents.

Kept out of the build as a page of its own via exclude_patterns in conf.py —
otherwise Sphinx counts it as an orphan and fail_on_warning kills the build.
-->

```mermaid
erDiagram
    TRAINING_BLOCK ||--o{ TRAINING_PROGRAM : "is deployed as"
    TRAINING_GROUP ||--o{ TRAINING_PROGRAM : "trains"
    ATHLETE }o--o{ TRAINING_GROUP : "belongs to"
    TRAINING_GROUP ||--o{ TRAINING_GROUP_COACH : "is run by"

    TRAINING_PROGRAM ||--o{ TRAINING_PROGRAM_WORKOUT : "has days"
    TRAINING_PROGRAM_WORKOUT ||--o{ TRAINING_PROGRAM_EXERCISE : "has rows"
    TRAINING_PROGRAM ||--o{ SCHEDULED_SESSION : "is placed on a calendar as"

    TRAINING_SESSION ||--o{ SESSION_PARTICIPATION : "hosts"
    TRAINING_PROGRAM ||--o{ SESSION_PARTICIPATION : "is run in"
    TRAINING_SESSION ||--o{ SET : "contains"
    TRAINING_SESSION ||--|| DAILY_REPORT : "is frozen into"
    SET ||--o{ REP : "is made of"

    ATHLETE ||--o{ SET : "performs"
    ATHLETE ||--o{ ATHLETE_REFERENCE_MAX : "has benchmarks in"
    EXERCISE ||--o{ SET : "is performed as"
    NODE ||--o{ SET : "measured"
```
