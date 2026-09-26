import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Overview from "./pages/Overview.jsx";
import Reserves from "./pages/Reserves.jsx";
import Forecast from "./pages/Forecast.jsx";
import Actions from "./pages/Actions.jsx";
import Scenarios from "./pages/Scenarios.jsx";
import Integrity from "./pages/Integrity.jsx";
import Report from "./pages/Report.jsx";
import Login from "./pages/Login.jsx";
import { useAuth } from "./auth.jsx";

export default function App() {
  const { user } = useAuth();
  if (!user) return <Login />;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Overview />} />
        <Route path="reserves" element={<Reserves />} />
        <Route path="forecast" element={<Forecast />} />
        <Route path="actions" element={<Actions />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="integrity" element={<Integrity />} />
        <Route path="report" element={<Report />} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  );
}
