# Memory

Concept Forge owns working-memory business behavior; Archon/Ledger provides
the SQLite/document persistence implementation. In distributed mode the store
remains on the control host.

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
