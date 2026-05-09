import { useEffect, useState } from "react";
import { Lock, Radar, User } from "lucide-react";
import { Navigate } from "react-router-dom";

import SurfaceCard from "@/components/admin/SurfaceCard";
import BrandLogo from "@/components/BrandLogo";
import { useAuth } from "@/context/AuthContext";
import { request } from "@/lib/api";
import Alert from "@/design-system/components/Alert";
import Button from "@/design-system/components/Button";
import FormField from "@/design-system/components/FormField";
import Input from "@/design-system/components/Input";

type SetupState = {
  setup_required: boolean;
  can_bootstrap: boolean;
  recovery_required: boolean;
  admin_configured: boolean;
  master_configured: boolean;
};

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [setupUsername, setSetupUsername] = useState("");
  const [setupPassword, setSetupPassword] = useState("");
  const [setupPasswordConfirm, setSetupPasswordConfirm] = useState("");
  const [setupState, setSetupState] = useState<SetupState | null>(null);
  const [setupLoading, setSetupLoading] = useState(true);
  const [masterPassword, setMasterPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    request<SetupState>("/api/v1/auth/bootstrap_status")
      .then((state) => {
        if (!alive) return;
        setSetupState(state);
      })
      .catch(() => {
        if (!alive) return;
        setSetupState(null);
      })
      .finally(() => {
        if (alive) setSetupLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  if (isAuthenticated) return <Navigate to="/" replace />;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  async function submitBootstrap(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError("");
    if (setupPassword !== setupPasswordConfirm) {
      setLoading(false);
      setError("Passwords do not match");
      return;
    }
    try {
      const res = await request<{ master_password: string }>("/api/v1/auth/bootstrap", {
        method: "POST",
        body: { username: setupUsername, password: setupPassword },
      });
      setMasterPassword(res.master_password || "");
      setSetupState((prev) =>
        prev
          ? { ...prev, setup_required: false, can_bootstrap: false, recovery_required: false, admin_configured: true }
          : prev
      );
      setUsername(setupUsername);
      setPassword("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setLoading(false);
    }
  }

  const showBootstrap = Boolean(setupState?.setup_required && setupState?.can_bootstrap);
  const showRecovery = Boolean(setupState?.setup_required && setupState?.recovery_required && !setupState?.can_bootstrap);

  return (
    <div className="relative min-h-screen overflow-hidden px-6 py-10">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.18),transparent_28%),radial-gradient(circle_at_80%_12%,rgba(52,211,153,0.14),transparent_24%),linear-gradient(180deg,#06111e,#081522_40%,#070c14)]" />
      <div className="relative mx-auto grid min-h-[calc(100vh-5rem)] max-w-6xl items-center gap-8 lg:grid-cols-[1.2fr_0.8fr]">
        <div className="hidden space-y-6 lg:block">
          <p className="text-xs font-semibold uppercase tracking-[0.32em] text-primary">CarVision control room</p>
          <h1 className="max-w-3xl text-5xl font-semibold leading-tight text-foreground">
            Secure access to detection review, live camera operations, and retraining workflows.
          </h1>
          <div className="grid max-w-2xl gap-4 sm:grid-cols-3">
            {[
              ["Live monitoring", "Watch and manage stream health without losing context."],
              ["Detection QA", "Review, correct, and retrigger detections from one workspace."],
              ["Training loop", "Ship corrections back into the retraining pipeline faster."],
            ].map(([title, copy]) => (
              <SurfaceCard key={title} className="min-h-[148px] bg-card/60">
                <div className="rounded-2xl border border-primary/20 bg-primary/10 p-3 text-primary">
                  <Radar className="size-5" />
                </div>
                <h2 className="mt-4 text-base font-semibold text-foreground">{title}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{copy}</p>
              </SurfaceCard>
            ))}
          </div>
        </div>

        <SurfaceCard className="mx-auto w-full max-w-md border-primary/20 bg-card/85 p-8 shadow-shell">
          <div className="mb-8 flex flex-col items-center gap-4 text-center">
            <div className="rounded-[28px] border border-primary/30 bg-primary/10 p-4">
              <BrandLogo className="h-14 w-14 object-contain" />
            </div>
            <div className="space-y-1">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-primary">Admin sign-in</p>
              <h2 className="text-3xl font-semibold text-foreground">CarVision</h2>
              <p className="text-sm text-muted-foreground">Secure access to the realtime operations workspace.</p>
            </div>
          </div>

          {setupLoading ? (
            <Alert variant="info" className="mb-5">Checking authentication setup…</Alert>
          ) : null}

          {error ? (
            <Alert variant="error" onDismiss={() => setError("")} className="mb-5">
              {error}
            </Alert>
          ) : null}

          {showBootstrap ? (
            <form className="space-y-4" onSubmit={submitBootstrap}>
              <Alert variant="info">First run detected. Create the initial admin account.</Alert>
              <FormField label="Admin username" required>
                <Input
                  icon={<User className="size-4" />}
                  value={setupUsername}
                  onChange={(event) => setSetupUsername(event.target.value)}
                  placeholder="admin_user"
                  autoComplete="username"
                  required
                />
              </FormField>
              <FormField label="Admin password (min 8 chars)" required>
                <Input
                  icon={<Lock className="size-4" />}
                  type="password"
                  value={setupPassword}
                  onChange={(event) => setSetupPassword(event.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  required
                />
              </FormField>
              <FormField label="Confirm password" required>
                <Input
                  icon={<Lock className="size-4" />}
                  type="password"
                  value={setupPasswordConfirm}
                  onChange={(event) => setSetupPasswordConfirm(event.target.value)}
                  placeholder="••••••••"
                  autoComplete="new-password"
                  required
                />
              </FormField>
              <Button type="submit" variant="primary" size="lg" loading={loading} className="w-full">
                Create admin account
              </Button>
            </form>
          ) : (
            <form className="space-y-4" onSubmit={submit}>
              {showRecovery ? (
                <Alert variant="warning">
                  Admin account is removed. Use the master password with
                  <code className="ml-1">POST /api/v1/auth/admin/reset</code> to recreate admin access.
                </Alert>
              ) : null}
              {masterPassword ? (
                <Alert variant="success">
                  Master recovery password (save now): <code>{masterPassword}</code>
                </Alert>
              ) : null}
              <FormField label="Username" required>
                <Input
                  icon={<User className="size-4" />}
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="username"
                  autoComplete="username"
                  required
                />
              </FormField>

              <FormField label="Password" required>
                <Input
                  icon={<Lock className="size-4" />}
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
              </FormField>

              <Button type="submit" variant="primary" size="lg" loading={loading} className="w-full">
                Enter control room
              </Button>
            </form>
          )}
        </SurfaceCard>
      </div>
    </div>
  );
}
