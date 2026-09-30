"""Optional NVIDIA fingerprint; failures never fabricate available VRAM."""
import csv
import io
import subprocess


def sample():
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=uuid,name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=5, check=True)
        return [{"id": row[0].strip(), "name": row[1].strip(),
                 "vram": int(row[2].strip())*1024**2, "free_vram": int(row[3].strip())*1024**2}
                for row in csv.reader(io.StringIO(done.stdout)) if len(row) == 4]
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
