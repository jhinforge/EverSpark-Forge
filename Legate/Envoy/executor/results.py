"""Keep structured responses intact and bound human-readable task diagnostics."""

STRUCTURED_ACTIONS = frozenset({"chat", "resources", "default_negative", "submit",
                                "poll", "history", "fetch", "synthesize"})
RESPONSE_LIMIT = 60000
DIAGNOSTIC_TAIL = 4000


def command_result(done, action):
    succeeded = done.returncode == 0
    output = done.stdout if succeeded else (done.stderr or done.stdout)
    if succeeded and action in STRUCTURED_ACTIONS:
        if len(output.encode("utf-8")) > RESPONSE_LIMIT:
            return {"status": "failed", "output": "Forge response exceeds node task limit",
                    "exit_code": 1}
    else:
        output = output[-DIAGNOSTIC_TAIL:]
    return {"status": "completed" if succeeded else "failed", "output": output,
            "exit_code": done.returncode,
            **({"stage": done.stage} if getattr(done, "stage", None) else {})}
