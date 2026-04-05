import { Navigate, Route, Routes } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import AppShell from './components/AppShell';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import LivePage from './pages/LivePage';
import DetectionsPage from './pages/DetectionsPage';
import CamerasPage from './pages/CamerasPage';
import TrainingPage from './pages/TrainingPage';
import NotificationsPage from './pages/NotificationsPage';
import UploadPage from './pages/UploadPage';
import TrainingDataPage from './pages/TrainingDataPage';
import DatasetImportPage from './pages/DatasetImportPage';
import AllowedPlatesPage from './pages/AllowedPlatesPage';
import DiscoveryPage from './pages/DiscoveryPage';

function ShellPage({ children }) {
  return (
    <ProtectedRoute>
      <AppShell>{children}</AppShell>
    </ProtectedRoute>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<ShellPage><DashboardPage /></ShellPage>} />
      <Route path="/live" element={<ShellPage><LivePage /></ShellPage>} />
      <Route path="/detections" element={<ShellPage><DetectionsPage /></ShellPage>} />
      <Route path="/upload" element={<ShellPage><UploadPage /></ShellPage>} />
      <Route path="/dataset-import" element={<ShellPage><DatasetImportPage /></ShellPage>} />
      <Route path="/training-data" element={<ShellPage><TrainingDataPage /></ShellPage>} />
      <Route path="/cameras" element={<ShellPage><CamerasPage /></ShellPage>} />
      <Route path="/allowed" element={<ShellPage><AllowedPlatesPage /></ShellPage>} />
      <Route path="/discovery" element={<ShellPage><DiscoveryPage /></ShellPage>} />
      <Route path="/training" element={<ShellPage><TrainingPage /></ShellPage>} />
      <Route path="/notifications" element={<ShellPage><NotificationsPage /></ShellPage>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
