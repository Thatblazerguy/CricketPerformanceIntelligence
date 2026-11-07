/**
 * Shared UI components for loading, error, and empty states.
 */

export function LoadingSpinner({ message = 'Loading...' }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-slate-400">
      <div className="w-8 h-8 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin mb-3" />
      <span className="text-sm">{message}</span>
    </div>
  );
}

export function ErrorState({ message }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-red-400">
      <span className="text-4xl mb-3">⚠</span>
      <p className="text-sm max-w-sm text-center">{message}</p>
    </div>
  );
}

export function EmptyState({ message = 'No data available.' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-500">
      <span className="text-4xl mb-3">—</span>
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function StatCard({ label, value, sub, highlight = false }) {
  return (
    <div className={`rounded-lg p-4 ${highlight ? 'bg-indigo-900/40 border border-indigo-700' : 'bg-slate-800 border border-slate-700'}`}>
      <p className="text-xs text-slate-400 uppercase tracking-wider mb-1">{label}</p>
      <p className={`text-2xl font-bold ${highlight ? 'text-indigo-300' : 'text-white'}`}>
        {value ?? <span className="text-slate-500 text-base">—</span>}
      </p>
      {sub && <p className="text-xs text-slate-500 mt-1">{sub}</p>}
    </div>
  );
}

export function SampleNote({ note }) {
  if (!note) return null;
  return (
    <p className="text-xs text-slate-500 mt-3 italic">{note}</p>
  );
}

export function SampleWarning({ warning }) {
  if (!warning) return null;
  return (
    <div className="bg-amber-900/30 border border-amber-700 rounded px-3 py-2 text-xs text-amber-300 mt-3">
      ⚠ {warning}
    </div>
  );
}

export function Badge({ children, variant = 'default' }) {
  const styles = {
    default: 'bg-slate-700 text-slate-300',
    indigo: 'bg-indigo-900/50 text-indigo-300 border border-indigo-700',
    green: 'bg-emerald-900/40 text-emerald-300',
    amber: 'bg-amber-900/40 text-amber-300',
  };
  return (
    <span className={`inline-block text-xs px-2 py-0.5 rounded font-medium ${styles[variant]}`}>
      {children}
    </span>
  );
}

export function PageHeader({ title, subtitle }) {
  return (
    <div className="mb-8">
      <h1 className="text-2xl font-bold text-white tracking-tight">{title}</h1>
      {subtitle && <p className="text-slate-400 text-sm mt-1">{subtitle}</p>}
    </div>
  );
}

export function Table({ headers, rows, emptyMessage = 'No data.' }) {
  if (!rows || rows.length === 0) return <EmptyState message={emptyMessage} />;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700">
      <table className="w-full text-sm">
        <thead className="bg-slate-800 border-b border-slate-700">
          <tr>
            {headers.map((h, i) => (
              <th key={i} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">
          {rows.map((row, i) => (
            <tr key={i} className="hover:bg-slate-800/50 transition-colors">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-3 text-slate-200">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

