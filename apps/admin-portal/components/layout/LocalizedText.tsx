'use client';

import { useI18n } from '../../i18n/I18nProvider';

export function LocalizedText({ id, values }: { id: string; values?: Record<string, string | number | boolean> }) {
  const { t } = useI18n();
  return <>{t(id, values)}</>;
}

export function LocalizedDate({ value }: { value: string | number | Date | null | undefined }) {
  const { date } = useI18n();
  return <>{date(value, { dateStyle: 'medium', timeStyle: 'short' })}</>;
}

export function LocalizedNumber({ value }: { value: number }) {
  const { number } = useI18n();
  return <>{number(value)}</>;
}

export function LocalizedPercent({ value }: { value: number }) {
  const { percent } = useI18n();
  return <>{percent(value)}</>;
}

export function LocalizedDuration({ milliseconds }: { milliseconds: number }) {
  const { duration } = useI18n();
  return <>{duration(milliseconds)}</>;
}
