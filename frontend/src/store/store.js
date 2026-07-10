import { configureStore } from "@reduxjs/toolkit";
import chatReducer from "./chatSlice";
import interactionReducer from "./interactionSlice";

export const store = configureStore({
  reducer: {
    chat: chatReducer,
    interaction: interactionReducer,
  },
});
