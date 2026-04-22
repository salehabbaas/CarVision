import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import AppShell from "./components/AppShell";
import { LoadingState } from "./components/PageState";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import NotificationsPage from "./pages/NotificationsPage";
import { applyTheme, resolveTheme } from "./hooks/useTheme";

const LivePage = lazy(() => import("./pages/LivePage"));
const DetectionsPage = lazy(() => import("./pages/DetectionsPage"));
const CamerasPage = lazy(() => import("./pages/CamerasPage"));
const TrainingPage = lazy(() => import("./pages/TrainingPage"));
const MediaWorkspacePage = lazy(() => import("./pages/MediaWorkspacePage"));
const TrainingDataPage = lazy(() => import("./pages/TrainingDataPage"));
const AllowedPlatesPage = lazy(() => import("./pages/AllowedPlatesPage"));
const DiscoveryPage = lazy(() => import("./pages/DiscoveryPage"));
const CapturePage = lazy(() => import("./pages/CapturePage"));

function RouteLoader() {
  return <LoadingState rows={3} message="Loading workspace..." />;
}

function ShellPage({ children }: { children: React.ReactNode }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}

export default function App() {
  useEffect(() => {
    applyTheme(resolveTheme());
  }, []);

  return (
    <Suspense fallback={<RouteLoader />}>
      <Routes>
        <Route path="/capture/:cameraId" element={<CapturePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<ShellPage><DashboardPage /></ShellPage>} />
        <Route path="/live" element={<ShellPage><LivePage /></ShellPage>} />
        <Route path="/detections" element={<ShellPage><DetectionsPage /></ShellPage>} />
        <Route path="/upload" element={<ShellPage><MediaWorkspacePage /></ShellPage>} />
        <Route path="/dataset-import" element={<Navigate to="/upload?tab=dataset-import" replace />} />
        <Route path="/trained-data" element={<Navigate to="/upload?tab=trained-data" replace />} />
        <Route path="/clips" element={<Navigate to="/upload?tab=clips" replace />} />
        <Route path="/training-data" element={<ShellPage><TrainingDataPage /></ShellPage>} />
        <Route path="/cameras" element={<ShellPage><CamerasPage /></ShellPage>} />
        <Route path="/allowed" element={<ShellPage><AllowedPlatesPage /></ShellPage>} />
        <Route path="/discovery" element={<ShellPage><DiscoveryPage /></ShellPage>} />
        <Route path="/training" element={<ShellPage><TrainingPage /></ShellPage>} />
        <Route path="/notifications" element={<ShellPage><NotificationsPage /></ShellPage>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
