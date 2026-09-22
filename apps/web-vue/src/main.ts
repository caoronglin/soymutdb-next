import { createApp } from "vue";
import App from "./App.vue";

// Checkpoint-A bootstrap: mount the portal shell. The site variant is injected
// at build time (vite define), never inferred at runtime.
createApp(App).mount("#app");
