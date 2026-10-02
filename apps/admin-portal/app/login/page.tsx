'use client';

import { useEffect, useState, type FormEvent } from 'react';

import { useAuth } from '../../components/auth/AuthContext';
import { useI18n } from '../../i18n/I18nProvider';
import { authApi } from '../../lib/auth-api';
import { ApiHttpError } from '../../lib/http-client';

export default function LoginPage() {
  const { t } = useI18n();
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorKey, setErrorKey] = useState<string | null>(null);
  const [rememberMeEnabled, setRememberMeEnabled] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);

  useEffect(() => {
    void authApi.sessionPolicy()
      .then((policy) => setRememberMeEnabled(policy.remember_me_enabled))
      .catch(() => setRememberMeEnabled(false));
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setErrorKey(null);
    try {
      await login(email, password, rememberMe);
    } catch (cause) {
      if (cause instanceof ApiHttpError) {
        if (cause.status === 401) setErrorKey('auth.invalidCredentials');
        else if (cause.status === 429) setErrorKey('auth.rateLimited');
        else if (cause.status === 503) setErrorKey('auth.loginUnavailable');
        else setErrorKey('auth.loginFailed');
      } else {
        setErrorKey('auth.loginUnavailable');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page" id="main-content">
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="eyebrow">{t('navigation.productLabel')}</span>
          <h1 id="login-title">{t('auth.loginTitle')}</h1>
          <p>{t('auth.loginDescription')}</p>
        </div>
        <form className="login-form" onSubmit={(event) => void submit(event)}>
          <label className="field-label" htmlFor="login-email">{t('auth.identifierLabel')}</label>
          <input
            autoComplete="username"
            autoFocus
            className="field-control"
            id="login-email"
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="text"
            value={email}
          />
          <label className="field-label" htmlFor="login-password">{t('auth.passwordLabel')}</label>
          <input
            autoComplete="current-password"
            className="field-control"
            id="login-password"
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
          {rememberMeEnabled ? <label className="checkbox-row"><input checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} type="checkbox" /><span>{t('sessions.rememberMe')}</span></label> : null}
          {errorKey ? <p className="form-error" role="alert">{t(errorKey)}</p> : null}
          <button className="button login-submit" disabled={submitting} type="submit">
            {t(submitting ? 'auth.signingIn' : 'auth.signIn')}
          </button>
        </form>
      </section>
    </main>
  );
}
