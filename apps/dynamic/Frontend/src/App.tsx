import { useCallback, useEffect, useRef, useState } from 'react';
import type { Engine } from './data/engineData';
import { onAuthStateChanged, signInWithPopup, signOut, type User } from 'firebase/auth';
import { listDisplacementJobs } from './api/catalog';
import { Home } from './pages/Home';
import { ArchivePage } from './pages/ArchivePage';
import { DashboardPage } from './pages/DashboardPage';
import { parseDashboardView } from './dashboardDocument';
import { LandslidePage } from '../landslide/ui/LandslidePage';
import { RiverShiftPage } from './pages/RiverShiftPage';
import { auth, firebaseConfigured, googleProvider, missingFirebaseConfig } from './firebase';
import { isArchiveRoute, isDashboardRoute, isRiverShiftRoute, RIVER_SHIFT_PATH, isLandslideDisplacementRoute, isLandslideKnownPlaceAnalysisRoute, isLandslideKnownPlaceSetupAnalysisRoute, isLandslideKnownPlaceSetupRoute, isLandslideResultsRoute, isLandslideRoute, LANDSLIDE_DISPLACEMENT_PATH, LANDSLIDE_KNOWN_PLACE_PATH, LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH, LANDSLIDE_KNOWN_PLACE_SETUP_PATH, LANDSLIDE_PATH, LANDSLIDE_RESULTS_PATH, navigatePath, normalizePathname } from './routing';

