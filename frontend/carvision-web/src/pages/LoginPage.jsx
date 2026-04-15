import { useState } from 'react';
import { motion } from 'framer-motion';
import { User, Lock } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { Navigate } from 'react-router-dom';
import FormField   from '../design-system/components/FormField';
import Input       from '../design-system/components/Input';
import Button      from '../design-system/components/Button';
import Alert       from '../design-system/components/Alert';
import BrandLogo   from '../components/BrandLogo';

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('admin');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

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
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.42, ease: [0.16, 1, 0.3, 1] }}
        className="login-card glass"
      >
        {/* Brand mark */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, marginBottom: 24 }}>
          <BrandLogo className="login-logo" />
          <div style={{ textAlign: 'center' }}>
            <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700 }}>CarVision</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: '0.82rem' }}>
              Secure access to live cameras & ANPR workflow
            </p>
          </div>
        </div>

        {error && (
          <Alert variant="error" onDismiss={() => setError('')} style={{ marginBottom: 16 }}>
            {error}
          </Alert>
        )}

        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <FormField label="Username" required>
            <Input
              icon={<User size={15} />}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoComplete="username"
              required
            />
          </FormField>

          <FormField label="Password" required>
            <Input
              icon={<Lock size={15} />}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              required
            />
          </FormField>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            loading={loading}
            style={{ marginTop: 4, width: '100%' }}
          >
            Sign in
          </Button>
        </form>
      </motion.div>
    </div>
  );
}
