import { useState } from 'react';
import { motion } from 'framer-motion';
import { Shield } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Navigate } from 'react-router-dom';

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function submit(e) {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-page">
      <motion.form
        initial={{ y: 16, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="login-card glass"
        onSubmit={submit}
      >
        <div className="login-icon"><Shield size={22} /></div>
        <h2>CarVision Admin</h2>
        <p className="muted">Secure JWT access to live cameras and CarVision training workflow.</p>
        <label title="Account username used to access the admin panel.">Username</label>
        <input title="Enter your admin account username." value={username} onChange={(e) => setUsername(e.target.value)} required />
        <label title="Account password for the admin panel login.">Password</label>
        <input title="Enter your admin account password." type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        {error ? <div className="alert error">{error}</div> : null}
        <button className="btn primary" disabled={loading}>{loading ? 'Signing in...' : 'Sign in'}</button>
      </motion.form>
    </div>
  );
}
