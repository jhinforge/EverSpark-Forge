"""Shared admission error for active execution and maintenance operations."""
class BusyError(RuntimeError):
    pass

class TaskError(RuntimeError):
    pass
