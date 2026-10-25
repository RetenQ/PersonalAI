/** Original decorative SVG; no remote assets or tracking. */
export function SpaceMark() {
  return <div className="space-mark" aria-hidden="true"><svg viewBox="0 0 340 190" fill="none">
    <defs><pattern id="space-grid" width="18" height="18" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".6" fill="currentColor" opacity=".25"/></pattern><linearGradient id="space-fade" x1="80" y1="20" x2="270" y2="170" gradientUnits="userSpaceOnUse"><stop stopColor="#839caf"/><stop offset="1" stopColor="#7f9564"/></linearGradient></defs>
    <rect width="340" height="190" fill="url(#space-grid)"/>
    <g stroke="currentColor" strokeWidth=".75" opacity=".32"><ellipse cx="170" cy="98" rx="123" ry="45" transform="rotate(-22 170 98)"/><ellipse cx="170" cy="98" rx="123" ry="45" transform="rotate(38 170 98)"/><ellipse cx="170" cy="98" rx="123" ry="45" transform="rotate(98 170 98)"/></g>
    <path d="M68 131L170 97L269 62" stroke="url(#space-fade)" strokeWidth="1.25"/>
    <circle cx="170" cy="97" r="20" fill="#f5f6f1" stroke="#a8aea0"/><path d="M163 97h14m-7-7v14" stroke="#546939" strokeWidth="1.4"/>
    <circle cx="68" cy="131" r="4" fill="#7f9564"/><circle cx="269" cy="62" r="4" fill="#839caf"/>
    <g fontFamily="'Microsoft YaHei', sans-serif" fontSize="10" fill="currentColor"><text x="39" y="155">每次行动</text><text x="146" y="140">此刻的你</text><text x="247" y="45">长期目标</text></g>
  </svg></div>;
}
