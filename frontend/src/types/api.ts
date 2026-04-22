export interface AuthUser {
  username: string;
  role: string;
}

export interface AuthLoginResponse {
  access_token: string;
  user: AuthUser;
}

export interface DashboardSummary {
  totals?: Record<string, number>;
  details?: Record<string, number | string>;
  charts?: Record<string, any>;
  training?: {
    status?: string;
    message?: string;
  };
  future_metrics?: Record<string, any>;
  recent_events?: Array<Record<string, any>>;
}

export interface NotificationItem {
  id: number;
  title: string;
  message: string;
  is_read: boolean;
  created_at?: string | null;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  unread: number;
}
