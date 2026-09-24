import React, { useEffect } from "react";
import { AuthProvider, useAuth } from "./auth.jsx";
import Layout from "./components/Layout.jsx";
import { RealtimeProvider } from "./lib/realtime.jsx";
import { Spinner, Toaster } from "./components/ui.jsx";
import { match, navigate, useRoute } from "./router.js";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import PatientHome from "./pages/PatientHome.jsx";
import SelfExam from "./pages/SelfExam.jsx";
import Questionnaire from "./pages/Questionnaire.jsx";
import Chat from "./pages/Chat.jsx";
import Wigs from "./pages/Wigs.jsx";
import { PatientReports, PatientReport } from "./pages/PatientReports.jsx";
import DoctorContact from "./pages/DoctorContact.jsx";
import DoctorHome from "./pages/DoctorHome.jsx";
import DoctorPatients from "./pages/DoctorPatients.jsx";
import PatientDetail from "./pages/PatientDetail.jsx";
import DoctorReport from "./pages/DoctorReport.jsx";
import CalendarPage from "./pages/CalendarPage.jsx";
import Notifications from "./pages/Notifications.jsx";
import Corpus from "./pages/Corpus.jsx";

const ROUTES = {
  patient: [
    ["/home", PatientHome, "Bonjour"],
    ["/self-exam", SelfExam, "Autopalpation guidée"],
    ["/questionnaire", Questionnaire, "Questionnaire post-autopalpation"],
    ["/chat", Chat, "Assistante BreastFriend"],
    ["/wigs", Wigs, "Une perruque qui vous ressemble"],
    ["/reports", PatientReports, "Mes comptes rendus"],
    ["/reports/:id", PatientReport, "Compte rendu"],
    ["/doctor-contact", DoctorContact, "Mon médecin"],
  ],
  doctor: [
    ["/doctor", DoctorHome, "Tableau de bord"],
    ["/doctor/patients", DoctorPatients, "Mes patientes"],
    ["/doctor/patients/:id", PatientDetail, "Dossier patiente"],
    ["/doctor/reports/:id", DoctorReport, "Compte rendu"],
    ["/doctor/calendar", CalendarPage, "Agenda des rendez-vous"],
    ["/doctor/notifications", Notifications, "Notifications"],
    ["/doctor/corpus", Corpus, "Corpus médical du RAG"],
    ["/chat", Chat, "Assistante BreastFriend"],
  ],
};

function Router() {
  const { user, ready } = useAuth();
  const { path, query } = useRoute();
  const home = user?.role === "doctor" ? "/doctor" : "/home";

  useEffect(() => {
    if (!ready) return;
    if (!user && path !== "/login" && path !== "/register") navigate("/login");
    if (user && (path === "/" || path === "/login" || path === "/register")) navigate(home);
  }, [ready, user, path, home]);

  if (!ready) return <div className="center-screen"><Spinner /></div>;
  if (!user) return path === "/register" ? <Register /> : <Login />;
  return <RealtimeProvider user={user}><Routes user={user} path={path} query={query} /></RealtimeProvider>;
}

function Routes({ user, path, query }) {
  const home = user.role === "doctor" ? "/doctor" : "/home";
  for (const [pattern, Page, title] of ROUTES[user.role]) {
    const params = match(pattern, path);
    if (params) {
      return (
        <Layout path={path} title={title}>
          <Page params={params} query={query} />
        </Layout>
      );
    }
  }
  return (
    <Layout path={path} title="Page introuvable">
      <p>Cette page n'existe pas. <a href={`#${home}`}>Revenir à l'accueil</a></p>
    </Layout>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Router />
      <Toaster />
    </AuthProvider>
  );
}
