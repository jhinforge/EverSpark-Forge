"""Standalone provider-independent Archon Node host and local operator API."""
import argparse
import threading
from pathlib import Path
from .manager import NodeManager
from .transport.operator import OperatorServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--operator-port", type=int, default=8765)
    parser.add_argument("--state", type=Path, default=Path.home()/".everspark"/"nodes.json")
    args = parser.parse_args()
    manager = NodeManager(args.host, args.port, state_path=args.state)
    operator = None
    try:
        operator = OperatorServer(("127.0.0.1", args.operator_port), manager)
        manager.start()
        threading.Thread(target=operator.serve_forever, daemon=True).start()
        print(f"Node listener: {manager.url}; operator: http://127.0.0.1:{operator.server_port}", flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        if operator:
            operator.shutdown()
            operator.server_close()
        manager.close()


if __name__ == "__main__":
    main()
