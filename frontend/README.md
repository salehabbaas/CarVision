<div align="center">

# 🖥️ CarVision — Frontend

**React 18 · TypeScript · Vite · Tailwind CSS · Framer Motion**

[![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![Vite](https://img.shields.io/badge/Vite-6.x-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev)
[![Tailwind](https://img.shields.io/badge/Tailwind-3.x-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)](https://tailwindcss.com)

</div>

---

## 📁 Source Layout

```
frontend/src/
│
├── 📄 pages/                    # Route-level screen components
│   ├── Dashboard.tsx            #   Live multi-camera overview + 24h stats
│   ├── Cameras.tsx              #   Camera management & configuration
│   ├── Detections.tsx           #   Detection history with search & filters
│   ├── Allowed.tsx              #   Allowlist (authorized plates) management
│   ├── Training.tsx             #   Model training pipeline UI
│   ├── Notifications.tsx        #   Event notification feed
│   ├── Clips.tsx                #   Recorded clip library
│   └── Settings.tsx             #   App-wide settings
│
├── 🧩 components/               # Shared UI components
│   ├── CameraCard.tsx           #   Live camera tile with MJPEG stream
│   ├── DetectionRow.tsx         #   Single detection table row
│   ├── PlateOverlay.tsx         #   ALLOWED/DENIED badge overlay
│   ├── TrainingProgress.tsx     #   Training job progress indicator
│   └── ...
│
├── 🎨 design-system/            # Design primitives & tokens
│   ├── Button.tsx
│   ├── Card.tsx
│   ├── Badge.tsx
│   ├── Modal.tsx
│   └── ...
│
├── 🔌 context/                  # React context providers
│   ├── AuthContext.tsx          #   JWT auth state & login/logout
│   └── AppContext.tsx           #   App-wide shared state
│
├── 🪝 hooks/                    # Custom React hooks
│   ├── useDetections.ts         #   Paginated detections query
│   ├── useCameras.ts            #   Camera list & polling
│   ├── useTrainingStatus.ts     #   Training job live status
│   └── ...
│
└── 📦 lib/                      # API client & shared utilities
    ├── api.ts                   #   Typed API client (all endpoints)
    ├── auth.ts                  #   JWT token management
    └── utils.ts                 #   Formatting & helpers
```

---

## 🚀 Development

```bash
cd CarVision/frontend

# Install dependencies
npm install

# Start dev server  →  http://localhost:5173
npm run dev

# Type-check
npm run tsc

# Production build  →  dist/
npm run build

# Preview production build
npm run preview
```

---

## 🔌 API Connection

The frontend talks to the FastAPI backend via a typed API client in `src/lib/api.ts`. In development it proxies to `http://localhost:8000`. In production (Docker), it uses the `VITE_API_BASE_URL` environment variable.

```bash
# .env.local (development)
VITE_API_BASE_URL=http://localhost:8000

# .env.production (Docker / K8s)
VITE_API_BASE_URL=https://your-domain.com
```

---

## 📦 Key Dependencies

| Package | Version | Purpose |
|---|---|---|
| `react` | 18.3 | UI framework |
| `typescript` | 5.x | Type safety |
| `vite` | 6.x | Build tool & dev server |
| `tailwindcss` | 3.x | Utility-first styling |
| `framer-motion` | 11.x | Animations & transitions |
| `chart.js` + `react-chartjs-2` | 4.x | Detection analytics charts |
| `@tanstack/react-query` | 5.x | Server state & data fetching |
| `react-router-dom` | 6.x | Client-side routing |
| `lucide-react` | 0.4x | Icon library |
| `@radix-ui/*` | latest | Accessible UI primitives |
