import { SchedulerSurface } from '../../components/scheduler/SchedulerSurface';
import { PageHeader } from '../../components/layout/PageHeader';

export default function SchedulerPage() {
  return (
    <>
      <PageHeader page="scheduler" />
      <SchedulerSurface />
    </>
  );
}
