import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { Ai } from "./pages/Ai";
import { FiscalNotes } from "./pages/FiscalNotes";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { Upload } from "./pages/Upload";

// Split from App so tests can mount the routes inside a MemoryRouter with an
// initial URL (e.g. "/search?q=roads") — BrowserRouter can't be given one.
export function AppRoutes() {
  return (
    <>
      <Header />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/fiscal-notes" element={<FiscalNotes />} />
        {/* AI Mode is its own surface (2026-07-31), no longer a toggle on the
            two corpus pages. The corpus is picked inside it. */}
        <Route path="/ai" element={<Ai />} />
        <Route path="/upload" element={<Upload />} />
        {/* Stub route so the header's Settings pill isn't a dead link (Plan 5). */}
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
