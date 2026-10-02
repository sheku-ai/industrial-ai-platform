import { SearchDiscoveryWorkspace } from '../../components/search/SearchDiscoveryWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

export default function SearchDiscoveryPage() {
  return (
    <>
      <PageHeader page="search" />
      <SearchDiscoveryWorkspace />
    </>
  );
}
