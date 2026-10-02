import { platformApi, type JsonObject } from './platform-api';

export type ConnectorConfigurationField = {
  key: string;
  label: string;
  description: string | null;
  type: 'boolean' | 'integer' | 'number' | 'string';
  required: boolean;
  editable: boolean;
  options: Array<string | number | boolean>;
};

export type ConnectorCredentialContract = {
  supported: boolean;
  required: boolean;
  resolver_types: string[];
};

export type ConnectorCatalogType = JsonObject & {
  connector_type_id: string;
  code: string;
  name: string;
  description?: string | null;
  category?: string | null;
  status: string;
  configurable: boolean;
  configuration_unavailable_reason?: string | null;
  configuration_fields: ConnectorConfigurationField[];
  credential: ConnectorCredentialContract;
  runtime_executable: boolean;
};

export type ConnectorConfiguration = JsonObject & {
  connector_id: string;
  connector_type_id: string;
  code: string;
  name: string;
  status: string;
  enabled: boolean;
  configuration_status: string;
  configuration_validation_status: 'valid' | 'legacy_requires_review';
  configuration_version: number;
  configuration: JsonObject;
  credential_configured: boolean;
  credential_resolver_type: string | null;
};

export type ConnectorWorkspaceRuntime = {
  connector_workspace_runtime_schema_version: string;
  runtime_name: string;
  runtime_status: string;
  capabilities: {
    read?: boolean;
    administer?: boolean;
  };
  credential_resolver_types: string[];
  workspace_summary: JsonObject;
  connector_types: ConnectorCatalogType[];
  connectors: ConnectorConfiguration[];
  connector_configurations: JsonObject[];
  connector_runs: JsonObject;
  sync_ingestion_impact: JsonObject;
  audit_trace: JsonObject;
  diagnostics: {
    blocking_issues?: JsonObject[];
    warnings?: JsonObject[];
    pending_capabilities?: JsonObject[];
    degraded_items?: JsonObject[];
  };
  postgresql_source_of_truth: boolean;
  external_calls_performed: boolean;
  llm_used: boolean;
  qdrant_used: boolean;
};

export type ConnectorCredentialInput = {
  resolver_type: string;
  reference: string;
};

export type ConnectorConfigurationCreateInput = {
  connector_type_id: string;
  code: string;
  name: string;
  configuration: JsonObject;
  credential?: ConnectorCredentialInput;
};

export type ConnectorConfigurationUpdateInput = {
  expected_version: number;
  name?: string;
  configuration?: JsonObject;
  credential?: ConnectorCredentialInput;
  clear_credential?: boolean;
};

export type ConnectorConfigurationResult = {
  id: string;
  connector_type_id: string;
  code: string;
  name: string;
  status: string;
  enabled: boolean;
  lifecycle_status: 'active' | 'archived';
  configuration_version: number;
  configuration: JsonObject;
  configuration_status: 'valid' | 'legacy_requires_review';
  credential_configured: boolean;
  credential_resolver_type: string | null;
  created_at: string;
  updated_at: string;
};

export function getConnectorWorkspaceRuntime(): Promise<ConnectorWorkspaceRuntime> {
  return platformApi.get<ConnectorWorkspaceRuntime>('/api/connectors/workspace/runtime');
}

export function createConnectorConfiguration(
  payload: ConnectorConfigurationCreateInput,
): Promise<ConnectorConfigurationResult> {
  return platformApi.post<ConnectorConfigurationResult>(
    '/api/connectors/workspace/configurations',
    payload,
  );
}

export function updateConnectorConfiguration(
  connectorId: string,
  payload: ConnectorConfigurationUpdateInput,
): Promise<ConnectorConfigurationResult> {
  return platformApi.patch<ConnectorConfigurationResult>(
    `/api/connectors/workspace/configurations/${encodeURIComponent(connectorId)}`,
    payload,
  );
}

export function setConnectorConfigurationEnabled(
  connectorId: string,
  enabled: boolean,
  expectedVersion: number,
): Promise<ConnectorConfigurationResult> {
  return platformApi.post<ConnectorConfigurationResult>(
    `/api/connectors/workspace/configurations/${encodeURIComponent(connectorId)}/enabled`,
    { enabled, expected_version: expectedVersion },
  );
}

export function setConnectorConfigurationArchived(
  connectorId: string,
  archived: boolean,
  expectedVersion: number,
): Promise<ConnectorConfigurationResult> {
  return platformApi.post<ConnectorConfigurationResult>(
    `/api/connectors/workspace/configurations/${encodeURIComponent(connectorId)}/${archived ? 'archive' : 'restore'}`,
    { expected_version: expectedVersion },
  );
}
