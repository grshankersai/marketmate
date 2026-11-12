import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


async def create_agent() -> tuple[Any, list[Any], MultiServerMCPClient]:
  alpha_vantage_api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
  openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
  # missing_keys = [
  #     name
  #     for name, value in (
  #         ("ALPHA_VANTAGE_API_KEY", alpha_vantage_api_key),
  #         ("OPENROUTER_API_KEY", openrouter_api_key),
  #     )
  #     if not value
  # ]

  # if missing_keys:
  #   raise RuntimeError(
  #       f"Set the required environment variable(s): {', '.join(missing_keys)}"
  #   )

  # 1. Configure the MCP client pointing to Alpha Vantage's remote server
  client = MultiServerMCPClient({
      "alphavantage": {
          "transport": "http",
          "url": (
              f"https://mcp.alphavantage.co/mcp?apikey={alpha_vantage_api_key}"
          ),
      }
  })

  # 2. Automatically discover and load all tools exposed by the MCP server
  tools = await client.get_tools()
  print(f"Loaded {len(tools)} tools from Alpha Vantage MCP server.")

  # 3. Initialize your LLM
  llm = ChatOpenAI(model="nvidia/nemotron-3.5-lightning:free",
                 api_key=openrouter_api_key,
                 base_url="https://openrouter.ai/api/v1",
                 temperature=0)

  # 4. Create the LangGraph / LangChain agent with the discovered MCP tools
  agent_executor = create_react_agent(llm, tools)
  return agent_executor, tools, client


async def stream_agent(query: str) -> AsyncIterator[dict[str, Any]]:
  yield {"type": "agent_status", "status": "connecting"}
  agent_executor, tools, _client = await create_agent()
  yield {
      "type": "mcp_connected",
      "server": "alphavantage",
      "available_tools": [tool.name for tool in tools],
  }
  yield {"type": "agent_status", "status": "working"}

  seen_calls: set[str] = set()
  completed_calls: set[str] = set()
  pending_calls: dict[str, str] = {}
  final_state: dict[str, Any] | None = None

  async for state in agent_executor.astream(
      {"messages": [{"role": "user", "content": query}]},
      stream_mode="values",
  ):
    final_state = state
    for message in state.get("messages", []):
      if isinstance(message, AIMessage):
        for tool_call in message.tool_calls:
          call_id = tool_call.get("id")
          tool_name = tool_call.get("name")
          if call_id and tool_name and call_id not in seen_calls:
            seen_calls.add(call_id)
            pending_calls[call_id] = tool_name
            yield {
                "type": "tool_started",
                "server": "alphavantage",
                "tool": tool_name,
            }
      elif isinstance(message, ToolMessage):
        call_id = message.tool_call_id
        if call_id and call_id not in completed_calls:
          completed_calls.add(call_id)
          yield {
              "type": "tool_completed",
              "server": "alphavantage",
              "tool": pending_calls.get(call_id, message.name),
              "status": message.status,
          }

  final_message = next(
      (
          message
          for message in reversed(final_state["messages"])
          if isinstance(message, AIMessage) and not message.tool_calls
      ),
      None,
  ) if final_state else None
  if final_message is None:
    raise RuntimeError("The agent completed without a final assistant message")

  messages = []
  for message in final_state["messages"]:
    if isinstance(message, AIMessage) and message.tool_calls:
      messages.append({
          "type": "ai",
          "tool_calls": [
              {"name": tool_call["name"]}
              for tool_call in message.tool_calls
              if tool_call.get("name")
          ],
      })
    elif isinstance(message, ToolMessage):
      messages.append({
          "type": "tool",
          "name": message.name,
          "status": message.status,
      })
    elif message is final_message:
      messages.append({"type": "ai", "content": final_message.content})
    elif message.type == "human":
      messages.append({"type": "human", "content": message.content})

  yield {
      "type": "final_answer",
      "answer": final_message.content,
      "messages": messages,
  }
  yield {"type": "agent_status", "status": "completed"}


async def run_agent(query: str):
  agent_executor, _tools, _client = await create_agent()

  # Invoke the agent with the supplied query
  response = await agent_executor.ainvoke({"messages": [{"role": "user", "content": query}]})

  # Save the complete agent response, including tool calls and results
  response_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "response.txt")
  with open(response_path, "w", encoding="utf-8") as response_file:
    response_file.write(str(response))
  print(f"Full response saved to: {response_path}")

  return response


if __name__ == "__main__":
  sample_query = "What's the latest price and trading volume for Apple (AAPL) stock?"
  print(asyncio.run(run_agent(sample_query))["messages"][-1].content)