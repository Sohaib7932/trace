# ADR-002 — FastAPI, SQLAlchemy and SQLite

Status: accepted.

## Context
The first lesson depends on real Pydantic request validation and a committed note.
The team needs fast isolated tests and reproducible Windows/Linux setup, without
operating a database service before the learning loop works.

## Decision
Python 3.13, FastAPI, Pydantic v2/Settings, SQLAlchemy 2.0, Alembic and uv. Use
synchronous SQLAlchemy in synchronous handlers/services so blocking DB work stays
off the async event loop. SQLite is the initial local database. One scoped session
per unit of work; writes explicitly use `session.begin()`. Alembic owns all DDL.
Enable SQLite foreign keys and modern sqlite3 transaction control (`autocommit=False`)
on Python 3.13; bound lock waits. Use static pooling only for shared in-memory tests.

## Alternatives considered
- PostgreSQL now: strong concurrent-write support, but a new operational dependency.
- Raw sqlite3: less dependency weight, but puts row mapping and migration handling
  throughout application code and makes the future PostgreSQL option harder.
- Async ORM: useful at scale, but adds async lifecycle complexity before measurement.

## Advantages
Actual transactions, constraints, migrations, typed mappings and temporary-file tests.
One Python lockfile; no global package installations needed for the application.

## Disadvantages
SQLite has a single writer and differs from PostgreSQL in typing and migrations.
SQLAlchemy 2.0 is deliberately bounded below 2.1 for this foundation; upgrades need review.

## Consequences
No learner tables in Module 1. An intentionally empty baseline creates the Alembic
revision record, and readiness checks that record. Product tables arrive with real
use cases. Keep DB details in adapters; do not claim PostgreSQL is tested yet.

## Revisit when
Concurrent-write contention, hosting constraints or PostgreSQL-specific requirements
appear. Test migrations, constraints and transaction semantics on both engines first.
