# E_coder Vue frontend

Vue 3 + Composition API + Vite. Backend API contracts, SQLite data and approval rules are unchanged. UI state is rendered by Vue single-file components, with no imperative legacy page renderer.

## Run

The built frontend is committed under `../static/vue/assets/`, and `../static/index.html` points to that build. Start the backend normally with `../start.ps1`; no Node process is required for daily use.

For frontend development (Node.js >=22.12):

```powershell
cd frontend
npm ci
npm run dev
```

Start the backend on port 8765, then open http://127.0.0.1:5173/static/vue/ . Vite proxies `/api` and existing local images/fonts. It preserves Host and Origin together, so backend cross-origin write checks remain active. The dev server is restricted to the local loopback address.

```powershell
npm test
npm run build
npm run deploy
```

Deploy copies hashed assets before switching the index file, and keeps older hashed bundles for already-open tabs. All dependencies are project-local in `node_modules`; no global installation is needed. Lockfile is included. API credentials must stay server-side; never add a key to `VITE_*` variables.

## Structure

- `App.vue`: page selection and shared shell.
- `composables/useWorkbench.js`: session lifecycle, SSE reconnection/deduplication, drafts, uploads, folder binding, approvals and cleanup reconciliation. Cancels obsolete session/file responses.
- `components/ChatWorkspace.vue`: chat, composer, approvals, drag/paste attachments and native folder picker.
- `components/ExecutionPanel.vue`, `TimelineRecords.vue`: round summaries, tasks, files, context, model-call and token totals.
- `components/LibraryPage.vue`, `LibraryDetails.vue`: tools, Skills, parameters, Markdown guide, runtime and resource tabs.
- `components/SettingsPage.vue`: model configuration, in-memory secret draft cleared after save/unmount.
- `components/StoragePage.vue`: lazy-loaded inventory, filtering, pagination, selection and explicit permanent cleanup confirmation.
- `components/BaseDialog.vue`: native modal focus management, Escape and backdrop dismissal.
- `components/MarkdownText.vue`: bundled Marked + DOMPurify; allowlisted HTML, link schemes and disabled task-list inputs.
- `lib/timeline.js`, `lib/usage.js`: pure event aggregation; cumulative token snapshots are not repeatedly added.

The original white theme, compact cards/header, stable scrollbar gutter, local fonts and SVG assets are preserved. Only the latest message is auto-scrolled when the user is near the bottom; reading older content does not force a jump.

## Verification

Vitest tests cover SSE deduplication and replay, cumulative token snapshots, stale-session races, stream cleanup, duplicate run submission, failed-run draft retention, approval restoration, folder references, removed attachment reconciliation, Markdown sanitization, modal cancellation, stale Skill responses, configuration credential handling and signed cleanup confirmation.

Tests use mocked network responses; no model call or real storage deletion is performed.
