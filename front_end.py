import json
import os
from datetime import datetime
from typing import Any, Iterator

import requests
import streamlit as st


st.set_page_config(
    page_title="MarketMate | AI Assistant",
    page_icon="📈",
    layout="centered",
)

st.markdown(
    """
    <style>
      .stApp {
        background:
          radial-gradient(ellipse at 12% 0%, rgba(32, 116, 130, .18), transparent 34%),
          linear-gradient(160deg, #0b1118 0%, #101923 55%, #0c141c 100%);
        color: #edf4f5;
      }
      [data-testid="stHeader"] { background: transparent; }
      .hero {
        padding: 1.4rem 1.6rem;
        margin: .4rem 0 1.5rem;
        border: 1px solid rgba(147, 205, 194, .18);
        border-radius: 22px;
        background: linear-gradient(115deg, rgba(28, 62, 69, .72), rgba(20, 32, 43, .82));
        box-shadow: 0 18px 55px rgba(0, 0, 0, .18);
      }
      .hero-kicker {
        color: #78d7c1;
        font-size: .76rem;
        font-weight: 700;
        letter-spacing: .16em;
        text-transform: uppercase;
      }
      .hero h1 {
        margin: .45rem 0 .25rem;
        color: #f3fbfa;
        font-size: clamp(2rem, 5vw, 2.8rem);
        letter-spacing: -.045em;
      }
      .hero p { margin: 0; color: #a9bdc2; }
      [data-testid="stChatMessage"] {
        border: 1px solid rgba(147, 205, 194, .1);
        border-radius: 18px;
        background: rgba(18, 30, 40, .78);
      }
      [data-testid="stChatInput"] {
        border-color: rgba(120, 215, 193, .3);
      }
      div[data-testid="stStatusWidget"] {
        border: 1px solid rgba(120, 215, 193, .18);
        border-radius: 14px;
        background: rgba(16, 29, 38, .68);
      }
      .stCaption { color: #98adb2; }
    </style>
    """,
    unsafe_allow_html=True,
)


def parse_sse(response: requests.Response) -> Iterator[tuple[str, dict[str, Any]]]:
  event_name = "message"
  data_lines: list[str] = []

  for line in response.iter_lines(decode_unicode=True):
    if line is None:
      continue
    if isinstance(line, bytes):
      line = line.decode("utf-8")

    if not line:
      if data_lines:
        payload = json.loads("\n".join(data_lines))
        if not isinstance(payload, dict):
          raise ValueError("The server returned an invalid SSE data payload")
        yield event_name, payload
      event_name = "message"
      data_lines = []
      continue

    if line.startswith(":"):
      continue
    field, separator, value = line.partition(":")
    if not separator:
      value = ""
    elif value.startswith(" "):
      value = value[1:]
    if field == "event":
      event_name = value
    elif field == "data":
      data_lines.append(value)

  if data_lines:
    payload = json.loads("\n".join(data_lines))
    if not isinstance(payload, dict):
      raise ValueError("The server returned an invalid SSE data payload")
    yield event_name, payload


def describe_update(event_name: str, data: dict[str, Any]) -> str:
  if event_name == "agent_status":
    status = data.get("status", "working")
    return {
        "connecting": "Connecting to the agent and its MCP tools…",
        "working": "The agent is working on your request…",
        "completed": "Request complete.",
    }.get(status, f"Agent status: {status}")
  if event_name == "mcp_connected":
    tools = data.get("available_tools", [])
    server = data.get("server", "MCP server")
    tool_names = ", ".join(f"`{name}`" for name in tools[:8])
    remainder = f", and {len(tools) - 8} more" if len(tools) > 8 else ""
    tool_summary = f": {tool_names}{remainder}" if tool_names else ""
    return f"Connected to **{server}** · {len(tools)} tools available{tool_summary}"
  if event_name == "tool_started":
    return f"Calling **{data.get('tool', 'tool')}** on `{data.get('server', 'MCP')}`…"
  if event_name == "tool_completed":
    return f"**{data.get('tool', 'Tool')}** finished ({data.get('status', 'complete')})."
  if event_name == "error":
    return f"Request failed: {data.get('message', 'Unknown server error')}"
  return f"Received update: {event_name}"


if "messages" not in st.session_state:
  st.session_state.messages = []

st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Live AI Agent · Connected to MCP Server</div>
      <h1>Stock Market Mate</h1>
      <p>Ask a Stock Market (preferably US Stocks) related question and follow your AI agent as it works.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# with st.sidebar:
#   st.markdown("### Connection")
#   api_url = st.text_input(
#       "Agent API URL",
#       value=os.getenv("AGENT_API_URL", "http://127.0.0.1:8000/query"),
#       help="The FastAPI POST endpoint that streams Server-Sent Events.",
#   )
#   today_token = f"01{datetime.now().strftime('%d%m%Y')}01"
#   auth_token = st.text_input(
#       "Today's authentication token",
#       value=today_token,
#       type="password",
#   )
#   st.caption("Keep your API server running while chatting.")

# for item in st.session_state.messages:
#   with st.chat_message(item["role"]):
#     st.markdown(item["content"])
#     if item["role"] == "assistant" and item.get("messages"):
#       with st.expander("Run details"):
#         st.json(item["messages"])

query = st.chat_input("Ask about a ticker, market data, or a finance topic…")
if query:
  st.session_state.messages.append({"role": "user", "content": query})
  with st.chat_message("user"):
    st.markdown(query)

  with st.chat_message("assistant"):
    progress = st.status("Starting your request…", expanded=True)
    answer_placeholder = st.empty()
    answer = None
    messages = []
    try:
      
      api_url = "http://127.0.0.1:8000/query"
      auth_token = f"01{datetime.now().strftime('%d%m%Y')}01"

      with requests.post(
          api_url,
          json={"query": query, "auth_token": auth_token},
          headers={"Accept": "text/event-stream"},
          stream=True,
          timeout=(10, 300),
      ) as response:
        if not response.ok:
          detail = response.text.strip()
          raise RuntimeError(
              f"API returned HTTP {response.status_code}"
              + (f": {detail}" if detail else "")
          )
        response.encoding = "utf-8"
        for event_name, data in parse_sse(response):
          if event_name == "final_answer":
            answer = data.get("answer", "")
            messages = data.get("messages", [])
            progress.write("Final answer received.")
          else:
            progress.write(describe_update(event_name, data))
            if event_name == "error":
              raise RuntimeError(data.get("message", "The agent request failed"))

      if answer is None:
        raise RuntimeError("The stream ended before the agent sent a final answer")

      progress.update(label="Request complete", state="complete", expanded=False)
      answer_placeholder.markdown(answer or "_The agent returned an empty answer._")
      st.session_state.messages.append({
          "role": "assistant",
          "content": answer,
          "messages": messages,
      })
      if messages:
        with st.expander("Run details"):
          st.json(messages)
    except (requests.RequestException, ValueError, RuntimeError) as error:
      progress.update(label="Request failed", state="error", expanded=True)
      st.error(str(error))
      st.session_state.messages.append({
          "role": "assistant",
          "content": f"Sorry, I couldn't complete that request: {error}",
      })
