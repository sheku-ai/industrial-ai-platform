# Plugin SDK

Base SDK for connector plugins.

A connector plugin must implement:

- connect
- test_connection
- sync
- incremental_sync
- map_metadata
- map_permissions
- health_check

The SDK defines shared interfaces, expected responses, and execution contracts.
