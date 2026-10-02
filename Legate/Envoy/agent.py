"""Portable Node Agent; task execution remains on the existing pull channel."""
import os
import time
from .settings import DATA_DIR, TASK_JOURNAL, STARTUP_STATUS
from .identity import Identity
from .registration import Registration
from .heartbeat import Heartbeat
from .fingerprint.hardware import fingerprint
from .transport import Transport, BridgeError
from .executor.journal import execute_once


def startup_status(stage):
    try:
        STARTUP_STATUS.parent.mkdir(parents=True, exist_ok=True)
        STARTUP_STATUS.write_text(stage+"\n")
    except OSError:
        pass


def run():
    url = os.environ.get("EVERSPARK_NODE_URL") or os.environ["EVERSPARK_NODE_BRIDGE_URL"]
    identity = Identity(DATA_DIR/"identity.json")
    token = os.environ.pop("EVERSPARK_NODE_JOIN_TOKEN", None) or os.environ.pop("EVERSPARK_NODE_BOOTSTRAP", None)
    identity.bootstrap(token)
    metadata = {key: os.environ[variable] for key, variable in {
        "provider": "EVERSPARK_NODE_PROVIDER", "provider_instance_id": "EVERSPARK_NODE_PROVIDER_INSTANCE_ID"}.items() if os.environ.get(variable)}
    registration = Registration(identity, Transport(url, os.environ.get("EVERSPARK_NODE_PROXY")), fingerprint(DATA_DIR, metadata))
    heartbeat = Heartbeat(registration, DATA_DIR)
    heartbeat.thread.start()
    attempts = 0
    try:
        while True:
            if registration.authentication() is None:
                try:
                    response = registration.register()
                    attempts = 0
                    from .bandwidth import start
                    start(DATA_DIR)
                    startup_status("registered")
                    print(f"[EverSpark] Node {response['node_id']} registered", flush=True)
                except (OSError, ValueError, KeyError, RuntimeError) as exc:
                    attempts += 1
                    if attempts == 1 or attempts % 10 == 0:
                        reason = f"http_{exc.status}" if isinstance(exc, BridgeError) else type(exc).__name__
                        startup_status("registration_failed:"+reason)
                        print(f"[EverSpark] registration attempt {attempts} failed: {reason}", flush=True)
                    time.sleep(3)
                    continue
            authentication = registration.authentication()
            if authentication is None:
                continue
            try:
                task = registration.transport.request("/node/next", authentication)
                if not task:
                    continue
                try:
                    result = execute_once(task, journal=TASK_JOURNAL)
                except (OSError, ValueError, KeyError) as exc:
                    result = {"status": "failed", "output": f"Agent task journal error: {type(exc).__name__}", "exit_code": None}
                while True:
                    try:
                        registration.transport.request("/node/result", {**authentication, "task_id": task["id"], "result": result})
                        break
                    except BridgeError as exc:
                        if exc.status == 409:
                            break
                        if exc.status == 403:
                            registration.invalidate(authentication)
                            break
                        time.sleep(3)
                    except (OSError, ValueError, RuntimeError):
                        time.sleep(3)
            except BridgeError as exc:
                if exc.status == 403:
                    registration.invalidate(authentication)
                time.sleep(3)
            except (OSError, ValueError, KeyError, RuntimeError):
                time.sleep(3)
    finally:
        heartbeat.close()
