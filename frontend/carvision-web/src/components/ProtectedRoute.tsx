import { Navigate } from "react-router-dom";

import { useAuth } from "@/context/AuthContext";
import { LoadingState } from "@/components/PageState";

export default function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return (
      <div className="mx-auto flex min-h-screen w-full max-w-5xl items-center justify-center px-6">
        <div className="w-full max-w-lg">
          <LoadingState rows={2} message="Checking secure session..." />
        </div>
      </div>
    );
  }

  if (!isAuthenticated) return <Navigate to="/login" replace />;

  return <>{children}</>;
}
