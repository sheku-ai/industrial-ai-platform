import { createApiProxy } from '../../../lib/server/api-proxy';

export const dynamic = 'force-dynamic';

const proxy = createApiProxy('auth');

export const GET = proxy;
export const HEAD = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const OPTIONS = proxy;
