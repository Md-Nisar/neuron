import os, json
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool

@tool
def calculator(expression: str) -> str:
    """Evaluate an arithmetic expression."""
    return "391"

m = ChatOpenAI(model=os.environ["LLM_MODEL"], base_url=os.environ["LLM_BASE_URL"], api_key=os.environ["LLM_API_KEY"], max_retries=0, timeout=170)
for label, model in (("auto", m.bind_tools([calculator])), ("required", m.bind_tools([calculator], tool_choice="required"))):
    r = model.invoke("Use the calculator tool: what is 17 * 23?")
    print(label, "| tool_calls:", r.tool_calls, "| content:", repr(r.content)[:200], "| extra:", list(r.additional_kwargs))
