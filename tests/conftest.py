import os
import sys
from pathlib import Path

# Make the agent modules importable, and make sure tests never need real API keys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "data_incident_investigator_agent"))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")
