import subprocess
from pathlib import Path


def test_operator_poll_does_not_starve_or_invent_a_down_receiver():
    demo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        ["node", "tests/test_operator_poll.js"],
        cwd=demo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "operator poll scheduler ok" in completed.stdout
