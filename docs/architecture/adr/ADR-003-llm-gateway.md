# ADR 003: LLM Gateway

## Decision

All AI calls must go through an LLM Gateway.

## Context

The product must support local and external model providers.

## Rationale

A gateway prevents vendor lock-in and keeps business logic independent from model providers.

## Consequences

Applications must not call provider APIs directly. Provider configuration belongs to the AI Runtime layer.
