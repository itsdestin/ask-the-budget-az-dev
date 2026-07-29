import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { FiscalNotes } from "./pages/FiscalNotes";
import { Home } from "./pages/Home";
import { Search } from "./pages/Search";

export function App() {
  return (
    <BrowserRouter>
      <Header />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/search" element={<Search />} />
        <Route path="/fiscal-notes" element={<FiscalNotes />} />
      </Routes>
    </BrowserRouter>
  );
}
