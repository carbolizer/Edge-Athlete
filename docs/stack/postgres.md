# PostgreSQL

**What it is.** The database. The permanent record of everything that happened.

**How we use it.** One write per completed set, not one per rep — the tablet holds
reps until the set ends, then posts the batch:

```
rack screen ──whole set──► django ──one transaction──► postgres
```

Django owns the schema; nobody writes SQL by hand.

**Where it lives.** Container `edgeathlete-postgres`, image `postgres:15`, data in
the `postgres_data` volume. Not exposed outside the compose network.

**Worth knowing.** ⚠️ `docker compose down -v` and `ea-reset-hard` delete that
volume. That is the only way to lose a season of training, and it takes the NFC
wristband assignments with it — the seeder does not set those.

**More:** {doc}`../journal/database` for what the tables mean and why ·
{doc}`../reference/database` for a plain-English tour of every table
