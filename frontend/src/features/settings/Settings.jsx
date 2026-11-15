/**
 * Settings: Appearance (theme) and Data Management.
 */
import { PageHeader, SectionHeader } from '../../components/ui';
import ThemeSwitcher from '../../components/ThemeSwitcher';
import Icon from '../../components/icons';
import { useTheme } from '../../theme';
import DataManagement from './DataManagement';

function ThemePreview({ mode, active }) {
  const dark = mode === 'dark';
  return (
    <div className={`overflow-hidden rounded-2xl border transition-[border-color,box-shadow] duration-200 ${active ? 'border-accent shadow-[0_0_0_3px_rgb(var(--accent)/0.2)]' : 'border-line'}`} aria-hidden="true">
      <div className={`flex h-20 gap-1.5 p-2 ${dark ? 'bg-[#090a0d]' : 'bg-[#f5f5f7]'}`}>
        <div className={`w-6 rounded-lg ${dark ? 'bg-[#1e2028]' : 'bg-white/80 shadow-sm'}`} />
        <div className="flex flex-1 flex-col gap-1.5">
          <div className={`h-3 rounded-full ${dark ? 'bg-[#1e2028]' : 'bg-white shadow-sm'}`} />
          <div className={`flex-1 rounded-lg p-1.5 ${dark ? 'bg-[#17191f]' : 'bg-white shadow-sm'}`}>
            <div className={`h-1.5 w-8 rounded-full ${dark ? 'bg-[#2997ff]' : 'bg-[#0071e3]'}`} />
            <div className={`mt-1 h-1 w-12 rounded-full ${dark ? 'bg-white/20' : 'bg-black/15'}`} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Appearance() {
  const { preference, resolved, setTheme } = useTheme();
  return (
    <section className="panel mb-8 p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-md">
          <h3 className="text-[15px] font-semibold tracking-[-0.015em] text-white">Theme</h3>
          <p className="mt-1 text-[13px] leading-relaxed text-slate-500">
            Choose a light or dark interface, or follow your device. Currently showing the <span className="font-medium text-slate-300">{resolved}</span> theme{preference === 'system' ? ' from your system setting' : ''}.
          </p>
        </div>
        <ThemeSwitcher />
      </div>
      <div className="mt-5 grid max-w-xl grid-cols-3 gap-3">
        {[{ id: 'light', label: 'Light' }, { id: 'dark', label: 'Dark' }, { id: 'system', label: 'System' }].map(m => (
          <button key={m.id} type="button" onClick={() => setTheme(m.id)} className="group rounded-2xl text-left" aria-label={`Use ${m.label} appearance`} aria-pressed={preference === m.id}>
            {m.id === 'system'
              ? <div className={`grid grid-cols-2 overflow-hidden rounded-2xl border transition-[border-color,box-shadow] duration-200 ${preference === 'system' ? 'border-accent shadow-[0_0_0_3px_rgb(var(--accent)/0.2)]' : 'border-line'}`}><div className="h-20 bg-[#f5f5f7]" /><div className="h-20 bg-[#090a0d]" /></div>
              : <ThemePreview mode={m.id} active={preference === m.id} />}
            <div className={`mt-2 flex items-center gap-1.5 pl-1 text-[13px] ${preference === m.id ? 'font-medium text-white' : 'text-slate-400 group-hover:text-slate-200'}`}>
              {preference === m.id && <Icon name="check" size={14} className="text-accent" />}{m.label}
            </div>
          </button>
        ))}
      </div>
    </section>
  );
}

export default function Settings() {
  return (
    <div>
      <PageHeader eyebrow="System" title="Settings" subtitle="Appearance, and how CPI keeps its cricket data current." />
      <SectionHeader title="Appearance" subtitle="Your choice is saved on this device." />
      <Appearance />
      <SectionHeader title="Data management" subtitle="Cricsheet synchronisation, schedule and import history." />
      <DataManagement />
    </div>
  );
}
