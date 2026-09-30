"""Stop a deployment command group if its owning Agent disappears."""
import os
import signal
import subprocess
import sys


def run(parent, args):
    child = subprocess.Popen(args)
    while True:
        # Parent identity is checked before and after each short wait. No daemon
        # command continues downloading/installing after its Agent has died.
        if os.getppid() != parent:
            os.killpg(os.getpgrp(), signal.SIGKILL)
        try:
            return child.wait(timeout=.25)
        except subprocess.TimeoutExpired:
            pass


if __name__ == "__main__":
    sys.exit(run(int(sys.argv[1]), sys.argv[2:]))
