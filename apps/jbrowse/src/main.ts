import { createApp } from "vue";
import { registerDefaultTrackRenderers } from "@soymutdb/genome-view";
import App from "./App.vue";
import "./index.css";

// Bind the backend track types to their Vue renderers before mounting.
registerDefaultTrackRenderers();

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createApp(App).mount(rootEl);
