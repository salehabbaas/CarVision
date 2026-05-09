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

export interface HardwareInfo {
  cpu: boolean;
  cuda: boolean;
  mps: boolean;
  gpu_names: string[];
  pytorch_available: boolean;
  usable_backends: string[];
}

export interface RuntimeSettings {
  runtime_profile: string;
  inference_device: string;
  training_device: string;
  model_backend: string;
  target_detection_fps: number;
  batch_inference: boolean;
  max_live_cameras: number;
  jpeg_quality: number;
  plate_region: string;
  ocr_engine: string;
  updated_at: string | null;
}
