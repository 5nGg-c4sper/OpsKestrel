import { useEffect, useState } from "react";
import {
  Activity,
  Bird,
  ClipboardCheck,
  LayoutDashboard,
  Menu,
  Play,
  Radio,
  ShieldCheck,
  X
} from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useConsole } from "../state/ConsoleProvider";
import { useAuth } from "../state/AuthProvider";
import { className } from "../lib/format";

const navigation = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/new", label: "New run", icon: Play },
  { to: "/run", label: "Run monitor", icon: Activity },
  { to: "/reviews", label: "Reviews", icon: ClipboardCheck }
];

const pageNames: Record<string, string> = {
  "/": "Operations overview",
  "/new": "New run",
  "/run": "Run monitor",
  "/reviews": "Human reviews"
};

export function AppShell() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { overview } = useConsole();
  const { session } = useAuth();
  const location = useLocation();
  const workers = overview?.workers ?? [];
  const activeWorkers = workers.filter(
    (worker) => worker.state !== "offline"
  ).length;
  const currentPage =
    pageNames[location.pathname] ?? pageNames["/"];

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <button
        type="button"
        className="mobile-menu-button"
        onClick={() => setSidebarOpen((current) => !current)}
        aria-label={sidebarOpen ? "Close navigation" : "Open navigation"}
        aria-expanded={sidebarOpen}
      >
        {sidebarOpen ? <X size={21} /> : <Menu size={21} />}
      </button>

      {sidebarOpen ? (
        <button
          type="button"
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <aside className={className("app-sidebar", sidebarOpen && "is-open")}>
        <NavLink className="brand" to="/" aria-label="OpsKestrel overview">
          <span className="brand-mark">
            <Bird size={23} strokeWidth={1.8} />
          </span>
          <span>
            <strong>OpsKestrel</strong>
            <small>Operations console</small>
          </span>
        </NavLink>

        <nav className="primary-nav" aria-label="Primary navigation">
          {navigation.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                className={({ isActive }) =>
                  className("nav-link", isActive && "is-active")
                }
                end={item.end}
                key={item.to}
                to={item.to}
              >
                <Icon size={18} strokeWidth={1.8} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />

        <div className="sidebar-status">
          <div className="sidebar-status-row">
            <span className="live-dot" />
            <span>{activeWorkers} worker online</span>
          </div>
          <div className="sidebar-status-row subdued">
            <ShieldCheck size={15} />
            <span>
              {session ? `${session.operator} · ${session.role}` : "Review locked"}
            </span>
          </div>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="topbar-context">OpsKestrel</span>
            <strong>{currentPage}</strong>
          </div>
          <div className="topbar-health">
            <Radio size={16} />
            <span>
              {overview?.worker_error
                ? "Worker status unavailable"
                : `${activeWorkers} active`}
            </span>
          </div>
        </header>
        <div className="page-canvas">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