function App() {
  const [pathname, setPathname] = useState(() => normalizePathname(window.location.pathname));
  const pathnameRef = useRef(pathname);
  const [user, setUser] = useState<User | null>(null);
  const [authState, setAuthState] = useState<'idle' | 'loading' | 'ready' | 'error'>('loading');
  const [authError, setAuthError] = useState<string | null>(null);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [pendingRoute, setPendingRoute] = useState<string | null>(null);
  const [hasActiveDisplacementTask, setHasActiveDisplacementTask] = useState(false);

  const navigateTo = useCallback((nextPath: string) => {
    const normalizedPath = navigatePath(nextPath, window.location.pathname, window.history.pushState.bind(window.history));
    pathnameRef.current = normalizedPath;
    setPathname(normalizedPath);
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const nextPath = normalizePathname(window.location.pathname);
      pathnameRef.current = nextPath;
      setPathname(nextPath);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const refreshDisplacementTaskState = useCallback(async (currentUser: User) => {
    try {
      const jobs = await listDisplacementJobs(currentUser);
      setHasActiveDisplacementTask(jobs.some((job) => ['queued', 'dispatching', 'running'].includes(job.state)));
    } catch {
      // A backend outage must not create a false navigation lock. The task
      // screen presents its own recoverable account-state error instead.
    }
  }, []);

  useEffect(() => {
    if (!user) {
      setHasActiveDisplacementTask(false);
      return undefined;
    }
    void refreshDisplacementTaskState(user);
    const timer = window.setInterval(() => { void refreshDisplacementTaskState(user); }, 5000);
    return () => window.clearInterval(timer);
  }, [refreshDisplacementTaskState, user]);

  useEffect(() => {
    // The account task may continue while the user visits Home. Only the map
    // workspace is locked because changing its AOI during an active task would
    // be misleading; the durable status route stays available.
    if (hasActiveDisplacementTask && pathname === LANDSLIDE_PATH) {
      navigateTo(LANDSLIDE_DISPLACEMENT_PATH);
    }
  }, [hasActiveDisplacementTask, navigateTo, pathname]);

  useEffect(() => {
    if (!auth) {
      setAuthState('idle');
      return undefined;
    }

    return onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setAuthState(currentUser ? 'ready' : 'idle');
      setAuthError(null);
      const currentPath = pathnameRef.current;
      if (!currentUser && (isLandslideRoute(currentPath) || isRiverShiftRoute(currentPath))) {
        setPendingRoute(currentPath);
        setAuthModalOpen(true);
        navigateTo('/');
      }
    }, (error) => {
      setAuthError(error.message);
      setAuthState('error');
    });
  }, [navigateTo]);

  const handleSignIn = async () => {
    if (!auth || !googleProvider) {
      setAuthError('Firebase is not configured for this local environment.');
      setAuthState('error');
      return;
    }

    setAuthState('loading');
    try {
      await signInWithPopup(auth, googleProvider);
      setAuthState('ready');
      setAuthError(null);
      setAuthModalOpen(false);
      if (pendingRoute) {
        navigateTo(pendingRoute);
        setPendingRoute(null);
      }
    } catch (error: unknown) {
      setAuthError(error instanceof Error ? error.message : 'Authentication failed');
      setAuthState('error');
    }
  };

  const handleSignOut = async () => {
    if (!auth) return;
    try {
      await signOut(auth);
      setPendingRoute(null);
      setAuthModalOpen(false);
      if (isLandslideRoute(pathname) || isRiverShiftRoute(pathname)) {
        navigateTo('/');
      }
    } catch (error: unknown) {
      setAuthError(error instanceof Error ? error.message : 'Sign out failed');
    }
  };

  const handleSelectEngine = (engine: Engine) => {
    // Known Place starts in its own AOI/date-window setup, then proceeds to
    // the existing two-polygon analysis page. Landslide and Glacier retain
    // the target-free AOI workspace.
    const targetRoute = engine.id === 'known-place'
      ? LANDSLIDE_KNOWN_PLACE_SETUP_PATH
      : engine.id === 'river-shift' ? RIVER_SHIFT_PATH : LANDSLIDE_PATH;
    if (!user) {
      setPendingRoute(targetRoute);
      setAuthModalOpen(true);
      return;
    }

    setAuthModalOpen(false);
    navigateTo(targetRoute);
  };

  const handleOpenWorkspace = useCallback(() => {
    if (!user) {
      setPendingRoute(LANDSLIDE_PATH);
      setAuthModalOpen(true);
      return;
    }
    setAuthModalOpen(false);
    navigateTo(LANDSLIDE_PATH);
  }, [navigateTo, user]);

  if (isDashboardRoute(pathname)) {
    const searchParams = new URLSearchParams(window.location.search);
    return (
      <DashboardPage
        jobId={searchParams.get('jobId') || ''}
        view={parseDashboardView(searchParams.get('view'))}
        user={user}
        authState={authState}
        authError={authError}
        onSignIn={handleSignIn}
      />
    );
  }

  if (isArchiveRoute(pathname)) {
    return (
      <ArchivePage
        user={user}
        authState={authState}
        onSignIn={handleSignIn}
        onSignOut={handleSignOut}
        onOpenWorkspace={handleOpenWorkspace}
      />
    );
  }

  if (isRiverShiftRoute(pathname)) {
    if (!user) {
      return (
        <Home
          user={user}
          authState={authState}
          authError={authError}
          firebaseConfigured={firebaseConfigured}
          missingFirebaseConfig={missingFirebaseConfig}
          showAuthModal={true}
          onCloseAuthModal={() => { setAuthModalOpen(false); setPendingRoute(null); }}
          onSignIn={handleSignIn}
          onSignOut={handleSignOut}
          onSelectEngine={handleSelectEngine}
          onOpenWorkspace={handleOpenWorkspace}
        />
      );
    }

    return (
      <RiverShiftPage
        key={user.uid}
        user={user}
        firebaseConfigured={firebaseConfigured}
        authState={authState}
        onHome={() => navigateTo('/')}
        onSignIn={handleSignIn}
        onSignOut={handleSignOut}
      />
    );
  }

  if (isLandslideRoute(pathname)) {
    if (!user) {
      return (
        <Home
          user={user}
          authState={authState}
          authError={authError}
          firebaseConfigured={firebaseConfigured}
          missingFirebaseConfig={missingFirebaseConfig}
          showAuthModal={true}
          onCloseAuthModal={() => { setAuthModalOpen(false); setPendingRoute(null); }}
          onSignIn={handleSignIn}
          onSignOut={handleSignOut}
          onSelectEngine={handleSelectEngine}
          onOpenWorkspace={handleOpenWorkspace}
        />
      );
    }

    return (
      <LandslidePage
        key={user.uid}
        user={user}
        onHome={() => navigateTo('/')}
        isResultsPage={isLandslideResultsRoute(pathname)}
        isDisplacementPage={isLandslideDisplacementRoute(pathname)}
        isKnownPlaceAnalysisPage={isLandslideKnownPlaceAnalysisRoute(pathname)}
        isKnownPlaceSetupPage={isLandslideKnownPlaceSetupRoute(pathname)}
        onDisplacements={() => navigateTo(LANDSLIDE_DISPLACEMENT_PATH)}
        onKnownPlaceAnalysis={() => navigateTo(
          isLandslideKnownPlaceSetupRoute(pathname)
            ? LANDSLIDE_KNOWN_PLACE_SETUP_ANALYSIS_PATH
            : LANDSLIDE_KNOWN_PLACE_PATH
        )}
        onResults={() => navigateTo(LANDSLIDE_RESULTS_PATH)}
        onBackToMap={() => navigateTo(
          isLandslideKnownPlaceSetupAnalysisRoute(pathname)
            ? LANDSLIDE_KNOWN_PLACE_SETUP_PATH
            : LANDSLIDE_PATH
        )}
        onDisplacementTaskActivityChange={setHasActiveDisplacementTask}
        onSignOut={handleSignOut}
      />
    );
  }

  return (
    <Home
      user={user}
      authState={authState}
      authError={authError}
      firebaseConfigured={firebaseConfigured}
      missingFirebaseConfig={missingFirebaseConfig}
      showAuthModal={authModalOpen}
      onCloseAuthModal={() => { setAuthModalOpen(false); setPendingRoute(null); }}
      onSignIn={handleSignIn}
      onSignOut={handleSignOut}
      onSelectEngine={handleSelectEngine}
          onOpenWorkspace={handleOpenWorkspace}
    />
  );
}

export default App;
