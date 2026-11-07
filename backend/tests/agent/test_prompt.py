from app.agent.prompt import AUDIENCE_DEV, AUDIENCE_PM, build_system_prompt


def test_system_prompt_tells_the_model_tool_results_are_data_not_instructions():
    # Tool results now include content from arbitrary scanned (often third-party)
    # code — a crafted comment/README could otherwise look like an instruction to
    # a model with no guard against that.
    prompt = build_system_prompt(AUDIENCE_DEV)
    assert "instructions to follow" in prompt


def test_system_prompt_still_carries_the_audience_instructions():
    assert "product manager" in build_system_prompt(AUDIENCE_PM)
    assert "developer" in build_system_prompt(AUDIENCE_DEV)
