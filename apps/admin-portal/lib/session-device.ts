export type SessionDevice = { browser: string | null; platform: string | null };

function majorVersion(userAgent: string, pattern: RegExp): string | null {
  return userAgent.match(pattern)?.[1] ?? null;
}

export function parseSessionDevice(value: string | null): SessionDevice {
  const userAgent = String(value ?? '').slice(0, 512);
  if (!userAgent) return { browser: null, platform: null };
  const edge = majorVersion(userAgent, /(?:Edg|EdgiOS|EdgA)\/(\d+)/);
  const chrome = majorVersion(userAgent, /(?:Chrome|CriOS)\/(\d+)/);
  const firefox = majorVersion(userAgent, /(?:Firefox|FxiOS)\/(\d+)/);
  const safari = /Safari\//.test(userAgent) && !edge && !chrome;
  const browser = edge ? `Edge ${edge}`
    : chrome ? `Chrome ${chrome}`
      : firefox ? `Firefox ${firefox}`
        : safari ? 'Safari'
          : null;
  const platform = /iPhone/.test(userAgent) ? 'iPhone'
    : /iPad/.test(userAgent) ? 'iPad'
      : /Android/.test(userAgent) ? 'Android'
        : /Macintosh|Mac OS X/.test(userAgent) ? 'macOS'
          : /Windows/.test(userAgent) ? 'Windows'
            : /Linux/.test(userAgent) ? 'Linux'
              : null;
  return { browser, platform };
}

export function sessionDeviceLabel(
  userAgent: string | null,
  onLabel: string,
  unknownLabel: string,
): string {
  const device = parseSessionDevice(userAgent);
  if (!device.browser) return unknownLabel;
  return device.platform ? `${device.browser} ${onLabel} ${device.platform}` : device.browser;
}
