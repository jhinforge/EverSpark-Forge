# Memory

The first migrated Memory layer is a local SQLite working-memory store.

It currently owns:

- sessions;
- bounded conversation history;
- successful generation task records;
- per-session clearing;
- one automatically assigned current subject per conversation;
- current Character Subject documents;
- immutable subject revision history.

The default database is `Data/Memory/everspark.db`, which is ignored by Git.
No personal history is bundled with the repository.

Working Memory v0 and the first conversation-derived structured state object
are now implemented.
Episodic recall, consolidation, relevance scoring, and forgetting policies
remain future work.
