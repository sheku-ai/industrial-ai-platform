
import { LocalizedText } from '../layout/LocalizedText';
import type { OperationalHealthIssue } from '../../lib/operations-api';

export function OperationalHealthIssues({ issues }: { issues: OperationalHealthIssue[] }) {
  if (!issues.length) {
    return (
      <section className="card">
        <h2><LocalizedText id="copy.operational_issues_494b56da" /></h2>
        <p><LocalizedText id="copy.no_active_operational_issues_41c7d933" /></p>
      </section>
    );
  }

  return (
    <section className="table-card">
      <h2><LocalizedText id="copy.operational_issues_494b56da" /></h2>
      <table>
        <thead>
          <tr><th><LocalizedText id="copy.severity_de314fa0" /></th><th><LocalizedText id="common.code" /></th><th><LocalizedText id="copy.source_6da13add" /></th><th><LocalizedText id="copy.resource_021493f3" /></th><th><LocalizedText id="copy.observed_2e159b44" /></th><th><LocalizedText id="copy.detail_7c9a7c06" /></th></tr>
        </thead>
        <tbody>
          {issues.map((issue, index) => (
            <tr key={`${issue.code}-${issue.resource_key ?? 'aggregate'}-${index}`}>
              <td>{issue.severity}</td>
              <td><code>{issue.code}</code></td>
              <td>{issue.source}</td>
              <td>{issue.resource_key ?? issue.resource_type}</td>
              <td>{issue.observed_value ?? '—'}</td>
              <td>{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
