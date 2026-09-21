# Memory

The first migrated Memory layer is a local SQLite working-memory store.

It currently owns:

- sessions;
- bounded conversation history;
- successful generation task records;
- per-session clearing.

The default database is `Data/Memory/everspark.db`, which is ignored by Git.
No personal history is bundled with the repository.

This is deliberately described as **Working Memory v0**, not the final Memory
architecture. Episodic recall, structured state memory, the reusable character
subject document, consolidation, and forgetting policies remain future work.
