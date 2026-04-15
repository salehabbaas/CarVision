import { useMemo, useState } from 'react';

function pickThemePng() {
  if (typeof window === 'undefined') return '/Black_Logo.png';
  const root = document.documentElement;
  const dataTheme = (root.getAttribute('data-theme') || '').toLowerCase();
  const className = (root.className || '').toLowerCase();
  const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
  const isDarkTheme = dataTheme === 'dark' || className.includes('dark') || prefersDark;
  return isDarkTheme ? '/White_Logo.png' : '/Black_Logo.png';
}

export default function BrandLogo({ className = '', alt = 'CarVision logo' }) {
  const fallbackPng = useMemo(() => pickThemePng(), []);
  const [src, setSrc] = useState('/CarVision_Logo.svg');

  return (
    <img
      className={className}
      src={src}
      alt={alt}
      onError={() => setSrc(fallbackPng)}
      loading="eager"
      decoding="async"
    />
  );
}

