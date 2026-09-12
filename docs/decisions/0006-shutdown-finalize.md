# ADR 0006: bounded shutdown finalization and orphan reconciliation

## Status

Accepted for W1a-fix.

## Decision

ToneWatch chooses consistency policy **(b)**: an encoded file is kept if
shutdown reaches a bound before its database row is committed. The next app
startup scans the configured recordings root and inserts a `Recording` row for
each valid UUID-named MP3 or Ogg file that is missing from the database. If
the corresponding call is missing, startup creates it with status
`interrupted`; an existing non-terminal call is changed to `interrupted`.
Reconciliation only adds rows; it never removes files. Files with an invalid
call UUID, unsafe paths, or unreadable metadata are skipped and logged.
Files outside that root are never inspected or modified.

Encoding and persistence are separate shutdown phases. Channel finalization
has its own bounded budget, followed by a separate persistence drain budget.
The configured shutdown budget defaults to an even split between those
phases, so the normal worst case is `finalize budget + drain budget`. Encoding
continues through cancellation when its worker has started, and database
commits are shielded from task cancellation. If either phase expires, the
file remains eligible for startup reconciliation.
The supervisor then cancels and awaits every owned drain, persistence loop,
and commit task before the application disposes the database engine. The
observable shutdown bound is the two phase budgets plus a small event-loop and
database-close epsilon.

## Consequences

The API may not expose a recording until its reconciliation row exists, but a
slow host cannot lose the audio file or cancel an in-flight SQLite commit
without logging that the commit was abandoned for startup reconciliation.
The reconciliation scan uses the same recordings-root escape and symlink
checks as retention and reads PyAV metadata in a worker thread.
