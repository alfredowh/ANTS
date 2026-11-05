from ants.evalkit import runbook


def test_catalog_is_consistent():
    assert runbook.check(runbook.load()) == []


def test_command_defaults_and_overrides():
    data = runbook.load()
    cmd = next(c for c in data["commands"] if c["id"] == "exp04.run")
    default = runbook.command_text(data, cmd, multiline=False)
    assert default.startswith("uv run python -m ants.orchestrator.scene_context_exp")
    assert "--token-budget 900000" in default and "--groups" not in default
    tuned = runbook.command_text(
        data, cmd, {"--groups": True, "--token-budget": False}, {"--groups": "G"}, multiline=False
    )
    assert "--groups G" in tuned and "--token-budget" not in tuned


def test_values_with_spaces_or_json_are_quoted():
    data = runbook.load()
    cmd = next(c for c in data["commands"] if c["id"] == "exp01.run")
    text = runbook.command_text(data, cmd, {"--task": True, "--scale-json": True}, multiline=False)
    assert "--task 'put the bowl on the plate'" in text
    assert "--scale-json '{" in text


def test_todo_block_is_replaced_not_duplicated(tmp_path):
    data = runbook.load()
    todo = tmp_path / "todo.md"
    todo.write_text("# To do\n", encoding="utf-8")
    runbook.write_todo(data, todo)
    runbook.write_todo(data, todo)
    assert todo.read_text(encoding="utf-8").count(runbook.START) == 1


def test_html_embeds_catalog_without_closing_script_tags():
    page = runbook.html(runbook.load())
    assert "/*DATA*/" not in page and "exp04.run" in page
