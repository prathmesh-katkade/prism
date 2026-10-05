# ADR 0024: analytical workspace persistence across SQLite and MySQL

Date: 2026-10-04

Status: accepted

## Evidence

The final isolated MySQL 8.4.9 gate contradicted the earlier assumption that
MySQL was unavailable. Its executable existed outside PATH. Startup then failed
because report JSON columns declared literal TEXT defaults. After that correction,
the live 100,000-row upload failed because MySQL TEXT could not hold frame_json.
Neither failure occurred in the isolated SQLite gate.

## Decision

Report writes explicitly supply JSON collection fields. Legacy report columns
are added nullable and backfilled to empty arrays; startup repeats the backfill
to recover an interrupted migration. No literal TEXT default is required.

Dataset frame storage uses LONGTEXT on MySQL and retains TEXT on SQLite.
An existing MySQL frame_json column is widened in place, preserving revisions.
No production database was used for verification. DDL can acquire a database
lock; deployment must allow startup migration to complete before serving traffic.

## Verification and limits

The report legacy-schema regression verifies retained content and repeat startup.
Real MySQL parity, registry, promotion and report tests ran against a disposable
loopback server. A browser rerun against the previously populated MySQL history
database accepted and displayed the 100,000-row fixture after the widening.
Final exact gate counts and raw log names live in the workspace release report.

This fixes storage compatibility; it does not promise that arbitrary datasets
fit memory or meet a latency target. The 100k observations are single local runs,
not a service-level guarantee. Atlas bindings and promotion policies are unchanged.
