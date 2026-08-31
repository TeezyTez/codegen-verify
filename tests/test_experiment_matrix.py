import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "project"))

from build_experiment_matrix import build_jobs


def test_experiment_jobs_are_paired_and_cover_the_last_partial_shard():
    jobs = build_jobs(
        conditions=["direct_1", "spec_guided"],
        seeds=[0, 1],
        total_tasks=21,
        shard_size=10,
        rounds=3,
        supported_only=True,
    )

    assert len(jobs) == 12
    assert {job["limit"] for job in jobs if job["start"] == 20} == {1}
    assert all(job["rounds"] == 0 for job in jobs if job["condition_id"] == "direct_1")
    assert len({job["job_id"] for job in jobs}) == len(jobs)
    assert all("--max-model-calls" in job["command"] for job in jobs)
    assert all(job["budget"]["max_candidates"] == 8 for job in jobs)
    assert all(job["command"][-1] == "--supported-only" for job in jobs)
