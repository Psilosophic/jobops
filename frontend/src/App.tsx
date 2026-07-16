import { useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import PanicDrawer from "./components/PanicDrawer";
import Jobs from "./pages/Jobs";
import MorningReport from "./pages/MorningReport";
import ReviewQueue from "./pages/ReviewQueue";
import Sources from "./pages/Sources";

const nav = [
  { to: "/", label: "Morning Report" },
  { to: "/review", label: "Review Queue" },
  { to: "/jobs", label: "Jobs" },
  { to: "/sources", label: "Sources & Policy" },
];

export default function App() {
  const [panicOpen, setPanicOpen] = useState(false);
  return (
    <div className="min-h-screen text-zinc-100">
      <header className="sticky top-0 z-40 flex items-center gap-1 border-b border-zinc-800 bg-zinc-950/95 px-4 py-2 backdrop-blur">
        <span className="mr-4 text-lg font-bold tracking-tight text-emerald-400">JobOps</span>
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"}
            className={({ isActive }) =>
              `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-zinc-800 text-white" : "text-zinc-400 hover:text-white"}`}>
            {n.label}
          </NavLink>
        ))}
        <div className="grow" />
        <button onClick={() => setPanicOpen(true)} className="btn-danger animate-none font-bold">
          ⏻ PANIC
        </button>
      </header>
      <main className="mx-auto max-w-7xl p-4">
        <Routes>
          <Route path="/" element={<MorningReport />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/sources" element={<Sources />} />
        </Routes>
      </main>
      <PanicDrawer open={panicOpen} onClose={() => setPanicOpen(false)} />
    </div>
  );
}
