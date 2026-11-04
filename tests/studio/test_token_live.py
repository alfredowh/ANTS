"""The in-flight part of the token tracker stays separate from real counts."""

from ants.studio.token_live import InFlight


def stage(name, status, **extra):
    return {"kind": "pipeline_stage", "stage": name, "status": status, **extra}


def test_nothing_running_means_nothing_to_show():
    assert InFlight().snapshot() is None


def test_first_generation_knows_only_its_prompt_size():
    live = InFlight()
    live.observe(stage("prompt", "done", chars=4000))
    live.observe(stage("generate", "started"))
    snap = live.snapshot()
    assert snap["approx_input_tokens"] == 1000
    assert "approx_output_tokens" not in snap
    live.observe(stage("generate", "done"))
    assert live.snapshot() is None


def test_a_repair_has_no_invented_size_only_a_clock():
    live = InFlight()
    live.observe(stage("prompt", "done", chars=4000))
    live.observe(stage("generate", "started"))
    live.observe(stage("generate", "done"))
    live.observe(stage("generate", "started"))
    started = live._call["started"]
    snap = live.snapshot(now=started + 83)
    assert snap["elapsed_s"] == 83
    assert "approx_input_tokens" not in snap


def test_rewrite_and_stop():
    live = InFlight()
    live.observe(stage("rewrite", "started"))
    assert live.snapshot()["label"] == "Muse Wonder rewriting"
    live.observe({"kind": "stop_requested"})
    assert live.snapshot() is None


def test_chat_counts_streamed_text_until_it_ends():
    live = InFlight()
    delta = {"payload_type": "run.output.delta", "payload": {"text": "x" * 40}}
    live.observe({"kind": "chat_muse_event", "event": delta})
    live.observe({"kind": "chat_muse_event", "event": delta})
    assert live.snapshot()["approx_output_tokens"] == 20
    live.observe({"kind": "chat_done"})
    assert live.snapshot() is None
