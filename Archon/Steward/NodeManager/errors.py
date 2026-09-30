class NodeError(RuntimeError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class NodeTaskError(NodeError):
    def __init__(self, detail, exit_code):
        super().__init__("Node Agent execution failed")
        self.stage, self.detail, self.exit_code = "agent_execution", detail or "No Agent output", exit_code


class NodeRegistrationError(NodeError):
    def __init__(self, node_id):
        super().__init__("Node Agent did not become online before timeout", 504)
        self.stage = "agent_registration"
        self.detail = f"Node {node_id}: inspect Agent registration and heartbeat logs"
