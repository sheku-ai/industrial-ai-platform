import { createApiProxy } from '../../../lib/server/api-proxy';

const proxy = createApiProxy('setup');

export const dynamic = 'force-dynamic';
export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
