# ClipFlow — Project Overview & Architecture Vision

## 1. Project Concept & Core Mission

**ClipFlow** (powered by TurboTube) is a high-performance, self-hosted media ingestion and download engine designed for power users, creators, and media archivists. 

Traditional media downloading solutions typically fall into two extremes:
1. **Ad-ridden, untrusted web converters:** Cloud-based download sites are heavily rate-limited, compress and degrade audio/video bitrates, enforce artificial queues, and expose users to malicious ads and tracking.
2. **Complex CLI utilities:** Tools like `yt-dlp`, `aria2c`, and `ffmpeg` offer maximum fidelity and speed, but lack persistent queue management, live visual streaming feedback, disk asset organization, and mobile touch accessibility.

**ClipFlow unites raw engine performance with senior UI/UX craftsmanship.** It provides a local, private, and secure service that saturates high-speed network connections while presenting an intuitive, neo-brutalist interface with real-time SSE telemetrics.

```
┌─────────────────────────────────────────────────────────────┐
│  Browser UI (Vanilla ES6+ / CSS)     CLI (Rich Terminal)    │
│         │                                     │             │
│         │ SSE Stream (Live Metrics)           │             │
│         └──────────────┬──────────────────────┘             │
│                        ▼                                    │
│                 FastAPI + Uvicorn                           │
│                        │                                    │
│                        ▼                                    │
│             JobManager Queue & Watchdog                     │
│         ┌──────────────┼──────────────┐                     │
│         ▼              ▼              ▼                     │
│      aria2c        yt-dlp core      ffmpeg                  │
│    (Segments)     (Extraction)     (Muxing)                 │
│         └──────────────┬──────────────┘                     │
│                        ▼                                    │
│            SQLite WAL + Connection Pool                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Key Architecture Pillars

### 2.1 Max-Throughput Concurrency & Multi-Segment Engine
- **Parallel Chunk Acceleration:** Employs `aria2c` multi-segmented connection splitting (up to 16–24 parallel HTTP ranges per file) to saturate fiber and broadband connections.
- **Dedicated Probe ThreadPool:** Heavy media probes and playlist schema expansions run in an isolated threadpool (`_probe_executor`), ensuring API responsiveness and UI snappy-ness even while inspecting 100+ video playlists.
- **Worker Throttling & Queue Management:** Dynamic concurrency controls allow running multiple worker threads without CPU or disk I/O thrashing.

### 2.2 Byte-Accurate Download Resumption
- **Partial Fragment Preservation:** Maintains partial byte buffers (`.part`, `.ytdl`, `.aria2`), allowing interrupted or cancelled downloads to resume seamlessly from the exact byte offset where they stopped.
- **Semantic Separation:**
  - **Resume:** Preserves previously downloaded bytes and continues remaining segments.
  - **Restart:** Purges stale chunks and re-downloads clean streams from byte 0.
- **Auto-Recovery on Restart:** If the host machine or server restarts during an active batch, interrupted jobs are automatically flagged and can be resumed in a single click.

### 2.3 Neo-Brutalist Visual Design (Positivus Design System)
- **High-Contrast Geometry:** Crisp borders (`1.5px solid #191A23`), tactile drop-shadows (`4px 4px 0px #191A23`), smooth corner radii (`20px`), and vibrant electric lime highlights (`#B9FF66`).
- **Fluid Animation Engine:**
  - Continuous barber-pole progress stripes calibrated to the gradient periodicity ($33.94\text{px}$) to eliminate visual stutter.
  - Specular light reflection shimmer sweeping across full card widths.
  - Soft radial pulsating status badges for live activity.
  - Non-destructive DOM reconciliation that updates counters and progress bars in-place without resetting user scroll or collapsing expanded accordions.
- **Dynamic Theme Synchronizer:** Seamless switching between Positivus Light, Neo Dark, and OS System Auto-detection.
- **Mobile Responsive Transformation:** Converts complex tabular data into stacked, touch-friendly card layouts on mobile viewports (<768px).

### 2.4 Production-Grade Fault Tolerance & Self-Healing
- **Three-State Circuit Breaker:** Detects upstream platform outages or rate-limiting bans (`CLOSED -> OPEN -> HALF_OPEN -> CLOSED`), failing fast to protect network resources and recovering automatically.
- **Sliding-Window Rate Limiter:** Protects mutating API endpoints against rapid request floods with memory-bounded LRU key eviction.
- **Download Watchdog:** Background monitor detects hung worker threads exceeding wall-clock deadlines and automatically cancels them to unblock queue capacity.
- **Write-Batching Flusher:** Consolidates high-frequency progress persistence into a single atomic SQLite transaction every 3 seconds, cutting disk write contention by over $80\%$.

### 2.5 Privacy, Local Storage & Security Boundaries
- **Strict SSRF Defense:** Enforces strict URL host validation, blocking access to `localhost`, internal subnets (`10.0.0.0/8`, `192.168.0.0/16`, `172.16.0.0/12`), cloud metadata services (`169.254.169.254`), and local filesystem URIs (`file://`).
- **Disk File Management:** Direct local asset management with safe file launching in native OS media players (`os.startfile`), traversal-guarded deletions, and one-click temporary fragment cleanup.
- **Zero Cloud Leakage:** All metadata, cookies, and database records remain strictly on the host filesystem under local control.

---

## 3. Supported Workflows

| Capability | Description |
|---|---|
| **Single Video & Audio** | Download highest resolution (4K/1080p/60fps) MP4/MKV, or extract audio to MP3, M4A, FLAC, OPUS with metadata and thumbnail embedding. |
| **Playlists & Channels** | Interactive playlist probe picker with search filtering, selection counters, "Select All", and range selection. |
| **SponsorBlock Integration** | Automatically detect and cut sponsored segments, intros, outros, and subscription reminders directly from the video stream. |
| **Cookie & Auth Management** | Secure upload and isolation of Netscape cookie files for accessing age-restricted or member-only media. |
| **One-Click Local Launch** | Portable startup via `start.bat` with automatic dependency installation and instant browser launching. |

---

## 4. Technology Stack

- **Backend:** Python 3.10+, FastAPI, Starlette, Uvicorn, Pydantic Settings.
- **Core Downloader:** `yt-dlp`, `aria2c`, `ffmpeg`, `mutagen`.
- **Database:** SQLite 3 in WAL mode with connection pooling.
- **Frontend:** Vanilla ES6+ JavaScript, CSS3 custom properties, Lucide SVG vector sprites.
- **Testing:** Pytest, AnyIO (100% automated coverage across 93 tests).
