import type { User } from 'firebase/auth';
import { ProfileControl } from './ProfileControl';

type HeaderProps = {
  user: User | null;
  authState: 'idle' | 'loading' | 'ready' | 'error';
  onSignIn: () => void;
  onSignOut: () => void;
  isArchivePage?: boolean;
};

export function Header({ user, authState, onSignIn, onSignOut, isArchivePage = false }: HeaderProps) {
  const sectionPrefix = isArchivePage ? '/#' : '#';
  const navItems = [
    { label: 'Home', href: isArchivePage ? '/' : '#home', current: !isArchivePage },
    { label: 'Cases', href: `${sectionPrefix}cases`, current: false },
    { label: 'Method', href: `${sectionPrefix}method`, current: false },
    { label: 'Data', href: `${sectionPrefix}data`, current: false },
    { label: 'Archive', href: '/archive', current: isArchivePage },
  ];

  return (
    <header className="site-header">
      <a className="brand-lockup" href={isArchivePage ? '/' : '#home'} aria-label="SARGuardian home">
        <span className="brand-mark" aria-hidden="true"><span className="brand-mountain" /><span className="brand-water" /></span>
        <span className="brand-copy">
          <strong><b>SAR</b>Guardian</strong>
          <small>EARTH IN SIGHT</small>
        </span>
      </a>

      <nav className="main-nav" aria-label="Main navigation">
        {navItems.map((item) => (
          <a
            className={item.current ? 'nav-link is-current' : 'nav-link'}
            href={item.href}
            key={item.href}
            aria-current={item.current ? 'page' : undefined}
          >
            {item.label}
          </a>
        ))}
      </nav>

      <div className="header-actions">
        {user ? (
          <ProfileControl user={user} onSignOut={onSignOut} />
        ) : (
          <button className="sign-in-button" onClick={onSignIn} type="button" disabled={authState === 'loading'}>
            <span className="google-mark" aria-hidden="true">G</span>
            {authState === 'loading' ? 'Signing in...' : 'Sign in'}
          </button>
        )}
      </div>
    </header>
  );
}
