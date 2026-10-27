# ClipFlow — Detailed Implementation Plan & UI Specification

**Product design:** Positivus-inspired  
**Platform:** Responsive web application  
**Theme:** Light and dark modes  
**Scope:** Full application with real authorized downloading  
**Layout:** Spacious cards, rounded geometry, strong typography

Reference design: [Positivus Landing Page — Figma Community](https://www.figma.com/community/file/1230604708032389430/positivus-landing-page-design)

> ClipFlow is a working name. The goal is to preserve the reference's bold typography, lime-green accents, outlined cards, rounded geometry, and spacious layouts while building a real download-management application.

Downloads must be limited to content the user owns, has permission to download, or is otherwise authorized to access, using a source and method that permit downloading. Do not bypass DRM or other technical access restrictions.

## 1. Product definition

### Core user journey

1. Paste a supported video URL.
2. Validate the URL and inspect available metadata.
3. Display a video preview and permitted formats.
4. Choose quality, format, and download destination.
5. Submit a download job to the backend.
6. Track progress; pause or cancel where supported.
7. Access completed files and previous download records.

### MVP priorities

- A working download flow
- Reliable progress reporting
- Useful error messages
- Responsive design
- Persistent job history

Authentication, analytics, and advanced preferences can come later.

## 2. Visual design specification

### Color tokens

| Token | Light theme | Dark theme |
|---|---|---|
| Page background | `#F5F5F0` | `#111218` |
| Card surface | `#FFFFFF` | `#191A23` |
| Primary text | `#191A23` | `#F5F5F0` |
| Secondary text | `#666666` | `#B6B6C2` |
| Accent | `#B9FF66` | `#B9FF66` |
| Border | `#191A23` | `#454650` |

Keep the lime accent consistent in both themes. Use semantic design tokens for surfaces, text, borders, and focus states rather than styling every component separately.

### Component tokens

| Property | Specification |
|---|---|
| Headings | Space Grotesk or similar geometric sans-serif |
| UI/body text | Inter or similar readable sans-serif |
| Page title | 30–36px desktop; 26–30px mobile |
| Body text | 14–16px |
| Main cards | 20–24px radius |
| Inputs | 12–16px radius; minimum 48px height |
| Buttons | 48px primary action height |
| Borders | 1px solid theme border token |
| Shadows | Subtle offset charcoal shadows on featured light-theme cards |
| Spacing | 4px base unit; primarily 16, 24, 32, and 40px |
| Icons | Lucide React, consistently sized around 18–22px |
| Animation | Restrained 150–220ms transitions |

Use dark borders and offset shadows selectively in light mode. In dark mode, prefer lower-contrast borders and restrained shadows.

## 3. Navigation and page structure

Use a desktop sidebar around 240px wide and a compact top bar. Set a maximum readable content width of approximately 1440px, with 24–32px page padding.

| Page | Priority | Purpose |
|---|---|---|
| Overview | P1 | Dashboard, primary URL input, summary metrics, recent activity |
| Downloads | P1 | Active jobs, queue management, progress and task controls |
| History | P1 | Completed and failed jobs, search and filters |
| Files | P2 | Output file listing and safe file actions |
| Settings | P2 | Appearance, format defaults, storage and queue preferences |
| Help | P3 | Supported sources, errors, troubleshooting and app information |

## 4. Page specifications

### 4.1 Overview

**Purpose:** Make the primary download action obvious and show current activity at a glance.

**Layout:**
- Greeting and concise page title, such as “Download Studio.”
- Prominent URL input with paste and clear actions.
- Analyze button with a loading state.
- Four summary cards: active, completed, failed, and total.
- Active download preview with progress.
- Recent downloads list.
- Quick links to Downloads and History.

Keep the URL form as the strongest visual element. Summary cards should remain secondary.

**States:** idle, validating, analyzing, ready, error, and unavailable.

### 4.2 Downloads

**Purpose:** Manage jobs currently queued or being processed.

**UI requirements:**
- Filters for all, active, queued, completed, and failed jobs.
- Search by video title.
- Job cards with thumbnail, title, format, estimated size, status, and progress.
- Speed and estimated time remaining when available.
- Pause/resume only when the engine supports it.
- Cancel with confirmation when appropriate.
- Retry eligible failures without creating duplicate jobs.
- Empty state when no jobs exist.
- Configurable concurrency limit.

Do not fabricate progress. If the engine cannot report a meaningful percentage, show an indeterminate progress indicator.

### 4.3 History

Use a searchable list or table on desktop, converting rows to cards on mobile.

| Column | Information |
|---|---|
| Video | Thumbnail and title |
| Format | Container and resolution/audio format |
| File size | Final size when known |
| Date | Completion time |
| Status | Completed or failed |
| Actions | Open, reveal, retry, remove record |

Provide filters for status, date range, and format. Bulk actions can be deferred.

**Important:** Deleting a history record must not silently delete the actual output file. Treat record removal and file deletion as separate actions.

### 4.4 Files

- Searchable file list
- Name, format, size, and modified date
- Open file and reveal in destination folder when supported
- Copy file path where appropriate
- Delete with confirmation
- Clear messaging when a file has moved or disappeared

A hosted browser app cannot freely access arbitrary folders on the user's computer. File opening and revealing may require a local companion service; a hosted app should instead use browser downloads or explicitly configured storage.

### 4.5 Settings

Organize preferences into sections:

- **Appearance:** light, dark, or system theme.
- **Downloads:** default format and quality.
- **Storage:** destination, available space, and cleanup options.
- **Queue:** concurrent jobs and behavior after errors.
- **Privacy:** history retention and local data clearing.
- **About:** app version, supported sources, and troubleshooting.

Persist preferences in the backend or browser storage as appropriate. Never store secrets or credentials in frontend local storage.

## 5. Video analysis and format selection

The video preview is the second most important screen after Overview.

### Preview fields

- Thumbnail
- Video title
- Channel or source name, if available
- Duration, if available
- Available formats and quality options
- Estimated file size, when the engine provides a reasonable estimate
- Destination selection
- Primary “Add to downloads” action

### Interaction requirements

1. Validate the URL before calling the metadata service.
2. Show loading skeletons while metadata is retrieved.
3. Display real title, thumbnail, duration, and available formats.
4. Explain unsupported, restricted, or inaccessible content.
5. Let the user select an available format and destination.
6. Show estimated size only when available and reasonably reliable.
7. Create a job only after the user confirms.
8. Confirm job creation and link to the queue.

Never infer format availability solely from the video's advertised resolution. Format options must come from real metadata.

## 6. Technical architecture

Keep the frontend, download engine, and job state separate. The frontend must never pretend a download is running simply by animating a progress bar.

### Recommended stack

| Layer | Recommendation | Reason |
|---|---|---|
| Frontend | React, TypeScript, Vite | Fast development and clear component structure |
| Styling | Tailwind CSS | Design tokens and responsive layouts |
| Icons | Lucide React | Consistent line-icon language |
| Routing | React Router | Separate dashboard pages |
| Server state | TanStack Query | API caching, mutations, and invalidation |
| Backend | Python + FastAPI | Clear API contracts and worker integration |
| Database | SQLite initially; PostgreSQL for multi-user deployment | Persistent jobs and history |
| Queue | Database-backed worker initially; Redis + RQ/Celery if needed | Background processing |
| Progress updates | Server-Sent Events (SSE) | Stream job updates to the browser |
| Validation | Pydantic backend; Zod frontend | Validate at both boundaries |
| Testing | Vitest, React Testing Library, Playwright, pytest | Unit, integration, and end-to-end tests |

This is a proposed stack, not a requirement to use every library. For a single-user local app, SQLite and a simple background worker can be enough. Add Redis, PostgreSQL, and distributed processing only when the workload requires them.

### API contract

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/metadata` | Validate a URL and retrieve permitted metadata |
| `GET /api/v1/formats` | Retrieve available formats for a validated media item |
| `POST /api/v1/jobs` | Create a download job |
| `GET /api/v1/jobs` | List jobs with pagination and filters |
| `GET /api/v1/jobs/{id}` | Retrieve current status for a job |
| `POST /api/v1/jobs/{id}/cancel` | Request cancellation |
| `POST /api/v1/jobs/{id}/pause` | Request pause where supported |
| `POST /api/v1/jobs/{id}/resume` | Resume where supported |
| `GET /api/v1/jobs/{id}/events` | Stream progress/status using SSE |
| `GET /api/v1/history` | Retrieve historical job records |
| `DELETE /api/v1/history/{id}` | Remove a history record |

For file access, add a separately authorized download endpoint or local-file integration appropriate to the deployment model.

### Job state model

Suggested states:

- `queued`
- `validating`
- `preparing`
- `downloading`
- `processing`
- `completed`
- `failed`
- `cancellation_requested`
- `cancelled`
- `paused` (only if supported)

A job should include a stable ID, normalized source URL, selected format, status, progress when available, output metadata, timestamps, and a safe error code. Enforce valid state transitions on the backend, make retries idempotent where practical, and clean up partial output after cancellation or failure.

### Deployment model decision

A hosted backend cannot automatically write to an arbitrary folder on a user's computer. Choose one of these models explicitly:

1. **Hosted web app:** Server processes jobs; browser receives completed files through an authorized download response.
2. **Local web app:** A local service manages the user's output directory with strict local-access controls.
3. **Hybrid:** Hosted UI connects to an authenticated local companion.

For a first version intended for one Windows laptop, a local service can be simpler than a full cloud-storage system.

Downloading must respect applicable terms, copyright permissions, and access restrictions. Prefer official download mechanisms or sources that expressly authorize the intended operation. Do not build around circumventing DRM or technical restrictions.

## 7. Reusable component inventory

Build the shared design system before implementing every page.

| Component | Responsibility |
|---|---|
| `AppShell` | Shared layout and page container |
| `Sidebar` | Desktop navigation and active route |
| `Topbar` | Search, theme switch, and actions |
| `MobileNavigation` | Compact mobile navigation |
| `PageHeader` | Page title, subtitle, and actions |
| `Card` | Standard outlined surface |
| `StatCard` | Summary metrics |
| `UrlInput` | URL entry, validation, and paste action |
| `VideoPreview` | Metadata and thumbnail |
| `FormatSelector` | Available formats and quality |
| `DownloadJobCard` | Job details and available controls |
| `ProgressBar` | Real progress or indeterminate state |
| `StatusBadge` | Consistent job-state labels |
| `EmptyState` | No jobs, history, or search results |
| `ErrorState` | Recoverable and terminal errors |
| `ConfirmDialog` | Cancellation and destructive actions |
| `Toast` | Brief success/failure feedback |
| `Skeleton` | Loading placeholders |
| `ThemeProvider` | Theme selection and persistence |

Keep business logic in hooks and service modules rather than embedding it directly in UI components. For example, `useDownloadJobs()` should manage queries and mutations, while `DownloadJobCard` focuses on rendering a job.

## 8. Responsive behavior

| Breakpoint | Behavior |
|---|---|
| Desktop: 1024px and above | Persistent sidebar, spacious cards, two-column dashboard sections |
| Tablet: 768–1023px | Collapsible sidebar, reduced gutters, columns only when readable |
| Mobile: below 768px | Single-column content, compact header, mobile navigation, full-width primary actions |

Responsive rules:

- Avoid horizontal scrolling in the main dashboard.
- Convert tables into stacked cards on narrow screens.
- Allow long titles and URLs to wrap safely.
- Use touch targets around 44px or larger.
- Keep the primary URL input and action easy to reach.
- Respect keyboard focus, reduced-motion preferences, and accessible contrast.
- Test at 360px, 390px, 768px, 1024px, and 1440px widths.

## 9. Interaction and error-state specification

| Situation | Expected response |
|---|---|
| Empty URL | Disable analyze or show helpful validation |
| Invalid URL | Explain the problem beside the input |
| Unsupported source | Explain that the source is unsupported |
| Metadata loading | Show skeletons; prevent duplicate submissions |
| No formats available | Explain that no supported option is available |
| Job submitted | Confirm and link to the queue |
| Waiting in queue | Show queued status and position if known |
| Downloading | Update progress only from real engine events |
| Progress unavailable | Show indeterminate progress, not a fabricated percentage |
| Job paused | Show paused state and resume action if supported |
| Job completed | Offer file action and update history |
| Job failed | Show concise reason and eligible retry action |
| Server unavailable | Preserve form data and offer retry |
| File missing | Explain that the file cannot be found and refresh the record |
| Cancel requested | Distinguish request from confirmed cancellation |

Use toasts for small confirmations, inline messages for form validation, and dialogs for destructive actions. Every loading state must have a success, failure, or timeout outcome.

## 10. Suggested project structure

```text
clipflow/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── App.tsx
│   │   │   └── router.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   ├── ui/
│   │   │   ├── downloader/
│   │   │   └── jobs/
│   │   ├── pages/
│   │   │   ├── Overview.tsx
│   │   │   ├── Downloads.tsx
│   │   │   ├── History.tsx
│   │   │   ├── Files.tsx
│   │   │   └── Settings.tsx
│   │   ├── hooks/
│   │   ├── services/
│   │   ├── types/
│   │   ├── styles/
│   │   └── main.tsx
│   └── tests/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   ├── workers/
│   │   ├── storage/
│   │   └── main.py
│   ├── migrations/
│   └── tests/
├── docs/
│   ├── design-system.md
│   ├── api-contract.md
│   └── setup.md
├── .env.example
├── .gitignore
└── README.md
```

Do not add authentication, a distributed queue, or complex deployment infrastructure until the core use case needs it. Even a single-user app needs server-side validation and careful control over which URLs and files its backend can access.

## 11. Phased implementation checklist

### Phase 1 — Foundation

- [ ] Initialize frontend and backend projects.
- [ ] Define color, spacing, and typography tokens.
- [ ] Implement light/dark theme switching.
- [ ] Build `AppShell`, sidebar, and responsive header.
- [ ] Create shared buttons, cards, badges, and dialogs.

### Phase 2 — Dashboard UI

- [ ] Build Overview page and URL form.
- [ ] Add summary cards and recent downloads.
- [ ] Create empty, loading, and error states.
- [ ] Implement mobile and tablet layouts.

### Phase 3 — Backend and metadata

- [ ] Define API schemas and validation.
- [ ] Implement supported-source metadata retrieval.
- [ ] Return real available formats and quality information.
- [ ] Add persistent job records and safe storage configuration.

### Phase 4 — Download engine

- [ ] Implement authorized download processing.
- [ ] Add job queue and concurrency limits.
- [ ] Persist state transitions and error codes.
- [ ] Stream progress through SSE.
- [ ] Implement supported pause, resume, and cancellation behavior.

### Phase 5 — Queue and history

- [ ] Connect frontend to real APIs.
- [ ] Build filters, search, and pagination.
- [ ] Implement retries and duplicate-job protection.
- [ ] Add file actions and history cleanup.

### Phase 6 — Hardening and release

- [ ] Test invalid URLs and inaccessible content.
- [ ] Test worker failures and interrupted jobs.
- [ ] Secure URL fetching, filesystem paths, and API access.
- [ ] Check accessibility and responsive breakpoints.
- [ ] Add installation instructions, logging, and deployment configuration.

## 12. Definition of done

- [ ] The design is consistent across light and dark modes.
- [ ] Every navigation item leads to a functioning page.
- [ ] URL validation and metadata retrieval use real backend responses.
- [ ] A supported download produces a real output file.
- [ ] Progress and terminal states reflect the actual worker.
- [ ] Jobs and history survive application restarts.
- [ ] Cancellation, failure, and retry behavior have been tested.
- [ ] File actions cannot access arbitrary unauthorized filesystem paths.
- [ ] Remote URL fetching cannot be abused to access internal services.
- [ ] Responsive layouts, keyboard navigation, and accessible contrast are tested.
- [ ] Setup and troubleshooting instructions are documented.

## 13. Recommended execution order

Start with the design system and Overview page, then build the download workflow as a vertical slice:

**URL input → metadata → format selection → real job → progress → completed file**

Once that works end to end, build History, Files, and Settings around the same job model. This avoids polishing six screens before verifying that the core download process works.
