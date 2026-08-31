import json
import sys
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from run_experiment_matrix import completed, job_command, load_matrix


def test_matrix_runner_validates_and_uses_current_python(tmp_path):
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps({"jobs": [{
        "job_id": "job-1",
        "command": ["python", "project/run_humaneval.py", "--limit", "1"],
    }]}), encoding="utf-8")

    job = load_matrix(path)[0]
    command = job_command(job, tmp_path / "job-1")

    assert command[0] == sys.executable
    assert command[-2:] == ["--output-dir", str(tmp_path / "job-1")]


def test_matrix_runner_resume_requires_completed_manifest(tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "manifest.json").write_text('{"completed": false}', encoding="utf-8")
    assert not completed(job_dir)
    (job_dir / "manifest.json").write_text('{"completed": true}', encoding="utf-8")
    assert completed(job_dir)


def test_matrix_runner_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps({"jobs": [
        {"job_id": "same", "command": ["python", "x"]},
        {"job_id": "same", "command": ["python", "x"]},
    ]}), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_matrix(path)

