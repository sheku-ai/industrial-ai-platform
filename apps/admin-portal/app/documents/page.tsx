
import { LocalizedText } from '../../components/layout/LocalizedText';
import { DocumentWorkspace } from '../../components/documents/DocumentWorkspace';
import { PageHeader } from '../../components/layout/PageHeader';

type DocumentsPageProps = {
  searchParams?: Promise<{ organization_node_id?: string | string[] }>;
};

export default async function DocumentsPage({ searchParams }: DocumentsPageProps) {
  const params = searchParams ? await searchParams : {};
  const organizationNodeId = typeof params.organization_node_id === 'string'
    ? params.organization_node_id
    : null;

  return (
    <>
      <PageHeader page="documents" />
      <section className="capability-section" id="document-lifecycle">
        <DocumentWorkspace organizationNodeId={organizationNodeId} />
      </section>
      <details className="advanced-panel capability-section" id="document-builder">
        <summary><LocalizedText id="copy.document_configuration_2592490b" /></summary>
        <div className="advanced-panel-content"><header className="section-header"><span className="eyebrow"><LocalizedText id="pages.security.section" /></span><h2><LocalizedText id="copy.document_builder_40d2a9f8" /></h2><p><LocalizedText id="copy.reusable_document_types_and_metadata_fields_are_mana_0753d2fa" /></p></header><p><a className="button secondary" href="/organization/document-configuration"><LocalizedText id="copy.open_document_configuration_540d5a6e" /></a></p></div>
      </details>
    </>
  );
}
