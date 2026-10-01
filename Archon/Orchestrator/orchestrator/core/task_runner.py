"""Coordinate Forge steps without resolving their internal resources."""
from Aegis.Shared.errors import TaskError

class TaskRunner:
    def __init__(self, concept, image):
        self.concept = concept
        self.image = image

    def run(self, user_text, session_id, selection=None, notify=None):
        # The context belongs to Concept Forge; only its opaque instruction and
        # result callback cross this boundary. Legacy options are forwarded intact.
        with self.concept.prepare_generation(user_text, session_id, selection or {},
                                             notify or (lambda _message: None)) as prepared:
            result = self.image.generate(prepared.instruction, selection,
                                         notify or (lambda _message: None))
            return prepared.complete(result)
