import json
import logging
from datetime import datetime
import secrets

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from agent import stream_agent

app = FastAPI(title="Agent API")
logger = logging.getLogger(__name__)


class AgentRequest(BaseModel):
  query: str = Field(min_length=1, max_length=4000)
  auth_token: str = Field(min_length=12, max_length=12)


@app.post("/query")
async def query_agent(request: AgentRequest) -> StreamingResponse:
  expected_token = f"01{datetime.now().strftime('%d%m%Y')}01"
  if not secrets.compare_digest(request.auth_token, expected_token):
    raise HTTPException(status_code=401, detail="Invalid or expired authentication token")

  async def events():
    try:
      async for update in stream_agent(request.query):
        yield (
            f"event: {update['type']}\n"
            f"data: {json.dumps(update, ensure_ascii=False)}\n\n"
        )
    except Exception:
      logger.exception("Agent request failed while streaming")
      error = {
          "type": "error",
          "message": "Agent request failed. Check the server logs for details.",
      }
      yield f"event: error\ndata: {json.dumps(error)}\n\n"

  return StreamingResponse(
      events(),
      media_type="text/event-stream",
      headers={
          "Cache-Control": "no-cache",
          "X-Accel-Buffering": "no",
      },
  )