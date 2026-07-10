// The draft mirrors the backend's InteractionDraft shape exactly. This slice
// never sets its own fields from user typing - only setDraft (fed by SSE
// 'final' events) and commitDraft (POST /interactions) touch it, because the
// form is chat-controlled only.
import { createAsyncThunk, createSlice } from "@reduxjs/toolkit";
import { commitInteraction } from "../api/client";

const initialState = {
  draft: {},
  followupSuggestions: [],
  committing: false,
  committedId: null,
  commitError: null,
};

export const commitDraft = createAsyncThunk(
  "interaction/commit",
  async (_, { getState, rejectWithValue }) => {
    const { chat } = getState();
    try {
      return await commitInteraction(chat.threadId);
    } catch (err) {
      return rejectWithValue(err.message);
    }
  },
);

const interactionSlice = createSlice({
  name: "interaction",
  initialState,
  reducers: {
    setDraft(state, action) {
      state.draft = action.payload || {};
    },
    setFollowupSuggestions(state, action) {
      state.followupSuggestions = action.payload || [];
    },
    clearCommitError(state) {
      state.commitError = null;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(commitDraft.pending, (state) => {
        state.committing = true;
        state.commitError = null;
      })
      .addCase(commitDraft.fulfilled, (state, action) => {
        state.committing = false;
        state.committedId = action.payload.id;
      })
      .addCase(commitDraft.rejected, (state, action) => {
        state.committing = false;
        state.commitError = action.payload || "Failed to log interaction.";
      });
  },
});

export const { setDraft, setFollowupSuggestions, clearCommitError } = interactionSlice.actions;
export default interactionSlice.reducer;
