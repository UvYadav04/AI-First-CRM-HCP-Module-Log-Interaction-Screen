// Orchestrates one chat turn: send the message, consume the SSE stream, and
// fan updates out to both slices (chat transcript + form draft). A plain
// thunk rather than createAsyncThunk since the result arrives as a stream
// of events, not one resolved value.
import { streamChat } from "../api/client";
import { addUserMessage, appendToken, finalizeStream, setError, setStatus, startAssistantStream } from "./chatSlice";
import { setDraft, setFollowupSuggestions } from "./interactionSlice";

export const sendMessage = (text) => async (dispatch, getState) => {
  const trimmed = text.trim();
  if (!trimmed) return;

  dispatch(addUserMessage(trimmed));
  dispatch(setStatus("thinking"));

  const { chat } = getState();
  let streamStarted = false;

  try {
    await streamChat({
      threadId: chat.threadId,
      message: trimmed,
      onEvent: ({ event, data }) => {
        if (event === "token") {
          if (!streamStarted) {
            dispatch(startAssistantStream());
            dispatch(setStatus("streaming"));
            streamStarted = true;
          }
          dispatch(appendToken(data));
        } else if (event === "final") {
          const payload = JSON.parse(data);
          dispatch(setDraft(payload.draft));
          const followup = (payload.tool_results || []).find((r) => r.tool === "suggest_followup" && r.ok);
          if (followup?.data) dispatch(setFollowupSuggestions(followup.data));
          dispatch(finalizeStream());
        } else if (event === "error") {
          dispatch(setError(data));
        } else if (event === "status" && data === "done") {
          dispatch(setStatus("idle"));
        }
      },
    });
  } catch (err) {
    dispatch(setError(`Couldn't reach the assistant: ${err.message}. Please try again.`));
  }
};
