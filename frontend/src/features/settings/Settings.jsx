/**
 * Settings page. Data Management is currently the only section.
 */
import { PageHeader } from '../../components/ui';
import DataManagement from './DataManagement';

export default function Settings() {
  return (
    <div>
      <PageHeader title="Settings" subtitle="Configure how CPI keeps its cricket data current." />
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">Data Management</h2>
      <DataManagement />
    </div>
  );
}
