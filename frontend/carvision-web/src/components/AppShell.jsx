import { Bell, Camera, Gauge, LogOut, Radar, ShieldCheck, BrainCircuit, Upload, FolderCheck, Network, ListChecks, Archive } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

const menu = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/live', label: 'Live DVR', icon: Radar },
  { to: '/detections', label: 'Detections', icon: ShieldCheck },
  { to: '/upload', label: 'Upload & Test', icon: Upload },
  { to: '/dataset-import', label: 'Dataset Import', icon: Archive },
  { to: '/training-data', label: 'Training Data', icon: FolderCheck },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/allowed', label: 'Allowed Plates', icon: ListChecks },
  { to: '/discovery', label: 'Discovery', icon: Network },
  { to: '/training', label: 'Training', icon: BrainCircuit },
  { to: '/notifications', label: 'Notifications', icon: Bell },
];

export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const location = useLocation();

  return (
    <div className="app-shell">
      <aside className="sidebar glass">
        <div className="brand">
          <span className="brand-dot" />
          <div>
            <div className="brand-title">CarVision</div>
            <div className="brand-sub">by SpinelTech</div>
          </div>
        </div>
        <nav className="menu">
          {menu.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink key={item.to} to={item.to} className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`} end={item.to === '/'}>
                <Icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>

      <main className="main-area">
        <header className="topbar glass">
          <motion.div
            key={location.pathname}
            initial={{ y: 6, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.25 }}
          >
            <h1>{menu.find((m) => (m.to === '/' ? location.pathname === '/' : location.pathname.startsWith(m.to)))?.label || 'CarVision'}</h1>
            <p className="muted">Realtime plate detection, feedback, and retraining.</p>
          </motion.div>
          <div className="topbar-right">
            <span className="badge">{user?.username || 'admin'}</span>
            <button className="btn ghost" onClick={logout}>
              <LogOut size={15} /> Logout
            </button>
          </div>
        </header>
        <section className="page-content">{children}</section>
      </main>
    </div>
  );
}
