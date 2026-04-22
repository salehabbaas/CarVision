export default function BrandLogo({ className = "", alt = "CarVision logo" }: { className?: string; alt?: string }) {
  return (
    <img
      className={`brand-logo-theme ${className}`.trim()}
      src="/CarVision_Logo.svg"
      alt={alt}
      loading="eager"
      decoding="async"
    />
  );
}
