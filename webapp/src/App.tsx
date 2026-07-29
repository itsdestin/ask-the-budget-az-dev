import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { FiscalNotes } from "./pages/FiscalNotes";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";

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
