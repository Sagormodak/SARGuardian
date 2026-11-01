import type { User } from 'firebase/auth';
import { Footer } from '../components/Footer';
import { Header } from '../components/Header';
import { ArchiveSection } from '../components/ArchiveSection';

type ArchivePageProps = {
  user: User | null;
  authState: 'idle' | 'loading' | 'ready' | 'error';
  onSignIn: () => void;
  onSignOut: () => void;
  onOpenWorkspace: () => void;
};

export function ArchivePage({ user, authState, onSignIn, onSignOut, onOpenWorkspace }: ArchivePageProps) {
  return (
    <div className="home-page archive-page">
      <div className="environment-layer" aria-hidden="true" />
      <div className="ambient-vignette" aria-hidden="true" />
      <Header
        user={user}
        authState={authState}
        onSignIn={onSignIn}
        onSignOut={onSignOut}
        isArchivePage
      />
      <main className="home-main archive-main">
        <div className="archive-page-heading">
          <p className="section-eyebrow">YOUR WORKSPACE</p>
          <h1>Analysis archive</h1>
          <p>Review previous AOI analyses, their processing status and verified result bundles.</p>
        </div>
        <ArchiveSection user={user} onSignIn={onSignIn} onOpenWorkspace={onOpenWorkspace} />
      </main>
      <Footer isArchivePage />
    </div>
  );
}
