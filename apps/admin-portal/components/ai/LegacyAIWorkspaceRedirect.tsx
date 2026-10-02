'use client';

import { useEffect } from 'react';

const ASK_AI_HASHES: Record<string, string> = {
  '#assistant-workspace': '/ask',
  '#chat': '/ask',
  '#conversations': '/ask#conversation-history',
};

export function LegacyAIWorkspaceRedirect() {
  useEffect(() => {
    const destination = ASK_AI_HASHES[window.location.hash];
    if (destination) window.location.replace(destination);
  }, []);
  return null;
}
