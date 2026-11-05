import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/ui";
import { BoxSetList, BoxSetPage } from "./pages/BoxSets";
import { ItemForm } from "./pages/ItemForm";
import { More, Trash, WishList } from "./pages/Lists";
import { Login } from "./pages/Login";
import { Overview } from "./pages/Overview";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { TitlePage } from "./pages/TitlePage";
import { AppProvider, useApp } from "./state";

function Routed() {
  const { user, loading, can } = useApp();
  if (loading) return <p className="status-line" style={{ padding: 24 }}>LOADING…</p>;
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="search" element={<Search />} />
        <Route path="titles/:id" element={<TitlePage />} />
        {can("editor") && <Route path="items/new" element={<ItemForm key="new" />} />}
        {can("editor") && <Route path="items/:id/edit" element={<ItemForm />} />}
        <Route path="boxsets" element={<BoxSetList />} />
        <Route path="boxsets/:id" element={<BoxSetPage />} />
        <Route path="wishlist" element={<WishList />} />
        <Route path="trash" element={<Trash />} />
        <Route path="more" element={<More />} />
        <Route path="settings/*" element={<Settings />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <AppProvider>
      <ToastProvider>
        <BrowserRouter>
          <Routed />
        </BrowserRouter>
      </ToastProvider>
    </AppProvider>
  );
}
