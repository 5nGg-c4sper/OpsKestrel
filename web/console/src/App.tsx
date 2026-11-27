import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { NewRunPage } from "./pages/NewRunPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ReviewsPage } from "./pages/ReviewsPage";
import { RunPage } from "./pages/RunPage";
import { AuthProvider } from "./state/AuthProvider";
import { ConsoleProvider } from "./state/ConsoleProvider";
import { ToastProvider } from "./state/ToastProvider";

export default function App() {
  return (
    <HashRouter>
      <ToastProvider>
        <ConsoleProvider>
          <AuthProvider>
            <Routes>
              <Route element={<AppShell />}>
                <Route index element={<OverviewPage />} />
                <Route path="new" element={<NewRunPage />} />
                <Route path="run" element={<RunPage />} />
                <Route path="reviews" element={<ReviewsPage />} />
                <Route path="*" element={<Navigate replace to="/" />} />
              </Route>
            </Routes>
          </AuthProvider>
        </ConsoleProvider>
      </ToastProvider>
    </HashRouter>
  );
}
