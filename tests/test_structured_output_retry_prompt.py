from runner.agent.prompts import structured_output_retry_prompt


def test_structured_output_retry_prompt_substitutes_parser_error():
    prompt = structured_output_retry_prompt("tasks must contain at least 1 items")
    assert "Parser feedback: tasks must contain at least 1 items" in prompt
    assert "{error}" not in prompt
