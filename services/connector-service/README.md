# Connector Service

Sprint 6A foundation.

Purpose: register connectors, manage connector instances, run sync jobs, and expose connector status.

Core objects:
- connectors
- connector_instances
- connector_sync_jobs
- connector_events

A connector must follow the platform connector contract and must not modify core services directly.
