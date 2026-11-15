/**
 * Light / Dark / System switcher rendered as an iOS-style segmented control
 * with a sliding thumb. `compact` shows icons only (header); the full variant
 * shows labels (Settings › Appearance).
 */
import { useTheme, THEME_MODES } from '../theme';
import Icon from './icons';

export default function ThemeSwitcher({ compact = false, size, className = '' }) {
  const { preference, setTheme } = useTheme();
  const index = Math.max(0, THEME_MODES.findIndex(m => m.id === preference));
  const w = compact ? 30 : size === 'md' ? 74 : 92;
  return (
    <div role="radiogroup" aria-label="Appearance" className={`segmented ${className}`}>
      <span aria-hidden="true" className="segment-thumb" style={{ width: w, transform: `translateX(${index * (w + 2)}px)` }} />
      {THEME_MODES.map(m => (
        <button key={m.id} type="button" role="radio" aria-checked={preference === m.id} onClick={() => setTheme(m.id)}
          title={compact ? `${m.label} appearance` : undefined} aria-label={compact ? `${m.label} appearance` : undefined}
          className={`segment ${compact ? 'h-[26px] text-xs' : size === 'md' ? 'h-8 gap-1 text-xs' : 'h-8 text-[13px]'}`} style={{ width: w }}>
          <Icon name={m.icon} size={compact ? 14 : 15} />
          {!compact && m.label}
        </button>
      ))}
    </div>
  );
}
