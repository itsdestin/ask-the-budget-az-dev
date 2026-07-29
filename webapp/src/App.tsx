import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { FiscalNotes } from "./pages/FiscalNotes";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";

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
