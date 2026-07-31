import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { HealthGate } from "./HealthGate";
import { Admin } from "./pages/Admin";
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
        <Route path="/settings" element={<Settings />} />
        {/* Always routable, even for a non-admin: the page itself explains who
            holds admin. A route that 404'd would make a shared link look like
            a broken app rather than a permission the reader doesn't have. */}
        <Route path="/admin" element={<Admin />} />
      </Routes>
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      {/* The health gate wraps the ROUTER, not a route (S18): a broken share
          must not depend on client-side routing working, and nobody navigates
          to "/repair" — they are sitting on "/" watching an app that won't
          start. */}
      <HealthGate>
        <AppRoutes />
      </HealthGate>
    </BrowserRouter>
  );
}
