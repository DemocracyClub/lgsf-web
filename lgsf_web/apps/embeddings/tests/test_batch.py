"""--remote and --manifest, without AWS: uploads and jobs are faked."""

import io
import json

import pytest
from django.core.management import CommandError, call_command
from embeddings import batch
from embeddings.tasks import read_manifest


def test_an_array_job_for_several_shards():
    request = batch.job_request(
        "run-1", "s3://bucket/runs/run-1/", 3, "queue", "definition", []
    )
    assert request["arrayProperties"] == {"size": 3}
    assert request["jobQueue"] == "queue"
    assert request["jobDefinition"] == "definition"
    assert request["containerOverrides"]["command"] == [
        "python",
        "manage.py",
        "embed_documents",
        "--manifest",
        "s3://bucket/runs/run-1/",
        "--source",
        "s3",
    ]


def test_a_plain_job_for_one_shard():
    # Batch's smallest array job is 2.
    request = batch.job_request("run-1", "s3://b/r/", 1, "q", "d", ["--force"])
    assert "arrayProperties" not in request
    assert request["containerOverrides"]["command"][-1] == "--force"


def test_array_index(monkeypatch):
    monkeypatch.delenv("AWS_BATCH_JOB_ARRAY_INDEX", raising=False)
    assert batch.array_index() == 0
    monkeypatch.setenv("AWS_BATCH_JOB_ARRAY_INDEX", "7")
    assert batch.array_index() == 7


def test_remote_dry_run(documents_on_disk, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    out = io.StringIO()
    call_command(
        "embed_documents",
        "--remote",
        "--shards",
        "2",
        "--dry-run",
        "--workers",
        "2",
        stdout=out,
    )
    output = out.getvalue()
    assert output.startswith("3 files in 2 shards (2, 1)")
    [directory] = tmp_path.glob("embedding-run-*")
    assert sorted(p.name for p in directory.iterdir()) == [
        "run.json",
        "shard-00000.jsonl",
        "shard-00001.jsonl",
    ]
    tasks = read_manifest(str(directory), 0) + read_manifest(str(directory), 1)
    assert sorted(t.content_hash for t in tasks) == ["aaa", "bbb", "ccc"]
    request = json.loads(output.split("Would submit:\n")[1])
    command = request["containerOverrides"]["command"]
    assert command[command.index("--workers") + 1] == "2"
    assert request["arrayProperties"] == {"size": 2}


def test_remote(documents_on_disk, tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    uploaded = []
    submitted = []
    monkeypatch.setattr(
        batch,
        "upload_manifest",
        lambda directory, bucket, prefix, run_id: uploaded.append(
            (bucket, prefix, run_id)
        ),
    )
    monkeypatch.setattr(
        batch, "submit_job", lambda request: submitted.append(request) or "j-1"
    )
    out = io.StringIO()
    call_command("embed_documents", "MAN", "--remote", stdout=out)
    [(bucket, prefix, run_id)] = uploaded
    assert (bucket, prefix) == ("lgsf-data-archive", "embedding-runs/")
    [request] = submitted
    assert request["jobName"] == f"embed-documents-{run_id}"
    assert "arrayProperties" not in request
    assert "Submitted job j-1" in out.getvalue()


def test_remote_with_a_manifest():
    with pytest.raises(CommandError, match="can't be used together"):
        call_command("embed_documents", "--remote", "--manifest", "x")


def test_a_manifest_shard_is_chosen_by_the_array_index(
    documents_on_disk,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    call_command(
        "embed_documents",
        "--remote",
        "--shards",
        "2",
        "--dry-run",
        stdout=io.StringIO(),
    )
    [directory] = tmp_path.glob("embedding-run-*")
    monkeypatch.setenv("AWS_BATCH_JOB_ARRAY_INDEX", "1")
    out = io.StringIO()
    call_command(
        "embed_documents", "--manifest", str(directory), "--dry-run", stdout=out
    )
    assert out.getvalue().startswith("1 documents, in 1 files")
